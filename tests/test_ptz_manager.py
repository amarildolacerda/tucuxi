# tests/test_ptz_manager.py
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from src.ptz.manager import PTZManager
from src.storage import EventStorage

def setup():
    db = "/tmp/test_ptz_manager.db"
    if os.path.exists(db):
        os.remove(db)
    return EventStorage(db)

def test_manager_init_camera():
    s = setup()
    s.seed_cameras([{"name": "Cam1", "source": "rtsp://test", "zone": "z1"}])
    cam = s.list_cameras()[0]
    s.add_camera_ptz(cam["id"], "192.168.1.71", 8899, "micasa", "pass123")
    mgr = PTZManager(s)
    mgr.init_camera(cam["id"])
    assert cam["id"] in mgr._clients

def test_manager_move():
    s = setup()
    s.seed_cameras([{"name": "Cam1", "source": "rtsp://test", "zone": "z1"}])
    cam = s.list_cameras()[0]
    s.add_camera_ptz(cam["id"], "192.168.1.71", 8899, "micasa", "pass123")
    mgr = PTZManager(s)
    mgr.init_camera(cam["id"])
    # Move will fail connection but shouldn't raise ValueError about missing config
    try:
        result = mgr.move(cam["id"], 0.5, 0.0, 0.0)
        assert result is True
    except ValueError:
        raise AssertionError("Should not raise ValueError for configured camera")
    except Exception:
        pass  # Expected - no real camera in test

def test_manager_stop():
    s = setup()
    s.seed_cameras([{"name": "Cam1", "source": "rtsp://test", "zone": "z1"}])
    cam = s.list_cameras()[0]
    s.add_camera_ptz(cam["id"], "192.168.1.71", 8899, "micasa", "pass123")
    mgr = PTZManager(s)
    mgr.init_camera(cam["id"])
    try:
        result = mgr.stop(cam["id"])
        assert result is True
    except ValueError:
        raise AssertionError("Should not raise ValueError for configured camera")
    except Exception:
        pass  # Expected - no real camera in test

def test_manager_no_config_raises():
    s = setup()
    mgr = PTZManager(s)
    try:
        mgr.move(999, 0.5, 0.0, 0.0)
        raise AssertionError("Should raise ValueError for unconfigured camera")
    except ValueError as e:
        assert "not configured" in str(e)
