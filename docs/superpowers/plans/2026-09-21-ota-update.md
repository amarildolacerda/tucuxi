# OTA Update Mechanism Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement an OTA update mechanism that checks GitHub for newer releases and allows users to apply updates from the dashboard.

**Architecture:** New `src/update.py` module handles version checking via GitHub API and update application via git pull + Docker/bare metal detection. Two Flask endpoints (`/api/system/update-check`, `/api/system/update`). Frontend card in Settings page with 5 UI states. Timer checks on startup + every 24h.

**Tech Stack:** Python, Flask, GitHub REST API (public, no auth), subprocess for git/docker commands, vanilla JS frontend.

## Global Constraints

- Branch tracked: `main` (releases with semver tags `v0.0.0`)
- GitHub repo: `https://github.com/amarildolacerda/tucuxi.git` (public)
- No credentials on Pi — GitHub API without token, git pull via HTTPS public
- Deployment modes: Docker Compose OR bare metal (auto-detected)
- Permission: `manage_settings` required for all update endpoints
- Rate limit: 1 update per 5 minutes
- Timer: 1x on startup + every 24h
- `.env` preserved via backup before update
- `APP_VERSION = "1.0.0"` in `src/config.py` is the version source of truth

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `src/update.py` | UpdateManager: check, apply, detect mode, state |
| Modify | `src/app.py` | Add 2 endpoints + register UpdateManager |
| Modify | `src/main.py` | Start update timer on app boot |
| Create | `src/static/sections/update.js` | Frontend JS for update card |
| Modify | `src/templates/sections/settings.html` | Add update card HTML |
| Create | `tests/test_update.py` | Unit tests for UpdateManager |

---

### Task 1: Create `src/update.py` — UpdateManager core

**Files:**
- Create: `src/update.py`
- Test: `tests/test_update.py`

**Interfaces:**
- Consumes: `src/config.py` → `APP_VERSION`, `GITHUB_REPO_SLUG` (new constant)
- Produces: `UpdateManager` class with `check_for_update()`, `apply_update(tag)`, `detect_deploy_mode()`, `get_status()` methods

- [ ] **Step 1: Write failing tests for UpdateManager**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/c/git/tucuxi && python -m pytest tests/test_update.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.update'`

- [ ] **Step 3: Implement UpdateManager**

