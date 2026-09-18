# tests/test_ptz_storage.py
import json
import os
from src.storage import EventStorage

def setup_storage():
    db_path = "/tmp/test_ptz_storage.db"
    if os.path.exists(db_path):
        os.remove(db_path)
    return EventStorage(db_path)

def test_add_camera_ptz():
    s = setup_storage()
    s.seed_cameras([{"name": "Cam1", "source": "rtsp://test", "zone": "z1"}])
    cam = s.list_cameras()[0]
    result = s.add_camera_ptz(cam["id"], "192.168.1.71", 8899, "micasa", "pass123")
    assert result is True
    ptz = s.get_camera_ptz(cam["id"])
    assert ptz is not None
    assert ptz["onvif_host"] == "192.168.1.71"
    assert ptz["onvif_port"] == 8899

def test_get_camera_ptz_missing():
    s = setup_storage()
    assert s.get_camera_ptz(999) is None

def test_add_ptz_preset():
    s = setup_storage()
    s.seed_cameras([{"name": "Cam1", "source": "rtsp://test", "zone": "z1"}])
    cam = s.list_cameras()[0]
    s.add_camera_ptz(cam["id"], "192.168.1.71", 8899, "micasa", "pass123")
    preset_id = s.add_ptz_preset(cam["id"], "Entrada", {"pan": 0.5, "tilt": -0.3, "zoom": 1.2})
    assert preset_id > 0
    presets = s.list_ptz_presets(cam["id"])
    assert len(presets) == 1
    assert presets[0]["name"] == "Entrada"

def test_remove_ptz_preset():
    s = setup_storage()
    s.seed_cameras([{"name": "Cam1", "source": "rtsp://test", "zone": "z1"}])
    cam = s.list_cameras()[0]
    s.add_camera_ptz(cam["id"], "192.168.1.71", 8899, "micasa", "pass123")
    preset_id = s.add_ptz_preset(cam["id"], "Entrada", {"pan": 0.5})
    result = s.remove_ptz_preset(preset_id)
    assert result is True
    assert len(s.list_ptz_presets(cam["id"])) == 0
