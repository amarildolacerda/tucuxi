"""Routing do snapshot_info para o canal automation (sensor Motion do HA)."""
from src.event_rules import evaluate_rules
from src.notifications import DEFAULT_ROUTING


def test_automation_snapshot_info_enabled_by_default():
    """Objetos detectados devem chegar ao HA por padrão (sensor Motion)."""
    assert DEFAULT_ROUTING["automation"]["snapshot_info"] is True


def test_snapshot_info_reaches_mqtt_state_via_db_routing(tmp_path, monkeypatch):
    """Cenário reportado: truck detectado (snapshot_info) deve ligar o motion (ON).
    Usa routing real do banco, como o main faz."""
    from src.alerts import AlertService, mqtt_handler
    from src.storage import EventStorage

    calls = []
    monkeypatch.setattr("src.alerts.publish.single", lambda *a, **k: calls.append((a, k)))
    monkeypatch.setenv("MQTT_BROKER_URL", "localhost")
    monkeypatch.setenv("MQTT_TOPIC", "homeassistant/security/alert")

    storage = EventStorage(tmp_path / "events.db")
    storage.ensure_default_routing(DEFAULT_ROUTING)

    service = AlertService()
    service.register_handler(mqtt_handler)
    service.routing = storage.get_all_routing()
    channels = evaluate_rules("snapshot_info", "privada", False)["alert"]
    service.send("1", "entrada", "snapshot_info", "Objetos detectados: truck",
                 routing_channels=channels)

    states = [c for c in calls if c[0][0] == "secur/secur_cam1/state"]
    assert states and states[-1][1].get("payload") == "ON"


def test_snapshot_automation_migration_runs_once(tmp_path):
    """DB legado com automation.snapshot_info=False deve ser corrigido uma vez;
    mudança posterior do usuário deve ser respeitada."""
    from src.notifications import ensure_snapshot_automation_routing
    from src.storage import EventStorage

    storage = EventStorage(tmp_path / "events.db")
    storage.set_routing("automation", "snapshot_info", False)

    assert ensure_snapshot_automation_routing(storage) is True
    assert storage.get_routing("automation")["snapshot_info"] is True

    storage.set_routing("automation", "snapshot_info", False)
    assert ensure_snapshot_automation_routing(storage) is False
    assert storage.get_routing("automation")["snapshot_info"] is False