```python
# src/update.py
"""OTA Update Manager — checks GitHub for newer releases and applies updates."""

import os
import logging
import shutil
import subprocess
import time
from datetime import datetime, timezone

import requests

from .config import APP_VERSION

logger = logging.getLogger("update")

GITHUB_REPO = "amarildolacerda/tucuxi"
GITHUB_API_BASE = "https://api.github.com"
CHECK_INTERVAL = 24 * 60 * 60  # 24 hours
RATE_LIMIT_SECONDS = 5 * 60    # 5 minutes between apply attempts
MAX_RETRY = 3


def parse_version(version_str):
    """Parse 'v1.2.3' or '1.2.3' into tuple (1, 2, 3)."""
    v = version_str.lstrip("v")
    parts = v.split(".")
    return tuple(int(p) for p in parts)


class UpdateManager:
    def __init__(self, project_dir=None):
        self.project_dir = project_dir or os.getcwd()
        self.current_version = APP_VERSION
        self.update_available = False
        self.latest_version = None
        self.latest_tag = None
        self.last_check = None
        self.last_error = None
        self.updating = False
        self.update_log = []
        self._last_apply_time = 0.0

    def get_status(self):
        """Return current update status as dict."""
        return {
            "current_version": self.current_version,
            "update_available": self.update_available,
            "latest_version": self.latest_version,
            "latest_tag": self.latest_tag,
            "last_check": self.last_check.isoformat() if self.last_check else None,
            "last_error": self.last_error,
            "updating": self.updating,
            "update_log": self.update_log,
        }

    def detect_deploy_mode(self):
        """Detect if project uses Docker Compose or bare metal."""
        compose_files = [
            "docker-compose.yml",
            "docker-compose.yaml",
            "compose.yml",
            "compose.yaml",
        ]
        for f in compose_files:
            if os.path.exists(os.path.join(self.project_dir, f)):
                return "docker"
        return "bare_metal"

    def check_for_update(self):
        """Check GitHub API for latest tag on main branch."""
        try:
            url = f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/git/refs/tags"
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            tags = resp.json()

            if not tags:
                self.last_error = "No tags found"
                return

            # Extract version numbers from tags
            versions = []
            for tag in tags:
                ref = tag.get("ref", "")
                if ref.startswith("refs/tags/"):
                    tag_name = ref.replace("refs/tags/", "")
                    try:
                        ver = parse_version(tag_name)
                        versions.append((ver, tag_name))
                    except (ValueError, IndexError):
                        continue

            if not versions:
                self.last_error = "No valid version tags found"
                return

            # Get highest version
            versions.sort(key=lambda x: x[0], reverse=True)
            latest_ver, latest_tag = versions[0]
            current_ver = parse_version(self.current_version)

            self.latest_version = latest_tag.lstrip("v")
            self.latest_tag = latest_tag
            self.update_available = latest_ver > current_ver
            self.last_check = datetime.now(timezone.utc)
            self.last_error = None

            logger.info(
                "Update check: current=%s latest=%s available=%s",
                self.current_version, self.latest_version, self.update_available,
            )

        except Exception as e:
            self.last_error = str(e)
            logger.error("Update check failed: %s", e)

    def apply_update(self, tag):
        """Apply update: git checkout tag + rebuild. Returns (success, log)."""
        if self.updating:
            return False, ["Update already in progress"]

        now = time.time()
        if now - self._last_apply_time < RATE_LIMIT_SECONDS:
            remaining = int(RATE_LIMIT_SECONDS - (now - self._last_apply_time))
            return False, [f"Rate limited. Try again in {remaining}s"]

        self.updating = True
        self.update_log = []
        self._last_apply_time = now

        try:
            self._log(f"Starting update to {tag}")

            # Backup .env
            self._backup_env()

            # Git fetch + checkout
            self._run_cmd(["git", "fetch", "origin", "main"])
            self._run_cmd(["git", "checkout", tag])

            # Detect mode and rebuild
            mode = self.detect_deploy_mode()
            self._log(f"Deploy mode: {mode}")

            if mode == "docker":
                self._run_cmd(["docker", "compose", "pull"])
                self._run_cmd(["docker", "compose", "up", "-d"])
            else:
                self._run_cmd(["pip", "install", "-e", "."])
                # Try to restart systemd service
                self._run_cmd(["sudo", "systemctl", "restart", "tucuxi"], allow_fail=True)

            self._log("Update completed successfully")
            return True, self.update_log

        except Exception as e:
            self._log(f"ERROR: {e}")
            self._rollback()
            return False, self.update_log

        finally:
            self.updating = False

    def _backup_env(self):
        """Backup .env file before update."""
        env_path = os.path.join(self.project_dir, ".env")
        if os.path.exists(env_path):
            backup_path = env_path + ".backup"
            shutil.copy2(env_path, backup_path)
            self._log(f"Backed up .env to .env.backup")

    def _rollback(self):
        """Rollback to previous commit on error."""
        try:
            self._log("Rolling back to previous commit...")
            self._run_cmd(["git", "checkout", "-"])
            self._log("Rollback completed")
        except Exception as e:
            self._log(f"Rollback failed: {e}")

    def _run_cmd(self, cmd, allow_fail=False):
        """Run a shell command and log output."""
        self._log(f"$ {' '.join(cmd)}")
        try:
            result = subprocess.run(
                cmd,
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                timeout=300,
            )
            if result.stdout:
                self._log(result.stdout.strip())
            if result.returncode != 0:
                msg = f"Command failed (exit {result.returncode}): {result.stderr.strip()}"
                if allow_fail:
                    self._log(f"WARNING: {msg}")
                else:
                    raise RuntimeError(msg)
        except subprocess.TimeoutExpired:
            if allow_fail:
                self._log("WARNING: Command timed out")
            else:
                raise RuntimeError("Command timed out after 300s")

    def _log(self, message):
        """Append to update log."""
        self.update_log.append(message)
        logger.info("UPDATE: %s", message)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /mnt/c/git/tucuxi && python -m pytest tests/test_update.py -v`
