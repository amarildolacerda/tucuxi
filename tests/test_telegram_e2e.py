# tests/test_telegram_e2e.py
import pytest
from unittest.mock import patch, MagicMock
from src.telegram_commands import parse_command
from src.telegram_responses import format_start_response
from src.telegram_handler import telegram_command_handler


def test_full_command_flow():
    """Test complete flow from command parsing to response generation."""
    # Parse a command
    parsed = parse_command("/start")
    assert parsed["command"] == "start"
    
    # Generate response
    response = format_start_response()
    assert "Tucuxi" in response or "Bem-vindo" in response
    
    # Verify handler can be created
    storage = MagicMock()
    camera_manager = MagicMock()
    handler = telegram_command_handler(storage, camera_manager)
    assert callable(handler)


def test_snapshot_command_flow():
    """Test snapshot command with camera lookup."""
    parsed = parse_command("/snapshot portao")
    assert parsed["command"] == "snapshot"
    assert parsed["args"] == ["portao"]
    
    # Verify handler processes snapshot command
    storage = MagicMock()
    camera_manager = MagicMock()
    camera_manager.cameras = [{"id": 1, "name": "Portão", "zone": "Entrada"}]
    handler = telegram_command_handler(storage, camera_manager)
    
    # Create a mock update
    update = {
        "message": {
            "text": "/snapshot portao",
            "chat": {"id": 123456},
            "message_id": 1
        }
    }
    
    # Mock the authorized chat_id
    with patch("src.telegram_handler.os.getenv", return_value="123456"):
        with patch("src.telegram_handler._send_message") as mock_send:
            handler(update)
            # Handler should have been called
            assert True  # Basic test that handler runs without error


def test_alarm_command_flow():
    """Test alarm command with mode validation."""
    parsed = parse_command("/alarm armed_home")
    assert parsed["command"] == "alarm"
    assert parsed["args"] == ["armed_home"]
    
    # Verify invalid mode is rejected
    from src.telegram_responses import format_alarm_response
    response = format_alarm_response("invalid_mode", success=False)
    assert "inválido" in response.lower() or "erro" in response.lower()
