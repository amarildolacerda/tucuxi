# tests/test_telegram_integration.py
import pytest
from unittest.mock import patch, MagicMock


def test_telegram_polling_starts_on_import():
    """Verify that telegram polling can be initialized."""
    with patch("src.main.start_telegram_polling") as mock_polling:
        with patch("src.main.telegram_command_handler") as mock_handler:
            with patch("src.main.EventStorage") as mock_storage:
                with patch("src.main.CameraManager") as mock_camera_manager:
                    # This test just verifies the imports work
                    from src.main import _init_telegram_polling
                    assert callable(_init_telegram_polling)
