# tests/test_telegram_responses.py
import pytest
from src.telegram_responses import (
    format_start_response,
    format_status_response,
    format_events_response,
    format_cameras_response,
    format_help_response,
    format_alarm_response,
    format_snapshot_error,
    format_access_denied,
)


def test_format_start_response():
    result = format_start_response()
    assert "Bem-vindo" in result or "Tucuxi" in result
    assert "/status" in result
    assert "/snapshot" in result


def test_format_status_response():
    cameras = [{"id": 1, "name": "Portão", "zone": "Entrada"}]
    alarm_mode = "armed_home"
    last_event = {"event_type": "motion_detected", "camera_id": 1}
    
    result = format_status_response(cameras, alarm_mode, last_event)
    assert "1 configurada" in result
    assert "armed_home" in result or "armado" in result.lower()
    assert "motion_detected" in result or "movimento" in result.lower()


def test_format_events_response():
    events = [
        {"event_type": "motion_detected", "camera_id": 1, "timestamp": 1234567890},
        {"event_type": "object_detected", "camera_id": 2, "timestamp": 1234567880},
    ]
    result = format_events_response(events)
    assert "motion_detected" in result or "movimento" in result.lower()
    assert "object_detected" in result or "objeto" in result.lower()


def test_format_events_empty():
    result = format_events_response([])
    assert "nenhum" in result.lower() or "sem eventos" in result.lower()


def test_format_cameras_response():
    cameras = [
        {"id": 1, "name": "Portão", "zone": "Entrada", "status": "online"},
        {"id": 2, "name": "Jardim", "zone": "Extrema", "status": "offline"},
    ]
    result = format_cameras_response(cameras)
    assert "Portão" in result
    assert "Jardim" in result
    assert "🟢" in result or "🔴" in result


def test_format_help_response():
    result = format_help_response()
    assert "/start" in result
    assert "/status" in result
    assert "/snapshot" in result
    assert "/alarm" in result
    assert "/events" in result
    assert "/cameras" in result
    assert "/help" in result


def test_format_alarm_response_success():
    result = format_alarm_response("armed_home", success=True)
    assert "armed_home" in result or "armado" in result.lower()


def test_format_alarm_response_invalid():
    result = format_alarm_response("invalid_mode", success=False)
    assert "inválido" in result.lower() or "erro" in result.lower()


def test_format_snapshot_error():
    result = format_snapshot_error("Camera not found")
    assert "erro" in result.lower() or "não encontrada" in result.lower()


def test_format_access_denied():
    result = format_access_denied()
    assert "acesso" in result.lower() or "negado" in result.lower()
