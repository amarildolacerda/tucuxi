# tests/test_sensitivity.py
import pytest
from src.storage import EventStorage
from src.sensitivity import SensitivityManager, SensitivityLevel, SENSITIVITY_PRESETS, validate_custom_params, CONFIG_DEFAULT_PARAMS
from src import config as config_module

DEFAULT_KEYS = {
    "motion_min_area",
    "motion_persist_frames",
    "detector_confidence",
    "detector_iou",
    "track_iou_threshold",
}


def _storage(tmp_path):
    return EventStorage(tmp_path / "events.db")


# ── Storage tests ──

def test_get_sensitivity_unconfigured_returns_default(tmp_path):
    storage = _storage(tmp_path)
    result = storage.get_camera_sensitivity(1)
    assert result["level"] == "default"
    assert result["configured"] is False


def test_set_and_get_sensitivity(tmp_path):
    storage = _storage(tmp_path)
    storage.seed_cameras([{"name": "Test", "source": "rtsp://test", "zone": "test"}])
    camera = storage.list_cameras()[0]
    storage.set_camera_sensitivity(camera["id"], "high")
    result = storage.get_camera_sensitivity(camera["id"])
    assert result == {"level": "high", "configured": True}


def test_set_level_default_clears_record(tmp_path):
    storage = _storage(tmp_path)
    storage.seed_cameras([{"name": "Test", "source": "rtsp://test", "zone": "test"}])
    camera = storage.list_cameras()[0]
    storage.set_camera_sensitivity(camera["id"], "high")
    assert storage.get_camera_sensitivity(camera["id"])["configured"] is True
    storage.set_camera_sensitivity(camera["id"], "default")
    result = storage.get_camera_sensitivity(camera["id"])
    assert result["configured"] is False
    assert result["level"] == "default"


def test_get_sensitivity_legacy_custom_treated_as_default(tmp_path):
    storage = _storage(tmp_path)
    storage.seed_cameras([{"name": "Test", "source": "rtsp://test", "zone": "test"}])
    camera = storage.list_cameras()[0]
    with storage.lock:
        cur = storage.connection.cursor()
        cur.execute(
            "INSERT INTO camera_sensitivity (camera_id, level, custom_params, updated_at) VALUES (?, 'custom', NULL, ?)",
            (camera["id"], "2026-09-11T00:00:00+00:00"),
        )
        storage.connection.commit()
    result = storage.get_camera_sensitivity(camera["id"])
    assert result["level"] == "default"
    assert result["configured"] is False


# ── Sensitivity module tests ──

def test_presets_have_all_keys():
    for level in [SensitivityLevel.LOW, SensitivityLevel.MEDIUM, SensitivityLevel.HIGH]:
        assert DEFAULT_KEYS.issubset(SENSITIVITY_PRESETS[level].keys())


def test_config_default_params_match_env_config():
    """CONFIG_DEFAULT_PARAMS reflete os valores de config.py (env/defaults)."""
    expected = {
        "motion_min_area": config_module.MOTION_MIN_AREA,
        "motion_persist_frames": config_module.MOTION_PERSIST_FRAMES,
        "detector_confidence": config_module.DETECTOR_CONFIDENCE,
        "detector_iou": config_module.DETECTOR_IOU,
        "track_iou_threshold": config_module.TRACK_IOU_THRESHOLD,
    }
    assert CONFIG_DEFAULT_PARAMS == expected


def test_unconfigured_camera_falls_back_to_config(tmp_path):
    """Câmera sem registro usa os valores de config.py (env), não o preset MÉDIO."""
    storage = _storage(tmp_path)
    storage.seed_cameras([{"name": "Test", "source": "rtsp://test", "zone": "test"}])
    camera = storage.list_cameras()[0]
    mgr = SensitivityManager(storage)
    params = mgr.get_effective_params(camera["id"])
    assert params == CONFIG_DEFAULT_PARAMS


def test_get_effective_params_returns_preset(tmp_path):
    storage = _storage(tmp_path)
    storage.seed_cameras([{"name": "Test", "source": "rtsp://test", "zone": "test"}])
    camera = storage.list_cameras()[0]
    storage.set_camera_sensitivity(camera["id"], "medium")
    mgr = SensitivityManager(storage)
    params = mgr.get_effective_params(camera["id"])
    assert params == SENSITIVITY_PRESETS[SensitivityLevel.MEDIUM]


def test_set_level_persists(tmp_path):
    storage = _storage(tmp_path)
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


def test_set_level_custom_without_params_returns_error(tmp_path):
    storage = _storage(tmp_path)
    storage.seed_cameras([{"name": "Test", "source": "rtsp://test", "zone": "test"}])
    camera = storage.list_cameras()[0]
    mgr = SensitivityManager(storage)
    error = mgr.set_level(camera["id"], "custom")
    assert error is not None