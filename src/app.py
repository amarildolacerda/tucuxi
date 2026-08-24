import cv2
import os
import time
import threading
from datetime import datetime, timezone
from flask import Flask, jsonify, render_template, request, Response, send_file, g, abort
from .camera import CameraStream
from .storage import EventStorage
from .masking import frame_for_storage
from .config import is_privacy_mode_on
from . import config as cfg
from .notifications import CHANNELS, EVENT_TYPES
from .status import build_system_status
from .auth import setup_auth, require_auth, require_permission, has_permission, PERMISSIONS, DEFAULT_ROLE_PERMISSIONS, invalidate_permission_cache
import base64
import json
import numpy as np
from typing import Optional
import logging
import io
import zipfile

logger = logging.getLogger(__name__)


def _is_valid_schedule(schedule):
    if not isinstance(schedule, dict):
        return False
    start = schedule.get("start")
    end = schedule.get("end")
    if not isinstance(start, str) or not isinstance(end, str):
        return False
    try:
        time.strptime(start, "%H:%M")
        time.strptime(end, "%H:%M")
    except ValueError:
        return False
    return True


def _is_valid_retention_policy(policy):
    """True se policy é None ou dict com chaves opcionais thumbnails/clips/days (ints >= 0)."""
    if policy is None:
        return True
    if not isinstance(policy, dict):
        return False
    for key in ("thumbnails", "clips", "days"):
        if key in policy:
            value = policy[key]
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                return False
    return True


def _effective_event_prune_policy(storage):
    """Política efetiva de prune de eventos: defaults do config sobrescritos
    pela política salva via POST /api/events/prune (settings.event_prune_policy).

    A página de retenção mostra e edita esta política; o scheduler automático
    também a usa — valores salvos na UI têm precedência sobre o config.
    """
    policy = {
        "enabled": cfg.EVENT_PRUNE_ENABLED,
        "type_days": dict(cfg.EVENT_PRUNE_TYPE_DAYS),
        "default_days": cfg.EVENT_PRUNE_DEFAULT_DAYS,
        "max_age_days": cfg.EVENT_PRUNE_MAX_AGE_DAYS,
        "interval_seconds": cfg.EVENT_PRUNE_INTERVAL_SECONDS,
    }
    raw = storage.get_setting("event_prune_policy")
    if not raw:
        return policy
    try:
        saved = json.loads(raw)
    except (ValueError, TypeError):
        return policy
    if not isinstance(saved, dict):
        return policy
    if isinstance(saved.get("type_days"), dict):
        for key, value in saved["type_days"].items():
            if isinstance(key, str) and isinstance(value, (int, float)) and not isinstance(value, bool):
                policy["type_days"][key] = float(value)
    for key in ("default_days", "max_age_days"):
        value = saved.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            policy[key] = float(value)
    return policy


def _is_valid_direction_line(line):
    """True se None ou dict {"axis": "vertical"|"horizontal", "position": float 0-1}."""
    if line is None:
        return True
    if not isinstance(line, dict):
        return False
    axis = line.get("axis")
    position = line.get("position")
    if axis not in ("vertical", "horizontal"):
        return False
    if isinstance(position, bool) or not isinstance(position, (int, float)):
        return False
    return 0.0 <= position <= 1.0


def _validate_mask_polygons(mask_polygons):
    """Valida mask_polygons (mesmo formato de exclusion_zones).

    Retorna None se válido, ou uma mensagem de erro. Polígonos malformados
    (ponto sem y, ponto não-dict, x/y não numérico) quebrariam
    apply_mask_blur no worker (frame_for_storage, fora de try/except) —
    matando a thread da câmera silenciosamente.
    """
    if mask_polygons is None:
        return None
    if not isinstance(mask_polygons, list):
        return "mask_polygons deve ser uma lista de polígonos"
    for poly in mask_polygons:
        if not isinstance(poly, list) or not poly:
            return "mask_polygons deve ser uma lista de polígonos (cada polígono é uma lista não vazia de pontos)"
        for point in poly:
            if not isinstance(point, dict):
                return "cada ponto de mask_polygons deve ser um objeto com x e y"
            x = point.get("x")
            y = point.get("y")
            if (not isinstance(x, (int, float)) or isinstance(x, bool)
                    or not isinstance(y, (int, float)) or isinstance(y, bool)):
                return "cada ponto de mask_polygons deve ter x e y numéricos"
    return None


def _get_allowed_camera_ids(user):
    """Return the set of camera_ids the user can access, or None for unrestricted."""
    if not user or user.get("role") != "viewer":
        return None
    ids = storage.get_user_cameras(user["id"])
    return set(ids) if ids else None


def _camera_allowed(user, camera_id):
    """True if the user can access this specific camera."""
    allowed = _get_allowed_camera_ids(user)
    if allowed is None:
        return True
    return camera_id in allowed


def _filter_cameras(cameras, user):
    """Filter a list of camera dicts by user access."""
    allowed = _get_allowed_camera_ids(user)
    if allowed is None:
        return cameras
    return [c for c in cameras if c["id"] in allowed]


def _filter_events_by_cameras(events, user):
    """Filter events by user camera access."""
    allowed = _get_allowed_camera_ids(user)
    if allowed is None:
        return events
    return [e for e in events if str(e.get("camera_id", "")) in {str(i) for i in allowed}]


try:
    from .identity import build_recognizer, IdentityRecognizer
except Exception:
    build_recognizer = None
    IdentityRecognizer = None


