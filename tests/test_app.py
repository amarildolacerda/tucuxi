import json
import pytest
from src.app import create_app
from src.camera import CameraStream


@pytest.fixture
def app(tmp_path):
    db_path = tmp_path / "test.db"
    app = create_app(db_path=db_path)
    app.config.update({"TESTING": True})
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def test_health_route(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json == {"status": "ok"}


def test_docs_route(client):
    response = client.get("/docs")
    assert response.status_code == 200
    assert b"Secur API Documentation" in response.data
    assert b"/status" in response.data
    assert b"/workers" in response.data


def test_status_route(client):
    response = client.get("/status")
    assert response.status_code == 200
    body = response.json
    assert body["status"] == "ok"
    assert "camera_count" in body
    assert "recent_events" in body
    assert "cameras" in body
    assert isinstance(body["cameras"], list)


def test_settings_section_renders_sensitivity_config(client):
    response = client.get("/section/settings")
    assert response.status_code == 200
    assert b"sensitivity-config" in response.data


def test_settings_js_no_slider_strings(client):
    # Busca o JS servido na rota de static
    resp = client.get("/static/sections/settings.js")
    assert resp.status_code == 200
    js = resp.get_data(as_text=True)
    # Nada de sliders customizados
    assert "SLIDER_DEFS" not in js
    assert "range" not in js
    assert "saveCustom" not in js


def test_settings_js_has_default_profile(client):
    resp = client.get("/static/sections/settings.js")
    js = resp.get_data(as_text=True)
    assert "default" in js
    assert "'Padrão'" in js or '"Padrão"' in js


def test_workers_route(client):
    response = client.get("/workers")
    assert response.status_code == 200
    body = response.json
    assert body["active_workers"] == 0
    assert body["workers"] == []


def test_cameras_route_initial_empty(client):
    response = client.get("/cameras")
    assert response.status_code == 200
    assert isinstance(response.json, list)


def test_add_camera_rejects_invalid_source(client, monkeypatch):
    def fake_validate_source(source):
        return False

    monkeypatch.setattr(CameraStream, "validate_source", staticmethod(fake_validate_source))
    response = client.post(
        "/cameras",
        data=json.dumps({"name": "Test Camera", "source": "invalid-source", "zone": "test"}),
        content_type="application/json",
    )
    assert response.status_code == 400
    assert response.json["error"] == "source inválido ou stream inacessível"


def test_add_camera_accepts_valid_source(client, monkeypatch):
    def fake_validate_source(source):
        return True

    monkeypatch.setattr(CameraStream, "validate_source", staticmethod(fake_validate_source))
    response = client.post(
        "/cameras",
        data=json.dumps({"name": "Test Camera", "source": "valid-source", "zone": "test"}),
        content_type="application/json",
    )
    assert response.status_code == 201
    assert response.json["name"] == "Test Camera"
    assert response.json["source"] == "valid-source"
    assert response.json["zone"] == "test"


def test_camera_thumbnails_route(client, monkeypatch):
    from src.camera import CameraStream
    monkeypatch.setattr(CameraStream, "validate_source", staticmethod(lambda s: True))
    resp = client.post("/cameras", json={"name": "Cam", "source": "source://x", "zone": "entrada"})
    assert resp.status_code == 201
    cam_id = resp.json["id"]

    # no thumbnails yet
    resp = client.get(f"/camera/{cam_id}/thumbnails")
    assert resp.status_code == 200
    assert resp.json == []


def test_camera_thumbnails_route_404(client):
    resp = client.get("/camera/999/thumbnails")
    assert resp.status_code == 404


def test_thumbnail_image_route_404(client):
    resp = client.get("/thumbnails/999/image")
    assert resp.status_code == 404


def test_notifications_get(client):
    resp = client.get("/api/notifications")
    assert resp.status_code == 200
    body = resp.json
    assert [c["key"] for c in body["channels"]] == ["telegram", "automation"]
    assert "motion_detected" in [e["key"] for e in body["events"]]
    assert "routing" in body


def test_notifications_put(client):
    resp = client.put("/api/notifications/routing", json={"channel": "telegram", "event_type": "no_motion", "enabled": True})
    assert resp.status_code == 200
    body = client.get("/api/notifications").json
    assert body["routing"]["telegram"]["no_motion"] is True


def test_notifications_put_invalid(client):
    resp = client.put("/api/notifications/routing", json={"channel": "nope", "event_type": "no_motion", "enabled": True})
    assert resp.status_code == 400
    resp = client.put("/api/notifications/routing", json={"channel": "telegram", "event_type": "nope", "enabled": True})
    assert resp.status_code == 400


def test_put_routing_refreshes_in_memory_alert_service(tmp_path):
    """Regressão: desabilitar um evento no dashboard (PUT /api/notifications/routing)
    deve valer imediatamente no envio real. O AlertService decide o envio usando o
    routing em memória (snapshot do boot, main.py) — o PUT precisa recarregá-lo,
    senão as mensagens continuam chegando até o restart do servidor."""
    from src.alerts import AlertService

    sent = []
    handler = lambda payload: sent.append(payload)
    handler.channel = "telegram"
    service = AlertService()
    service.register_handler(handler)
    service.routing = {"telegram": {"motion_detected": True}}

    db_path = tmp_path / "routing.db"
    app = create_app(db_path=db_path, alerts=service)
    app.config.update({"TESTING": True})
    client = app.test_client()

    # Desabilita motion_detected no Telegram (o que o toggle do dashboard faz).
    resp = client.put("/api/notifications/routing", json={
        "channel": "telegram", "event_type": "motion_detected", "enabled": False,
    })
    assert resp.status_code == 200

    # Sem restart, o serviço em memória já reflete o novo valor.
    assert service.routing["telegram"]["motion_detected"] is False

    # Envio real NÃO passa pelo handler telegram para o evento desabilitado.
    service.send("1", "entrada", "motion_detected", "teste")
    assert sent == []

    # Reabilita → volta a enviar imediatamente (sem restart).
    resp = client.put("/api/notifications/routing", json={
        "channel": "telegram", "event_type": "motion_detected", "enabled": True,
    })
    assert resp.status_code == 200
    assert service.routing["telegram"]["motion_detected"] is True
    service.send("1", "entrada", "motion_detected", "teste")
    assert [p["event_type"] for p in sent] == ["motion_detected"]


def test_add_camera_with_alert_classes(client, monkeypatch):
    from src.camera import CameraStream
    monkeypatch.setattr(CameraStream, "validate_source", staticmethod(lambda s: True))
    response = client.post(
        "/cameras",
        data=json.dumps({
            "name": "Cam", "source": "valid-source", "zone": "entrada",
            "alert_classes": ["person", "car"],
            "exclusion_zones": [[{"x": 0, "y": 0}, {"x": 100, "y": 0}, {"x": 100, "y": 100}]],
        }),
        content_type="application/json",
    )
    assert response.status_code == 201
    assert response.json["alert_classes"] == ["person", "car"]
    assert response.json["exclusion_zones"] == [[{"x": 0, "y": 0}, {"x": 100, "y": 0}, {"x": 100, "y": 100}]]


def test_add_camera_rejects_invalid_alert_classes(client, monkeypatch):
    from src.camera import CameraStream
    monkeypatch.setattr(CameraStream, "validate_source", staticmethod(lambda s: True))
    response = client.post(
        "/cameras",
        data=json.dumps({"name": "Cam", "source": "valid-source", "alert_classes": "person"}),
        content_type="application/json",
    )
    assert response.status_code == 400


def test_api_classes(client):
    response = client.get("/api/classes")
    assert response.status_code == 200
    assert "person" in response.json["classes"]


def test_camera_clips_route(client, monkeypatch):
    from src.camera import CameraStream
    monkeypatch.setattr(CameraStream, "validate_source", staticmethod(lambda s: True))
    resp = client.post("/cameras", json={"name": "Cam", "source": "source://x", "zone": "entrada"})
    cam_id = resp.json["id"]

    resp = client.get(f"/camera/{cam_id}/clips")
    assert resp.status_code == 200
    assert resp.json == []


def test_camera_clips_route_404(client):
    resp = client.get("/camera/999/clips")
    assert resp.status_code == 404


def test_clip_metadata_route_404(client):
    resp = client.get("/clips/999")
    assert resp.status_code == 404


def test_clip_video_route_404(client):
    resp = client.get("/clips/999/video")
    assert resp.status_code == 404


@pytest.fixture
def clip_env(tmp_path, monkeypatch):
    """Client + storage pair sharing ONE EventStorage instance.

    EventStorage deletes the DB file on init when running under pytest, so a
    second instance would orphan the app's sqlite connection (writes would go
    to a fresh file the app never sees). To seed clips the app must serve, the
    app is built around the same storage instance the test mutates.
    """
    from src.app import create_app
    from src.storage import EventStorage

    db_path = tmp_path / "test.db"
    storage = EventStorage(db_path)

    def _shared_event_storage(db_path=None):
        return storage

    monkeypatch.setattr("src.app.EventStorage", _shared_event_storage)
    app = create_app(db_path=db_path)
    app.config.update({"TESTING": True})
    return app.test_client(), storage


def test_clip_video_route_200(clip_env, tmp_path, monkeypatch):
    from src.camera import CameraStream
    monkeypatch.setattr(CameraStream, "validate_source", staticmethod(lambda s: True))
    client, storage = clip_env
    resp = client.post("/cameras", json={"name": "Cam", "source": "source://x", "zone": "entrada"})
    assert resp.status_code == 201
    cam_id = resp.json["id"]

    clip_file = tmp_path / "clip.mp4"
    clip_file.write_bytes(b"mp4data")
    clip_id = storage.add_event_clip(cam_id, None, str(clip_file), 5.0)

    resp = client.get(f"/clips/{clip_id}/video")
    assert resp.status_code == 200
    assert resp.mimetype == "video/mp4"
    assert resp.data == b"mp4data"


def test_delete_camera_removes_clips_and_thumbnails(clip_env, tmp_path, monkeypatch):
    from src.camera import CameraStream
    monkeypatch.setattr(CameraStream, "validate_source", staticmethod(lambda s: True))
    client, storage = clip_env
    resp = client.post("/cameras", json={"name": "Cam", "source": "source://x", "zone": "entrada"})
    assert resp.status_code == 201
    cam_id = resp.json["id"]

    thumb = tmp_path / "thumb.jpg"
    thumb.write_bytes(b"jpegdata")
    storage.add_camera_thumbnail(cam_id, str(thumb), "motion_detected")
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"mp4data")
    storage.add_event_clip(cam_id, None, str(clip), 5.0)

    resp = client.delete(f"/cameras/{cam_id}")
    assert resp.status_code == 200
    assert resp.json == {"status": "removido"}
    assert storage.list_camera_thumbnails(cam_id) == []
    assert storage.list_event_clips(cam_id) == []
    assert not thumb.exists()
    assert not clip.exists()


