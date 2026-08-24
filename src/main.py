import logging
import os
import time
import threading
import cv2

from .config import (
    DEFAULT_CAMERAS,
    DETECTOR_CLASSES,
    DETECTOR_CONFIDENCE,
    DETECTOR_IOU,
    DETECTOR_MODEL_PATH,
    FRAME_WAIT_SECONDS,
    WORKER_HEALTHY_TIMEOUT_SECONDS,
    SERVER_HOST,
    SERVER_PORT,
    MOTION_MIN_AREA,
    NO_MOTION_ALERT_SECONDS,
    ALERT_COOLDOWN_SECONDS,
    ALERT_COOLDOWN_BY_EVENT,
    THUMBNAILS_DIR,
    THUMBNAIL_INTERVAL_SECONDS,
    THUMBNAIL_DIFF_THRESHOLD,
    THUMBNAIL_HISTORY_SIZE,
    EVENT_DEDUP_WINDOW_SECONDS,
    CLIP_PRE_SECONDS,
    CLIP_POST_SECONDS,
    CLIP_FPS,
    CLIPS_DIR,
    CLIP_HISTORY_SIZE,
    PRIVACY_MODE,
    is_privacy_mode_on,
    TRACK_IOU_THRESHOLD,
    TRACK_MAX_AGE_SECONDS,
    LOITERING_SECONDS,
    LOITERING_MAX_DISTANCE,
    LOITERING_LABELS,
    FALL_ASPECT_RATIO,
)
from .camera import CameraStream
from .detector import ObjectDetector
from .motion import MotionDetector
from .geometry import bbox_center_in_polygons
from .masking import frame_for_storage
from .alerts import AlertService, telegram_handler, mqtt_handler, home_assistant_handler, siren_handler, mqtt_register_device
from .app import create_app
from .storage import EventStorage
from .identity import IdentityRecognizer, RECOGNITION_LABELS, build_recognizer
from .event_rules import decide_worker_event, _unpack_worker_decision
from .alert_rules import AlertRuleEngine
from .notifications import DEFAULT_ROUTING
from .events import CameraEvent, LocalEventQueue
from .tracking import IoUTracker
from .behavior import check_loitering, check_direction_crossing, check_fall

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _worker_healthy(last_frame_time, now, timeout):
    """Câmera saudável se recebeu ao menos um frame e o último é recente.

    last_frame_time None => fonte nunca entregou frame (ex: RTSP morto).
    """
    if last_frame_time is None:
        return False
    return (now - last_frame_time) <= timeout


