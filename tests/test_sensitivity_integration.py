# tests/test_sensitivity_integration.py
import json
import pytest
from unittest.mock import MagicMock
from src.sensitivity import SensitivityManager, SensitivityLevel, SENSITIVITY_PRESETS, CONFIG_DEFAULT_PARAMS
from src.storage import EventStorage


def _storage(tmp_path):
    return EventStorage(tmp_path / "events.db")


def test_worker_receives_sensitivity_on_init(tmp_path):
    """When a worker starts, it should apply sensitivity from DB."""
    storage = _storage(tmp_path)
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


def test_unconfigured_worker_keeps_env_params(tmp_path):
    """Sem registro no DB, o worker mantém os parâmetros do ambiente (não o preset)."""
    storage = _storage(tmp_path)
    storage.seed_cameras([{"name": "Test", "source": "rtsp://test", "zone": "test"}])
    camera = storage.list_cameras()[0]
    mgr = SensitivityManager(storage)
    mock_worker = MagicMock()
    mock_worker._motion_detector_ref = MagicMock()
    mock_worker.object_detector = MagicMock()
    mock_worker._tracker_ref = MagicMock()
    mgr.register_worker(camera["id"], mock_worker)
    params = mgr.get_effective_params(camera["id"])
    mgr.apply_to_workers(camera["id"], params)
    assert mock_worker._motion_detector_ref.min_area == CONFIG_DEFAULT_PARAMS["motion_min_area"]
    assert mock_worker.object_detector.confidence_threshold == CONFIG_DEFAULT_PARAMS["detector_confidence"]


def test_set_level_updates_worker_in_realtime(tmp_path):
    """Changing level should immediately update worker params."""
    storage = _storage(tmp_path)
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


def test_apply_to_workers_no_worker(tmp_path):
    """apply_to_workers should not crash if no worker registered."""
    storage = _storage(tmp_path)
    mgr = SensitivityManager(storage)
    params = mgr.get_effective_params(999)
    mgr.apply_to_workers(999, params)  # Should not raise


def test_unregister_worker(tmp_path):
    """Unregistering a worker should remove it from the manager."""
    storage = _storage(tmp_path)
    storage.seed_cameras([{"name": "Test", "source": "rtsp://test", "zone": "test"}])
    camera = storage.list_cameras()[0]
    mgr = SensitivityManager(storage)
    mock_worker = MagicMock()
    mgr.register_worker(camera["id"], mock_worker)
    assert camera["id"] in mgr._workers
    mgr.unregister_worker(camera["id"])
    assert camera["id"] not in mgr._workers


def test_custom_params_applied_to_worker(tmp_path):
    """Custom params should be applied to the worker correctly."""
    storage = _storage(tmp_path)
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


# ── API tests ──

@pytest.fixture
def client(tmp_path):
    from src.app import create_app
    app = create_app(db_path=tmp_path / "test.db")
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_api_get_sensitivity(client):
    """GET /api/cameras/1/sensitivity returns current level."""
    resp = client.get("/api/cameras/1/sensitivity")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "level" in data
    assert "effective_params" in data


def test_api_set_sensitivity_high(client):
    """PUT /api/cameras/1/sensitivity sets level."""
    resp = client.put("/api/cameras/1/sensitivity", json={"level": "high"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["level"] == "high"


def test_api_set_sensitivity_custom(client):
    """PUT /api/cameras/1/sensitivity with custom params."""
    custom = {"motion_min_area": 4000, "motion_persist_frames": 3, "detector_confidence": 0.35, "detector_iou": 0.42, "track_iou_threshold": 0.28}
    resp = client.put("/api/cameras/1/sensitivity", json={"level": "custom", "custom_params": custom})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["level"] == "custom"
    assert data["effective_params"] == custom


def test_api_set_sensitivity_invalid_level(client):
    """PUT with invalid level returns 400."""
    resp = client.put("/api/cameras/1/sensitivity", json={"level": "invalid"})
    assert resp.status_code == 400


def test_api_set_sensitivity_custom_without_params(client):
    """PUT custom without custom_params returns 400."""
    resp = client.put("/api/cameras/1/sensitivity", json={"level": "custom"})
    assert resp.status_code == 400


def test_api_presets(client):
    """GET /api/sensitivity/presets returns all presets."""
    resp = client.get("/api/sensitivity/presets")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "low" in data
    assert "medium" in data
    assert "high" in data