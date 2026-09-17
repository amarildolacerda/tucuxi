# tests/test_ptz_autotracker.py
import os
import sys
import time
from unittest.mock import MagicMock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

def test_autotracker_no_detections():
    from src.ptz.autotracker import Autotracker
    mock_manager = MagicMock()
    tracker = Autotracker(mock_manager)
    result = tracker.process_detection(1, [])
    assert result is None

def test_autotracker_follows_person():
    from src.ptz.autotracker import Autotracker
    mock_manager = MagicMock()
    tracker = Autotracker(mock_manager, cooldown_seconds=0)
    detections = [{"class": "person", "bbox": [0.7, 0.4, 0.9, 0.6], "confidence": 0.9}]
    result = tracker.process_detection(1, detections)
    assert result is not None
    assert result["pan"] > 0  # person is right of center
    assert abs(result["tilt"]) < 1.0

def test_autotracker_ignores_deadzone():
    from src.ptz.autotracker import Autotracker
    mock_manager = MagicMock()
    tracker = Autotracker(mock_manager, cooldown_seconds=0)
    # person centered — should not move
    detections = [{"class": "person", "bbox": [0.45, 0.45, 0.55, 0.55], "confidence": 0.9}]
    result = tracker.process_detection(1, detections)
    assert result is None

def test_autotracker_cooldown():
    from src.ptz.autotracker import Autotracker
    mock_manager = MagicMock()
    tracker = Autotracker(mock_manager, cooldown_seconds=5)
    detections = [{"class": "person", "bbox": [0.8, 0.3, 1.0, 0.7], "confidence": 0.9}]
    result1 = tracker.process_detection(1, detections)
    assert result1 is not None
    result2 = tracker.process_detection(1, detections)
    assert result2 is None  # still in cooldown

def test_autotracker_execute_move():
    from src.ptz.autotracker import Autotracker
    mock_manager = MagicMock()
    tracker = Autotracker(mock_manager)
    ok = tracker.execute_move(1, 0.5, -0.3, 0.0)
    assert ok is True
    mock_manager.move.assert_called_once_with(1, 0.5, -0.3, 0.0)

def test_autotracker_execute_move_error():
    from src.ptz.autotracker import Autotracker
    mock_manager = MagicMock()
    mock_manager.move.side_effect = ConnectionError("offline")
    tracker = Autotracker(mock_manager)
    ok = tracker.execute_move(1, 0.5, -0.3, 0.0)
    assert ok is False

def test_autotracker_ignores_non_person():
    from src.ptz.autotracker import Autotracker
    mock_manager = MagicMock()
    tracker = Autotracker(mock_manager, cooldown_seconds=0)
    detections = [{"class": "car", "bbox": [0.8, 0.3, 1.0, 0.7], "confidence": 0.9}]
    result = tracker.process_detection(1, detections)
    assert result is None