class CameraWorker:
    def __init__(self, camera, storage: EventStorage, alerts: AlertService, object_detector: ObjectDetector, identity_recognizer=None, event_bus=None):
        self.camera = camera
        self.storage = storage
        self.alerts = alerts
        self.object_detector = object_detector
        self.identity_recognizer = identity_recognizer
        self.event_bus = event_bus
        self._privacy_check_time = 0.0
        self._privacy_on = False
        self.last_frame_time = None
        self._last_thumb_time = None
        self._last_saved_thumb = None
        self._last_saved_thumb_path = None
        self._repr_frame = None
        self._repr_time = 0.0
        self._latest_frame = None
        self._latest_frame_time = None
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        # Estado de gravação de clipe (instância p/ start_clip e o loop contínuo)
        self._frame_buffer = None
        self._frame = None
        self._clip_writer = None
        self._clip_end_time = 0.0
        self._clip_event_id = None
        self._clip_path = None
        self._clip_frames_written = 0
        self._last_clip_write = 0.0

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=2)

    def is_running(self):
        return self.thread.is_alive()

    def status(self):
        return {
            "camera_id": self.camera.get("id"),
            "name": self.camera.get("name"),
            "zone": self.camera.get("zone"),
            "source": self.camera.get("source"),
            "running": self.thread.is_alive(),
            "healthy": _worker_healthy(self.last_frame_time, time.time(), WORKER_HEALTHY_TIMEOUT_SECONDS),
        }

    def get_latest_frame(self):
        """Retorna (frame_mascarado, timestamp_epoch) do último frame, ou (None, None)."""
        return self._latest_frame, self._latest_frame_time

    def _should_save_thumbnail(self, frame, now):
        """Decisão de captura de thumbnail: intervalo mínimo + dedup por
        cena estável (representante + janela)."""
        if not should_capture_thumbnail(self._last_thumb_time, now, THUMBNAIL_INTERVAL_SECONDS):
            return False
        if not self._scene_changed(frame, now):
            return False
        return True

    def _scene_changed(self, frame, now):
        """True se a cena deve ser tratada como nova (salvar/suprimir).

        - sem representante: sempre nova;
        - janela expirada: refresh obrigatório;
        - frames_similar falha: cena mudou de fato.
        """
        if self._repr_frame is None:
            return True
        if now - self._repr_time >= EVENT_DEDUP_WINDOW_SECONDS:
            return True
        return not frames_similar(self._repr_frame, frame, THUMBNAIL_DIFF_THRESHOLD)

    def _update_repr(self, frame, now):
        """Atualiza o representante de cena (mini 64x64 + timestamp)."""
        self._repr_frame = _thumbnail_mini(frame)
        self._repr_time = now
        # Mantém fallback de alerta Telegram consistente
        self._last_saved_thumb = self._repr_frame

    def _should_emit_event(self, identity_info, fall, loitering, direction, frame, now):
        """Eventos de baixo-valor em cena estável são suprimidos para não
        poluir o grid com imagens quase-idênticas. Eventos de segurança
        (identidade/intruso/queda/loitering/direção) sempre emitem."""
        high_value = (
            identity_info is not None
            or fall
            or loitering is not None
            or direction is not None
        )
        if high_value:
            return True
        return self._scene_changed(frame, now)

    def _capture_thumbnail(self, storage_frame, event_type, now, keep=THUMBNAIL_HISTORY_SIZE, days=None, event_id=None, force=False):
        """Salva um thumbnail com dedup por similaridade (ou force=True).

        Retorna o path (str) se gravou, ou None se pulado (intervalo não
        cumprido, cena estável já representada ou falha de escrita).
        Em todo save bem-sucedido atualiza o representante de cena.
        """
        if not force and not self._should_save_thumbnail(storage_frame, now):
            return None
        try:
            cam_dir = THUMBNAILS_DIR / f"cam{self.camera['id']}"
            cam_dir.mkdir(parents=True, exist_ok=True)
            filename = f"{int(now * 1000)}.jpg"
            path = cam_dir / filename
            ok, jpg = cv2.imencode(".jpg", storage_frame)
            if not ok:
                return None
            path.write_bytes(jpg.tobytes())
            self.storage.add_camera_thumbnail(self.camera["id"], str(path), event_type, event_id=event_id)
            self.storage.prune_camera_thumbnails(self.camera["id"], keep=keep, max_age_days=days)
        except Exception:
            logger.warning("Falha ao capturar thumbnail (câmera %s)", self.camera.get("name"))
            return None
        self._last_thumb_time = now
        self._update_repr(storage_frame, now)
        self._last_saved_thumb_path = str(path)
        return str(path)

    def _latest_thumbnail_path(self):
        """Último path de thumbnail salvo (mesmo se o dedup bloqueou uma captura nova).
        Usado para o alerta do Telegram quando _capture_thumbnail retorna None."""
        return self._last_saved_thumb_path

    def build_candidate_event(self, detections, identity_info, identity_label, zone_name,
                              zone_classification, zone_schedule, now, fall, loitering, direction,
                              thumb_path, no_motion=False):
        """Constrói um CameraEvent candidato (N0/N1) para o event_bus.

        NÃO decide nem dispara alerta/HA: apenas produz o evento. A decisão
        (N2–N4) e a gravação de clipe ficam a cargo de AlertRuleEngine.
        """
        in_schedule = is_within_schedule(zone_schedule, now)
        kept = triage_n1(detections, no_motion)
        return CameraEvent(
            camera_id=str(self.camera["id"]),
            zone=zone_name,
            zone_classification=zone_classification,
            timestamp=now,
            level=1 if (kept and not no_motion) else 0,
            source="local",
            detections=detections,
            identity_info=identity_info,
            identity_label=identity_label,
            in_schedule=in_schedule,
            fall=fall,
            loitering=loitering,
            direction=direction,
            camera_name=self.camera["name"],
            alert_classes=self.camera.get("alert_classes"),
            thumbnail_path=thumb_path,
            no_motion=no_motion,
            dropped=not kept,
        )

    def start_clip(self, event_id):
        """Inicia a gravação de clipe (janela pré-evento + pós-evento).

        Extraído do loop de run(): apenas inicializa o writer a partir do
        buffer pré-evento. O loop contínuo de escrita de frames em
        self._clip_writer permanece em run() e NÃO é removido.
        """
        now = time.time()
        if self._clip_writer is not None:
            logger.debug("Clipe já ativo (câmera %s) — pulando", self.camera.get("name"))
            return
        try:
            cam_dir = CLIPS_DIR / f"cam{self.camera['id']}"
            cam_dir.mkdir(parents=True, exist_ok=True)
            clip_path = str(cam_dir / f"{int(now * 1000)}.mp4")
            writer = cv2.VideoWriter(
                clip_path, cv2.VideoWriter_fourcc(*"mp4v"), CLIP_FPS,
                (self._frame.shape[1], self._frame.shape[0]),
            )
            if not writer.isOpened():
                writer.release()
                logger.warning("Falha ao abrir VideoWriter (câmera %s)", self.camera.get("name"))
                return
            frames_written = 0
            for buf in self._frame_buffer.frames():
                dec = cv2.imdecode(buf, cv2.IMREAD_COLOR)
                if dec is not None:
                    writer.write(dec)
                    frames_written += 1
            self._clip_writer = writer
            self._clip_frames_written = frames_written
            self._clip_end_time = now + CLIP_POST_SECONDS
            self._clip_event_id = event_id
            self._clip_path = clip_path
            self._last_clip_write = now - 1.0 / CLIP_FPS
        except Exception:
            logger.warning("Falha ao iniciar gravação de clipe (câmera %s)", self.camera.get("name"))

    def identity_enabled(self):
        """Reconhecimento de identidade habilitado? (flag de privacidade com cache de 5s)."""
        now = time.time()
        if now - self._privacy_check_time >= 5.0:
            self._privacy_check_time = now
            try:
                self._privacy_on = is_privacy_mode_on(self.storage.get_setting("privacy_mode"))
            except Exception:
                self._privacy_on = False
        return self.identity_recognizer is not None and not self._privacy_on

    def run(self):
        camera_stream = CameraStream(self.camera["source"])
        motion_detector = MotionDetector(min_area=MOTION_MIN_AREA)
        tracker = IoUTracker(iou_threshold=TRACK_IOU_THRESHOLD, max_age_seconds=TRACK_MAX_AGE_SECONDS)
        last_motion_time = None
        no_motion_alerted = False
        # True apenas quando um evento de movimento/atividade foi efetivamente
        # emitido desde o último "sem movimento". Evita "sem movimento" repetido
        # por ruído do detector que não gera evento real.
        motion_reported = False
        self._frame_buffer = CircularFrameBuffer(maxlen=max(1, int(CLIP_PRE_SECONDS * CLIP_FPS)))
        self._clip_writer = None
        self._clip_end_time = 0.0
        self._clip_event_id = None
        self._clip_path = None
        self._clip_frames_written = 0
        self._last_clip_write = 0.0
        thumb_keep, thumb_days = THUMBNAIL_HISTORY_SIZE, None
        clip_keep, clip_days = CLIP_HISTORY_SIZE, None
        last_buffer_push = time.time()

        while not self.stop_event.is_set():
            frame = camera_stream.read()
            if frame is not None:
                self.last_frame_time = time.time()
            if frame is None:
                time.sleep(1)
                continue

            # Máscara de privacidade: o que é salvo/exibido (thumbnail, clipe,
            # snapshot) usa o frame mascarado; a detecção abaixo usa `frame` original.
            storage_frame = frame_for_storage(frame, self.camera.get("mask_polygons"))
            self._frame = frame
            self._latest_frame = storage_frame
            self._latest_frame_time = time.time()

            now = time.time()

            # Sample the pre-event buffer at CLIP_FPS cadence so the window
            # spans CLIP_PRE_SECONDS and playback runs at real-time speed.
            # Frames are stored JPEG-encoded (~50-150KB) instead of raw BGR
            # (~46MB at 640x480 per camera) to keep the worker footprint low.
            if now - last_buffer_push >= 1.0 / CLIP_FPS:
                last_buffer_push = now
                ok, jpg = cv2.imencode(".jpg", storage_frame)
                if ok:
                    self._frame_buffer.push(jpg)

            # Finalize clip recording after the post-event window.
            # The whole write/release block is guarded so a failing writer
            # (disk full, corrupted codec) cannot kill the worker thread.
            if self._clip_writer is not None:
                try:
                    if now < self._clip_end_time:
                        # Post-event frames are written at CLIP_FPS cadence,
                        # matching the pre-event buffer sampling.
                        if now - self._last_clip_write >= 1.0 / CLIP_FPS:
                            self._last_clip_write = now
                            self._clip_writer.write(storage_frame)
                            self._clip_frames_written += 1
                    else:
                        self._clip_writer.release()
                        self._clip_writer = None
                        if self._clip_frames_written > 0:
                            try:
                                self.storage.add_event_clip(
                                    self.camera["id"],
                                    self._clip_event_id,
                                    self._clip_path,
                                    self._clip_frames_written / CLIP_FPS,
                                )
                            except Exception:
                                logger.warning("Falha ao registrar clipe (câmera %s)", self.camera.get("name"))
                            if self._clip_event_id is not None:
                                try:
                                    self.storage.update_event_clip_path(self._clip_event_id, self._clip_path)
                                except Exception:
                                    logger.warning("Falha ao linkar clipe ao evento (câmera %s)", self.camera.get("name"))
                        else:
                            # No frames written (e.g. failed encoder): drop the
                            # empty file instead of registering a broken clip.
                            try:
                                os.remove(self._clip_path)
                            except Exception:
                                pass
                        try:
                            self.storage.prune_event_clips(self.camera["id"], keep=clip_keep, max_age_days=clip_days)
                        except Exception:
                            logger.warning("Falha ao podar clipes (câmera %s)", self.camera.get("name"))
                except Exception:
                    logger.exception("Falha na gravação do clipe (câmera %s)", self.camera.get("name"))
                    try:
                        self._clip_writer.release()
                    except Exception:
                        pass
                    self._clip_writer = None

            # Look up zone classification and schedule (once)
            zone_name = self.camera.get("zone")
            zone_classification = None
            zone_schedule = None
            zone_direction_line = None
            if zone_name:
                zones = self.storage.list_zones()
                zone_obj = next((z for z in zones if z["name"] == zone_name), None)
                if zone_obj:
                    zone_classification = zone_obj.get("classification")
                    zone_schedule = zone_obj.get("schedule")
                    zone_retention = zone_obj.get("retention_policy")
                    zone_direction_line = zone_obj.get("direction_line")
                    thumb_keep, thumb_days = resolve_retention(zone_retention, "thumbnails", THUMBNAIL_HISTORY_SIZE)
                    clip_keep, clip_days = resolve_retention(zone_retention, "clips", CLIP_HISTORY_SIZE)

            exclusion_polygons = self.camera.get("exclusion_zones") or []
            motion_detected = motion_detector.detect(frame, exclusion_polygons=exclusion_polygons)
            if motion_detected:
                last_motion_time = time.time()
                no_motion_alerted = False
                motion_reported = True

                try:
                    detections = self.object_detector.detect(frame)
                    detections = filter_detections_by_classes(detections, self.camera.get("alert_classes"))
                    if exclusion_polygons:
                        detections = [d for d in detections if not bbox_center_in_polygons(d["bbox"], exclusion_polygons)]

                    tracks = tracker.update(detections, now=now)

                    loitering = check_loitering(
                        tracks, now, LOITERING_SECONDS, LOITERING_MAX_DISTANCE, set(LOITERING_LABELS)
                    )

                    fall = any(check_fall(d, FALL_ASPECT_RATIO) for d in detections)

                    direction = None
                    if zone_direction_line and tracks:
                        if zone_direction_line.get("axis") == "vertical":
                            line_px = {"axis": "vertical", "x": zone_direction_line["position"] * frame.shape[1]}
                        else:
                            line_px = {"axis": "horizontal", "y": zone_direction_line["position"] * frame.shape[0]}
                        for t in tracks:
                            direction = check_direction_crossing(t["prev_centroid"], t["centroid"], line_px)
                            if direction is not None:
                                break

                    identity_info = None
                    identity_label = None
                    if detections and self.identity_enabled():
                        for det in detections:
                            if det["label"] in RECOGNITION_LABELS:
                                bbox = det["bbox"]
                                x, y, w, h = bbox["x"], bbox["y"], bbox["w"], bbox["h"]
                                crop = frame[y:y + h, x:x + w]
                                if crop.size > 0:
                                    identity_info = self.identity_recognizer.recognize(crop, det["label"])
                                    identity_label = det["label"]
                                    break

                    # N0/N1: a captura apenas PRODUZ eventos; NÃO decide nem
                    # dispara alerta/HA (isso é N2–N4, a cargo de AlertRuleEngine).
                    now = time.time()
                    event = self.build_candidate_event(
                        detections, identity_info, identity_label, zone_name,
                        zone_classification, zone_schedule, now, fall, loitering,
                        direction, None, no_motion=False,
                    )
                    if self._should_emit_event(identity_info, fall, loitering, direction, storage_frame, now):
                        thumb_path = self._capture_thumbnail(
                            storage_frame, None, time.time(), thumb_keep, thumb_days,
                            event_id=event.event_id,
                        )
                        event.thumbnail_path = thumb_path or self._latest_thumbnail_path()
                        self.event_bus.enqueue(event)
                        # Inicia a gravação do clipe (janela pré-evento + pós-evento);
                        # o loop contínuo de escrita permanece em run().
                        self.start_clip(event.event_id)
                except Exception:
                    logger.exception("Erro no processamento do frame (câmera %s)", self.camera.get("name"))
                    time.sleep(1)
                    continue

                # Thumbnail history: captura com dedup durante movimento contínuo
                now_thumb = time.time()
                self._capture_thumbnail(storage_frame, None, now_thumb, thumb_keep, thumb_days, event_id=None)
            else:
                # No motion: after NO_MOTION_ALERT_SECONDS without any occurrence, send "sem movimento"
                if should_send_no_motion(
                    last_motion_time, motion_reported, no_motion_alerted,
                    time.time(), NO_MOTION_ALERT_SECONDS,
                ):
                    no_motion_alerted = True
                    ev = self.build_candidate_event(
                        [], None, None, zone_name, zone_classification, zone_schedule,
                        time.time(), False, None, None, None, no_motion=True,
                    )
                    # Força salvar o frame atual (cena quieta) -> grid mostra a
                    # cena real, não a imagem anterior (stale).
                    thumb_path = self._capture_thumbnail(
                        storage_frame, "no_motion", time.time(),
                        thumb_keep, thumb_days, event_id=None, force=True,
                    )
                    ev.thumbnail_path = thumb_path or self._latest_thumbnail_path()
                    self.event_bus.enqueue(ev)
                    motion_reported = False

            time.sleep(FRAME_WAIT_SECONDS)