def test_add_camera_with_mask_polygons(client, monkeypatch):
    from src.camera import CameraStream
    monkeypatch.setattr(CameraStream, "validate_source", staticmethod(lambda s: True))
    polygons = [[{"x": 0, "y": 0}, {"x": 100, "y": 0}, {"x": 100, "y": 100}]]
    response = client.post(
        "/cameras",
        data=json.dumps({"name": "Cam", "source": "valid-source", "zone": "entrada", "mask_polygons": polygons}),
        content_type="application/json",
    )
    assert response.status_code == 201
    assert response.json["mask_polygons"] == polygons


def test_add_camera_rejects_invalid_mask_polygons(client, monkeypatch):
    from src.camera import CameraStream
    monkeypatch.setattr(CameraStream, "validate_source", staticmethod(lambda s: True))
    response = client.post(
        "/cameras",
        data=json.dumps({"name": "Cam", "source": "valid-source", "mask_polygons": "not-a-list"}),
        content_type="application/json",
    )
    assert response.status_code == 400


def test_update_camera_mask_polygons(client, monkeypatch):
    from src.camera import CameraStream
    monkeypatch.setattr(CameraStream, "validate_source", staticmethod(lambda s: True))
    resp = client.post("/cameras", json={"name": "Cam", "source": "valid-source", "zone": "entrada"})
    cam_id = resp.json["id"]

    polygons = [[{"x": 0, "y": 0}, {"x": 50, "y": 0}, {"x": 50, "y": 50}]]
    resp = client.put(
        f"/cameras/{cam_id}",
        data=json.dumps({"name": "Cam", "source": "valid-source", "zone": "entrada", "mask_polygons": polygons}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json["mask_polygons"] == polygons
    # GET detail: mask_polygons persiste no round-trip
    resp = client.get("/cameras")
    assert resp.json[0]["mask_polygons"] == polygons


def test_add_camera_rejects_malformed_mask_polygons(client, monkeypatch):
    from src.camera import CameraStream
    monkeypatch.setattr(CameraStream, "validate_source", staticmethod(lambda s: True))
    bad_cases = [
        [[{"x": 0}]],                       # falta y
        [[["a", "b"]]],                     # pontos não-dict
        [[{"x": "a", "y": 0}]],             # x não numérico
        [[{"x": 0, "y": 0}, {"x": "b", "y": 5}]],  # y não numérico
        [[{"x": True, "y": 0}]],            # bool não é numérico
        [[]],                               # polígono vazio
    ]
    for bad in bad_cases:
        response = client.post(
            "/cameras",
            data=json.dumps({"name": "Cam", "source": "valid-source", "mask_polygons": bad}),
            content_type="application/json",
        )
        assert response.status_code == 400, f"deveria rejeitar mask_polygons={bad}"


def test_snapshot_route_applies_mask_polygons(client, monkeypatch):
    import cv2
    import numpy as np
    from src.camera import CameraStream
    monkeypatch.setattr(CameraStream, "validate_source", staticmethod(lambda s: True))

    class FakeCapture:
        def __init__(self, source):
            pass

        def isOpened(self):
            return True

        def set(self, *args, **kwargs):
            return True

        def read(self):
            frame = np.zeros((100, 100, 3), dtype=np.uint8)
            frame[45:55, 45:55] = 255  # quadrado branco no centro
            return True, frame

        def release(self):
            pass

    monkeypatch.setattr("src.app.cv2.VideoCapture", FakeCapture)

    resp = client.post(
        "/cameras",
        data=json.dumps({
            "name": "Cam", "source": "source://x", "zone": "entrada",
            "mask_polygons": [[{"x": 40, "y": 40}, {"x": 60, "y": 40}, {"x": 60, "y": 60}, {"x": 40, "y": 60}]],
        }),
        content_type="application/json",
    )
    cam_id = resp.json["id"]

    resp = client.get(f"/camera/{cam_id}/snapshot")
    assert resp.status_code == 200
    arr = cv2.imdecode(np.frombuffer(resp.data, np.uint8), cv2.IMREAD_COLOR)
    # dentro do polígono o blur espalhou o branco com o fundo preto
    assert int(arr[50, 50, 0]) < 200
    # fora do polígono permanece preto (JPEG pode variar ~poucos níveis)
    assert int(arr[10, 10, 0]) < 10


def test_snapshot_route_raw_skips_mask(client, monkeypatch):
    import cv2
    import numpy as np
    from src.camera import CameraStream
    monkeypatch.setattr(CameraStream, "validate_source", staticmethod(lambda s: True))

    class FakeCapture:
        def __init__(self, source):
            pass

        def isOpened(self):
            return True

        def set(self, *args, **kwargs):
            return True

        def read(self):
            frame = np.zeros((100, 100, 3), dtype=np.uint8)
            frame[45:55, 45:55] = 255  # quadrado branco no centro
            return True, frame

        def release(self):
            pass

    monkeypatch.setattr("src.app.cv2.VideoCapture", FakeCapture)

    resp = client.post(
        "/cameras",
        data=json.dumps({
            "name": "Cam", "source": "source://x", "zone": "entrada",
            "mask_polygons": [[{"x": 40, "y": 40}, {"x": 60, "y": 40}, {"x": 60, "y": 60}, {"x": 40, "y": 60}]],
        }),
        content_type="application/json",
    )
    cam_id = resp.json["id"]

    resp = client.get(f"/camera/{cam_id}/snapshot?raw=1")
    assert resp.status_code == 200
    arr = cv2.imdecode(np.frombuffer(resp.data, np.uint8), cv2.IMREAD_COLOR)
    # sem máscara: o quadrado branco permanece intacto
    assert int(arr[50, 50, 0]) > 200


def test_snapshot_route_without_mask_keeps_frame(client, monkeypatch):
    import cv2
    import numpy as np
    from src.camera import CameraStream
    monkeypatch.setattr(CameraStream, "validate_source", staticmethod(lambda s: True))

    class FakeCapture:
        def __init__(self, source):
            pass

        def isOpened(self):
            return True

        def set(self, *args, **kwargs):
            return True

        def read(self):
            frame = np.zeros((100, 100, 3), dtype=np.uint8)
            frame[45:55, 45:55] = 255
            return True, frame

        def release(self):
            pass

    monkeypatch.setattr("src.app.cv2.VideoCapture", FakeCapture)

    resp = client.post("/cameras", json={"name": "Cam", "source": "source://x", "zone": "entrada"})
    cam_id = resp.json["id"]

    resp = client.get(f"/camera/{cam_id}/snapshot")
    assert resp.status_code == 200
    arr = cv2.imdecode(np.frombuffer(resp.data, np.uint8), cv2.IMREAD_COLOR)
    assert int(arr[50, 50, 0]) > 200  # branco puro preservado


def test_add_zone_with_retention_policy(client):
    resp = client.post(
        "/zones",
        data=json.dumps({"name": "Entrada", "classification": "pública",
                         "retention_policy": {"thumbnails": 5, "clips": 3, "days": 7}}),
        content_type="application/json",
    )
    assert resp.status_code == 201
    assert resp.json["retention_policy"] == {"thumbnails": 5, "clips": 3, "days": 7}


def test_add_zone_rejects_invalid_retention_policy(client):
    resp = client.post(
        "/zones",
        data=json.dumps({"name": "Entrada", "classification": "pública", "retention_policy": "5"}),
        content_type="application/json",
    )
    assert resp.status_code == 400
    resp = client.post(
        "/zones",
        data=json.dumps({"name": "Entrada", "classification": "pública", "retention_policy": {"days": -1}}),
        content_type="application/json",
    )
    assert resp.status_code == 400


def test_update_zone_retention_policy(client):
    resp = client.post("/zones", json={"name": "Entrada", "classification": "pública"})
    zone_id = resp.json["id"]
    resp = client.put(
        f"/zones/{zone_id}",
        data=json.dumps({"name": "Entrada", "classification": "pública",
                         "retention_policy": {"thumbnails": 10}}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json["retention_policy"] == {"thumbnails": 10}


def test_settings_get_default(client):
    resp = client.get("/api/settings")
    assert resp.status_code == 200
    assert resp.json == {"privacy_mode": False}


def test_settings_put_and_get(client):
    resp = client.put("/api/settings", json={"privacy_mode": True})
    assert resp.status_code == 200
    assert resp.json == {"privacy_mode": True}
    assert client.get("/api/settings").json["privacy_mode"] is True


def test_settings_put_invalid(client):
    resp = client.put("/api/settings", json={"privacy_mode": "yes"})
    assert resp.status_code == 400


def test_settings_put_turns_off_again(client):
    client.put("/api/settings", json={"privacy_mode": True})
    resp = client.put("/api/settings", json={"privacy_mode": False})
    assert resp.status_code == 200
    assert client.get("/api/settings").json["privacy_mode"] is False


def test_add_zone_with_direction_line(client):
    resp = client.post("/zones", json={
        "name": "Portão", "classification": "segurança",
        "direction_line": {"axis": "vertical", "position": 0.5},
    })
    assert resp.status_code == 201
    assert resp.json["direction_line"] == {"axis": "vertical", "position": 0.5}


def test_add_zone_rejects_invalid_direction_line(client):
    resp = client.post("/zones", json={
        "name": "Portão", "classification": "segurança",
        "direction_line": {"axis": "diagonal", "position": 0.5},
    })
    assert resp.status_code == 400

    resp = client.post("/zones", json={
        "name": "Portão", "classification": "segurança",
        "direction_line": {"axis": "vertical", "position": 2},
    })
    assert resp.status_code == 400

    resp = client.post("/zones", json={
        "name": "Portão", "classification": "segurança",
        "direction_line": "vertical",
    })
    assert resp.status_code == 400


def test_update_zone_direction_line(client):
    resp = client.post("/zones", json={"name": "Entrada", "classification": "pública"})
    zone_id = resp.json["id"]
    resp = client.put(f"/zones/{zone_id}", json={
        "name": "Entrada", "classification": "pública",
        "direction_line": {"axis": "horizontal", "position": 0.3},
    })
    assert resp.status_code == 200
    assert resp.json["direction_line"] == {"axis": "horizontal", "position": 0.3}


def test_prune_saves_policy_and_config_reflects_it(client):
    """POST /api/events/prune com política salva a política; /api/config passa
    a refleti-la (a limpeza automática usa a política efetiva)."""
    resp = client.post("/api/events/prune", json={
        "type_days": {"motion_detected": 3, "capture": 15},
        "default_days": 10,
        "max_age_days": 60,
    })
    assert resp.status_code == 200
    assert resp.json["saved"] is True
    assert "deleted" in resp.json

    cfg = client.get("/api/config").json
    pruning = cfg["event_pruning"]
    assert pruning["type_days"]["motion_detected"] == 3
    assert pruning["type_days"]["capture"] == 15
    assert pruning["default_days"] == 10
    assert pruning["max_age_days"] == 60


def test_prune_policy_partial_update_keeps_previous_values(client):
    """Envio parcial (só type_days) preserva default/max_age salvos antes."""
    client.post("/api/events/prune", json={
        "type_days": {"motion_detected": 3},
        "default_days": 10,
        "max_age_days": 60,
    })
    resp = client.post("/api/events/prune", json={
        "type_days": {"capture": 20},
    })
    assert resp.status_code == 200

    pruning = client.get("/api/config").json["event_pruning"]
    assert pruning["type_days"]["capture"] == 20
    assert pruning["type_days"]["motion_detected"] == 3  # preservado
    assert pruning["default_days"] == 10                 # preservado
    assert pruning["max_age_days"] == 60                 # preservado


def test_prune_rejects_invalid_policy(client):
    resp = client.post("/api/events/prune", json={"type_days": {"motion_detected": -1}})
    assert resp.status_code == 400
    resp = client.post("/api/events/prune", json={"default_days": "sete"})
    assert resp.status_code == 400
    resp = client.post("/api/events/prune", json={"max_age_days": True})
    assert resp.status_code == 400


def test_events_retained_filter_beyond_limit(clip_env):
    """Eventos retidos não podem ficar fora do corte de 100: /events?retained=1
    retorna retidos antigos que o /events normal não mostra."""
    client, storage = clip_env
    ids = [storage.add_event("1", "z", "motion_detected", f"e{i}") for i in range(105)]
    oldest = ids[0]
    resp = client.put(f"/api/events/{oldest}/retain", json={"retain": True})
    assert resp.status_code == 200

    # Sem filtro: só os 100 mais recentes — o retido antigo fica de fora.
    all_events = client.get("/events").json
    assert len(all_events) == 100
    assert oldest not in [e["id"] for e in all_events]

    # Com retained=1: o retido antigo aparece, e só retidos são retornados.
    retained_events = client.get("/events?retained=1").json
    assert any(e["id"] == oldest for e in retained_events)
    assert all(e["retained"] == 1 for e in retained_events)

    # retained=0: só não-retidos.
    non_retained = client.get("/events?retained=0").json
    assert all(e["retained"] == 0 for e in non_retained)
