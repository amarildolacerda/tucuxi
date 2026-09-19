# tests/test_telegram_polling.py
import pytest
import time
import threading
from unittest.mock import patch, MagicMock
from src.telegram_polling import start_telegram_polling


def test_polling_starts_and_stops():
    with patch("src.telegram_polling.requests") as mock_requests:
        with patch("src.telegram_polling.os.getenv", return_value="test_token"):
            # Mock getUpdates response
            mock_response = MagicMock()
            mock_response.json.return_value = {"ok": True, "result": []}
            mock_requests.get.return_value = mock_response
            
            handler = MagicMock()
            
            # Start polling in a thread
            stop_event = threading.Event()
            
            def run_polling():
                start_telegram_polling(handler, 0.1, stop_event)
            
            thread = threading.Thread(target=run_polling)
            thread.daemon = True
            thread.start()
            
            # Let it run for a short time
            time.sleep(0.3)
            
            # Stop polling
            stop_event.set()
            time.sleep(0.1)
            
            # Verify handler was called (or at least getUpdates was called)
            assert mock_requests.get.called


def test_polling_processes_updates():
    with patch("src.telegram_polling.requests") as mock_requests:
        with patch("src.telegram_polling.os.getenv", return_value="test_token"):
            # Mock getUpdates response with an update
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "ok": True,
                "result": [
                    {
                        "update_id": 1,
                        "message": {
                            "text": "/start",
                            "chat": {"id": 123456},
                            "message_id": 1
                        }
                    }
                ]
            }
            mock_requests.get.return_value = mock_response
            
            handler = MagicMock()
            
            stop_event = threading.Event()
            
            def run_polling():
                start_telegram_polling(handler, 0.1, stop_event)
            
            thread = threading.Thread(target=run_polling)
            thread.daemon = True
            thread.start()
            
            time.sleep(0.3)
            stop_event.set()
            time.sleep(0.1)
            
            # Verify handler was called with the update
            handler.assert_called()