def triage_n1(detections, no_motion):
    """Triagem na borda (N1): descarta ruído, mantém se há detecções reais
    ou se for meta-evento (no_motion)."""
    if no_motion:
        return True
    return bool(detections)


def should_send_no_motion(last_motion_time, motion_reported, no_motion_alerted, now, threshold):
    """Decide se deve emitir 'sem movimento'.

    Só deve ocorrer se houve um evento de movimento/atividade efetivamente
    emitido desde o último 'sem movimento' (motion_reported), evitando
    repetições causadas por ruído do detector que não gera evento real.
    """
    return (
        last_motion_time is not None
        and motion_reported
        and not no_motion_alerted
        and (now - last_motion_time) >= threshold
    )


def filter_detections_by_classes(detections, alert_classes):
    """Mantém apenas detecções cujo label está em alert_classes.
    alert_classes None/vazio = todas as classes."""
    if not alert_classes:
        return detections
    allowed = set(alert_classes)
    return [d for d in detections if d["label"] in allowed]


def is_within_schedule(schedule, now=None):
    """True se `now` (epoch) está dentro do schedule {"start": "HH:MM", "end": "HH:MM"}.
    Sem schedule → sempre True. Suporta virada de meia-noite (start > end)."""
    if not schedule:
        return True
    start = schedule.get("start")
    end = schedule.get("end")
    if not start or not end:
        return True
    now = now if now is not None else time.time()
    current = time.strftime("%H:%M", time.localtime(now))
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end


