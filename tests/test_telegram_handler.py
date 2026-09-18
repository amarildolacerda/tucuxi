# tests/test_telegram_handler.py
import pytest
import json
from unittest.mock import patch, MagicMock
from src.telegram_handler import telegram_command_handler


@pytest.fixture
def mock_storage():
    storage = MagicMock()
    storage.get_recent_events.return_value = [
        {"event_type": "motion_detected", "camera_id": 1, "timestamp": 1234567890}
    ]
    return storage


@pytest.fixture
def mock_camera_manager():
    manager = MagicMock()
    manager.cameras = [
        {"id": 1, "name": "Portão", "zone": "Entrada", "status": "online"}
    ]
    manager.get_worker.return_value = MagicMock()
    return manager


def test_handler_processes_start_command(mock_storage, mock_camera_manager):
    with patch("src.telegram_handler.requests") as mock_requests:
        mock_requests.post.return_value = MagicMock(status_code=200)
        
        handler = telegram_command_handler(mock_storage, mock_camera_manager)
        
        update = {
            "message": {
                "text": "/start",
                "chat": {"id": 123456},
                "message_id": 1
            }
        }
        
        with patch("src.telegram_handler.os.getenv", return_value="123456"):
            handler(update)
        
        mock_requests.post.assert_called()


def test_handler_rejects_unauthorized_chat(mock_storage, mock_camera_manager):
    with patch("src.telegram_handler.requests") as mock_requests:
        mock_requests.post.return_value = MagicMock(status_code=200)
        
        handler = telegram_command_handler(mock_storage, mock_camera_manager)
        
        update = {
            "message": {
                "text": "/start",
                "chat": {"id": 999999},
                "message_id": 1
            }
        }
        
        with patch("src.telegram_handler.os.getenv", return_value="123456"):
            handler(update)
        
        # Should send access denied message
        mock_requests.post.assert_called()
        call_args = mock_requests.post.call_args
        assert "acesso negado" in call_args[1]["data"]["text"].lower() or \
               "negado" in call_args[1]["data"]["text"].lower()
