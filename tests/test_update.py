# tests/test_update.py
import pytest
from unittest.mock import patch, MagicMock
from src.update import UpdateManager


class TestUpdateManager:
    def setup_method(self):
        self.um = UpdateManager()

    def test_initial_state(self):
        status = self.um.get_status()
        assert status["current_version"] == "1.0.0"
        assert status["update_available"] is False
        assert status["latest_version"] is None
        assert status["updating"] is False

    def test_detect_deploy_mode_docker(self, tmp_path):
        (tmp_path / "docker-compose.yml").write_text("services:")
        um = UpdateManager(project_dir=str(tmp_path))
        assert um.detect_deploy_mode() == "docker"

    def test_detect_deploy_mode_compose(self, tmp_path):
        (tmp_path / "compose.yaml").write_text("services:")
        um = UpdateManager(project_dir=str(tmp_path))
        assert um.detect_deploy_mode() == "docker"

    def test_detect_deploy_mode_bare_metal(self, tmp_path):
        um = UpdateManager(project_dir=str(tmp_path))
        assert um.detect_deploy_mode() == "bare_metal"

    def test_parse_version(self):
        assert self.um.parse_version("1.0.0") == (1, 0, 0)
        assert self.um.parse_version("0.12.3") == (0, 12, 3)

    def test_parse_version_tag(self):
        assert self.um.parse_version("v1.2.3") == (1, 2, 3)

    @patch("src.update.requests.get")
    def test_check_for_update_available(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {"ref": "refs/tags/v1.1.0"},
            {"ref": "refs/tags/v1.0.0"},
        ]
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        self.um.check_for_update()
        status = self.um.get_status()
        assert status["update_available"] is True
        assert status["latest_version"] == "1.1.0"

    @patch("src.update.requests.get")
    def test_check_for_update_none_available(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {"ref": "refs/tags/v1.0.0"},
        ]
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        self.um.check_for_update()
        status = self.um.get_status()
        assert status["update_available"] is False
        assert status["latest_version"] == "1.0.0"

    @patch("src.update.requests.get")
    def test_check_for_update_api_error(self, mock_get):
        mock_get.side_effect = Exception("Network error")
        self.um.check_for_update()
        status = self.um.get_status()
        assert status["update_available"] is False
        assert status["last_error"] == "Network error"


class TestUpdateEndpoints:
    def setup_method(self):
        import tempfile
        from src.app import create_app
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        self.app = create_app(db_path=self.db_path)
        self.app.config["TESTING"] = True
        # Create admin user (but don't login — each test decides)
        self.client = self.app.test_client()
        self.client.post("/api/setup", json={"username": "admin", "password": "secret123"})

    def teardown_method(self):
        import os
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def _login(self):
        """Login and return auth headers."""
        resp = self.client.post("/api/auth/login", json={"username": "admin", "password": "secret123"})
        import re
        set_cookie = resp.headers.get("Set-Cookie", "")
        m = re.search(r"session_token=([^;]+)", set_cookie)
        token = m.group(1) if m else None
        return {"Cookie": f"session_token={token}"} if token else {}

    def test_update_check_requires_auth(self):
        # Fresh app + client with no users at all — require_permission skips auth when no users exist,
        # so we need a client that HAS users but does NOT send a session cookie.
        import tempfile
        from src.app import create_app
        db_fd, db_path = tempfile.mkstemp(suffix=".db")
        try:
            app = create_app(db_path=db_path)
            app.config["TESTING"] = True
            fresh_client = app.test_client()
            # Create a user so has_users() returns True, but don't login
            fresh_client.post("/api/setup", json={"username": "admin", "password": "secret123"})
            # New client without the cookie from setup
            fresh_client2 = app.test_client()
            resp = fresh_client2.get("/api/system/update-check")
            assert resp.status_code in (401, 403)
        finally:
            import os
            os.close(db_fd)
            os.unlink(db_path)

    def test_update_check_returns_version(self):
        resp = self.client.get("/api/system/update-check", headers=self._login())
        assert resp.status_code == 200
        data = resp.get_json()
        assert "current_version" in data
        assert "update_available" in data

    def test_update_post_requires_tag(self):
        resp = self.client.post("/api/system/update", json={}, headers=self._login())
        assert resp.status_code == 400