def get_cooldown_for_event(event_type):
    """Cooldown específico por evento, com fallback para o global."""
    return ALERT_COOLDOWN_BY_EVENT.get(event_type, ALERT_COOLDOWN_SECONDS)


def resolve_retention(policy, kind, default):
    """Resolve (keep, max_age_days) da política de retenção da zona para um tipo.

    policy: dict {"thumbnails": N, "clips": N, "days": N} (campos opcionais).
    kind: "thumbnails" ou "clips".
    Sem política → (default, None). keep=0 é respeitado (apaga tudo).
    """
    if not policy:
        return default, None
    keep = policy.get(kind)
    days = policy.get("days")
    return (int(keep) if keep is not None else default,
            int(days) if days is not None else None)


class CircularFrameBuffer:
    """Buffer circular de frames (janela pré-evento). Descarta o mais antigo."""

    def __init__(self, maxlen: int):
        self.maxlen = maxlen
        self._items = []

    def push(self, frame):
        self._items.append(frame)
        if len(self._items) > self.maxlen:
            self._items.pop(0)

    def frames(self):
        return list(self._items)


def should_capture_thumbnail(last_thumb_time, now, interval):
    if last_thumb_time is None:
        return True
    return (now - last_thumb_time) >= interval


_THUMBNAIL_MINI_SIZE = 64