Expected: All 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/update.py tests/test_update.py
git commit -m "feat(update): add UpdateManager with GitHub API version checking"
```

---

### Task 2: Add update endpoints to `src/app.py`

**Files:**
- Modify: `src/app.py` — add 2 endpoints + init UpdateManager
- Test: `tests/test_update.py` (add endpoint tests)

**Interfaces:**
- Consumes: `UpdateManager` from `src/update.py`
- Produces: `GET /api/system/update-check`, `POST /api/system/update` endpoints

- [ ] **Step 1: Write failing tests for endpoints**

Add to `tests/test_update.py`:

```python
class TestUpdateEndpoints:
    def setup_method(self):
        from src.app import create_app
        self.app = create_app(testing=True)
        self.client = self.app.test_client()

    def test_update_check_requires_auth(self):
        resp = self.client.get("/api/system/update-check")
        assert resp.status_code in (401, 403)

    def test_update_check_returns_version(self):
        # Need to set up auth first — test with admin session
        with self.client.session_transaction() as sess:
            sess["user"] = "admin"
            sess["role"] = "manage_settings"
        resp = self.client.get("/api/system/update-check")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "current_version" in data
        assert "update_available" in data

    def test_update_post_requires_tag(self):
        with self.client.session_transaction() as sess:
            sess["user"] = "admin"
            sess["role"] = "manage_settings"
        resp = self.client.post("/api/system/update", json={})
        assert resp.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/c/git/tucuxi && python -m pytest tests/test_update.py::TestUpdateEndpoints -v`
Expected: FAIL — endpoints don't exist yet

- [ ] **Step 3: Add endpoints to `src/app.py`**

In `src/app.py`, find where other `/api/system/` endpoints are defined (near `/api/system/reboot`) and add:

```python
    # --- Update endpoints ---
    from .update import UpdateManager
    _update_manager = UpdateManager()

    @app.route("/api/system/update-check", methods=["GET"])
    def update_check():
        user = getattr(g, "current_user", None)
        if not _camera_allowed(user, -1):  # use manage_settings check
            return jsonify({"error": "Sem permissão"}), 403
        _update_manager.check_for_update()
        return jsonify(_update_manager.get_status())

    @app.route("/api/system/update", methods=["POST"])
    def update_apply():
        user = getattr(g, "current_user", None)
        if not _camera_allowed(user, -1):
            return jsonify({"error": "Sem permissão"}), 403
        data = request.get_json(silent=True) or {}
        tag = data.get("tag")
        if not tag:
            return jsonify({"error": "tag é obrigatório"}), 400
        success, log = _update_manager.apply_update(tag)
        return jsonify({
            "success": success,
            "message": "Atualizado com sucesso" if success else "Falha ao atualizar",
            "log": log,
        }), 200 if success else 500
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /mnt/c/git/tucuxi && python -m pytest tests/test_update.py::TestUpdateEndpoints -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/app.py tests/test_update.py
git commit -m "feat(update): add update-check and update endpoints"
```

---

### Task 3: Add update timer to `src/main.py`

**Files:**
- Modify: `src/main.py` — add background timer for periodic update checks

**Interfaces:**
- Consumes: `UpdateManager` from `src/update.py`
- Produces: Background thread that calls `check_for_update()` on startup + every 24h

- [ ] **Step 1: Add timer code to `src/main.py`**

After the app starts (near the end of `main()` function, where other background threads are started), add:

```python
    # Update checker: check on startup + every 24h
    from .update import UpdateManager, CHECK_INTERVAL
    update_mgr = UpdateManager()

    def _update_timer():
        while not stop_event.is_set():
            try:
                update_mgr.check_for_update()
            except Exception:
                logger.exception("Update check failed")
            stop_event.wait(CHECK_INTERVAL)

    update_thread = threading.Thread(target=_update_timer, daemon=True, name="update-checker")
    update_thread.start()
