# src/telegram_handler.py
"""Telegram command handler for Tucuxi bot."""

import os
import json
import logging
import requests
from .telegram_commands import parse_command
from .telegram_responses import (
    format_start_response,
    format_status_response,
    format_events_response,
    format_cameras_response,
    format_help_response,
    format_alarm_response,
    format_snapshot_error,
    format_access_denied,
)

logger = logging.getLogger(__name__)


def telegram_command_handler(storage, camera_manager):
    """Create a command handler function.
    
    Args:
        storage: EventStorage instance for querying events
        camera_manager: CameraManager instance for camera operations
        
    Returns:
        Function that processes Telegram updates
    """
    def handler(update: dict):
        message = update.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        text = message.get("text", "")
        
        # Validate chat_id
        authorized_chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if str(chat_id) != str(authorized_chat_id):
            _send_message(chat_id, format_access_denied())
            return
        
        # Parse command
        parsed = parse_command(text)
        command = parsed["command"]
        args = parsed["args"]
        
        # Process command
        if command == "start":
            _send_message(chat_id, format_start_response())
        
        elif command == "status":
            cameras = camera_manager.storage.list_cameras() if hasattr(camera_manager, "storage") else []
            alarm_mode = _get_alarm_mode()
            last_event = _get_last_event(storage)
            _send_message(chat_id, format_status_response(cameras, alarm_mode, last_event))
        
        elif command == "snapshot":
            if not args:
                _send_message(chat_id, "Uso: /snapshot <id|nome>")
                return
            _handle_snapshot(chat_id, args[0], camera_manager)
        
        elif command == "alarm":
            if not args:
                _send_message(chat_id, "Uso: /alarm <armed_home|armed_away|disarmed>")
                return
            _handle_alarm(chat_id, args[0])
        
        elif command == "events":
            count = int(args[0]) if args and args[0].isdigit() else 5
            events = _get_events(storage, count)
            _send_message(chat_id, format_events_response(events))
        
        elif command == "cameras":
            cameras = camera_manager.storage.list_cameras() if hasattr(camera_manager, "storage") else []
            _send_message(chat_id, format_cameras_response(cameras))
        
        elif command == "help":
            _send_message(chat_id, format_help_response())
        
        else:
            _send_message(chat_id, f"Comando desconhecido: /{command}\nUse /help para ver comandos disponíveis.")
    
    return handler


def _send_message(chat_id: int, text: str):
    """Send a text message via Telegram API."""
    api_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not api_token:
        logger.debug("Telegram send skipped: TELEGRAM_BOT_TOKEN not configured")
        return
    
    url = f"https://api.telegram.org/bot{api_token}/sendMessage"
    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }
    
    try:
        response = requests.post(url, data=data, timeout=10)
        response.raise_for_status()
    except Exception:
        logger.exception("Failed to send Telegram message")


def _handle_snapshot(chat_id: int, camera_ref: str, camera_manager):
    """Handle snapshot command."""
    # Find camera by ID or name
    cameras = camera_manager.storage.list_cameras() if hasattr(camera_manager, "storage") else []
    camera = None
    for cam in cameras:
        if str(cam.get("id")) == camera_ref or cam.get("name", "").lower() == camera_ref.lower():
            camera = cam
            break
    
    if not camera:
        _send_message(chat_id, f"Câmera não encontrada: {camera_ref}")
        return
    
    # Get worker and capture frame
    worker = camera_manager.get_worker(camera["id"]) if hasattr(camera_manager, "get_worker") else None
    if not worker:
        _send_message(chat_id, format_snapshot_error("Câmera offline"))
        return
    
    # Capture and send photo
    _send_photo_from_worker(chat_id, worker, camera["name"])


def _send_photo_from_worker(chat_id: int, worker, camera_name: str):
    """Capture frame from worker and send as photo."""
    api_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not api_token:
        return
    
    try:
        # Get current frame from worker
        frame = worker.get_current_frame() if hasattr(worker, "get_current_frame") else None
        if frame is None:
            _send_message(chat_id, format_snapshot_error("Não foi possível capturar frame"))
            return
        
        # Encode frame to JPEG
        import cv2
        _, buffer = cv2.imencode(".jpg", frame)
        
        url = f"https://api.telegram.org/bot{api_token}/sendPhoto"
        data = {"chat_id": chat_id, "caption": f"📷 {camera_name}"}
        
        response = requests.post(
            url,
            data=data,
            files={"photo": ("snapshot.jpg", buffer.tobytes(), "image/jpeg")},
            timeout=10
        )
        response.raise_for_status()
    except Exception:
        logger.exception("Failed to send snapshot")
        _send_message(chat_id, format_snapshot_error("Erro ao enviar snapshot"))


def _handle_alarm(chat_id: int, mode: str):
    """Handle alarm mode change command."""
    valid_modes = ["armed_home", "armed_away", "disarmed"]
    if mode not in valid_modes:
        _send_message(chat_id, format_alarm_response(mode, success=False))
        return
    
    # Publish alarm mode via MQTT
    try:
        import paho.mqtt.publish as publish
        broker = os.getenv("MQTT_BROKER_URL", "192.168.1.12")
        port = int(os.getenv("MQTT_BROKER_PORT", "1883"))
        username = os.getenv("MQTT_USERNAME")
        password = os.getenv("MQTT_PASSWORD")
        
        auth = {"username": username, "password": password} if username and password else None
        payload = json.dumps({"alarm_mode": mode})
        
        publish.single("tucuxi/mode/alarme/set", payload, hostname=broker, port=port, auth=auth)
        _send_message(chat_id, format_alarm_response(mode, success=True))
    except Exception:
        logger.exception("Failed to change alarm mode")
        _send_message(chat_id, format_alarm_response(mode, success=False))


def _get_alarm_mode() -> str:
    """Get current alarm mode from MQTT or storage."""
    # This would need to be implemented based on how alarm mode is stored
    return "armed_home"  # Default fallback


def _get_last_event(storage) -> dict:
    """Get the most recent event from storage."""
    try:
        events = storage.get_recent_events(1) if hasattr(storage, "get_recent_events") else []
        return events[0] if events else {}
    except Exception:
        return {}


def _get_events(storage, count: int) -> list:
    """Get recent events from storage."""
    try:
        return storage.get_recent_events(count) if hasattr(storage, "get_recent_events") else []
    except Exception:
        return []
