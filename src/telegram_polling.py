# src/telegram_polling.py
"""Telegram polling thread for Tucuxi bot."""

import os
import logging
import time
import requests
import threading
from typing import Callable

logger = logging.getLogger(__name__)


def start_telegram_polling(handler: Callable, interval: float = 1.0, stop_event: threading.Event = None):
    """Start polling Telegram for updates.
    
    Args:
        handler: Function to process each update
        interval: Polling interval in seconds
        stop_event: Threading event to signal stopping
    """
    api_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not api_token:
        logger.debug("Telegram polling skipped: TELEGRAM_BOT_TOKEN not configured")
        return
    
    offset = 0
    url = f"https://api.telegram.org/bot{api_token}/getUpdates"
    
    logger.info("Telegram polling started (interval=%.1fs)", interval)
    
    while stop_event is None or not stop_event.is_set():
        try:
            params = {"offset": offset, "timeout": interval}
            response = requests.get(url, params=params, timeout=interval + 5)
            data = response.json()
            
            if data.get("ok") and data.get("result"):
                for update in data["result"]:
                    try:
                        handler(update)
                    except Exception:
                        logger.exception("Failed to process Telegram update")
                    
                    offset = update["update_id"] + 1
        
        except requests.exceptions.Timeout:
            # Normal timeout, continue polling
            pass
        except Exception:
            logger.exception("Telegram polling error")
            time.sleep(interval)
    
    logger.info("Telegram polling stopped")