```

- [ ] **Step 2: Verify no import errors**

Run: `cd /mnt/c/git/tucuxi && python -c "from src.update import UpdateManager; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/main.py
git commit -m "feat(update): add background update checker timer (startup + 24h)"
```

---

### Task 4: Create frontend update card HTML

**Files:**
- Modify: `src/templates/sections/settings.html` — add update card below reboot button

- [ ] **Step 1: Add HTML for update card**

In `src/templates/sections/settings.html`, find the reboot section and add below it:

```html
        <!-- Atualização -->
        <div class="card">
            <h3>Atualização do Sistema</h3>
            <div id="update-status">
                <p class="muted">Verificando atualizações...</p>
            </div>
            <div id="update-actions" style="display:none;">
                <button id="btn-check-update" class="button-secondary">Verificar agora</button>
                <button id="btn-apply-update" class="button-primary" style="display:none;">Atualizar</button>
            </div>
            <div id="update-progress" style="display:none;">
                <div class="spinner"></div>
                <p id="update-progress-text">Atualizando...</p>
                <pre id="update-log" class="update-log"></pre>
            </div>
            <div id="update-result" style="display:none;"></div>
        </div>
```

- [ ] **Step 2: Commit**

```bash
git add src/templates/sections/settings.html
git commit -m "feat(update): add update card HTML to settings page"
```

---

### Task 5: Create frontend update JS

**Files:**
- Create: `src/static/sections/update.js`
- Modify: `src/templates/sections/settings.html` — include the JS file

**Interfaces:**
- Consumes: `GET /api/system/update-check`, `POST /api/system/update`
- Produces: Update UI state management, poll during update

- [ ] **Step 1: Create `src/static/sections/update.js`**

```javascript
// src/static/sections/update.js
// Update card logic for settings page

const UPDATE_CHECK_INTERVAL = 2000; // 2s poll during update

let _updateState = {
    currentVersion: null,
    latestVersion: null,
    available: false,
    updating: false,
};

export function initUpdate() {
    checkForUpdate();
    _bindEvents();
}

function _bindEvents() {
    const btnCheck = document.getElementById("btn-check-update");
    const btnApply = document.getElementById("btn-apply-update");

    if (btnCheck) {
        btnCheck.addEventListener("click", () => checkForUpdate());
    }
    if (btnApply) {
        btnApply.addEventListener("click", () => applyUpdate());
    }
}

async function checkForUpdate() {
    const statusEl = document.getElementById("update-status");
    const actionsEl = document.getElementById("update-actions");

    statusEl.innerHTML = '<p class="muted">Verificando atualizações...</p>';

    try {
        const resp = await fetch("/api/system/update-check");
        if (!resp.ok) throw new Error("Falha ao checar atualizações");
        const data = await resp.json();

        _updateState.currentVersion = data.current_version;
        _updateState.latestVersion = data.latest_version;
        _updateState.available = data.update_available;

        if (data.update_available) {
            statusEl.innerHTML = `
                <p>Versão atual: <strong>${data.current_version}</strong></p>
                <p>Disponível: <strong style="color:var(--warning)">${data.latest_version}</strong></p>
            `;
            const btnApply = document.getElementById("btn-apply-update");
            btnApply.style.display = "inline-block";
            btnApply.textContent = `Atualizar para ${data.latest_version}`;
        } else {
            statusEl.innerHTML = `
                <p>Versão atual: <strong>${data.current_version}</strong></p>
                <p class="muted" style="color:var(--success)">Sistema atualizado</p>
            `;
        }

        actionsEl.style.display = "block";

    } catch (e) {
        statusEl.innerHTML = `<p style="color:var(--error)">Erro: ${e.message}</p>`;
        actionsEl.style.display = "block";
    }
}

async function applyUpdate() {
    const tag = _updateState.latestVersion
        ? `v${_updateState.latestVersion}`
        : null;

    if (!tag) return;

    const progressEl = document.getElementById("update-progress");
    const progressText = document.getElementById("update-progress-text");
    const logEl = document.getElementById("update-log");
    const actionsEl = document.getElementById("update-actions");
    const resultEl = document.getElementById("update-result");

    actionsEl.style.display = "none";
    progressEl.style.display = "block";
    progressText.textContent = "Atualizando... Não desligue o Pi.";
    logEl.textContent = "";

    try {
        const resp = await fetch("/api/system/update", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ tag }),
        });
        const data = await resp.json();

        progressEl.style.display = "none";
        resultEl.style.display = "block";

        if (data.success) {
            resultEl.innerHTML = `
                <p style="color:var(--success)"><strong>Atualizado com sucesso! Reiniciando...</strong></p>
            `;
            setTimeout(() => location.reload(), 10000);
        } else {
            resultEl.innerHTML = `
                <p style="color:var(--error)"><strong>Falha ao atualizar</strong></p>
                <pre class="update-log">${(data.log || []).join("\n")}</pre>
                <button class="button-secondary" onclick="location.reload()">Tentar novamente</button>
            `;
        }
    } catch (e) {
        progressEl.style.display = "none";
        resultEl.style.display = "block";
        resultEl.innerHTML = `
            <p style="color:var(--error)"><strong>Erro: ${e.message}</strong></p>
            <button class="button-secondary" onclick="location.reload()">Tentar novamente</button>
        `;
    }
}

