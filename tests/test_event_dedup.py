# tests/test_event_dedup.py
import importlib
import threading
import time

import numpy as np

import src.config as cfg
from src.main import CameraWorker, frames_similar, _thumbnail_mini
from src.config import THUMBNAIL_DIFF_THRESHOLD, EVENT_DEDUP_WINDOW_SECONDS, THUMBNAIL_INTERVAL_SECONDS


def test_event_dedup_window_default():
    # Recarrega para garantir default limpo (sem env var setada)
    importlib.reload(cfg)
    assert isinstance(cfg.EVENT_DEDUP_WINDOW_SECONDS, float)
    assert cfg.EVENT_DEDUP_WINDOW_SECONDS > 0


# ---------- Helpers ----------

def _frame(fill=100, obj=None):
    frame = np.full((480, 640, 3), fill, np.uint8)
    if obj:
        y0, y1, x0, x1, val = obj
        frame[y0:y1, x0:x1] = val
    return frame


def _make_worker(storage=None, object_detector=None, event_bus=None):
    return CameraWorker(
        {"id": "cam1", "name": "Cam", "zone": "entrada", "source": "rtsp://x"},
        storage=storage, alerts=None, object_detector=object_detector, event_bus=event_bus,
    )


class _FakeStorage:
    def __init__(self):
        self.added = []
        self.pruned = []
    def add_camera_thumbnail(self, camera_id, path, event_type, event_id=None):
        self.added.append((camera_id, path, event_type))
    def prune_camera_thumbnails(self, camera_id, keep=None, max_age_days=None):
        self.pruned.append(camera_id)
    def list_zones(self):
        return []


# ---------- Task 2: _scene_changed / _update_repr ----------

def test_scene_changed_first_frame_true():
    w = _make_worker()
    assert w._scene_changed(_frame(), 1000.0) is True


def test_scene_changed_within_window_similar_false():
    w = _make_worker()
    w._repr_frame = _thumbnail_mini(_frame())
    w._repr_time = 1000.0
    # mesma cena, dentro da janela -> não mudou
    assert w._scene_changed(_frame(), 1000.0 + EVENT_DEDUP_WINDOW_SECONDS - 1) is False


def test_scene_changed_after_window_true():
    w = _make_worker()
    w._repr_frame = _thumbnail_mini(_frame())
    w._repr_time = 1000.0
    assert w._scene_changed(_frame(), 1000.0 + EVENT_DEDUP_WINDOW_SECONDS + 1) is True


def test_scene_changed_different_scene_true():
    w = _make_worker()
    w._repr_frame = _thumbnail_mini(_frame())
    w._repr_time = 1000.0
    assert w._scene_changed(_frame(obj=(100, 300, 200, 400, 255)), 1000.0 + 1) is True


def test_update_repr_sets_state():
    w = _make_worker()
    f = _frame(obj=(100, 300, 200, 400, 255))
    w._update_repr(f, 1234.0)
    assert w._repr_frame is not None
    assert w._repr_time == 1234.0


# ---------- Task 3: _capture_thumbnail force ----------

def test_capture_thumbnail_force_bypasses_dedup(tmp_path, monkeypatch):
    import src.main as main_mod
    monkeypatch.setattr(main_mod, "THUMBNAILS_DIR", tmp_path)
    storage = _FakeStorage()
    w = _make_worker(storage=storage)
    w._repr_frame = _thumbnail_mini(_frame())
    w._repr_time = 1000.0
    w._last_thumb_time = 1000.0
    # cena igual DENTRO da janela seria dedup normal; com force=True salva
    p = w._capture_thumbnail(_frame(), "no_motion", 1000.0 + 1, force=True)
    assert p is not None
    assert len(storage.added) == 1


# ---------- Task 4: _should_emit_event ----------

def test_should_emit_event_high_value_always():
    w = _make_worker()
    w._repr_frame = _thumbnail_mini(_frame())
    w._repr_time = 1000.0
    # identidade presente -> sempre emite, mesmo cena estável
    assert w._should_emit_event({"known": True, "name": "Jo"}, False, None, None, _frame(), 1000.0 + 1) is True
    # queda/loitering/direção -> sempre emitem
    assert w._should_emit_event(None, True, None, None, _frame(), 1000.0 + 1) is True
    assert w._should_emit_event(None, False, {"first_seen": 0}, None, _frame(), 1000.0 + 1) is True


def test_should_emit_event_low_value_suppressed_when_stable():
    w = _make_worker()
    w._repr_frame = _thumbnail_mini(_frame())
    w._repr_time = 1000.0
    # baixo-valor (sem identidade/fall/loiter/direction) + cena estável -> suprimir
    assert w._should_emit_event(None, False, None, None, _frame(), 1000.0 + 1) is False
    # baixo-valor mas cena mudou -> emitir
    assert w._should_emit_event(None, False, None, None, _frame(obj=(100, 300, 200, 400, 255)), 1000.0 + 1) is True


def test_run_suppresses_low_value_and_still_emits_no_motion(tmp_path, monkeypatch):
    import src.main as main_mod

    # Frame com bloco que "pisca" (+30) a cada frame: dispara MotionDetector
    # (área > min_area) mas mantém média 64x64 <= THUMBNAIL_DIFF_THRESHOLD (cena similar).
    def make_frame(on):
        f = np.full((480, 640, 3), 100, np.uint8)
        val = 130 if on else 100
        f[200:300, 200:300] = val  # 100x100
        return f

    class FakeStream:
        def __init__(self, frames):
            self._it = iter(frames)
        def read(self):
            try:
                return next(self._it)
            except StopIteration:
                return None

    class FakeDetector:
        def detect(self, frame):
            return []  # sem objetos -> evento baixo-valor (motion_detected/snapshot_info)

    class FakeBus:
        def __init__(self):
            self.events = []
        def enqueue(self, ev):
            self.events.append(ev)

    storage = _FakeStorage()
    bus = FakeBus()
    w = _make_worker(storage=storage, object_detector=FakeDetector(), event_bus=bus)
    # 5 frames "piscando" (movimento ruído) + 3 frames idênticos estáticos (quiet)
    frames = [make_frame(i % 2 == 0) for i in range(5)] + [make_frame(False) for _ in range(3)]
    monkeypatch.setattr(main_mod, "CameraStream", lambda *a, **k: FakeStream(frames))
    monkeypatch.setattr(main_mod, "THUMBNAILS_DIR", tmp_path)
    # Reduz janela de "sem movimento" para o teste não precisar esperar 60s
    monkeypatch.setattr(main_mod, "NO_MOTION_ALERT_SECONDS", 0.05)

    t = threading.Thread(target=w.run, daemon=True)
    t.start()
    time.sleep(2.0)  # processa os 8 frames
    w.stop_event.set()
    t.join(timeout=3)

    # Apenas 1 evento de baixo-valor deve ter sido enfileirado (demais suprimidos)
    low_value = [e for e in bus.events if not e.no_motion]
    assert len(low_value) == 1, f"esperado 1 evento de baixo-valor, veio {len(low_value)}"
    # Após quietude, no_motion deve ser emitido (prova motion_reported funcionando)
    assert any(e.no_motion for e in bus.events), "no_motion não foi emitido"
