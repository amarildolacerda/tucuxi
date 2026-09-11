"""Testes das regras N4 (event_rules) — foco: roteamento para o canal real
dos handlers MQTT/Home Assistant/Sirene (canal 'automation').

Regressão (bug HA/MQTT): as regras usavam os canais legados 'mqtt'/'ha'
que não correspondem a handler nenhum (todos usam channel='automation').
Resultado: mqtt_handler, home_assistant_handler e siren_handler NUNCA eram
invocados — o Motion sensor do Home Assistant ficava sempre 'idle'.
"""

import pytest

from src.event_rules import evaluate_rules


@pytest.mark.parametrize(
    "event_type,no_motion",
    [
        ("motion_detected", False),
        ("snapshot_info", False),
        ("no_motion", True),
    ],
)
def test_motion_events_route_to_automation_channel(event_type, no_motion):
    """Motion/no_motion/snapshot_info precisam chegar ao canal 'automation'
    (onde estÃ£o mqtt_handler/home_assistant_handler), senÃ£o o Motion sensor
    do HA nunca alterna entre motion/idle."""
    channels = evaluate_rules(event_type, "privada", no_motion)["alert"]
    assert "automation" in channels


def test_rules_use_real_handler_channel_not_legacy_names():
    """Nenhuma regra deve usar os canais legados 'mqtt'/'ha' — eles
    nÃ£o correspondem a handler nenhum e silenciam MQTT/HA/Sirene."""
    for event_type in ("motion_detected", "snapshot_info", "no_motion",
                       "fall_detected", "intruder_detected", "loitering",
                       "direction_change", "identity_recognized"):
        channels = evaluate_rules(event_type, "privada", event_type == "no_motion")["alert"]
        assert "mqtt" not in channels
        assert "ha" not in channels


def test_motion_event_publica_mqtt_via_rules(monkeypatch):
    """IntegraÃ§Ã£o: derivando routing_channels das RULES (fix), o mqtt_handler
    (channel='automation') precisa publicar de fato em MQTT — hoje nÃ£o
    publica porque a regra de motion/snapshot_info nÃ£o inclui 'automation'."""
    from src.alerts import AlertService, mqtt_handler
    from src.event_rules import evaluate_rules

    calls = []
    monkeypatch.setattr("src.alerts.publish.single", lambda *a, **k: calls.append((a, k)))
    monkeypatch.setenv("MQTT_BROKER_URL", "localhost")
    monkeypatch.setenv("MQTT_TOPIC", "homeassistant/security/alert")

    service = AlertService()
    service.register_handler(mqtt_handler)

    for event_type, no_motion in (("motion_detected", False), ("snapshot_info", False), ("no_motion", True)):
        calls.clear()
        channels = evaluate_rules(event_type, "privada", no_motion)["alert"]
        service.send("1", "entrada", event_type, "x", routing_channels=channels)
        assert calls, f"{event_type} deveria publicar em MQTT (canais={channels})"