// Auto-init if loaded directly
if (document.getElementById("update-status")) {
    initUpdate();
}
```

- [ ] **Step 2: Include JS in settings.html**

At the bottom of `src/templates/sections/settings.html`, add:

```html
<script type="module" src="/static/sections/update.js"></script>
```

- [ ] **Step 3: Commit**

```bash
git add src/static/sections/update.js src/templates/sections/settings.html
git commit -m "feat(update): add update card frontend JS with state management"
```

---

### Task 6: Dashboard banner for available updates

**Files:**
- Modify: `src/static/core.js` — add banner check on dashboard load

**Interfaces:**
- Consumes: `GET /api/system/update-check`
- Produces: Yellow banner at top of dashboard when update is available

- [ ] **Step 1: Add banner check to `src/static/core.js`**

At the end of `core.js` (after DOM ready), add:

```javascript
    // Check for updates and show banner
    fetch("/api/system/update-check")
        .then(r => r.ok ? r.json() : null)
        .then(data => {
            if (data && data.update_available) {
                const banner = document.createElement("div");
                banner.className = "update-banner";
                banner.innerHTML = `Nova versão disponível: <strong>${data.latest_version}</strong> — <a href="/?section=settings">Atualizar</a>`;
                document.body.prepend(banner);
            }
        })
        .catch(() => {}); // Silent fail for update check
```

- [ ] **Step 2: Add banner CSS**

In the main CSS file or `<style>` block, add:

```css
.update-banner {
    background: var(--warning, #f0ad4e);
    color: #000;
    padding: 0.5rem 1rem;
    text-align: center;
    font-size: 0.9rem;
    position: sticky;
    top: 0;
    z-index: 1000;
}
.update-banner a {
    color: #000;
    font-weight: bold;
    text-decoration: underline;
}
.update-log {
    background: var(--surface-2, #f5f5f5);
    padding: 0.5rem;
    border-radius: var(--radius-sm, 4px);
    font-size: 0.8rem;
    max-height: 200px;
    overflow-y: auto;
}
```

- [ ] **Step 3: Commit**

```bash
git add src/static/core.js
git commit -m "feat(update): add dashboard banner for available updates"
```

---

### Task 7: Add config constants

**Files:**
- Modify: `src/config.py` — add `GITHUB_REPO_SLUG` constant

- [ ] **Step 1: Add constant to config.py**

After `APP_VERSION`, add:

```python
# GitHub repo for OTA updates (owner/repo format)
GITHUB_REPO_SLUG = os.getenv("GITHUB_REPO_SLUG", "amarildolacerda/tucuxi")
```

- [ ] **Step 2: Use constant in update.py**

Replace the hardcoded `GITHUB_REPO` in `src/update.py`:

```python
from .config import APP_VERSION, GITHUB_REPO_SLUG

# In UpdateManager.check_for_update():
url = f"{GITHUB_API_BASE}/repos/{GITHUB_REPO_SLUG}/git/refs/tags"
```

- [ ] **Step 3: Commit**

```bash
git add src/config.py src/update.py
git commit -m "feat(update): add GITHUB_REPO_SLUG config constant"
```

---

### Task 8: Run all tests and verify

**Files:**
- Test: `tests/test_update.py` — all tests

- [ ] **Step 1: Run full test suite**

Run: `cd /mnt/c/git/tucuxi && python -m pytest tests/test_update.py -v`
Expected: All tests PASS

- [ ] **Step 2: Verify imports**

Run: `cd /mnt/c/git/tucuxi && python -c "from src.update import UpdateManager; print(UpdateManager().get_status())"`
Expected: Status dict with `current_version: "1.0.0"`

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "feat: OTA update mechanism complete (GitHub API + git pull + dashboard UI)"
```
