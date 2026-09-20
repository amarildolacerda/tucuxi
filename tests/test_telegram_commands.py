# tests/test_telegram_commands.py
import pytest
from src.telegram_commands import parse_command


def test_parse_start_command():
    result = parse_command("/start")
    assert result["command"] == "start"
    assert result["args"] == []


def test_parse_status_command():
    result = parse_command("/status")
    assert result["command"] == "status"
    assert result["args"] == []


def test_parse_snapshot_with_id():
    result = parse_command("/snapshot 1")
    assert result["command"] == "snapshot"
    assert result["args"] == ["1"]


def test_parse_snapshot_with_name():
    result = parse_command("/snapshot portao")
    assert result["command"] == "snapshot"
    assert result["args"] == ["portao"]


def test_parse_alarm_command():
    result = parse_command("/alarm armed_home")
    assert result["command"] == "alarm"
    assert result["args"] == ["armed_home"]


def test_parse_events_default():
    result = parse_command("/events")
    assert result["command"] == "events"
    assert result["args"] == []


def test_parse_events_with_count():
    result = parse_command("/events 10")
    assert result["command"] == "events"
    assert result["args"] == ["10"]


def test_parse_cameras_command():
    result = parse_command("/cameras")
    assert result["command"] == "cameras"
    assert result["args"] == []


def test_parse_help_command():
    result = parse_command("/help")
    assert result["command"] == "help"
    assert result["args"] == []


def test_parse_unknown_command():
    result = parse_command("/unknown")
    assert result["command"] == "unknown"
    assert result["args"] == []


def test_parse_empty_text():
    result = parse_command("")
    assert result["command"] is None
    assert result["args"] == []


def test_parse_non_command_text():
    result = parse_command("hello world")
    assert result["command"] is None
    assert result["args"] == []
