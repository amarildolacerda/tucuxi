# tests/test_sensitivity.py
import pytest
from src.storage import EventStorage

def test_get_sensitivity_returns_default():
    storage = EventStorage()
    result = storage.get_camera_sensitivity(1)
    assert result["level"] == "medium"
    assert result["custom_params"] is None

def test_set_and_get_sensitivity():
    storage = EventStorage()
    storage.seed_cameras([{"name": "Test", "source": "rtsp://test", "zone": "test"}])
    camera = storage.list_cameras()[0]
    storage.set_camera_sensitivity(camera["id"], "high")
    result = storage.get_camera_sensitivity(camera["id"])
    assert result["level"] == "high"
    assert result["custom_params"] is None

def test_set_custom_params():
    storage = EventStorage()
    storage.seed_cameras([{"name": "Test", "source": "rtsp://test", "zone": "test"}])
    camera = storage.list_cameras()[0]
    custom = {"motion_min_area": 4000, "motion_persist_frames": 3, "detector_confidence": 0.35, "detector_iou": 0.42, "track_iou_threshold": 0.28}
    storage.set_camera_sensitivity(camera["id"], "custom", custom)
    result = storage.get_camera_sensitivity(camera["id"])
    assert result["level"] == "custom"
    assert result["custom_params"] == custom
