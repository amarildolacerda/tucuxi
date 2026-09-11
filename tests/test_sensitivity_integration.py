# tests/test_sensitivity_integration.py
import pytest
from unittest.mock import MagicMock
from src.sensitivity import SensitivityManager, SensitivityLevel, SENSITIVITY_PRESETS
from src.storage import EventStorage


def test_worker_receives_sensitivity_on_init():
    """When a worker starts, it should apply sensitivity from DB."""
    storage = EventStorage()
    storage.seed_cameras([{"name": "Test", "source": "rtsp://test", "zone": "test"}])
    camera = storage.list_cameras()[0]
    storage.set_camera_sensitivity(camera["id"], "high")
    mgr = SensitivityManager(storage)
    # Simulate worker registration
    mock_worker = MagicMock()
    mock_worker._motion_detector_ref = MagicMock()
    mock_worker.object_detector = MagicMock()
    mock_worker._tracker_ref = MagicMock()
    mgr.register_worker(camera["id"], mock_worker)
    params = mgr.get_effective_params(camera["id"])
    mgr.apply_to_workers(camera["id"], params)
    assert mock_worker._motion_detector_ref.min_area == SENSITIVITY_PRESETS[SensitivityLevel.HIGH]["motion_min_area"]
    assert mock_worker.object_detector.confidence_threshold == SENSITIVITY_PRESETS[SensitivityLevel.HIGH]["detector_confidence"]


def test_set_level_updates_worker_in_realtime():
    """Changing level should immediately update worker params."""
    storage = EventStorage()
    storage.seed_cameras([{"name": "Test", "source": "rtsp://test", "zone": "test"}])
    camera = storage.list_cameras()[0]
    mgr = SensitivityManager(storage)
    mock_worker = MagicMock()
    mock_worker._motion_detector_ref = MagicMock()
    mock_worker.object_detector = MagicMock()
    mock_worker._tracker_ref = MagicMock()
    mgr.register_worker(camera["id"], mock_worker)
    # Set to high
    mgr.set_level(camera["id"], "high")
    assert mock_worker._motion_detector_ref.min_area == 3000
    # Set to low
    mgr.set_level(camera["id"], "low")
    assert mock_worker._motion_detector_ref.min_area == 8000


def test_apply_to_workers_no_worker():
    """apply_to_workers should not crash if no worker registered."""
    storage = EventStorage()
    mgr = SensitivityManager(storage)
    params = mgr.get_effective_params(999)
    mgr.apply_to_workers(999, params)  # Should not raise


def test_unregister_worker():
    """Unregistering a worker should remove it from the manager."""
    storage = EventStorage()
    storage.seed_cameras([{"name": "Test", "source": "rtsp://test", "zone": "test"}])
    camera = storage.list_cameras()[0]
    mgr = SensitivityManager(storage)
    mock_worker = MagicMock()
    mgr.register_worker(camera["id"], mock_worker)
    assert camera["id"] in mgr._workers
    mgr.unregister_worker(camera["id"])
    assert camera["id"] not in mgr._workers


def test_custom_params_applied_to_worker():
    """Custom params should be applied to the worker correctly."""
    storage = EventStorage()
    storage.seed_cameras([{"name": "Test", "source": "rtsp://test", "zone": "test"}])
    camera = storage.list_cameras()[0]
    custom = {"motion_min_area": 4000, "motion_persist_frames": 3, "detector_confidence": 0.35, "detector_iou": 0.42, "track_iou_threshold": 0.28}
    storage.set_camera_sensitivity(camera["id"], "custom", custom)
    mgr = SensitivityManager(storage)
    mock_worker = MagicMock()
    mock_worker._motion_detector_ref = MagicMock()
    mock_worker.object_detector = MagicMock()
    mock_worker._tracker_ref = MagicMock()
    mgr.register_worker(camera["id"], mock_worker)
    params = mgr.get_effective_params(camera["id"])
    mgr.apply_to_workers(camera["id"], params)
    assert mock_worker._motion_detector_ref.min_area == 4000
    assert mock_worker._motion_detector_ref.persist_frames == 3
    assert mock_worker.object_detector.confidence_threshold == 0.35
    assert mock_worker.object_detector.iou_threshold == 0.42
    assert mock_worker._tracker_ref.iou_threshold == 0.28
