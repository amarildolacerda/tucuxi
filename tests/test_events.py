from src.event_rules import decide_worker_event, _unpack_worker_decision
import pytest


@pytest.fixture
def app(tmp_path):
    from src.app import create_app
    app = create_app(db_path=tmp_path / "test.db")
    app.config.update({"TESTING": True})
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def test_decide_fall():
    et, det, *_ = decide_worker_event([], None, "public", "cam1", fall=True, now=1.0)
    assert et == "fall_detected"


def test_unpack_none():
    assert _unpack_worker_decision(None) == (None,) * 6


def test_events_level_columns(tmp_path):
    from src.storage import EventStorage
    s = EventStorage(str(tmp_path / "t.db"))
    eid = s.add_event("1", "z", "motion", "d", level=0, source="local", dropped=False)
    assert eid > 0
    s.update_event_level(eid, 4, event_type="motion", disposition="alert")
    rows = s.list_events(level=4)
    assert len(rows) == 1 and rows[0]["source"] == "local" and rows[0]["dropped"] == 0
    assert s.list_events(level=9) == []


def test_local_queue_delivers():
    from src.events import LocalEventQueue, CameraEvent
    q = LocalEventQueue()
    received = []
    q.subscribe(lambda e: received.append(e))
    q.start()
    ev = CameraEvent(camera_id="1", source="local")
    q.enqueue(ev)
    import time; time.sleep(0.2)
    assert received and received[0].camera_id == "1"


def test_engine_decides_and_alerts(monkeypatch):
    from src.alert_rules import AlertRuleEngine
    from src.events import CameraEvent
    calls = []
    alerts = type("A", (), {"send": lambda *a, **k: calls.append(1)})()
    stor = type("S", (), {
        "add_event": lambda *a, **k: 7,
        "update_event_level": lambda *a, **k: True,
    })()
    cm = type("CM", (), {"request_clip": lambda *a, **k: None})()
    eng = AlertRuleEngine(stor, alerts, cm)
    ev = CameraEvent(camera_id="1", source="local", detections=[{"label": "person", "bbox": {}}])
    ev.timestamp = 1.0
    eng.handle(ev)          # 1º: alerta
    ev2 = CameraEvent(camera_id="1", source="local", detections=[{"label": "person", "bbox": {}}])
    ev2.timestamp = 2.0     # dentro do cooldown
    eng.handle(ev2)         # não deve alertar de novo (cooldown)
    assert len(calls) == 1


def test_worker_emits_not_alerts():
    import src.events as ev_mod
    sent = []
    class FakeBus:
        def enqueue(self, e): sent.append(e)
        def subscribe(self, h): pass
        def start(self): pass
    # usa CameraWorker com stubs; verifica que enfileira e NÃO chama alerts.send
    from src.main import CameraWorker
    cam = {"id": "1", "name": "cam1", "alert_classes": ["person"]}
    alerts_spy = {"called": False}
    class FakeAlerts:
        def send(self, *a, **k): alerts_spy["called"] = True
    w = CameraWorker.__new__(CameraWorker)
    w.camera = cam
    w.event_bus = FakeBus()
    w.alerts = FakeAlerts()
    ce = w.build_candidate_event([{"label": "person"}], None, None, "zone", "public",
                                 None, 1.0, False, None, None, None, no_motion=False)
    assert ce.source == "local" and ce.level == 1 and ce.dropped is False
    assert alerts_spy["called"] is False


def test_request_clip(monkeypatch):
    import threading
    from src.main import CameraManager
    called = []
    class W:
        def start_clip(self, eid): called.append(eid)
        def status(self): return {}
    cm = CameraManager.__new__(CameraManager)
    cm.lock = threading.Lock()
    cm.workers = {"1": W()}
    cm.request_clip("1", 99)
    assert called == [99]


def test_ingest_enqueues(client, monkeypatch):
    q = []
    monkeypatch.setattr(client.application, "event_bus", type("B", (), {"enqueue": q.append})())
    r = client.post("/api/ingest", json={"camera_id": "5", "detections": [{"label": "person"}]})
    assert r.status_code == 202 and q and q[0].source == "edge" and q[0].level == 1
    # sensor heterogêneo (alagamento)
    r3 = client.post("/api/ingest", json={"camera_id": "flood-1", "device_type": "sensor", "event_type": "flood", "details": "nivel alto"})
    assert r3.status_code == 202 and q[-1].device_type == "sensor" and q[-1].event_type == "flood"
    r2 = client.post("/api/ingest", json={})
    assert r2.status_code == 400



def test_api_config_endpoint(client):
    """Testa se /api/config retorna parâmetros esperados sem erro 500."""
    resp = client.get("/api/config")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "motion" in data
    assert "alerts" in data
    assert "detector" in data
    assert "identity" in data
    assert "thumbnails" in data
    assert "clips" in data
    assert "tracking" in data
    assert "behavior" in data
    assert "privacy_mode" in data
    # Verifica alguns valores específicos
    from src.config import MOTION_MIN_AREA
    assert data["motion"]["min_area_px"] == MOTION_MIN_AREA
    assert data["alerts"]["no_motion_alert_seconds"] == 60