def create_app(camera_manager=None, db_path=None, alerts=None, event_bus=None):
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.event_bus = event_bus
    storage = EventStorage(db_path) if db_path is not None else EventStorage()
    # recognizer_factory hook: tests or callers may set app.recognizer_factory = lambda storage: recognizer
    def _make_recognizer() -> Optional[object]:
        # Prefer the shared recognizer used by the camera workers so cache
        # refreshes (enroll/remove/import) propagate to live recognition.
        if camera_manager is not None and getattr(camera_manager, "identity_recognizer", None) is not None:
            return camera_manager.identity_recognizer
        if hasattr(app, "recognizer_factory") and callable(app.recognizer_factory):
            return app.recognizer_factory(storage)
        if build_recognizer is None:
            return None
        return build_recognizer(storage)

    app.recognizer_factory_internal = _make_recognizer

    # ── Auth setup ──
    setup_auth(app, storage)

    @app.route("/health")
    def health():
        return jsonify({"status": "ok"})

    @app.route("/status")
    def status():
        cameras = storage.list_cameras()
        events = storage.list_events(limit=10)
        status_payload = {
            "status": "ok",
            "version": cfg.APP_VERSION,
            "camera_count": len(cameras),
            "recent_events": len(events),
            "cameras": cameras,
        }

        if camera_manager is not None:
            status_payload["worker_status"] = camera_manager.get_status()
            status_payload["active_workers"] = len(status_payload["worker_status"])

        return jsonify(status_payload)

    @app.route("/api/system-status")
    def api_system_status():
        return jsonify(build_system_status(camera_manager))

    @app.route("/api/config")
    def api_config():
        """Parâmetros de configuração efetivos (read-only) para o painel 'Configurações em uso'."""
        return jsonify({
            "motion": {
                "min_area_px": cfg.MOTION_MIN_AREA,
                "frame_wait_seconds": cfg.FRAME_WAIT_SECONDS,
                "worker_healthy_timeout_seconds": cfg.WORKER_HEALTHY_TIMEOUT_SECONDS,
            },
            "alerts": {
                "no_motion_alert_seconds": cfg.NO_MOTION_ALERT_SECONDS,
                "cooldown_seconds": cfg.ALERT_COOLDOWN_SECONDS,
                "cooldown_by_event": cfg.ALERT_COOLDOWN_BY_EVENT,
            },
            "detector": {
                "model_path": cfg.DETECTOR_MODEL_PATH or "não configurado",
                "confidence": cfg.DETECTOR_CONFIDENCE,
                "iou": cfg.DETECTOR_IOU,
                "classes": cfg.DETECTOR_CLASSES,
            },
            "identity": {
                "enabled": cfg.IDENTITY_ENABLED,
                "face_model_path": cfg.IDENTITY_FACE_MODEL_PATH or "não configurado",
                "reid_model_path": cfg.IDENTITY_REID_MODEL_PATH or "não configurado",
                "match_threshold": cfg.IDENTITY_MATCH_THRESHOLD,
            },
            "thumbnails": {
                "interval_seconds": cfg.THUMBNAIL_INTERVAL_SECONDS,
                "diff_threshold": cfg.THUMBNAIL_DIFF_THRESHOLD,
                "history_size": cfg.THUMBNAIL_HISTORY_SIZE,
            },
            "clips": {
                "pre_seconds": cfg.CLIP_PRE_SECONDS,
                "post_seconds": cfg.CLIP_POST_SECONDS,
                "fps": cfg.CLIP_FPS,
                "history_size": cfg.CLIP_HISTORY_SIZE,
            },
            "tracking": {
                "iou_threshold": cfg.TRACK_IOU_THRESHOLD,
                "max_age_seconds": cfg.TRACK_MAX_AGE_SECONDS,
            },
            "behavior": {
                "loitering_seconds": cfg.LOITERING_SECONDS,
                "loitering_max_distance": cfg.LOITERING_MAX_DISTANCE,
                "loitering_labels": cfg.LOITERING_LABELS,
                "fall_aspect_ratio": cfg.FALL_ASPECT_RATIO,
            },
"event_pruning": _effective_event_prune_policy(storage),
            "privacy_mode": cfg.PRIVACY_MODE,
        })

    @app.route("/api/events/prune", methods=["POST"])
    @require_permission("prune_events")
    def api_events_prune():
        """Executa limpeza de eventos sob demanda e SALVA a política de retenção.
        Body opcional: {"type_days": {"motion_detected": 1}, "default_days": 7, "max_age_days": 30}
        Se omitido, usa a política efetiva (config + política salva).
        """
        data = request.get_json(silent=True) or {}
        type_days = data.get("type_days")
        default_days = data.get("default_days")
        max_age_days = data.get("max_age_days")

        # Validação da política enviada (se houver) antes de salvar/executar.
        if type_days is not None:
            if not isinstance(type_days, dict) or not all(
                isinstance(k, str)
                and isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0
                for k, v in type_days.items()
            ):
                return jsonify({"error": "type_days deve ser dict {tipo: dias >= 0}"}), 400
        for name, value in (("default_days", default_days), ("max_age_days", max_age_days)):
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0):
                return jsonify({"error": f"{name} deve ser número >= 0"}), 400

        effective = _effective_event_prune_policy(storage)
        if type_days is not None or default_days is not None or max_age_days is not None:
            # Persiste a política: campos omitidos herdam a política efetiva atual
            # (type_days parcial é mesclado, não substituído).
            saved_type_days = dict(effective["type_days"])
            if type_days is not None:
                saved_type_days.update(type_days)
            saved = {
                "type_days": saved_type_days,
                "default_days": default_days if default_days is not None else effective["default_days"],
                "max_age_days": max_age_days if max_age_days is not None else effective["max_age_days"],
            }
            storage.set_setting("event_prune_policy", json.dumps(saved))
            effective = saved

        deleted = storage.prune_events(
            type_days=effective["type_days"],
            default_days=effective["default_days"],
            max_age_days=effective["max_age_days"],
        )
        return jsonify({"deleted": deleted, "saved": True})

    @app.route("/api/events/<int:event_id>/retain", methods=["PUT"])
    @require_permission("retain_event")
    def api_event_retain(event_id):
        """Toggle retain flag on an event."""
        data = request.get_json(silent=True) or {}
        retain = data.get("retain")
        if retain is None:
            return jsonify({"error": "retain (bool) é obrigatório"}), 400
        try:
            with storage.lock:
                cursor = storage.connection.cursor()
                cursor.execute(
                    "UPDATE events SET retained = ? WHERE id = ?",
                    (1 if retain else 0, event_id)
                )
                storage.connection.commit()
                if cursor.rowcount == 0:
                    return jsonify({"error": "Evento não encontrado"}), 404
            return jsonify({"status": "ok", "retained": bool(retain)})
        except Exception:
            logger.exception("Erro ao atualizar retain")
            return jsonify({"error": "Erro interno"}), 500

    @app.route("/workers")
    def workers():
        return jsonify({
            "workers": camera_manager.get_status() if camera_manager is not None else [],
            "active_workers": len(camera_manager.get_status()) if camera_manager is not None else 0,
        })

    @app.route("/api/dashboard")
    def api_dashboard():
        user = getattr(g, "current_user", None)
        cameras = _filter_cameras(storage.list_cameras(), user)
        events = _filter_events_by_cameras(storage.list_events(limit=100), user)
        zones = storage.list_zones()
        n0_events = storage.list_events(level=0, limit=100)
        worker_status = camera_manager.get_status() if camera_manager is not None else []
        return jsonify({
            "cameras": cameras,
            "events": events,
            "zones": zones,
            "n0_events": n0_events,
            "worker_status": worker_status,
        })

    @app.route("/camera/<int:camera_id>/snapshot")
    def camera_snapshot(camera_id):
        user = getattr(g, "current_user", None)
        if not _camera_allowed(user, camera_id):
            return jsonify({"error": "Sem permissão para acessar esta câmera"}), 403
        import logging
        import threading
        log = logging.getLogger(__name__)

        camera = storage.get_camera(camera_id)
        if not camera:
            return jsonify({"error": "Câmera não encontrada"}), 404

        # Fast path: serve the worker's latest in-memory frame (no new capture).
        # ?raw=1 retorna o frame sem máscara (usado no preview do formulário de câmera).
        raw = request.args.get("raw") == "1"
        if camera_manager is not None:
            frame, ts = camera_manager.get_latest_frame(camera_id)
            if frame is not None:
                try:
                    out = frame if raw else frame_for_storage(frame, camera.get("mask_polygons"))
                    ok, jpg = cv2.imencode(".jpg", out)
                    if ok:
                        captured_iso = datetime.fromtimestamp(ts, timezone.utc).isoformat()
                        return Response(
                            jpg.tobytes(),
                            mimetype="image/jpeg",
                            headers={"Cache-Control": "no-store", "X-Snapshot-Time": captured_iso},
                        )
                except Exception:
                    pass  # fall through to VideoCapture below

        source = camera["source"]
        log.info("Snapshot requested for camera %s (source=%s)", camera_id, source)

        result = {"frame": None, "error": None}

        def capture_frame():
            try:
                cap = cv2.VideoCapture(source)
                if not cap.isOpened():
                    result["error"] = "Não foi possível abrir a fonte de vídeo"
                    return

                is_network = source.startswith("http") or source.startswith("rtsp") or source.endswith(".m3u8")
                if is_network:
                    cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000)
                    cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000)
                    # Skip buffered/garbage frames
                    for _ in range(3):
                        cap.read()

                success, frame = cap.read()
                cap.release()

                if not success or frame is None:
                    result["error"] = "Não foi possível capturar o frame"
                else:
                    result["frame"] = frame
            except Exception as e:
                result["error"] = f"Exceção: {e}"

        thread = threading.Thread(target=capture_frame, daemon=True)
        thread.start()
        thread.join(timeout=10)

        if thread.is_alive():
            log.warning("Snapshot timed out for camera %s (source=%s)", camera_id, source)
            return jsonify({"error": "Timeout ao capturar frame (stream inacessível)"}), 504

        if result["error"]:
            log.warning("Snapshot failed for camera %s: %s", camera_id, result["error"])
            return jsonify({"error": result["error"]}), 502

        frame = result["frame"]
        if not raw:
            frame = frame_for_storage(frame, camera.get("mask_polygons"))
        success, jpg = cv2.imencode(".jpg", frame)
        if not success:
            return jsonify({"error": "Falha ao codificar imagem"}), 500

        log.info("Snapshot OK for camera %s", camera_id)
        # X-Snapshot-Time = ISO 8601 (UTC) do momento da captura do frame,
        # para o dashboard mostrar "capturado há Xs" e envelhecer dinamicamente.
        captured_iso = datetime.now(timezone.utc).isoformat()
        return Response(
            jpg.tobytes(),
            mimetype="image/jpeg",
            headers={
                "Cache-Control": "no-store",
                "X-Snapshot-Time": captured_iso,
            },
        )

    @app.route("/camera/<int:camera_id>/thumbnails")
    def camera_thumbnails(camera_id):
        user = getattr(g, "current_user", None)
        if not _camera_allowed(user, camera_id):
            return jsonify({"error": "Sem permissão para acessar esta câmera"}), 403
        camera = storage.get_camera(camera_id)
        if not camera:
            return jsonify({"error": "Câmera não encontrada"}), 404
        items = storage.list_camera_thumbnails(camera_id, limit=20)
        out = []
        for it in items:
            out.append({
                "id": it["id"],
                "timestamp": it["timestamp"],
                "event_type": it["event_type"],
                "url": f"/thumbnails/{it['id']}/image",
                "event_id": it.get("event_id"),
                "level": it.get("event_level"),
                "disposition": it.get("event_disposition"),
                "dropped": bool(it.get("event_dropped")) if it.get("event_dropped") is not None else None,
            })
        return jsonify(out)

    @app.route("/thumbnails/<int:thumb_id>/image")
    def thumbnail_image(thumb_id):
        item = storage.get_camera_thumbnail(thumb_id)
        if not item:
            return jsonify({"error": "Thumbnail não encontrado"}), 404
        path = item["path"]
        if not os.path.exists(path):
            return jsonify({"error": "Thumbnail não encontrado"}), 404
        return send_file(path, mimetype="image/jpeg")

    @app.route("/camera/<int:camera_id>/clips")
    def camera_clips(camera_id):
        user = getattr(g, "current_user", None)
        if not _camera_allowed(user, camera_id):
            return jsonify({"error": "Sem permissão para acessar esta câmera"}), 403
        camera = storage.get_camera(camera_id)
        if not camera:
            return jsonify({"error": "Câmera não encontrada"}), 404
        items = storage.list_event_clips(camera_id, limit=20)
        out = []
        for it in items:
            out.append({
                "id": it["id"],
                "timestamp": it["timestamp"],
                "duration_s": it["duration_s"],
                "url": f"/clips/{it['id']}/video",
            })
        return jsonify(out)

    @app.route("/clips/<int:clip_id>")
    def clip_metadata(clip_id):
        item = storage.get_event_clip(clip_id)
        if not item:
            return jsonify({"error": "Clipe não encontrado"}), 404
        return jsonify(item)

    @app.route("/clips/<int:clip_id>/video")
    def clip_video(clip_id):
        item = storage.get_event_clip(clip_id)
        if not item:
            return jsonify({"error": "Clipe não encontrado"}), 404
        path = item["path"]
        if not os.path.exists(path):
            return jsonify({"error": "Clipe não encontrado"}), 404
        return send_file(path, mimetype="video/mp4")

    @app.route("/export")
    def export_events():
        """Exporta eventos + thumbnails + clipes em um arquivo ZIP (Fase 5.4).

        Query params: camera_id (int), start (epoch), end (epoch), limit (default 500, cap 2000).
        """
        camera_id = request.args.get("camera_id", type=int)
        start = request.args.get("start", type=float)
        end = request.args.get("end", type=float)
        limit = request.args.get("limit", default=500, type=int)
        limit = max(1, min(limit, 2000))

        events = storage.list_events(camera_id=camera_id, limit=limit, start=start, end=end)
        for ev in events:
            ev["thumbnail_path"] = storage.get_event_thumbnail_path(ev["id"])

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("events.json", json.dumps(events, indent=2, default=str))
            for ev in events:
                thumb = ev.get("thumbnail_path")
                if thumb and os.path.exists(thumb):
                    ext = os.path.splitext(thumb)[1] or ".jpg"
                    zf.write(thumb, f"thumbnails/{ev['id']}{ext}")
                clip = storage.get_event_clip_path(ev["id"])
                if clip and os.path.exists(clip):
                    zf.write(clip, f"clips/{os.path.basename(clip)}")
        buf.seek(0)
        return send_file(
            buf,
            mimetype="application/zip",
            as_attachment=True,
            download_name=f"secur-export-{int(time.time())}.zip",
        )

    @app.route("/docs")
    def docs():
        api_docs = [
            {"path": "/", "method": "GET", "description": "Dashboard HTML"},
            {"path": "/health", "method": "GET", "description": "Service health check"},
            {"path": "/status", "method": "GET", "description": "Service and worker summary"},
            {"path": "/workers", "method": "GET", "description": "Current worker status"},
            {"path": "/api/dashboard", "method": "GET", "description": "Payload agregado do dashboard (câmeras, eventos, zonas, N0, status dos workers)"},
            {"path": "/camera/<id>/snapshot", "method": "GET", "description": "Capture a current frame preview"},
            {"path": "/cameras", "method": "GET", "description": "List cameras"},
            {"path": "/cameras", "method": "POST", "description": "Add a new camera"},
            {"path": "/cameras/<id>", "method": "PUT", "description": "Update a camera"},
            {"path": "/cameras/<id>", "method": "DELETE", "description": "Remove a camera"},
            {"path": "/zones", "method": "GET", "description": "List zones"},
            {"path": "/zones", "method": "POST", "description": "Add a new zone"},
            {"path": "/zones/<id>", "method": "PUT", "description": "Update a zone"},
            {"path": "/zones/<id>", "method": "DELETE", "description": "Remove a zone"},
            {"path": "/events", "method": "GET", "description": "Recent event history"},
            {"path": "/camera/<id>/thumbnails", "method": "GET", "description": "Lista os últimos thumbnails da câmera"},
            {"path": "/thumbnails/<id>/image", "method": "GET", "description": "Imagem JPEG de um thumbnail"},
            {"path": "/camera/<id>/clips", "method": "GET", "description": "Lista os últimos clipes de vídeo da câmera"},
            {"path": "/clips/<id>", "method": "GET", "description": "Metadados de um clipe"},
            {"path": "/clips/<id>/video", "method": "GET", "description": "Stream MP4 de um clipe"},
            {"path": "/export", "method": "GET", "description": "Exporta eventos + thumbnails + clipes em ZIP"},
            {"path": "/api/notifications", "method": "GET", "description": "Canais, eventos e routing de notificações"},
            {"path": "/api/notifications/routing", "method": "PUT", "description": "Atualiza routing de um evento em um canal"},
            {"path": "/api/classes", "method": "GET", "description": "Lista de classes de objetos detectáveis (filtro por câmera)"},
            {"path": "/api/settings", "method": "GET", "description": "Flags globais (modo privacidade)"},
            {"path": "/api/settings", "method": "PUT", "description": "Atualiza flags globais (privacy_mode)"},
            {"path": "/login", "method": "GET", "description": "Tela de login"},
            {"path": "/api/auth/login", "method": "POST", "description": "Autenticar (username/password)"},
            {"path": "/api/auth/logout", "method": "POST", "description": "Encerrar sessão"},
            {"path": "/api/auth/me", "method": "GET", "description": "Dados do usuário logado + permissões"},
            {"path": "/users", "method": "GET", "description": "Gestão de usuários (HTML)"},
            {"path": "/api/users", "method": "GET", "description": "Lista usuários"},
            {"path": "/api/users", "method": "POST", "description": "Criar usuário"},
            {"path": "/api/users/<id>", "method": "PUT", "description": "Editar usuário"},
            {"path": "/permissions", "method": "GET", "description": "Permissões por role (HTML)"},
            {"path": "/api/permissions", "method": "GET", "description": "Permissões atuais por role"},
            {"path": "/api/permissions", "method": "PUT", "description": "Atualizar permissões de um role"},
            {"path": "/api/api-keys", "method": "GET", "description": "Lista API keys"},
            {"path": "/api/api-keys", "method": "POST", "description": "Criar API key (retorna chave uma vez)"},
            {"path": "/api/api-keys/<id>", "method": "DELETE", "description": "Revogar API key"},
            {"path": "/audit", "method": "GET", "description": "Log de auditoria (HTML)"},
            {"path": "/api/audit", "method": "GET", "description": "Lista registros de auditoria (filtro por user, action)"},
        ]
        return render_template("docs.html", api_docs=api_docs)

    @app.route("/cameras")
    def cameras():
        user = getattr(g, "current_user", None)
        cams = storage.list_cameras()
        return jsonify(_filter_cameras(cams, user))

    @app.route("/cameras", methods=["POST"])
    @require_permission("manage_cameras")
    def add_camera():
        payload = request.get_json() or {}
        name = payload.get("name")
        source = payload.get("source")
        zone = payload.get("zone")
        alert_classes = payload.get("alert_classes")
        exclusion_zones = payload.get("exclusion_zones")
        mask_polygons = payload.get("mask_polygons")

        if not name or not source:
            return jsonify({"error": "name and source são obrigatórios"}), 400

        if alert_classes is not None and not isinstance(alert_classes, list):
            return jsonify({"error": "alert_classes deve ser uma lista"}), 400
        if exclusion_zones is not None and not isinstance(exclusion_zones, list):
            return jsonify({"error": "exclusion_zones deve ser uma lista de polígonos"}), 400
        mask_err = _validate_mask_polygons(mask_polygons)
        if mask_err:
            return jsonify({"error": mask_err}), 400

        if not CameraStream.validate_source(source):
            return jsonify({"error": "source inválido ou stream inacessível"}), 400

        camera_id = storage.add_camera(name, source, zone, alert_classes=alert_classes, exclusion_zones=exclusion_zones, mask_polygons=mask_polygons)
        return jsonify({
            "id": camera_id, "name": name, "source": source, "zone": zone,
            "alert_classes": alert_classes, "exclusion_zones": exclusion_zones,
            "mask_polygons": mask_polygons,
        }), 201

    @app.route("/cameras/<int:camera_id>", methods=["PUT"])
    @require_permission("manage_cameras")
    def update_camera(camera_id):
        camera = storage.get_camera(camera_id)
        if not camera:
            return jsonify({"error": "Câmera não encontrada"}), 404

        payload = request.get_json() or {}
        name = payload.get("name")
        source = payload.get("source")
        zone = payload.get("zone")
        alert_classes = payload.get("alert_classes")
        exclusion_zones = payload.get("exclusion_zones")
        mask_polygons = payload.get("mask_polygons")

        if not name or not source:
            return jsonify({"error": "name and source são obrigatórios"}), 400

        if alert_classes is not None and not isinstance(alert_classes, list):
            return jsonify({"error": "alert_classes deve ser uma lista"}), 400
        if exclusion_zones is not None and not isinstance(exclusion_zones, list):
            return jsonify({"error": "exclusion_zones deve ser uma lista de polígonos"}), 400
        mask_err = _validate_mask_polygons(mask_polygons)
        if mask_err:
            return jsonify({"error": mask_err}), 400

        if not CameraStream.validate_source(source):
            return jsonify({"error": "source inválido ou stream inacessível"}), 400

        storage.update_camera(camera_id, name, source, zone, alert_classes=alert_classes, exclusion_zones=exclusion_zones, mask_polygons=mask_polygons)
        updated_camera = storage.get_camera(camera_id)
        return jsonify(updated_camera), 200

    @app.route("/cameras/<int:camera_id>", methods=["DELETE"])
    @require_permission("manage_cameras")
    def delete_camera(camera_id):
        removed = storage.remove_camera(camera_id)
        if not removed:
            return jsonify({"error": "Câmera não encontrada"}), 404
        storage.remove_camera_thumbnails(camera_id)
        storage.remove_event_clips(camera_id)
        return jsonify({"status": "removido"}), 200

    @app.route("/events")
    def events():
        user = getattr(g, "current_user", None)
        level = request.args.get("level", type=int)
        camera_id = request.args.get("camera_id")
        retained = request.args.get("retained", type=int)
        # Retidos são protegidos do prune e não podem ficar fora do corte de 100:
        # com retained=1 o limite sobe para 1000.
        limit = 1000 if retained == 1 else 100
        items = storage.list_events(limit=limit, level=level, camera_id=camera_id, retained=retained)
        items = _filter_events_by_cameras(items, user)
        return jsonify(items)

    @app.route("/api/ingest", methods=["POST"])
    def api_ingest():
        """Borda remota (câmeras E dispositivos/sensores) entra na fila em N1.

        Genérico: aceita JSON {camera_id (id de origem), device_type?, zone?,
        event_type?, details?, detections?, thumbnail_path?, identity_name?, ...}.
        Para sensores (ex.: alagamento), device_type="sensor" e event_type
        (ex.: "flood") é o sinal; detections pode vir vazio.
        """
        bus = getattr(app, "event_bus", None)
        if bus is None:
            return jsonify({"error": "event bus indisponivel"}), 503
        payload = request.get_json(silent=True) or {}
        camera_id = payload.get("camera_id")
        if not camera_id:
            return jsonify({"error": "camera_id obrigatorio"}), 400
        from .events import CameraEvent
        event = CameraEvent(
            camera_id=str(camera_id),
            device_type=payload.get("device_type", "camera"),
            zone=payload.get("zone"),
            zone_classification=payload.get("zone_classification"),
            level=1,
            source="edge",
            event_type=payload.get("event_type"),
            details=payload.get("details"),
            identity_name=payload.get("identity_name"),
            known=payload.get("known"),
            category=payload.get("category"),
            recognition_method=payload.get("recognition_method"),
            thumbnail_path=payload.get("thumbnail_path"),
            detections=payload.get("detections") or [],
            camera_name=payload.get("camera_name"),
            alert_classes=payload.get("alert_classes"),
        )
        bus.enqueue(event)
        return jsonify({"status": "enqueued", "event_id": event.event_id}), 202

    @app.route("/zones")
    def zones():
        return jsonify(storage.list_zones())

    @app.route("/api/notifications")
    def notifications_get():
        routing = storage.get_all_routing()
        return jsonify({
            "channels": CHANNELS,
            "events": EVENT_TYPES,
            "routing": routing,
        })

    @app.route("/api/notifications/routing", methods=["PUT"])
    @require_permission("manage_notifications")
    def notifications_put():
        payload = request.get_json() or {}
        channel = payload.get("channel")
        event_type = payload.get("event_type")
        enabled = payload.get("enabled")
        if enabled is None:
            return jsonify({"error": "enabled é obrigatório"}), 400
        valid_channels = {c["key"] for c in CHANNELS}
        valid_events = {e["key"] for e in EVENT_TYPES}
        if channel not in valid_channels:
            return jsonify({"error": "canal inválido"}), 400
        if event_type not in valid_events:
            return jsonify({"error": "evento inválido"}), 400
        storage.set_routing(channel, event_type, bool(enabled))
        # Regressão: desabilitar um evento no dashboard precisa valer na hora no
        # envio real. O AlertService decide usando `routing` em memória (snapshot
        # do boot, main.py) — sem recarregar, mensagens continuam saindo até o
        # restart, mesmo com o toggle desligado. Recarrega do storage após o PUT.
        if alerts is not None:
            alerts.routing = storage.get_all_routing()
        return jsonify({"status": "ok"}), 200

    @app.route("/api/classes")
    def classes():
        from .config import DETECTOR_CLASSES
        return jsonify({"classes": DETECTOR_CLASSES})

    @app.route("/api/settings")
    def settings_get():
        privacy_mode = storage.get_setting("privacy_mode", "false")
        return jsonify({"privacy_mode": is_privacy_mode_on(privacy_mode)})

    @app.route("/api/settings", methods=["PUT"])
    @require_permission("manage_settings")
    def settings_put():
        payload = request.get_json() or {}
        privacy_mode = payload.get("privacy_mode")
        if not isinstance(privacy_mode, bool):
            return jsonify({"error": "privacy_mode deve ser booleano"}), 400
        storage.set_setting("privacy_mode", "true" if privacy_mode else "false")
        return jsonify({"privacy_mode": privacy_mode}), 200


    # ========== Identity endpoints ==========
    @app.route("/identities", methods=["GET"])
    def list_identities():
        items = storage.list_identities()
        out = []
        for it in items:
            thumb = it.get('thumbnail_path')
            if thumb:
                it['thumbnail_url'] = f"/identities/{it['id']}/thumbnail"
            else:
                it['thumbnail_url'] = None
            out.append(it)
        return jsonify(out)

    @app.route("/identities", methods=["POST"])
    @require_permission("manage_identities")
    def add_identity():
        payload = request.get_json() or {}
        name = payload.get("name")
        species = payload.get("species")
        images_b64 = payload.get("images", [])

        if not name or not species:
            return jsonify({"error": "name and species are required"}), 400
        # validate species against recognizer labels
        try:
            from .identity import RECOGNITION_LABELS
            allowed = set(RECOGNITION_LABELS.values())
        except Exception:
            allowed = set(("person", "animal"))
        if species not in allowed:
            return jsonify({"error": f"species must be one of: {', '.join(sorted(allowed))}"}), 400

        images = []
        for s in images_b64:
            try:
                raw = base64.b64decode(s)
                arr = np.frombuffer(raw, dtype=np.uint8)
                img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if img is not None:
                    images.append(img)
            except Exception:
                continue

        recognizer = app.recognizer_factory_internal()
        if recognizer is None:
            # fallback: save mean embedding directly via storage if no recognizer available
            return jsonify({"error": "identity recognizer not configured"}), 503

        try:
            ident_id = recognizer.enroll(name, species, images)
        except Exception as e:
            return jsonify({"error": str(e)}), 400

        # persist thumbnail (first provided base64) if available
        try:
            if images_b64:
                thumb_b64 = images_b64[0]
                thumb_path = storage.save_identity_thumbnail(name, thumb_b64)
                if thumb_path:
                    storage.update_identity_thumbnail(ident_id, thumb_path)
                else:
                    logger.warning("Falha ao salvar thumbnail para identidade %s", name)
        except Exception:
            logger.exception("Falha ao persistir thumbnail para identidade %s", name)

        return jsonify({"id": ident_id, "name": name, "species": species}), 201

    @app.route('/identities/<int:identity_id>/thumbnail')
    def identity_thumbnail(identity_id: int):
        ident = storage.get_identity(identity_id)
        if not ident or not ident.get('thumbnail_path'):
            return jsonify({'error': 'Thumbnail not found'}), 404
        try:
            from flask import send_file
            return send_file(ident['thumbnail_path'], mimetype='image/jpeg')
        except Exception:
            return jsonify({'error': 'Failed to serve thumbnail'}), 500

    @app.route("/identities/<int:identity_id>", methods=["DELETE"])
    @require_permission("manage_identities")
    def delete_identity(identity_id):
        recognizer = app.recognizer_factory_internal()
        if recognizer is not None and hasattr(recognizer, "remove_identity"):
            removed = recognizer.remove_identity(identity_id)
        else:
            removed = storage.remove_identity(identity_id)
        if not removed:
            return jsonify({"error": "Identity not found"}), 404
        return jsonify({"status": "removido"}), 200

    @app.route('/identities/import', methods=['POST'])
    @require_permission("manage_identities")
    def import_identity():
        """Create an identity directly with a thumbnail (bypass recognizer). Useful for testing."""
        payload = request.get_json() or {}
        name = payload.get('name')
        species = payload.get('species')
        thumb_b64 = payload.get('thumbnail')

        if not name or not species:
            return jsonify({'error': 'name and species are required'}), 400

        # validate species against recognizer labels
        try:
            from .identity import RECOGNITION_LABELS
            allowed = set(RECOGNITION_LABELS.values())
        except Exception:
            allowed = set(("person", "animal"))
        if species not in allowed:
            return jsonify({'error': f"species must be one of: {', '.join(sorted(allowed))}"}), 400

        # create a placeholder embedding file with the real embedder dimension
        try:
            import numpy as _np
            recognizer = app.recognizer_factory_internal()
            dim = 128
            if recognizer is not None:
                for embedder in (getattr(recognizer, "face_embedder", None), getattr(recognizer, "reid_embedder", None)):
                    if embedder is None:
                        continue
                    try:
                        probe = embedder(_np.zeros((32, 32, 3), dtype=_np.uint8))
                        if probe is not None and probe.size > 0:
                            dim = int(probe.size)
                            break
                    except Exception:
                        continue
            emb = _np.zeros((dim,), dtype=_np.float32)
            emb_path = storage.save_identity_embedding(name, emb)
            ident_id = storage.add_identity(name, species, emb_path)
            if thumb_b64:
                thumb_path = storage.save_identity_thumbnail(name, thumb_b64)
                if thumb_path:
                    storage.update_identity_thumbnail(ident_id, thumb_path)
            if recognizer is not None and hasattr(recognizer, "refresh_cache"):
                recognizer.refresh_cache()
            return jsonify({'id': ident_id, 'name': name, 'species': species}), 201
        except Exception as e:
            logger.exception("Falha ao importar identidade")
            return jsonify({'error': 'falha ao importar identidade'}), 500

    @app.route("/zones", methods=["POST"])
    @require_permission("manage_zones")
    def add_zone():
        payload = request.get_json() or {}
        name = payload.get("name")
        classification = payload.get("classification", "pública")
        schedule = payload.get("schedule")
        retention_policy = payload.get("retention_policy")
        direction_line = payload.get("direction_line")

        if not name:
            return jsonify({"error": "name é obrigatório"}), 400

        if classification not in ('privativa', 'segurança', 'pública'):
            return jsonify({"error": "classification deve ser: privativa, segurança ou pública"}), 400

        if schedule is not None and not _is_valid_schedule(schedule):
            return jsonify({"error": "schedule deve ser {\"start\": \"HH:MM\", \"end\": \"HH:MM\"}"}), 400

        if not _is_valid_retention_policy(retention_policy):
            return jsonify({"error": "retention_policy deve ser {\"thumbnails\": N, \"clips\": N, \"days\": N}"}), 400

        if not _is_valid_direction_line(direction_line):
            return jsonify({"error": "direction_line deve ser {\"axis\": \"vertical|horizontal\", \"position\": 0-1}"}), 400

        existing = storage.list_zones()
        if any(z["name"] == name for z in existing):
            return jsonify({"error": "Zona com esse nome já existe"}), 400

        zone_id = storage.add_zone(name, classification, schedule=schedule,
                                   retention_policy=retention_policy, direction_line=direction_line)
        return jsonify({"id": zone_id, "name": name, "classification": classification,
                        "schedule": schedule, "retention_policy": retention_policy,
                        "direction_line": direction_line}), 201

    @app.route("/zones/<int:zone_id>", methods=["PUT"])
    @require_permission("manage_zones")
    def update_zone(zone_id):
        zone = storage.get_zone(zone_id)
        if not zone:
            return jsonify({"error": "Zona não encontrada"}), 404

        payload = request.get_json() or {}
        name = payload.get("name")
        classification = payload.get("classification")
        schedule = payload.get("schedule")
        retention_policy = payload.get("retention_policy")
        direction_line = payload.get("direction_line")

        if not name or not classification:
            return jsonify({"error": "name e classification são obrigatórios"}), 400

        if classification not in ('privativa', 'segurança', 'pública'):
            return jsonify({"error": "classification deve ser: privativa, segurança ou pública"}), 400

        if schedule is not None and not _is_valid_schedule(schedule):
            return jsonify({"error": "schedule deve ser {\"start\": \"HH:MM\", \"end\": \"HH:MM\"}"}), 400

        if not _is_valid_retention_policy(retention_policy):
            return jsonify({"error": "retention_policy deve ser {\"thumbnails\": N, \"clips\": N, \"days\": N}"}), 400

        if not _is_valid_direction_line(direction_line):
            return jsonify({"error": "direction_line deve ser {\"axis\": \"vertical|horizontal\", \"position\": 0-1}"}), 400

        storage.update_zone(zone_id, name, classification, schedule=schedule,
                            retention_policy=retention_policy, direction_line=direction_line)
        updated_zone = storage.get_zone(zone_id)
        return jsonify(updated_zone), 200

    @app.route("/zones/<int:zone_id>", methods=["DELETE"])
    @require_permission("manage_zones")
    def delete_zone(zone_id):
        removed = storage.remove_zone(zone_id)
        if not removed:
            return jsonify({"error": "Zona não encontrada"}), 404
        return jsonify({"status": "removido"}), 200

    @app.route("/")
    def dashboard():
        return render_template("dashboard.html")

    @app.route("/section/<name>")
    def section_partial(name):
        allowed = {
            "overview", "events", "cameras", "zones", "identities",
            "users", "permissions", "audit", "notifications", "settings", "retention",
        }
        if name not in allowed:
            abort(404)
        return render_template(f"sections/{name}.html")

    # ════════════════════════════════════════════════════════════════════
    # User management routes
    # ════════════════════════════════════════════════════════════════════

    @app.route("/users")
    def users_page():
        return render_template("users.html")

    @app.route("/api/users")
    @require_permission("view_users")
    def api_list_users():
        user = getattr(g, "current_user", None)
        # chefe_seguranca only sees users they created
        if user and user["role"] == "chefe_seguranca":
            users = storage.list_users(created_by=user["id"])
        else:
            users = storage.list_users()
        return jsonify(users)

    @app.route("/api/users", methods=["POST"])
    @require_permission("create_users")
    def api_create_user():
        from .auth import hash_password, CAN_CREATE_ROLES
        user = getattr(g, "current_user", None)
        data = request.get_json(silent=True) or {}
        username = data.get("username", "").strip()
        password = data.get("password", "")
        role = data.get("role", "")

        if not username or not password:
            return jsonify({"error": "Usuário e senha são obrigatórios"}), 400
        if len(password) < 6:
            return jsonify({"error": "Senha deve ter pelo menos 6 caracteres"}), 400
        if role not in ("admin", "chefe_seguranca", "vigilante", "viewer"):
            return jsonify({"error": "Role inválida"}), 400

        # Check if current user can create this role
        allowed_roles = CAN_CREATE_ROLES.get(user["role"], [])
        if role not in allowed_roles:
            return jsonify({"error": f"Sem permissão para criar role '{role}'"}), 403

        # Check username uniqueness
        if storage.get_user_by_username(username):
            return jsonify({"error": "Usuário já existe"}), 409

        user_id = storage.add_user(username, hash_password(password), role, created_by=user["id"])
        storage.add_audit_entry("create_user", user_id=user["id"],
                                target_type="user", target_id=str(user_id),
                                details={"username": username, "role": role},
                                ip_address=request.remote_addr)
        return jsonify({"id": user_id, "username": username, "role": role}), 201

    @app.route("/api/users/<int:user_id>", methods=["PUT"])
    @require_permission("manage_users")
    def api_update_user(user_id):
        user = getattr(g, "current_user", None)
        target = storage.get_user(user_id)
        if not target:
            return jsonify({"error": "Usuário não encontrado"}), 404

        # Check hierarchy: chefe_seguranca can only edit users they created
        if user["role"] == "chefe_seguranca" and target.get("created_by") != user["id"]:
            return jsonify({"error": "Sem permissão para editar este usuário"}), 403

        # Cannot deactivate yourself
        if user_id == user["id"]:
            data = request.get_json(silent=True) or {}
            if data.get("active") == 0:
                return jsonify({"error": "Você não pode desativar a si mesmo"}), 400

        # Cannot deactivate last admin
        data = request.get_json(silent=True) or {}
        if target["role"] == "admin" and data.get("active") == 0:
            if storage.count_active_admins() <= 1:
                return jsonify({"error": "Não é possível desativar o último admin"}), 400

        storage.update_user(user_id, **{k: v for k, v in data.items() if k in ("username", "role", "active")})
        storage.add_audit_entry("update_user", user_id=user["id"],
                                target_type="user", target_id=str(user_id),
                                details=data, ip_address=request.remote_addr)
        return jsonify({"status": "ok"})

    @app.route("/api/users/<int:user_id>/cameras", methods=["GET"])
    @require_permission("view_users")
    def api_get_user_cameras(user_id):
        user = getattr(g, "current_user", None)
        target = storage.get_user(user_id)
        if not target:
            return jsonify({"error": "Usuário não encontrado"}), 404
        # chefe_seguranca can only manage users they created
        if user["role"] == "chefe_seguranca" and target.get("created_by") != user["id"]:
            return jsonify({"error": "Sem permissão"}), 403
        camera_ids = storage.get_user_cameras(user_id)
        return jsonify({"user_id": user_id, "camera_ids": camera_ids})

    @app.route("/api/users/<int:user_id>/cameras", methods=["PUT"])
    @require_permission("manage_users")
    def api_set_user_cameras(user_id):
        user = getattr(g, "current_user", None)
        target = storage.get_user(user_id)
        if not target:
            return jsonify({"error": "Usuário não encontrado"}), 404
        # chefe_seguranca can only manage users they created
        if user["role"] == "chefe_seguranca" and target.get("created_by") != user["id"]:
            return jsonify({"error": "Sem permissão"}), 403
        data = request.get_json(silent=True) or {}
        camera_ids = data.get("camera_ids", [])
        if not isinstance(camera_ids, list):
            return jsonify({"error": "camera_ids deve ser uma lista"}), 400
        storage.set_user_cameras(user_id, camera_ids)
        storage.add_audit_entry("set_user_cameras", user_id=user.get("id") if user else None,
                                target_type="user", target_id=str(user_id),
                                details={"camera_ids": camera_ids}, ip_address=request.remote_addr)
        return jsonify({"status": "ok", "user_id": user_id, "camera_ids": camera_ids})

    # ════════════════════════════════════════════════════════════════════
    # Permissions routes
    # ════════════════════════════════════════════════════════════════════

    @app.route("/permissions")
    def permissions_page():
        return render_template("permissions.html")

    @app.route("/api/permissions")
    def api_get_permissions():
        return jsonify(storage.get_all_role_permissions())

    @app.route("/api/permissions", methods=["PUT"])
    @require_permission("manage_permissions")
    def api_update_permissions():
        from .auth import PERMISSIONS, invalidate_permission_cache
        data = request.get_json(silent=True) or {}
        updates = data.get("permissions", [])
        if not isinstance(updates, list):
            return jsonify({"error": "permissions deve ser uma lista"}), 400
        for item in updates:
            role = item.get("role")
            perm = item.get("permission")
            enabled = item.get("enabled")
            if role not in ("admin", "chefe_seguranca", "vigilante", "viewer"):
                return jsonify({"error": f"Role inválida: {role}"}), 400
            if perm not in PERMISSIONS:
                return jsonify({"error": f"Permissão inválida: {perm}"}), 400
            if not isinstance(enabled, bool):
                return jsonify({"error": "enabled deve ser booleano"}), 400
            storage.set_role_permission(role, perm, enabled)
        invalidate_permission_cache()
        storage.add_audit_entry("update_permissions", user_id=getattr(g, "current_user", {}).get("id"),
                                details={"updates": updates}, ip_address=request.remote_addr)
        return jsonify({"status": "ok"})

    @app.route("/api/permissions/definitions")
    def api_permission_definitions():
        from .auth import PERMISSIONS
        return jsonify(PERMISSIONS)

    # ════════════════════════════════════════════════════════════════════
    # API Keys routes
    # ════════════════════════════════════════════════════════════════════

    @app.route("/api/api-keys")
    @require_permission("manage_users")
    def api_list_keys():
        return jsonify(storage.list_api_keys())

    @app.route("/api/api-keys", methods=["POST"])
    @require_permission("manage_users")
    def api_create_key():
        import hashlib as _hl
        import secrets as _sec
        user = getattr(g, "current_user", None)
        data = request.get_json(silent=True) or {}
        name = data.get("name", "").strip()
        permissions = data.get("permissions")

        if not name:
            return jsonify({"error": "Nome é obrigatório"}), 400

        # Generate key: 48 hex chars (24 bytes)
        raw_key = _sec.token_hex(24)
        key_hash = _hl.sha256(raw_key.encode()).hexdigest()

        key_id = storage.add_api_key(key_hash, name, permissions, created_by=user.get("id") if user else None)
        storage.add_audit_entry("create_api_key", user_id=user.get("id") if user else None,
                                target_type="api_key", target_id=str(key_id),
                                details={"name": name}, ip_address=request.remote_addr)
        # Return the raw key ONCE — it cannot be retrieved later
        return jsonify({"id": key_id, "name": name, "key": raw_key}), 201

    @app.route("/api/api-keys/<int:key_id>", methods=["DELETE"])
    @require_permission("manage_users")
    def api_delete_key(key_id):
        user = getattr(g, "current_user", None)
        removed = storage.remove_api_key(key_id)
        if not removed:
            return jsonify({"error": "Chave não encontrada"}), 404
        storage.add_audit_entry("delete_api_key", user_id=user.get("id") if user else None,
                                target_type="api_key", target_id=str(key_id),
                                ip_address=request.remote_addr)
        return jsonify({"status": "removido"}), 200

    # ════════════════════════════════════════════════════════════════════
    # Audit log routes
    # ════════════════════════════════════════════════════════════════════

    @app.route("/audit")
    def audit_page():
        return render_template("audit.html")

    @app.route("/api/audit")
    @require_permission("view_audit_log")
    def api_list_audit():
        limit = request.args.get("limit", 100, type=int)
        offset = request.args.get("offset", 0, type=int)
        user_id = request.args.get("user_id", type=int)
        action = request.args.get("action")
        entries = storage.list_audit_log(limit=limit, offset=offset, user_id=user_id, action=action)
        return jsonify(entries)

    # Auto-pruning scheduler
    if cfg.EVENT_PRUNE_ENABLED:
        def _prune_loop():
            while True:
                time.sleep(cfg.EVENT_PRUNE_INTERVAL_SECONDS)
                try:
                    policy = _effective_event_prune_policy(storage)
                    deleted = storage.prune_events(
                        type_days=policy["type_days"],
                        default_days=policy["default_days"],
                        max_age_days=policy["max_age_days"],
                    )
                    if deleted:
                        logger.info("Auto-prune: %d eventos removidos", deleted)
                except Exception:
                    logger.exception("Erro no auto-prune")

        prune_thread = threading.Thread(target=_prune_loop, daemon=True)
        prune_thread.start()
        logger.info("Auto-prune scheduler iniciado (intervalo=%ds)", cfg.EVENT_PRUNE_INTERVAL_SECONDS)

    return app
