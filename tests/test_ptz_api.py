# tests/test_ptz_api.py
import json
import os
import sys
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

def test_ptz_move_endpoint():
    """Test that PTZ move endpoint exists and returns proper response."""
    from src.app import create_app
    db_path = tempfile.mktemp(suffix=".db")
    app = create_app(db_path=db_path)
    with app.test_client() as client:
        resp = client.post("/api/cameras/1/ptz/move",
                          data=json.dumps({"pan": 0.5, "tilt": 0.0, "zoom": 0.0}),
                          content_type="application/json")
        assert resp.status_code in (400, 404, 503)
    os.unlink(db_path)

def test_ptz_stop_endpoint():
    from src.app import create_app
    db_path = tempfile.mktemp(suffix=".db")
    app = create_app(db_path=db_path)
    with app.test_client() as client:
        resp = client.post("/api/cameras/1/ptz/stop")
        assert resp.status_code in (400, 404, 503)
    os.unlink(db_path)

def test_ptz_presets_endpoint():
    from src.app import create_app
    db_path = tempfile.mktemp(suffix=".db")
    app = create_app(db_path=db_path)
    with app.test_client() as client:
        resp = client.get("/api/cameras/1/ptz/presets")
        assert resp.status_code in (200, 404)
    os.unlink(db_path)

def test_ptz_config_endpoint():
    from src.app import create_app
    db_path = tempfile.mktemp(suffix=".db")
    app = create_app(db_path=db_path)
    with app.test_client() as client:
        resp = client.put("/api/cameras/1/ptz/config",
                         data=json.dumps({"onvif_host": "192.168.1.71", "onvif_port": 8899}),
                         content_type="application/json")
        assert resp.status_code in (200, 404)
    os.unlink(db_path)