def _thumbnail_mini(frame, size=_THUMBNAIL_MINI_SIZE):
    """Miniatura para o estado de dedup (memória baixa por câmera)."""
    if frame is None:
        return None
    try:
        return cv2.resize(frame, (size, size), interpolation=cv2.INTER_AREA)
    except Exception:
        return None


def frames_similar(a, b, threshold):
    """True se os frames são visualmente similares (NÃO salvar duplicata).

    Redimensiona ambos para 64x64 grayscale, absdiff e média da diferença.
    threshold = diferença média por pixel tolerável (ruído de sensor).
    Calibração (480x640 sintética): idêntico=0.0, jpeg roundtrip=0.0,
    ruído sigma3=~0.97, objeto forte 2.5% do frame=~9.1. Limiar 3.0 cobre
    ruído leve e separa mudança real de cena. None/erro -> False (nunca
    bloquear: se não der para comparar, salvar).
    """
    if a is None or b is None:
        return False
    try:
        mini_a = cv2.resize(a, (_THUMBNAIL_MINI_SIZE, _THUMBNAIL_MINI_SIZE))
        mini_b = cv2.resize(b, (_THUMBNAIL_MINI_SIZE, _THUMBNAIL_MINI_SIZE))
        gray_a = cv2.cvtColor(mini_a, cv2.COLOR_BGR2GRAY)
        gray_b = cv2.cvtColor(mini_b, cv2.COLOR_BGR2GRAY)
        diff = cv2.absdiff(gray_a, gray_b)
        return cv2.mean(diff)[0] <= threshold
    except Exception:
        return False


