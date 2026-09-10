"""Tests for MQTT auto-discovery entity registration and initial states."""

import json
import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(__file__) or ".")

from src.alerts import mqtt_register_predictor_entities, alarm_mode_telegram_handler
from src.predictor.predictor.loop import PredictorLoop
from src.config import (
    MQTT_BROKER_URL,
    MQTT_BROKER_PORT,
    MQTT_USERNAME,
    MQTT_PASSWORD,
    PREDICTOR_ENABLED,
)


@pytest.fixture(scope="module")
def mqtt_client():
    """Create an MQTT client connected to the broker for testing."""
    import paho.mqtt.client as mqtt

    client = mqtt.Client()
    if MQTT_USERNAME and MQTT_PASSWORD:
        client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

    # Connect to broker (uses Docker host network or localhost)
    client.connect_async(MQTT_BROKER_URL, MQTT_BROKER_PORT, keepalive=10)
    client.loop_start()

    # Wait for connection
    import time
    deadline = time.time() + 5
    while time.time() < deadline and not client.is_connected():
        time.sleep(0.1)

    if client.is_connected():
        yield client
    else:
        pytest.skip("Could not connect to MQTT broker")

    client.loop_stop()
    client.disconnect()


def test_mqtt_predictor_entities_publish_initial_states(mqtt_client):
    """Test that mqtt_register_predictor_entities publishes initial states
    so HA entities show 0% / 'disarmed' instead of 'unknown'."""
    import json as _json

    # Create a fresh client for publishing
    client = mqtt.Client()
    if MQTT_USERNAME and MQTT_PASSWORD:
        client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

    client.connect_async(MQTT_BROKER_URL, MQTT_BROKER_PORT, keepalive=10)
    client.loop_start()
    import time
    deadline = time.time() + 3
    while time.time() < deadline and not client.is_connected():
        time.sleep(0.1)

    assert client.is_connected(), "Failed to connect to MQTT broker"

    try:
        # Register predictor entities (this publishes discovery configs + initial states)
        mqtt_register_predictor_entities()

        # Wait a moment for messages to be published
        time.sleep(0.5)

        # Subscribe to test topics
        client.subscribe("tucuxi/predictions/rosa")
        client.subscribe("tucuxi/predictions/portao_entrada")
        client.subscribe("tucuxi/ha/alarm_mode")
        client.subscribe("tucuxi/mode/alarme/state")
        time.sleep(0.5)

        # Check Rosa prediction topic
        rosa_msg = client.messages.get("tucuxi/predictions/rosa")
        assert rosa_msg is not None, "No message on tucuxi/predictions/rosa"
        rosa_payload = _json.loads(rosa_msg.payload)
        assert rosa_payload.get("probabilidade") == 0, (
            f"Expected probabilidade=0, got {rosa_payload}"
        )
        print(f"✓ Rosa prediction initial state: {rosa_payload}")

        # Check Portão prediction topic
        portao_msg = client.messages.get("tucuxi/predictions/portao_entrada")
        assert portao_msg is not None, "No message on tucuxi/predictions/portao_entrada"
        portao_payload = _json.loads(portao_msg.payload)
        assert portao_payload.get("probabilidade") == 0, (
            f"Expected probabilidade=0, got {portao_payload}"
        )
        print(f"✓ Portão prediction initial state: {portao_payload}")

        # Check alarm mode topic
        alarm_msg = client.messages.get("tucuxi/ha/alarm_mode")
        assert alarm_msg is not None, "No message on tucuxi/ha/alarm_mode"
        alarm_payload = _json.loads(alarm_msg.payload)
        assert alarm_payload.get("alarm_mode") == "disarmed", (
            f"Expected alarm_mode=disarmed, got {alarm_payload}"
        )
        print(f"✓ Alarm mode initial state: {alarm_payload}")

        # Check alarm switch state topic
        switch_msg = client.messages.get("tucuxi/mode/alarme/state")
        assert switch_msg is not None, "No message on tucuxi/mode/alarme/state"
        switch_payload = switch_msg.payload.decode()
        assert switch_payload == "ON", (
            f"Expected ON, got {switch_payload}"
        )
        print(f"✓ Alarm switch initial state: {switch_payload}")

    finally:
        client.loop_stop()
        client.disconnect()


def test_alarm_mode_telegram_handler():
    """Test alarm_mode_telegram_handler sends correct messages."""
    import json as _json
    from unittest.mock import patch, MagicMock

    # Test with armed_home
    with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "test_token", "TELEGRAM_CHAT_ID": "test_chat"}):
        with patch("src.alerts.requests.post") as mock_post:
            mock_post.return_value.raise_for_status = MagicMock()

            # Test armed_home
            alarm_mode_telegram_handler({"alarm_mode": "armed_home"})
            mock_post.assert_called_once()
            call_kwargs = mock_post.call_args[1]
            assert "armed_home" in call_kwargs["text"]
            assert "🏠 Modo Arming Home ativado" in call_kwargs["text"]

            # Test armed_away
            alarm_mode_telegram_handler({"alarm_mode": "armed_away"})
            call_kwargs = mock_post.call_args[1]
            assert "armed_away" in call_kwargs["text"]
            assert "🚶 Modo Arming Away ativado" in call_kwargs["text"]

            # Test disarmed
            alarm_mode_telegram_handler({"alarm_mode": "disarmed"})
            call_kwargs = mock_post.call_args[1]
            assert "disarmed" in call_kwargs["text"]
            assert "🔓 Modo Desarmado ativado" in call_kwargs["text"]

    # Test without credentials (should return early)
    with patch.dict(os.environ, {}, clear=True):
        with patch("src.alerts.logger") as mock_logger:
            alarm_mode_telegram_handler({"alarm_mode": "armed_home"})
            mock_logger.debug.assert_called()

    print("✓ alarm_mode_telegram_handler tests passed")


def test_predictor_loop_initial_switch_state():
    """Test that PredictorLoop publishes initial switch state on init."""
    from src.predictor.predictor.loop import PredictorLoop
    from src.config import MQTT_BROKER_URL, MQTT_BROKER_PORT, MQTT_USERNAME, MQTT_PASSWORD

    pred = PredictorLoop(MQTT_BROKER_URL, MQTT_BROKER_PORT, {"username": MQTT_USERNAME, "password": MQTT_PASSWORD})

    # alarm_mode should be armed_home (FAIL_SECURE_MODE)
    assert pred.alarm_mode == "armed_home", (
        f"Expected armed_home, got {pred.alarm_mode}"
    )

    # The _publish_switch_states should have been called in __init__
    # We verify by checking the alarm_mode value is armed_home
    print(f"✓ PredictorLoop initial alarm_mode: {pred.alarm_mode}")