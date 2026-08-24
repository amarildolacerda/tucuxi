import json
import pytest
from pathlib import Path
from src.app import create_app
from src.storage import EventStorage
from src.auth import (
    hash_password, verify_password, generate_session_token,
    create_session, validate_session, has_permission,
    PermissionCache, LoginRateLimiter,
    PERMISSIONS, DEFAULT_ROLE_PERMISSIONS, CAN_CREATE_ROLES,
)


# ── Password hashing ────────────────────────────────────────────────────

class TestPasswordHashing:
    def test_hash_and_verify(self):
        h = hash_password("secret123")
        assert h != "secret123"
        assert verify_password("secret123", h)

    def test_wrong_password_fails(self):
        h = hash_password("secret123")
        assert not verify_password("wrong", h)

    def test_different_hashes(self):
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2  # salted


# ── Session tokens ──────────────────────────────────────────────────────

class TestSessions:
    def test_generate_token_is_hex(self):
        token = generate_session_token()
        assert len(token) == 64
        assert all(c in "0123456789abcdef" for c in token)

    def test_create_and_validate(self, tmp_path):
        storage = EventStorage(tmp_path / "test.db")
        user_id = storage.add_user("test", hash_password("pw"), "admin")
        token = create_session(storage, user_id, "127.0.0.1")
        user = validate_session(storage, token)
        assert user is not None
        assert user["username"] == "test"
        assert user["role"] == "admin"

    def test_invalid_token_returns_none(self, tmp_path):
        storage = EventStorage(tmp_path / "test.db")
        assert validate_session(storage, "nonexistent") is None

    def test_empty_token_returns_none(self, tmp_path):
        storage = EventStorage(tmp_path / "test.db")
        assert validate_session(storage, "") is None

    def test_deleted_session_returns_none(self, tmp_path):
        storage = EventStorage(tmp_path / "test.db")
        user_id = storage.add_user("test", hash_password("pw"), "admin")
        token = create_session(storage, user_id, "127.0.0.1")
        storage.delete_session(token)
        assert validate_session(storage, token) is None

    def test_inactive_user_returns_none(self, tmp_path):
        storage = EventStorage(tmp_path / "test.db")
        user_id = storage.add_user("test", hash_password("pw"), "admin")
        token = create_session(storage, user_id, "127.0.0.1")
        storage.update_user(user_id, active=0)
        assert validate_session(storage, token) is None


# ── Permission system ───────────────────────────────────────────────────

class TestPermissions:
    def test_permission_cache(self, tmp_path):
        storage = EventStorage(tmp_path / "test.db")
        storage.seed_default_permissions(DEFAULT_ROLE_PERMISSIONS)
        cache = PermissionCache(ttl_seconds=10)
        perms = cache.get(storage, "admin")
        assert perms.get("manage_cameras") is True

    def test_has_permission_admin(self, tmp_path):
        storage = EventStorage(tmp_path / "test.db")
        storage.seed_default_permissions(DEFAULT_ROLE_PERMISSIONS)
        assert has_permission(storage, "admin", "manage_cameras")
        assert has_permission(storage, "admin", "manage_settings")
        assert has_permission(storage, "admin", "view_live")

    def test_has_permission_viewer(self, tmp_path):
        storage = EventStorage(tmp_path / "test.db")
        storage.seed_default_permissions(DEFAULT_ROLE_PERMISSIONS)
        assert has_permission(storage, "viewer", "view_live")
        assert not has_permission(storage, "viewer", "manage_cameras")
        assert not has_permission(storage, "viewer", "dismiss_event")

    def test_has_permission_vigilante(self, tmp_path):
        storage = EventStorage(tmp_path / "test.db")
        storage.seed_default_permissions(DEFAULT_ROLE_PERMISSIONS)
        assert has_permission(storage, "vigilante", "view_live")
        assert has_permission(storage, "vigilante", "dismiss_event")
        assert has_permission(storage, "vigilante", "arm_disarm")
        assert not has_permission(storage, "vigilante", "manage_cameras")

    def test_has_permission_chefe(self, tmp_path):
        storage = EventStorage(tmp_path / "test.db")
        storage.seed_default_permissions(DEFAULT_ROLE_PERMISSIONS)
        assert has_permission(storage, "chefe_seguranca", "create_users")
        assert not has_permission(storage, "chefe_seguranca", "manage_cameras")

    def test_permission_override(self, tmp_path):
        storage = EventStorage(tmp_path / "test.db")
        storage.seed_default_permissions(DEFAULT_ROLE_PERMISSIONS)
        cache = PermissionCache(ttl_seconds=0)
        # Viewer shouldn't have dismiss_event
        assert not cache.get(storage, "viewer").get("dismiss_event")
        # Enable it
        storage.set_role_permission("viewer", "dismiss_event", True)
        assert cache.get(storage, "viewer").get("dismiss_event") is True

    def test_all_permissions_defined(self):
        assert len(PERMISSIONS) == 21
        for role in ("admin", "chefe_seguranca", "vigilante", "viewer"):
            assert role in DEFAULT_ROLE_PERMISSIONS


# ── Rate limiting ───────────────────────────────────────────────────────

