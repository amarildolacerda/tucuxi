import json
import os
import pytest
import requests
from src.alerts import AlertService, telegram_handler, mqtt_handler, home_assistant_handler
from src.notifications import CHANNELS, EVENT_TYPES, DEFAULT_ROUTING, is_enabled


def test_alert_service_calls_handlers(monkeypatch):
    called = []

    def handler(payload):
        called.append(payload)

    service = AlertService()
    service.register_handler(handler)
    service.send("1", "entrada", "motion_detected", "teste")

    assert len(called) == 1
    assert called[0]["camera_id"] == "1"
    assert called[0]["event_type"] == "motion_detected"


def test_telegram_handler_skips_without_config(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    def fake_post(*args, **kwargs):
        raise AssertionError("requests.post should not be called")

    monkeypatch.setattr("src.alerts.requests.post", fake_post)
    telegram_handler({"camera_id": "1", "event_type": "motion_detected"})


def test_telegram_handler_sends_message(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token123")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat123")

    class DummyResponse:
        status_code = 200

        def raise_for_status(self):
            return None

    called = {}

    def fake_post(url, data=None, timeout=None):
        called["url"] = url
        called["data"] = data
        called["timeout"] = timeout
        return DummyResponse()

    monkeypatch.setattr("src.alerts.requests.post", fake_post)

    telegram_handler({"camera_id": "1", "zone": "entrada", "event_type": "motion_detected", "details": "detalhe"})

    assert called["url"].startswith("https://api.telegram.org/bottoken123/sendMessage")
    assert called["data"]["chat_id"] == "chat123"
    assert "detalhe" in called["data"]["text"]
    assert called["data"]["parse_mode"] == "Markdown"
    assert called["timeout"] == 10


def test_mqtt_handler_publishes(monkeypatch):
    monkeypatch.setenv("MQTT_BROKER_URL", "test-broker")
    monkeypatch.setenv("MQTT_BROKER_PORT", "1883")
    monkeypatch.setenv("MQTT_USERNAME", "user")
    monkeypatch.setenv("MQTT_PASSWORD", "pass")
    monkeypatch.setenv("MQTT_TOPIC", "test/topic")

    captured = {}

    def fake_publish_single(topic, payload=None, hostname=None, port=None, auth=None, qos=None, retain=None):
        captured["topic"] = topic
        captured["payload"] = payload
        captured["hostname"] = hostname
        captured["port"] = port
        captured["auth"] = auth
        captured["qos"] = qos
        captured["retain"] = retain

    monkeypatch.setattr("src.alerts.publish.single", fake_publish_single)
    payload = {"camera_id": "1", "event_type": "motion_detected"}
    mqtt_handler(payload)

    assert captured["topic"] == "test/topic"
    assert json.loads(captured["payload"])["camera_id"] == "1"
    assert captured["hostname"] == "test-broker"
    assert captured["port"] == 1883
    assert captured["auth"] == {"username": "user", "password": "pass"}


def test_home_assistant_handler_skips_without_token(monkeypatch):
    monkeypatch.delenv("HOME_ASSISTANT_TOKEN", raising=False)

    def fake_post(*args, **kwargs):
        raise AssertionError("requests.post should not be called")

    monkeypatch.setattr("src.alerts.requests.post", fake_post)
    home_assistant_handler({"camera_id": "1", "event_type": "motion_detected"})


def test_home_assistant_handler_sends_event(monkeypatch):
    monkeypatch.setenv("HOME_ASSISTANT_URL", "http://ha.local:8123")
    monkeypatch.setenv("HOME_ASSISTANT_TOKEN", "secret")
    monkeypatch.setenv("HOME_ASSISTANT_EVENT_TYPE", "secur_alert")

    called = {}

    class DummyResponse:
        status_code = 200

        def raise_for_status(self):
            return None

    def fake_post(url, headers=None, json=None, timeout=None):
        called["url"] = url
        called["headers"] = headers
        called["json"] = json
        called["timeout"] = timeout
        return DummyResponse()

    monkeypatch.setattr("src.alerts.requests.post", fake_post)
    payload = {"camera_id": "1", "event_type": "motion_detected"}
    home_assistant_handler(payload)

    assert called["url"] == "http://ha.local:8123/api/events/secur_alert"
    assert called["headers"]["Authorization"] == "Bearer secret"
    assert called["json"] == payload
    assert called["timeout"] == 10


def test_notifications_registry():
    assert [c["key"] for c in CHANNELS] == ["telegram", "automation"]
    keys = [e["key"] for e in EVENT_TYPES]
    assert "motion_detected" in keys
    assert "no_motion" in keys
    assert "intruder_detected" in keys
    assert "loitering" in keys
    assert "direction_change" in keys
    assert "fall_detected" in keys
    assert "object_detected" in keys
    legacy = [e for e in EVENT_TYPES if e.get("legacy")]
    assert [e["key"] for e in legacy] == ["object_detected"]


def test_behavior_events_are_alerts():
    categories = {e["key"]: e["category"] for e in EVENT_TYPES}
    assert categories["loitering"] == "alerta"
    assert categories["direction_change"] == "alerta"
    assert categories["fall_detected"] == "alerta"


def test_default_routing_no_motion_off_telegram():
    assert DEFAULT_ROUTING["telegram"]["no_motion"] is False
    assert DEFAULT_ROUTING["telegram"]["motion_detected"] is True
    assert DEFAULT_ROUTING["automation"]["no_motion"] is True
    assert DEFAULT_ROUTING["automation"]["snapshot_info"] is False


def test_default_routing_behavior_events():
    # Telegram: loitering/direction off (verboso), queda on (emergência)
    assert DEFAULT_ROUTING["telegram"]["loitering"] is False
    assert DEFAULT_ROUTING["telegram"]["direction_change"] is False
    assert DEFAULT_ROUTING["telegram"]["fall_detected"] is True
    # Automation: todos os eventos de comportamento on
    assert DEFAULT_ROUTING["automation"]["loitering"] is True
    assert DEFAULT_ROUTING["automation"]["direction_change"] is True
    assert DEFAULT_ROUTING["automation"]["fall_detected"] is True


def test_is_enabled_defaults_true():
    assert is_enabled({}, "telegram", "motion_detected") is True
    assert is_enabled({"telegram": {"motion_detected": False}}, "telegram", "motion_detected") is False
    # Linha ausente cai no DEFAULT_ROUTING (no_motion/telegram default False) —
    # antes o fallback cego era True e notificações chegavam mesmo desabilitadas.
    assert is_enabled({"telegram": {"motion_detected": False}}, "telegram", "no_motion") is False


def test_is_enabled_falls_back_to_default_routing():
    # (i) linha existente false → False
    assert is_enabled({"telegram": {"motion_detected": False}}, "telegram", "motion_detected") is False
    # (ii) linha ausente, DEFAULT_ROUTING True → True
    assert is_enabled({}, "telegram", "motion_detected") is True
    assert is_enabled({"telegram": {}}, "telegram", "motion_detected") is True
    # (iii) linha ausente, DEFAULT_ROUTING False → False (ex: unknown_detected/telegram)
    assert is_enabled({}, "telegram", "unknown_detected") is False
    assert is_enabled({"telegram": {}}, "telegram", "unknown_detected") is False
    # (iv) canal inexistente no DEFAULT_ROUTING → permissivo final True
    assert is_enabled({}, "email", "motion_detected") is True


def test_alert_service_respects_routing(monkeypatch):
    called = []

    def handler(payload):
        called.append(payload)
    handler.channel = "telegram"

    service = AlertService()
    service.register_handler(handler)
    routing = {"telegram": {"motion_detected": False}}
    service.send("1", "entrada", "motion_detected", "teste", routing=routing)
    assert called == []

    # intruder_detected sem linha: default telegram é True → envia
    service.send("1", "entrada", "intruder_detected", "teste", routing=routing)
    assert len(called) == 1
    assert called[0]["event_type"] == "intruder_detected"


def test_alert_service_routing_channels_restricts_handlers(monkeypatch):
    """Task 6: routing_channels (regra N4) restringe quais canais disparam,
    ainda respeitando o routing de configuração."""
    called = []

    def h1(payload):
        called.append("telegram")
    h1.channel = "telegram"

    def h2(payload):
        called.append("automation")
    h2.channel = "automation"

    service = AlertService()
    service.register_handler(h1)
    service.register_handler(h2)

    # Regra restringe apenas ao canal telegram
    service.send("1", "entrada", "intruder_detected", "x", routing_channels=["telegram"])
    assert called == ["telegram"]

    called.clear()
    service.send("1", "entrada", "intruder_detected", "x", routing_channels=["automation"])
    assert called == ["automation"]

    # Sem routing_channels → sem restrição de regra (todos disparam)
    called.clear()
    service.send("1", "entrada", "intruder_detected", "x")
    assert called == ["telegram", "automation"]


def test_alert_service_skips_no_motion_for_telegram(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token123")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat123")

    def fake_post(*args, **kwargs):
        raise AssertionError("requests.post should not be called for no_motion")

    monkeypatch.setattr("src.alerts.requests.post", fake_post)

    service = AlertService()
    service.register_handler(telegram_handler)
    service.routing = {"telegram": {"no_motion": False}}
    service.send("1", "entrada", "no_motion", "teste")


def test_alert_service_with_storage_does_not_persist(monkeypatch):
    """Regressão Task 6: AlertService não persiste mais via storage — quem
    persiste é o AlertRuleEngine. Um storage passado no __init__ é ignorado."""
    recorded = []

    class FakeStorage:
        def add_event(self, camera_id, zone, event_type, details=None):
            recorded.append((camera_id, zone, event_type, details))

    service = AlertService(storage=FakeStorage())
    service.send("1", "entrada", "no_motion", "Sem movimento")

    assert recorded == []


def test_alert_service_payload_includes_optional_paths(monkeypatch):
    called = []

    def handler(payload):
        called.append(payload)

    service = AlertService()
    service.register_handler(handler)
    service.send(
        "1", "entrada", "motion_detected", "teste",
        thumbnail_path="/tmp/thumb.jpg", clip_path="/tmp/clip.mp4",
    )

    assert called[0]["thumbnail_path"] == "/tmp/thumb.jpg"
    assert called[0]["clip_path"] == "/tmp/clip.mp4"


def test_alert_service_returns_none_without_persistence(monkeypatch):
    """Task 6: send NÃO persiste mais — sem handler com retorno, o resultado
    é None (não existe mais handler de storage devolvendo um id)."""
    class FakeStorage:
        def add_event(self, camera_id, zone, event_type, details=None):
            return 42

    service = AlertService(storage=FakeStorage())
    event_id = service.send("1", "entrada", "motion_detected", "teste")
    assert event_id is None

    # Sem storage também: um handler comum que não devolve id → None.
    service2 = AlertService()
    service2.register_handler(lambda payload: None)
    assert service2.send("1", "entrada", "motion_detected") is None


def test_format_message_full_context():
    from src.alerts import _format_message
    payload = {
        "camera_id": "1",
        "zone": "Sala",
        "event_type": "intruder_detected",
        "details": "Pessoa detectada",
        "zone_classification": "privativa",
        "identity": "João",
        "known": True,
        "recognition_method": "face",
        "category": "person",
        "thumbnail_path": "/tmp/thumb.jpg",
        "clip_path": "/tmp/clip.mp4",
    }
    text = _format_message(payload)
    assert "privativa" in text
    assert "João" in text
    assert "face" in text
    assert "person" in text
    assert "thumb.jpg" in text
    assert "clip.mp4" in text


def test_format_message_minimal():
    from src.alerts import _format_message
    text = _format_message({"camera_id": "1", "zone": "entrada", "event_type": "motion_detected"})
    assert "Sem detalhes adicionais" in text
    assert "privativa" not in text
    assert "Identidade" not in text


def test_telegram_handler_sends_photo(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token123")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat123")
    thumb = tmp_path / "thumb.jpg"
    thumb.write_bytes(b"jpegdata")

    class DummyResponse:
        status_code = 200

        def raise_for_status(self):
            return None

    called = {}

    def fake_post(url, data=None, files=None, timeout=None):
        called["url"] = url
        called["data"] = data
        called["files"] = files
        called["timeout"] = timeout
        return DummyResponse()

    monkeypatch.setattr("src.alerts.requests.post", fake_post)
    telegram_handler({
        "camera_id": "1", "zone": "entrada", "event_type": "motion_detected",
        "details": "detalhe", "thumbnail_path": str(thumb),
    })

    assert called["url"].startswith("https://api.telegram.org/bottoken123/sendPhoto")
    assert called["data"]["chat_id"] == "chat123"
    assert "photo" in called["files"]
    assert called["timeout"] == 10


def test_telegram_handler_falls_back_to_text_when_thumbnail_missing(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token123")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat123")

    class DummyResponse:
        status_code = 200

        def raise_for_status(self):
            return None

    called = {}

    def fake_post(url, data=None, files=None, timeout=None):
        called["url"] = url
        called["data"] = data
        called["files"] = files
        return DummyResponse()

    monkeypatch.setattr("src.alerts.requests.post", fake_post)
    telegram_handler({
        "camera_id": "1", "zone": "entrada", "event_type": "motion_detected",
        "details": "detalhe", "thumbnail_path": "/tmp/nao-existe.jpg",
    })

    assert called["url"].startswith("https://api.telegram.org/bottoken123/sendMessage")
    assert called["files"] is None


def test_telegram_handler_photo_failure_falls_back_to_text(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token123")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat123")
    thumb = tmp_path / "thumb.jpg"
    thumb.write_bytes(b"jpegdata")

    class DummyResponse:
        status_code = 200

        def raise_for_status(self):
            return None

    calls = []

    def fake_post(url, data=None, files=None, timeout=None):
        calls.append(url)
        if len(calls) == 1:
            raise requests.exceptions.ConnectionError("upload failed")
        return DummyResponse()

    monkeypatch.setattr("src.alerts.requests.post", fake_post)
    telegram_handler({
        "camera_id": "1", "zone": "entrada", "event_type": "motion_detected",
        "details": "detalhe", "thumbnail_path": str(thumb),
    })

    assert len(calls) == 2
    assert calls[1].startswith("https://api.telegram.org/bottoken123/sendMessage")


# ── Fase 5.1: siren_handler ──
def test_siren_handler_publishes_for_critical_event(monkeypatch):
    from src import alerts
    calls = []
    def fake_single(topic, payload=None, hostname=None, port=None, auth=None, qos=None, retain=None):
        calls.append((topic, payload))
    monkeypatch.setattr(alerts.publish, "single", fake_single)
    monkeypatch.setenv("MQTT_BROKER_URL", "localhost")
    monkeypatch.setenv("MQTT_BROKER_PORT", "1883")
    alerts.siren_handler({
        "event_type": "intruder_detected", "camera_id": 1, "zone": "entrada", "timestamp": 123.0,
    })
    assert len(calls) == 1
    topic, payload = calls[0]
    assert topic == alerts.SIREN_MQTT_TOPIC
    data = json.loads(payload)
    assert data["action"] == "siren"
    assert data["event_type"] == "intruder_detected"
    assert data["camera_id"] == 1


def test_siren_handler_skips_non_critical_event(monkeypatch):
    from src import alerts
    calls = []
    monkeypatch.setattr(alerts.publish, "single", lambda *a, **k: calls.append(a))
    monkeypatch.setenv("MQTT_BROKER_URL", "localhost")
    alerts.siren_handler({"event_type": "motion_detected", "camera_id": 1})
    assert calls == []


def test_siren_handler_skips_without_broker(monkeypatch):
    from src import alerts
    calls = []
    monkeypatch.setattr(alerts.publish, "single", lambda *a, **k: calls.append(a))
    monkeypatch.delenv("MQTT_BROKER_URL", raising=False)
    alerts.siren_handler({"event_type": "intruder_detected", "camera_id": 1})
    assert calls == []