class CameraManager:
    def __init__(self, storage: EventStorage, alerts: AlertService, object_detector: ObjectDetector, identity_recognizer=None, event_bus=None):
        self.storage = storage
        self.alerts = alerts
        self.object_detector = object_detector
        self.identity_recognizer = identity_recognizer
        self.event_bus = event_bus
        self.workers = {}
        self.lock = threading.Lock()
        self.monitor_thread = threading.Thread(target=self.monitor_cameras, daemon=True)

    def start(self):
        self.storage.seed_cameras(DEFAULT_CAMERAS)
        self.monitor_thread.start()

    def monitor_cameras(self):
        while True:
            with self.lock:
                cameras = self.storage.list_cameras()
                active_ids = set(self.workers.keys())
                camera_ids = set(camera["id"] for camera in cameras)

                for camera in cameras:
                    if camera["id"] not in active_ids:
                        worker = CameraWorker(camera, self.storage, self.alerts, self.object_detector, self.identity_recognizer, self.event_bus)
                        worker.start()
                        self.workers[camera["id"]] = worker

                for camera_id in list(active_ids - camera_ids):
                    worker = self.workers.pop(camera_id, None)
                    if worker:
                        worker.stop()

            time.sleep(10)

    def get_status(self):
        with self.lock:
            return [worker.status() for worker in self.workers.values()]

    def get_latest_frame(self, camera_id):
        with self.lock:
            worker = self.workers.get(camera_id)
        if worker is None:
            return None, None
        return worker.get_latest_frame()

    def request_clip(self, camera_id, event_id):
        """Pede ao worker da câmera que grave o clipe do evento (janela
        pré-evento + pós-evento). Chamado pelo AlertRuleEngine na decisão N4."""
        with self.lock:
            worker = self.workers.get(camera_id)
        if worker is not None:
            worker.start_clip(event_id)


