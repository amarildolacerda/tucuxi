import io
import json
import zipfile

from src.app import create_app
from src.storage import EventStorage


def _make_app(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    storage = EventStorage(db_path)

    def _shared(db_path=None):
        return storage

    monkeypatch.setattr("src.app.EventStorage", _shared)
    app = create_app(db_path=db_path)
    app.config.update({"TESTING": True})
    return app.test_client(), storage


def _auth_headers(client):
    client.post("/api/setup", json={"username": "admin", "password": "secret123"})
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "secret123"})
    set_cookie = resp.headers.get("Set-Cookie", "")
    import re
    m = re.search(r"session_token=([^;]+)", set_cookie)
    assert m, f"No session_token in Set-Cookie: {set_cookie}"
    return {"Cookie": f"session_token={m.group(1)}"}


def test_export_returns_zip_with_events_thumb_and_clip(tmp_path, monkeypatch):
    from src.camera import CameraStream
    monkeypatch.setattr(CameraStream, "validate_source", staticmethod(lambda s: True))
    client, storage = _make_app(tmp_path, monkeypatch)

    resp = client.post("/cameras", json={"name": "Cam", "source": "source://x", "zone": "entrada"})
    assert resp.status_code == 201
    cam_id = resp.json["id"]

    thumb = tmp_path / "thumb.jpg"
    thumb.write_bytes(b"jpegdata")
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"mp4data")

    ev_id = storage.add_event(cam_id, "entrada", "intruder_detected", '{"score":0.9}')
    storage.update_event_clip_path(ev_id, str(clip))
    storage.add_camera_thumbnail(cam_id, str(thumb), "intruder_detected", event_id=str(ev_id))

    headers = _auth_headers(client)
    resp = client.get("/export", headers=headers)
    assert resp.status_code == 200
    assert resp.mimetype == "application/zip"

    zf = zipfile.ZipFile(io.BytesIO(resp.data))
    names = zf.namelist()
    assert "events.json" in names
    assert any(n.startswith("thumbnails/") for n in names)
    assert any(n.startswith("clips/") for n in names)

    events = json.loads(zf.read("events.json"))
    assert len(events) == 1
    assert events[0]["event_type"] == "intruder_detected"
    assert events[0]["clip_path"] == str(clip)


def test_export_requires_auth_when_users_exist(tmp_path, monkeypatch):
    from src.camera import CameraStream
    monkeypatch.setattr(CameraStream, "validate_source", staticmethod(lambda s: True))
    client, storage = _make_app(tmp_path, monkeypatch)
    # create a user so auth is enforced
    client.post("/api/setup", json={"username": "admin", "password": "secret123"})
    # a brand-new client with no session cookie must be redirected to /login
    fresh = client.application.test_client()
    resp = fresh.get("/export")
    assert resp.status_code == 302


def test_export_filters_by_camera(tmp_path, monkeypatch):
    from src.camera import CameraStream
    monkeypatch.setattr(CameraStream, "validate_source", staticmethod(lambda s: True))
    client, storage = _make_app(tmp_path, monkeypatch)

    r1 = client.post("/cameras", json={"name": "Cam1", "source": "source://a", "zone": "z1"})
    r2 = client.post("/cameras", json={"name": "Cam2", "source": "source://b", "zone": "z2"})
    cam1 = r1.json["id"]
    cam2 = r2.json["id"]

    storage.add_event(cam1, "z1", "motion_detected", "{}")
    storage.add_event(cam2, "z2", "motion_detected", "{}")

    headers = _auth_headers(client)
    resp = client.get(f"/export?camera_id={cam1}", headers=headers)
    assert resp.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(resp.data))
    events = json.loads(zf.read("events.json"))
    assert len(events) == 1
    assert events[0]["camera_id"] == str(cam1)