class TestRateLimiter:
    def test_lockout_after_max_attempts(self):
        limiter = LoginRateLimiter(max_attempts=3, window_seconds=60, lockout_seconds=60)
        assert not limiter.is_locked("1.2.3.4")
        limiter.record_failure("1.2.3.4")
        limiter.record_failure("1.2.3.4")
        assert not limiter.is_locked("1.2.3.4")
        limiter.record_failure("1.2.3.4")
        assert limiter.is_locked("1.2.3.4")

    def test_success_clears_attempts(self):
        limiter = LoginRateLimiter(max_attempts=3, window_seconds=60, lockout_seconds=60)
        limiter.record_failure("1.2.3.4")
        limiter.record_failure("1.2.3.4")
        limiter.record_success("1.2.3.4")
        # Should not be locked even after 2 failures
        limiter.record_failure("1.2.3.4")
        assert not limiter.is_locked("1.2.3.4")

    def test_different_ips_independent(self):
        limiter = LoginRateLimiter(max_attempts=2, window_seconds=60, lockout_seconds=60)
        limiter.record_failure("1.1.1.1")
        limiter.record_failure("1.1.1.1")
        assert limiter.is_locked("1.1.1.1")
        assert not limiter.is_locked("2.2.2.2")


# ── Role hierarchy ──────────────────────────────────────────────────────

class TestHierarchy:
    def test_admin_can_create_all(self):
        assert "admin" in CAN_CREATE_ROLES["admin"]
        assert "chefe_seguranca" in CAN_CREATE_ROLES["admin"]
        assert "vigilante" in CAN_CREATE_ROLES["admin"]
        assert "viewer" in CAN_CREATE_ROLES["admin"]

    def test_chefe_can_create_vigilante_and_viewer(self):
        assert "vigilante" in CAN_CREATE_ROLES["chefe_seguranca"]
        assert "viewer" in CAN_CREATE_ROLES["chefe_seguranca"]

    def test_chefe_cannot_create_admin(self):
        assert "admin" not in CAN_CREATE_ROLES["chefe_seguranca"]


# ── API integration ─────────────────────────────────────────────────────

class TestAuthIntegration:
    @pytest.fixture
    def client(self, tmp_path):
        db_path = tmp_path / "test.db"
        app = create_app(db_path=db_path)
        app.config["TESTING"] = True
        return app.test_client()

    def _setup_and_login(self, client):
        """Helper: create admin and login, returning the raw session token."""
        client.post("/api/setup", json={"username": "admin", "password": "secret123"})
        resp = client.post("/api/auth/login", json={"username": "admin", "password": "secret123"})
        set_cookie = resp.headers.get("Set-Cookie", "")
        import re
        m = re.search(r"session_token=([^;]+)", set_cookie)
        assert m, f"No session_token in Set-Cookie: {set_cookie}"
        return m.group(1)

    def _auth_headers(self, token):
        return {"Cookie": f"session_token={token}"}

    def test_first_run_setup(self, client):
        """Without users, POST /api/setup creates admin."""
        resp = client.post("/api/setup", json={"username": "admin", "password": "secret123"})
        assert resp.status_code in (200, 302)  # redirect to /

    def test_login_and_me(self, client):
        token = self._setup_and_login(client)
        resp = client.get("/api/auth/me", headers=self._auth_headers(token))
        assert resp.status_code == 200
        assert resp.json["user"]["username"] == "admin"

    def test_wrong_password_returns_401(self, client):
        client.post("/api/setup", json={"username": "admin", "password": "secret123"})
        resp = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
        assert resp.status_code == 401

    def test_protected_route_requires_auth(self, tmp_path):
        # Fresh app + client with no cookies: setup creates session but new client has no cookie
        app = create_app(db_path=tmp_path / "noauth.db")
        app.config["TESTING"] = True
        c = app.test_client()
        c.post("/api/setup", json={"username": "admin", "password": "secret123"})
        # New client (no cookies carried over)
        c2 = app.test_client()
        resp = c2.post("/cameras", json={"name": "test", "source": "rtsp://test"})
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_admin_can_access_protected_route(self, client):
        token = self._setup_and_login(client)
        resp = client.post("/cameras", json={"name": "test", "source": "rtsp://test"},
                          headers=self._auth_headers(token))
        assert resp.status_code in (200, 201, 400)  # 400 = invalid source, but not 401

    def test_logout_clears_session(self, client):
        token = self._setup_and_login(client)
        resp = client.post("/api/auth/logout", headers=self._auth_headers(token))
        assert resp.status_code == 200
        resp = client.post("/cameras", json={"name": "test", "source": "rtsp://test"},
                          headers=self._auth_headers(token))
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_create_user_via_api(self, client):
        token = self._setup_and_login(client)
        resp = client.post("/api/users", json={
            "username": "vigilante1", "password": "pass123", "role": "vigilante"
        }, headers=self._auth_headers(token))
        assert resp.status_code == 201
        assert resp.json["role"] == "vigilante"

    def test_create_user_duplicate_returns_409(self, client):
        token = self._setup_and_login(client)
        client.post("/api/users", json={"username": "user1", "password": "pass123", "role": "viewer"},
                    headers=self._auth_headers(token))
        resp = client.post("/api/users", json={"username": "user1", "password": "pass123", "role": "viewer"},
                          headers=self._auth_headers(token))
        assert resp.status_code == 409
