from unittest.mock import MagicMock
from src.storage import EventStorage
from src.sensitivity import SensitivityManager, SensitivityLevel, SENSITIVITY_PRESETS, CONFIG_DEFAULT_PARAMS
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

def test_get_sensitivity_returns_default(tmp_path):
    storage = _storage(tmp_path)
    result = storage.get_camera_sensitivity(1)
    assert result["level"] == "default"
    assert result["configured"] is False


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
    assert result["level"] == "high"
    assert result["configured"] is True


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
    expected = {
        "motion_min_area": config_module.MOTION_MIN_AREA,
        "motion_persist_frames": config_module.MOTION_PERSIST_FRAMES,
        "detector_confidence": config_module.DETECTOR_CONFIDENCE,
        "detector_iou": config_module.DETECTOR_IOU,
        "track_iou_threshold": config_module.TRACK_IOU_THRESHOLD,
    }
    assert CONFIG_DEFAULT_PARAMS == expected


def test_unconfigured_camera_falls_back_to_config(tmp_path):
    storage = _storage(tmp_path)
    storage.seed_cameras([{"name": "Test", "source": "rtsp://test", "zone": "test"}])
    camera = storage.list_cameras()[0]
    mgr = SensitivityManager(storage)
    params = mgr.get_effective_params(camera["id"])
    assert params == CONFIG_DEFAULT_PARAMS


def test_default_level_uses_config_params(tmp_path):
    storage = _storage(tmp_path)
    storage.seed_cameras([{"name": "Test", "source": "rtsp://test", "zone": "test"}])
    camera = storage.list_cameras()[0]
    storage.set_camera_sensitivity(camera["id"], "default")
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


def test_set_level_default_applies_to_workers(tmp_path):
    storage = _storage(tmp_path)
    storage.seed_cameras([{"name": "Test", "source": "rtsp://test", "zone": "test"}])
    camera = storage.list_cameras()[0]
    storage.set_camera_sensitivity(camera["id"], "high")
    mgr = SensitivityManager(storage)
    mock_worker = MagicMock()
    mock_worker._motion_detector_ref = MagicMock()
    mock_worker.object_detector = MagicMock()
    mock_worker._tracker_ref = MagicMock()
    mgr.register_worker(camera["id"], mock_worker)
    mgr.set_level(camera["id"], "default")
    assert mock_worker._motion_detector_ref.min_area == CONFIG_DEFAULT_PARAMS["motion_min_area"]