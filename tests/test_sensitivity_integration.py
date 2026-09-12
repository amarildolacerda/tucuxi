# tests/test_sensitivity_integration.py
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


def test_camera_payload_includes_sensitivity_level(client, monkeypatch):
    """'level' é atributo de câmera e deve vir junto no payload (GET /api/dashboard).
    Sem config: 'default'. Com config: o nível salvo."""
    from src.camera import CameraStream
    monkeypatch.setattr(CameraStream, "validate_source", staticmethod(lambda source: True))
    resp = client.post("/cameras", json={"name": "Cam", "source": "rtsp://test", "zone": "test"})
    assert resp.status_code == 201
    camera_id = resp.get_json()["id"]

    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    cameras = resp.get_json()["cameras"]
    assert isinstance(cameras, list) and cameras
    camera = next(c for c in cameras if c["id"] == camera_id)
    assert camera["level"] == "default"

    client.put(f"/api/cameras/{camera_id}/sensitivity", json={"level": "high"})
    resp = client.get("/api/dashboard")
    cameras = resp.get_json()["cameras"]
    camera = next(c for c in cameras if c["id"] == camera_id)
    assert camera["level"] == "high"


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


# ── API tests ──

@pytest.fixture
def client(tmp_path):
    from src.app import create_app
    app = create_app(db_path=tmp_path / "test.db")
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_api_get_sensitivity(client):
    resp = client.get("/api/cameras/1/sensitivity")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["level"] == "default"
    assert "effective_params" in data
    assert "custom_params" not in data


def test_api_set_sensitivity_high(client):
    resp = client.put("/api/cameras/1/sensitivity", json={"level": "high"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["level"] == "high"
    assert "custom_params" not in data


def test_api_set_sensitivity_default(client):
    client.put("/api/cameras/1/sensitivity", json={"level": "high"})
    resp = client.put("/api/cameras/1/sensitivity", json={"level": "default"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["level"] == "default"
    assert data["effective_params"] == CONFIG_DEFAULT_PARAMS


def test_api_list_cameras_includes_level(client, monkeypatch):
    """GET /api/cameras deve existir (lista otimizada usada pelo card de sensibilidade)
    e cada câmera deve trazer 'level' junto (atributo simples).
    Atributos complexos (effective_params) ficam só no endpoint dedicado /sensitivity."""
    from src.camera import CameraStream
    monkeypatch.setattr(CameraStream, "validate_source", staticmethod(lambda source: True))
    resp = client.post("/cameras", json={"name": "Cam", "source": "rtsp://test", "zone": "test"})
    assert resp.status_code == 201
    camera_id = resp.get_json()["id"]
    resp = client.get("/api/cameras")
    assert resp.status_code == 200
    cameras = resp.get_json()
    assert isinstance(cameras, list) and cameras
    cam = next(c for c in cameras if c["id"] == camera_id)
    assert cam["level"] == "default"
    assert "effective_params" not in cam

    client.put(f"/api/cameras/{camera_id}/sensitivity", json={"level": "high"})
    resp = client.get("/api/cameras")
    cam = next(c for c in resp.get_json() if c["id"] == camera_id)
    assert cam["level"] == "high"
    assert "effective_params" not in cam


def test_api_set_sensitivity_invalid_level(client):
    resp = client.put("/api/cameras/1/sensitivity", json={"level": "invalid"})
    assert resp.status_code == 400


def test_api_set_sensitivity_custom_rejected(client):
    resp = client.put("/api/cameras/1/sensitivity", json={"level": "custom"})
    assert resp.status_code == 400


def test_api_presets(client):
    resp = client.get("/api/sensitivity/presets")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "low" in data
    assert "medium" in data
    assert "high" in data
    assert "default" not in data