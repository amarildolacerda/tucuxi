"""Dedup de thumbnails: o histórico não pode encher de frames idênticos
quando a cena não muda. RED->GREEN cobre o helper puro `frames_similar`,
a decisão `_should_save_thumbnail` e o caminho completo `_capture_thumbnail`.

User: "o modelo de capturar imagem em um intervalo captura muitas imagens
repetidas e guarda varias imagens iguais, isto não ajuda a analisar as imagens".
"""

import importlib

import numpy as np

main_mod = importlib.import_module("src.main")
from src.config import THUMBNAIL_DIFF_THRESHOLD, THUMBNAIL_INTERVAL_SECONDS, EVENT_DEDUP_WINDOW_SECONDS
from src.main import CameraWorker, frames_similar, _thumbnail_mini


def _frame(fill=100, obj=None):
    frame = np.full((480, 640, 3), fill, np.uint8)
    if obj:
        y0, y1, x0, x1, val = obj
        frame[y0:y1, x0:x1] = val
    return frame


def _make_worker(storage=None):
    return CameraWorker(
        {"id": "cam1", "name": "Cam", "zone": "entrada", "source": "rtsp://x"},
        storage=storage,
        alerts=None,
        object_detector=None,
    )


class _FakeStorage:
    def __init__(self):
        self.added = []
        self.pruned = []

    def add_camera_thumbnail(self, camera_id, path, event_type, event_id=None):
        self.added.append((camera_id, path, event_type))

    def prune_camera_thumbnails(self, camera_id, keep=None, max_age_days=None):
        self.pruned.append(camera_id)


# ---------- Helper puro: frames_similar ----------

def test_frames_similar_identical_true():
    a = _frame()
    assert frames_similar(a, a.copy(), THUMBNAIL_DIFF_THRESHOLD) is True


def test_frames_similar_none_is_safe_false():
    assert frames_similar(None, _frame(), THUMBNAIL_DIFF_THRESHOLD) is False
    assert frames_similar(_frame(), None, THUMBNAIL_DIFF_THRESHOLD) is False
    assert frames_similar(None, None, THUMBNAIL_DIFF_THRESHOLD) is False


def test_frames_similar_real_change_false():
    a = _frame()
    b = _frame(obj=(100, 300, 200, 400, 255))  # objeto forte cobre ~6.5% do frame
    assert frames_similar(a, b, THUMBNAIL_DIFF_THRESHOLD) is False


def test_frames_similar_threshold_behavior():
    # Mudança pequena (bloco 20x20 +20): média 64x64 ~0.02
    a = _frame()
    b = _frame(obj=(230, 250, 300, 320, 120))
    assert frames_similar(a, b, 0.01) is False  # limiar apertado -> diferente
    assert frames_similar(a, b, 1.0) is True    # limiar folgado -> similar


def test_frames_similar_sensor_noise_below_threshold():
    # Ruído leve de sensor (sigma 3) fica ABAIXO do limiar (calibrado ~0.97)
    a = _frame()
    rng = np.random.default_rng(42)
    noisy = np.clip(a.astype(np.int16) + rng.normal(0, 3, a.shape), 0, 255).astype(np.uint8)
    assert frames_similar(a, noisy, THUMBNAIL_DIFF_THRESHOLD) is True


# ---------- Decisão do worker: _should_save_thumbnail ----------

def test_should_save_thumbnail_first_frame_true():
    worker = _make_worker()
    assert worker._should_save_thumbnail(_frame(), 1000.0) is True


def test_should_save_thumbnail_within_interval_false():
    worker = _make_worker()
    worker._repr_frame = _thumbnail_mini(_frame())
    worker._last_thumb_time = 1000.0
    now = 1000.0 + THUMBNAIL_INTERVAL_SECONDS - 1
    assert worker._should_save_thumbnail(_frame(obj=(100, 300, 200, 400, 255)), now) is False


def test_should_save_thumbnail_similar_within_window_false():
    worker = _make_worker()
    worker._repr_frame = _thumbnail_mini(_frame())
    worker._repr_time = 1000.0
    now = 1000.0 + THUMBNAIL_INTERVAL_SECONDS + 1
    # cena estática DENTRO da janela -> dedup (não salva)
    assert worker._should_save_thumbnail(_frame(), now) is False


def test_should_save_thumbnail_different_or_window_true():
    worker = _make_worker()
    worker._repr_frame = _thumbnail_mini(_frame())
    worker._repr_time = 1000.0
    # cena mudou -> salva
    assert worker._should_save_thumbnail(_frame(obj=(100, 300, 200, 400, 255)), 1000.0 + 1) is True
    # janela expirada -> salva mesmo cena igual
    worker2 = _make_worker()
    worker2._repr_frame = _thumbnail_mini(_frame())
    worker2._repr_time = 1000.0
    assert worker2._should_save_thumbnail(_frame(), 1000.0 + EVENT_DEDUP_WINDOW_SECONDS + 1) is True


# ---------- Caminho completo: _capture_thumbnail ----------

def test_capture_thumbnail_skips_identical_repeats(tmp_path, monkeypatch):
    monkeypatch.setattr(main_mod, "THUMBNAILS_DIR", tmp_path)
    storage = _FakeStorage()
    worker = _make_worker(storage=storage)

    t0 = 1000.0
    first = worker._capture_thumbnail(_frame(), "motion_detected", t0)
    assert first is not None
    assert len(storage.added) == 1

    # Mesmo frame (cena estática), intervalo já cumprido -> dedup pula
    second = worker._capture_thumbnail(_frame(), "motion_detected", t0 + THUMBNAIL_INTERVAL_SECONDS + 1)
    assert second is None
    assert len(storage.added) == 1  # spy não ganhou entrada repetida


def test_capture_thumbnail_saves_when_scene_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(main_mod, "THUMBNAILS_DIR", tmp_path)
    storage = _FakeStorage()
    worker = _make_worker(storage=storage)

    t0 = 1000.0
    first = worker._capture_thumbnail(_frame(), "motion_detected", t0)
    assert first is not None

    b = _frame(obj=(100, 300, 200, 400, 255))
    second = worker._capture_thumbnail(b, "motion_detected", t0 + THUMBNAIL_INTERVAL_SECONDS + 1)
    assert second is not None
    assert len(storage.added) == 2
    assert first != second
