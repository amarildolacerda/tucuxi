import src.alerts as alerts
from src.notifications import DEFAULT_ROUTING


def _payload(event_type, zone_classification="privativa", identity="João", known=True, category="person"):
    return {
        "camera_id": "1", "zone": "Entrada", "event_type": event_type,
        "details": "x", "zone_classification": zone_classification,
        "identity": identity, "known": known, "recognition_method": "face",
        "category": category,
    }


def test_telegram_skips_known_unknown_and_snapshot(monkeypatch):
    calls = []
    def fake_post(url, data=None, timeout=None, json=None):
        calls.append((url, data, json))
        class R:
            def raise_for_status(self): pass
        return R()
    monkeypatch.setattr(alerts.requests, "post", fake_post)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "y")

    service = alerts.AlertService()
    service.register_handler(alerts.telegram_handler)
    service.routing = DEFAULT_ROUTING

    for skipped in ("snapshot_info", "identity_recognized", "unknown_detected", "no_motion"):
        calls.clear()
        service.send("1", "Entrada", skipped, details="x")
        assert calls == [], f"telegram must skip {skipped}"

    calls.clear()
    service.send("1", "Entrada", "intruder_detected", details="x")
    assert len(calls) == 1, "telegram must alarm on intruder"

    calls.clear()
    service.send("1", "Entrada", "motion_detected", details="x")
    assert len(calls) == 1, "telegram must alarm on motion"


def test_mqtt_only_intruder(monkeypatch):
    import paho.mqtt.client as mqtt_mod

    instances = []
    class FakeClient:
        def __init__(self, *a, **k):
            self.published = []
            instances.append(self)
        def username_pw_set(self, *a, **k): pass
        def connect_async(self, *a, **k): pass
        def loop_start(self): pass
        def loop_stop(self): pass
        def is_connected(self): return True
        def enable_logger(self, *a, **k): pass
        def connect(self, *a, **k): pass
        def loop_forever(self, *a, **k): pass
        def publish(self, topic, payload, *a, **k):
            self.published.append((topic, payload))
            return None
        def disconnect(self): pass

    monkeypatch.setattr(mqtt_mod, "Client", FakeClient)
    monkeypatch.setenv("MQTT_BROKER_URL", "broker")
    monkeypatch.delenv("MQTT_TOPIC", raising=False)

    service = alerts.AlertService()
    service.register_handler(alerts.mqtt_handler)
    service.routing = DEFAULT_ROUTING

    instances.clear()
    service.send("1", "Entrada", "intruder_detected", details="x")
    assert instances and instances[0].published, "intruder must publish to MQTT"

    instances.clear()
    service.send("1", "Entrada", "identity_recognized", details="x")
    assert instances and instances[0].published, "identity must publish to MQTT (automation routing True)"

    instances.clear()
    service.send("1", "Entrada", "unknown_detected", details="x")
    assert instances and instances[0].published, "unknown_detected must publish to MQTT (automation routing True)"

    instances.clear()
    service.send("1", "Entrada", "snapshot_info", details="x")
    assert not (instances and instances[0].published), "snapshot_info must NOT publish to MQTT"


def test_ha_receives_all_identity_events(monkeypatch):
    calls = []
    def fake_post(url, data=None, timeout=None, json=None, **kwargs):
        calls.append((url, json))
        class R:
            def raise_for_status(self): pass
        return R()
    monkeypatch.setattr(alerts.requests, "post", fake_post)
    monkeypatch.setenv("HOME_ASSISTANT_TOKEN", "tok")
    monkeypatch.setenv("HOME_ASSISTANT_URL", "http://ha")

    for ev in ("identity_recognized", "intruder_detected", "unknown_detected"):
        calls.clear()
        alerts.home_assistant_handler(_payload(ev))
        assert calls, f"HA must receive {ev}"

    calls.clear()
    alerts.home_assistant_handler(_payload("snapshot_info"))
    assert calls == [], "HA must skip snapshot_info"

    calls.clear()
    alerts.home_assistant_handler(_payload("motion_detected", zone_classification="pública"))
    assert calls == [], "HA must skip public motion"

    calls.clear()
    alerts.home_assistant_handler(_payload("motion_detected", zone_classification="privativa"))
    assert calls, "HA must send private motion"