def main():
    storage = EventStorage()
    storage.ensure_default_routing(DEFAULT_ROUTING)
    alerts = AlertService(storage=storage)
    alerts.register_handler(telegram_handler)
    alerts.register_handler(mqtt_handler)
    alerts.register_handler(home_assistant_handler)
    alerts.register_handler(siren_handler)
    alerts.routing = storage.get_all_routing()

    object_detector = ObjectDetector(
        model_path=DETECTOR_MODEL_PATH,
        confidence_threshold=DETECTOR_CONFIDENCE,
        iou_threshold=DETECTOR_IOU,
        classes=DETECTOR_CLASSES,
    )

    if PRIVACY_MODE:
        storage.set_setting("privacy_mode", "true")
    elif storage.get_setting("privacy_mode") is None:
        storage.set_setting("privacy_mode", "false")

    if is_privacy_mode_on(storage.get_setting("privacy_mode")):
        logger.info("Modo privacidade ativo — reconhecimento de identidade desligado")
        identity_recognizer = None
    else:
        identity_recognizer = build_recognizer(storage)
    event_bus = LocalEventQueue()
    camera_manager = CameraManager(storage, alerts, object_detector, identity_recognizer, event_bus)
    camera_manager.start()

    # Consumidor da fila: AlertRuleEngine decide N2–N4 (persiste, alerta e
    # pede clipe). O worker apenas PRODUZ eventos N0/N1 no event_bus.
    alert_engine = AlertRuleEngine(storage, alerts, camera_manager)
    event_bus.subscribe(alert_engine.handle)
    event_bus.start()

    # Register device with HA via MQTT auto-discovery
    cameras = storage.list_cameras()
    mqtt_register_device(cameras)

    storage.seed_zones([
        {"name": "Entrada", "classification": "pública"},
        {"name": "Estacionamento", "classification": "pública"},
        {"name": "Corredor", "classification": "pública"},
        {"name": "Sala de servidores", "classification": "privativa"},
        {"name": "Recepção", "classification": "segurança"},
    ])

    app = create_app(camera_manager=camera_manager, alerts=alerts, event_bus=event_bus)
    app.run(host=SERVER_HOST, port=SERVER_PORT)
