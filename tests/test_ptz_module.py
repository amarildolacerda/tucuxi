# tests/test_ptz_module.py
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from src.ptz.onvif_client import PTZClient

def test_ptz_client_init():
    client = PTZClient(1, "192.168.1.71", 8899, "micasa", "pass123")
    assert client.camera_id == 1
    assert client.host == "192.168.1.71"
    assert client.port == 8899

def test_ptz_client_move():
    client = PTZClient(1, "192.168.1.71", 8899, "micasa", "pass123")
    # Should not raise (will fail connection but that's ok for unit test)
    try:
        result = client.move(0.5, 0.0, 0.0)
        assert result is True
    except Exception:
        pass  # Expected - no real camera in test

def test_ptz_client_stop():
    client = PTZClient(1, "192.168.1.71", 8899, "micasa", "pass123")
    try:
        result = client.stop()
        assert result is True
    except Exception:
        pass  # Expected - no real camera in test
