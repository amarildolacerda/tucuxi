# tests/test_sensitivity.py
import pytest
from src.storage import EventStorage
from src.sensitivity import SensitivityManager, SensitivityLevel, SENSITIVITY_PRESETS, validate_custom_params

# ── Storage tests ──

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

# ── Sensitivity module tests ──

def test_presets_have_all_keys():
    required = {"motion_min_area", "motion_persist_frames", "detector_confidence", "detector_iou", "track_iou_threshold"}
    for level in [SensitivityLevel.LOW, SensitivityLevel.MEDIUM, SensitivityLevel.HIGH]:
        assert required.issubset(SENSITIVITY_PRESETS[level].keys())

def test_medium_preset_matches_defaults():
    from src.config import MOTION_MIN_AREA, MOTION_PERSIST_FRAMES, DETECTOR_CONFIDENCE, DETECTOR_IOU, TRACK_IOU_THRESHOLD
    m = SENSITIVITY_PRESETS[SensitivityLevel.MEDIUM]
    assert m["motion_min_area"] == MOTION_MIN_AREA
    assert m["motion_persist_frames"] == MOTION_PERSIST_FRAMES
    assert m["detector_confidence"] == DETECTOR_CONFIDENCE
    assert m["detector_iou"] == DETECTOR_IOU
    assert m["track_iou_threshold"] == TRACK_IOU_THRESHOLD

def test_get_effective_params_returns_preset():
    storage = EventStorage()
    storage.seed_cameras([{"name": "Test", "source": "rtsp://test", "zone": "test"}])
    camera = storage.list_cameras()[0]
    mgr = SensitivityManager(storage)
    params = mgr.get_effective_params(camera["id"])
    assert params == SENSITIVITY_PRESETS[SensitivityLevel.MEDIUM]

def test_get_effective_params_returns_custom():
    storage = EventStorage()
    storage.seed_cameras([{"name": "Test", "source": "rtsp://test", "zone": "test"}])
    camera = storage.list_cameras()[0]
    custom = {"motion_min_area": 4000, "motion_persist_frames": 3, "detector_confidence": 0.35, "detector_iou": 0.42, "track_iou_threshold": 0.28}
    storage.set_camera_sensitivity(camera["id"], "custom", custom)
    mgr = SensitivityManager(storage)
    params = mgr.get_effective_params(camera["id"])
    assert params == custom

def test_set_level_persists():
    storage = EventStorage()
    storage.seed_cameras([{"name": "Test", "source": "rtsp://test", "zone": "test"}])
    camera = storage.list_cameras()[0]
    mgr = SensitivityManager(storage)
    mgr.set_level(camera["id"], SensitivityLevel.HIGH)
    result = storage.get_camera_sensitivity(camera["id"])
    assert result["level"] == "high"

def test_validate_custom_params_valid():
    custom = {"motion_min_area": 4000, "motion_persist_frames": 3, "detector_confidence": 0.35, "detector_iou": 0.42, "track_iou_threshold": 0.28}
    assert validate_custom_params(custom) is None

def test_validate_custom_params_missing_key():
    custom = {"motion_min_area": 4000}
    error = validate_custom_params(custom)
    assert error is not None
    assert "faltando" in error

def test_validate_custom_params_out_of_range():
    custom = {"motion_min_area": 500, "motion_persist_frames": 3, "detector_confidence": 0.35, "detector_iou": 0.42, "track_iou_threshold": 0.28}
    error = validate_custom_params(custom)
    assert error is not None
    assert "entre" in error

def test_set_level_custom_without_params_returns_error():
    storage = EventStorage()
    storage.seed_cameras([{"name": "Test", "source": "rtsp://test", "zone": "test"}])
    camera = storage.list_cameras()[0]
    mgr = SensitivityManager(storage)
    error = mgr.set_level(camera["id"], "custom")
    assert error is not None
