# PTZ Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add PTZ camera control via ONVIF, presets, and autotracking to the Secur project.

**Architecture:** Dedicated `src/ptz/` module with ONVIF client, PTZ manager, and autotracking thread. REST API endpoints for move/stop/presets/autotracking. Dashboard inline controls.

**Tech Stack:** Python, onvif-zeep, Flask, SQLite, OpenCV, YOLO (existing)

## Global Constraints

- Python 3.11+ (Docker image uses python:3.11-slim)
- Flask backend, vanilla JS frontend
- SQLite for storage (no PostgreSQL yet)
- Permissão `manage_cameras` para operações PTZ
- Follow existing code patterns in `src/storage.py`, `src/app.py`

---

## File Structure

| File | Responsibility |
|------|----------------|
| `src/ptz/__init__.py` | Export PTZManager |
| `src/ptz/onvif_client.py` | ONVIF connection, move, stop, presets |
| `src/ptz/manager.py` | State per camera, connection cache, command queue |
| `src/ptz/autotracking.py` | Async thread: detect person → calculate delta → move |
| `src/storage.py` | Add cameras_ptz and ptz_presets tables + CRUD |
| `src/app.py` | Add PTZ API routes |
| `src/templates/sections/cameras.html` | PTZ controls inline + dialog section |
| `src/static/sections/cameras.js` | PTZ UI logic |
| `tests/test_ptz_module.py` | Unit tests for PTZ module |
| `tests/test_ptz_api.py` | API integration tests |

---

### Task 1: Storage — PTZ Tables and CRUD

**Files:**
- Modify: `src/storage.py`
- Test: `tests/test_ptz_storage.py`

**Interfaces:**
- Produces: `add_camera_ptz()`, `get_camera_ptz()`, `update_camera_ptz()`, `remove_camera_ptz()`, `add_ptz_preset()`, `list_ptz_presets()`, `remove_ptz_preset()`

- [ ] **Step 1: Write failing tests for PTZ storage**

```python
# tests/test_ptz_storage.py
import json
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from storage import EventStorage

def setup_storage():
    db_path = "/tmp/test_ptz_storage.db"
    if os.path.exists(db_path):
        os.remove(db_path)
    return EventStorage(db_path)

def test_add_camera_ptz():
    s = setup_storage()
    s.seed_cameras([{"name": "Cam1", "source": "rtsp://test", "zone": "z1"}])
    cam = s.list_cameras()[0]
    result = s.add_camera_ptz(cam["id"], "192.168.1.71", 8899, "micasa", "pass123")
    assert result is True
    ptz = s.get_camera_ptz(cam["id"])
    assert ptz is not None
    assert ptz["onvif_host"] == "192.168.1.71"
    assert ptz["onvif_port"] == 8899

def test_get_camera_ptz_missing():
    s = setup_storage()
    assert s.get_camera_ptz(999) is None

def test_add_ptz_preset():
    s = setup_storage()
    s.seed_cameras([{"name": "Cam1", "source": "rtsp://test", "zone": "z1"}])
    cam = s.list_cameras()[0]
    s.add_camera_ptz(cam["id"], "192.168.1.71", 8899, "micasa", "pass123")
    preset_id = s.add_ptz_preset(cam["id"], "Entrada", {"pan": 0.5, "tilt": -0.3, "zoom": 1.2})
    assert preset_id > 0
    presets = s.list_ptz_presets(cam["id"])
    assert len(presets) == 1
    assert presets[0]["name"] == "Entrada"

def test_remove_ptz_preset():
    s = setup_storage()
    s.seed_cameras([{"name": "Cam1", "source": "rtsp://test", "zone": "z1"}])
    cam = s.list_cameras()[0]
    s.add_camera_ptz(cam["id"], "192.168.1.71", 8899, "micasa", "pass123")
    preset_id = s.add_ptz_preset(cam["id"], "Entrada", {"pan": 0.5})
    result = s.remove_ptz_preset(preset_id)
    assert result is True
    assert len(s.list_ptz_presets(cam["id"])) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_ptz_storage.py -v`
Expected: FAIL with `AttributeError: 'EventStorage' object has no attribute 'add_camera_ptz'`

- [ ] **Step 3: Add PTZ tables to storage**

In `src/storage.py`, add to `__init__` method (after existing table creation):

```python
cursor.execute("""
    CREATE TABLE IF NOT EXISTS cameras_ptz (
        camera_id INTEGER PRIMARY KEY,
        onvif_host TEXT NOT NULL,
        onvif_port INTEGER DEFAULT 80,
        onvif_user TEXT,
        onvif_pass TEXT,
        ptz_enabled BOOLEAN DEFAULT 0,
        autotracking BOOLEAN DEFAULT 0,
        updated_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (camera_id) REFERENCES cameras(id) ON DELETE CASCADE
    )
""")
cursor.execute("""
    CREATE TABLE IF NOT EXISTS ptz_presets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        camera_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        position TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (camera_id) REFERENCES cameras(id) ON DELETE CASCADE
    )
""")
```

- [ ] **Step 4: Add CRUD methods**

```python
def add_camera_ptz(self, camera_id, onvif_host, onvif_port=80, onvif_user=None, onvif_pass=None):
    with self.lock:
        cursor = self.connection.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO cameras_ptz (camera_id, onvif_host, onvif_port, onvif_user, onvif_pass) VALUES (?, ?, ?, ?, ?)",
            (camera_id, onvif_host, onvif_port, onvif_user, onvif_pass),
        )
        self.connection.commit()
        return cursor.rowcount > 0

def get_camera_ptz(self, camera_id):
    with self.lock:
        cursor = self.connection.cursor()
        cursor.execute("SELECT * FROM cameras_ptz WHERE camera_id = ?", (camera_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

def update_camera_ptz(self, camera_id, **kwargs):
    with self.lock:
        fields = []
        values = []
        for key, val in kwargs.items():
            if key in ("onvif_host", "onvif_port", "onvif_user", "onvif_pass", "ptz_enabled", "autotracking"):
                fields.append(f"{key} = ?")
                values.append(val)
        if not fields:
            return False
        fields.append("updated_at = datetime('now')")
        values.append(camera_id)
        cursor = self.connection.cursor()
        cursor.execute(f"UPDATE cameras_ptz SET {', '.join(fields)} WHERE camera_id = ?", values)
        self.connection.commit()
        return cursor.rowcount > 0

def remove_camera_ptz(self, camera_id):
    with self.lock:
        cursor = self.connection.cursor()
        cursor.execute("DELETE FROM cameras_ptz WHERE camera_id = ?", (camera_id,))
        self.connection.commit()
        return cursor.rowcount > 0

def add_ptz_preset(self, camera_id, name, position):
    with self.lock:
        cursor = self.connection.cursor()
        cursor.execute(
            "INSERT INTO ptz_presets (camera_id, name, position) VALUES (?, ?, ?)",
            (camera_id, name, json.dumps(position)),
        )
        self.connection.commit()
        return cursor.lastrowid

def list_ptz_presets(self, camera_id):
    with self.lock:
        cursor = self.connection.cursor()
        cursor.execute("SELECT * FROM ptz_presets WHERE camera_id = ? ORDER BY id", (camera_id,))
        rows = [dict(row) for row in cursor.fetchall()]
    for row in rows:
        row["position"] = json.loads(row["position"])
    return rows

def remove_ptz_preset(self, preset_id):
    with self.lock:
        cursor = self.connection.cursor()
        cursor.execute("DELETE FROM ptz_presets WHERE id = ?", (preset_id,))
        self.connection.commit()
        return cursor.rowcount > 0
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_ptz_storage.py -v`
Expected: All 4 tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/storage.py tests/test_ptz_storage.py
git commit -m "feat(ptz): add cameras_ptz and ptz_presets tables with CRUD"
```

---

### Task 2: PTZ Module — ONVIF Client

**Files:**
- Create: `src/ptz/__init__.py`
- Create: `src/ptz/onvif_client.py`
- Test: `tests/test_ptz_module.py`

**Interfaces:**
- Produces: `PTZClient(camera_id, host, port, user, password)` → `.move(pan, tilt, zoom)`, `.stop()`, `.get_presets()`, `.goto_preset(preset_token)`, `.get_capabilities()`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_ptz_module.py
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from ptz.onvif_client import PTZClient

def test_ptz_client_init():
    client = PTZClient(1, "192.168.1.71", 8899, "micasa", "pass123")
    assert client.camera_id == 1
    assert client.host == "192.168.1.71"

def test_ptz_client_move():
    client = PTZClient(1, "192.168.1.71", 8899, "micasa", "pass123")
    # Should not raise
    result = client.move(0.5, 0.0, 0.0)
    assert result is True or result is None

def test_ptz_client_stop():
    client = PTZClient(1, "192.168.1.71", 8899, "micasa", "pass123")
    result = client.stop()
    assert result is True or result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_ptz_module.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ptz'`

- [ ] **Step 3: Create module files**

`src/ptz/__init__.py`:
```python
from .onvif_client import PTZClient
from .manager import PTZManager

__all__ = ["PTZClient", "PTZManager"]
```

`src/ptz/onvif_client.py`:
```python
"""ONVIF PTZ client wrapper."""
import logging
from typing import Optional

try:
    from onvif import ONVIFCamera
except ImportError:
    ONVIFCamera = None

logger = logging.getLogger(__name__)


class PTZClient:
    """Wraps onvif-zeep for PTZ operations."""

    def __init__(self, camera_id: int, host: str, port: int = 80,
                 user: str = "", password: str = ""):
        if ONVIFCamera is None:
            raise ImportError("onvif-zeep not installed: pip install onvif-zeep")
        self.camera_id = camera_id
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self._cam: Optional[ONVIFCamera] = None
        self._ptz_service = None
        self._profile_token = None

    def _connect(self):
        """Lazy connection to ONVIF service."""
        if self._cam is not None:
            return
        logger.info(f"Connecting ONVIF {self.host}:{self.port}")
        self._cam = ONVIFCamera(self.host, self.port, self.user, self.password)
        media_service = self._cam.create_media_service()
        profiles = media_service.GetProfiles()
        if profiles:
            self._profile_token = profiles[0].token
        self._ptz_service = self._cam.create_ptz_service()

    def move(self, pan: float, tilt: float, zoom: float) -> bool:
        """Continuous move with velocity values (-1.0 to 1.0)."""
        self._connect()
        req = {
            "ProfileToken": self._profile_token,
            "Velocity": {
                "PanTilt": {"x": pan, "y": tilt},
                "Zoom": {"x": zoom}
            }
        }
        self._ptz_service.ContinuousMove(req)
        return True

    def stop(self) -> bool:
        """Stop all PTZ movement."""
        self._connect()
        self._ptz_service.Stop({"ProfileToken": self._profile_token})
        return True

    def get_presets(self) -> list:
        """Get list of configured presets."""
        self._connect()
        try:
            presets = self._ptz_service.GetPresets({"ProfileToken": self._profile_token})
            return [{"name": p.Name, "token": p.token} for p in presets]
        except Exception as e:
            logger.warning(f"GetPresets failed: {e}")
            return []

    def goto_preset(self, preset_token: str) -> bool:
        """Move to a preset position."""
        self._connect()
        self._ptz_service.GotoPreset({
            "ProfileToken": self._profile_token,
            "PresetToken": preset_token
        })
        return True

    def get_capabilities(self) -> dict:
        """Check PTZ capabilities."""
        self._connect()
        try:
            caps = self._ptz_service.GetServiceCapabilities()
            return {
                "continuous_move": getattr(caps, "ContinuousMove", None),
                "relative_move": getattr(caps, "RelativeMove", None),
                "absolute_move": getattr(caps, "AbsoluteMove", None),
            }
        except Exception as e:
            logger.warning(f"GetServiceCapabilities failed: {e}")
            return {}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_ptz_module.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/ptz/ tests/test_ptz_module.py
git commit -m "feat(ptz): add ONVIF client module"
```

---

### Task 3: PTZ Module — Manager

**Files:**
- Create: `src/ptz/manager.py`
- Test: `tests/test_ptz_manager.py`

**Interfaces:**
- Produces: `PTZManager(storage)` → `.init_camera()`, `.get_client()`, `.move()`, `.stop()`, `.shutdown()`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_ptz_manager.py
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from ptz.manager import PTZManager
from storage import EventStorage

def setup():
    db = "/tmp/test_ptz_manager.db"
    if os.path.exists(db):
        os.remove(db)
    return EventStorage(db)

def test_manager_init_camera():
    s = setup()
    s.seed_cameras([{"name": "Cam1", "source": "rtsp://test", "zone": "z1"}])
    cam = s.list_cameras()[0]
    s.add_camera_ptz(cam["id"], "192.168.1.71", 8899, "micasa", "pass123")
    mgr = PTZManager(s)
    mgr.init_camera(cam["id"])
    assert cam["id"] in mgr._clients

def test_manager_move():
    s = setup()
    s.seed_cameras([{"name": "Cam1", "source": "rtsp://test", "zone": "z1"}])
    cam = s.list_cameras()[0]
    s.add_camera_ptz(cam["id"], "192.168.1.71", 8899, "micasa", "pass123")
    mgr = PTZManager(s)
    result = mgr.move(cam["id"], 0.5, 0.0, 0.0)
    assert result is True

def test_manager_stop():
    s = setup()
    s.seed_cameras([{"name": "Cam1", "source": "rtsp://test", "zone": "z1"}])
    cam = s.list_cameras()[0]
    s.add_camera_ptz(cam["id"], "192.168.1.71", 8899, "micasa", "pass123")
    mgr = PTZManager(s)
    result = mgr.stop(cam["id"])
    assert result is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_ptz_manager.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement manager**

`src/ptz/manager.py`:
```python
"""PTZ manager — state and connection cache per camera."""
import logging
from typing import Dict, Optional
from .onvif_client import PTZClient

logger = logging.getLogger(__name__)


class PTZManager:
    """Manages PTZ clients for all cameras."""

    def __init__(self, storage):
        self.storage = storage
        self._clients: Dict[int, PTZClient] = {}

    def init_camera(self, camera_id: int):
        """Initialize PTZ client for a camera from storage config."""
        ptz_config = self.storage.get_camera_ptz(camera_id)
        if not ptz_config:
            logger.debug(f"No PTZ config for camera {camera_id}")
            return
        client = PTZClient(
            camera_id=camera_id,
            host=ptz_config["onvif_host"],
            port=ptz_config["onvif_port"],
            user=ptz_config.get("onvif_user", ""),
            password=ptz_config.get("onvif_pass", ""),
        )
        self._clients[camera_id] = client
        logger.info(f"PTZ client initialized for camera {camera_id}")

    def get_client(self, camera_id: int) -> Optional[PTZClient]:
        """Get PTZ client for a camera."""
        return self._clients.get(camera_id)

    def move(self, camera_id: int, pan: float, tilt: float, zoom: float) -> bool:
        """Move camera."""
        client = self._clients.get(camera_id)
        if not client:
            raise ValueError(f"PTZ not configured for camera {camera_id}")
        return client.move(pan, tilt, zoom)

    def stop(self, camera_id: int) -> bool:
        """Stop camera movement."""
        client = self._clients.get(camera_id)
        if not client:
            raise ValueError(f"PTZ not configured for camera {camera_id}")
        return client.stop()

    def goto_preset(self, camera_id: int, preset_token: str) -> bool:
        """Move to preset position."""
        client = self._clients.get(camera_id)
        if not client:
            raise ValueError(f"PTZ not configured for camera {camera_id}")
        return client.goto_preset(preset_token)

    def shutdown(self):
        """Disconnect all clients."""
        self._clients.clear()
        logger.info("PTZ manager shut down")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_ptz_manager.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/ptz/manager.py tests/test_ptz_manager.py
git commit -m "feat(ptz): add PTZ manager with connection cache"
```

---

### Task 4: API Routes — PTZ Endpoints

**Files:**
- Modify: `src/app.py`
- Test: `tests/test_ptz_api.py`

**Interfaces:**
- Consumes: `PTZManager`, `storage.add_camera_ptz()`, `storage.add_ptz_preset()`
- Produces: API routes `/api/cameras/<id>/ptz/*`

- [ ] **Step 1: Write failing API tests**

```python
# tests/test_ptz_api.py
import json
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

def test_ptz_move_endpoint():
    """Test that PTZ move endpoint exists and returns proper response."""
    from app import create_app
    app = create_app()
    with app.test_client() as client:
        # Without PTZ config, should return error
        resp = client.post("/api/cameras/1/ptz/move",
                          data=json.dumps({"pan": 0.5, "tilt": 0.0, "zoom": 0.0}),
                          content_type="application/json")
        assert resp.status_code in (400, 404)

def test_ptz_stop_endpoint():
    from app import create_app
    app = create_app()
    with app.test_client() as client:
        resp = client.post("/api/cameras/1/ptz/stop")
        assert resp.status_code in (400, 404)

def test_ptz_presets_endpoint():
    from app import create_app
    app = create_app()
    with app.test_client() as client:
        resp = client.get("/api/cameras/1/ptz/presets")
        assert resp.status_code in (200, 404)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_ptz_api.py -v`
Expected: FAIL with 404 (routes don't exist yet)

- [ ] **Step 3: Add PTZ routes to app.py**

In `src/app.py`, after the existing camera routes, add:

```python
# --- PTZ Routes ---

@app.route("/api/cameras/<int:camera_id>/ptz/move", methods=["POST"])
@require_permission("manage_cameras")
def ptz_move(camera_id):
    from .ptz import PTZManager
    ptz_manager = getattr(app, "ptz_manager", None)
    if not ptz_manager:
        return jsonify({"error": "PTZ não configurado"}), 503
    payload = request.get_json() or {}
    pan = payload.get("pan", 0.0)
    tilt = payload.get("tilt", 0.0)
    zoom = payload.get("zoom", 0.0)
    try:
        ptz_manager.move(camera_id, pan, tilt, zoom)
        return jsonify({"status": "moving"})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/cameras/<int:camera_id>/ptz/stop", methods=["POST"])
@require_permission("manage_cameras")
def ptz_stop(camera_id):
    ptz_manager = getattr(app, "ptz_manager", None)
    if not ptz_manager:
        return jsonify({"error": "PTZ não configurado"}), 503
    try:
        ptz_manager.stop(camera_id)
        return jsonify({"status": "stopped"})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/cameras/<int:camera_id>/ptz/presets", methods=["GET"])
@require_permission("manage_cameras")
def ptz_list_presets(camera_id):
    presets = storage.list_ptz_presets(camera_id)
    return jsonify(presets)

@app.route("/api/cameras/<int:camera_id>/ptz/presets", methods=["POST"])
@require_permission("manage_cameras")
def ptz_add_preset(camera_id):
    payload = request.get_json() or {}
    name = payload.get("name")
    position = payload.get("position")
    if not name or not position:
        return jsonify({"error": "name e position são obrigatórios"}), 400
    preset_id = storage.add_ptz_preset(camera_id, name, position)
    return jsonify({"id": preset_id, "name": name, "position": position}), 201

@app.route("/api/cameras/<int:camera_id>/ptz/presets/<int:preset_id>", methods=["DELETE"])
@require_permission("manage_cameras")
def ptz_delete_preset(camera_id, preset_id):
    removed = storage.remove_ptz_preset(preset_id)
    if not removed:
        return jsonify({"error": "Preset não encontrado"}), 404
    return jsonify({"status": "deleted"})

@app.route("/api/cameras/<int:camera_id>/ptz/presets/<int:preset_id>/goto", methods=["POST"])
@require_permission("manage_cameras")
def ptz_goto_preset(camera_id, preset_id):
    ptz_manager = getattr(app, "ptz_manager", None)
    if not ptz_manager:
        return jsonify({"error": "PTZ não configurado"}), 503
    presets = storage.list_ptz_presets(camera_id)
    preset = next((p for p in presets if p["id"] == preset_id), None)
    if not preset:
        return jsonify({"error": "Preset não encontrado"}), 404
    # Use ONVIF preset token if available, otherwise send position
    try:
        client = ptz_manager.get_client(camera_id)
        if client:
            onvif_presets = client.get_presets()
            match = next((p for p in onvif_presets if p["name"] == preset["name"]), None)
            if match:
                client.goto_preset(match["token"])
                return jsonify({"status": "moving_to_preset"})
        return jsonify({"error": "Preset ONVIF não encontrado"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/cameras/<int:camera_id>/ptz/config", methods=["PUT"])
@require_permission("manage_cameras")
def ptz_config(camera_id):
    payload = request.get_json() or {}
    onvif_host = payload.get("onvif_host")
    onvif_port = payload.get("onvif_port", 80)
    onvif_user = payload.get("onvif_user")
    onvif_pass = payload.get("onvif_pass")
    ptz_enabled = payload.get("ptz_enabled", False)

    if ptz_enabled and not onvif_host:
        return jsonify({"error": "onvif_host é obrigatório quando PTZ habilitado"}), 400

    existing = storage.get_camera_ptz(camera_id)
    if existing:
        storage.update_camera_ptz(camera_id, onvif_host=onvif_host, onvif_port=onvif_port,
                                  onvif_user=onvif_user, onvif_pass=onvif_pass,
                                  ptz_enabled=ptz_enabled)
    elif ptz_enabled:
        storage.add_camera_ptz(camera_id, onvif_host, onvif_port, onvif_user, onvif_pass)

    # Re-init PTZ manager
    ptz_manager = getattr(app, "ptz_manager", None)
    if ptz_manager and ptz_enabled:
        ptz_manager.init_camera(camera_id)

    return jsonify({"status": "updated"})

@app.route("/api/cameras/<int:camera_id>/ptz/autotracking", methods=["PUT"])
@require_permission("manage_cameras")
def ptz_autotracking(camera_id):
    payload = request.get_json() or {}
    enabled = payload.get("enabled", False)
    storage.update_camera_ptz(camera_id, autotracking=enabled)
    return jsonify({"autotracking": enabled})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_ptz_api.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/app.py tests/test_ptz_api.py
git commit -m "feat(ptz): add PTZ API endpoints"
```

---

### Task 5: Dashboard — PTZ Controls UI

**Files:**
- Modify: `src/templates/sections/cameras.html`
- Modify: `src/static/sections/cameras.js`

**Interfaces:**
- Consumes: API routes `/api/cameras/<id>/ptz/*`
- Produces: PTZ controls in camera dialog + inline PTZ panel

- [ ] **Step 1: Add PTZ section to camera dialog**

In `src/templates/sections/cameras.html`, inside the `<form id="camera-form">` before the form-actions div, add:

```html
<div class="form-row ptz-section">
    <label>PTZ (Pan/Tilt/Zoom)</label>
    <div class="checkbox-group">
        <label class="checkbox-label">
            <input type="checkbox" id="camera-ptz-enabled"> PTZ habilitado
        </label>
    </div>
    <div id="ptz-config-fields" class="hidden-panel">
        <div class="form-row">
            <label for="camera-onvif-port">Porta ONVIF</label>
            <input id="camera-onvif-port" type="number" value="80" placeholder="80">
        </div>
        <div class="form-row">
            <label for="camera-onvif-user">Usuário ONVIF</label>
            <input id="camera-onvif-user" type="text" placeholder="admin">
        </div>
        <div class="form-row">
            <label for="camera-onvif-pass">Senha ONVIF</label>
            <input id="camera-onvif-pass" type="password" placeholder="••••">
        </div>
        <div class="checkbox-group">
            <label class="checkbox-label">
                <input type="checkbox" id="camera-autotracking"> Autotracking (auto-follow)
            </label>
        </div>
    </div>
</div>
```

- [ ] **Step 2: Add PTZ inline controls after camera table**

In `src/templates/sections/cameras.html`, after the `</table>` closing tag but inside the section, add:

```html
<div id="ptz-controls-panel" class="hidden-panel" style="margin-top:1rem;padding:1rem;border:1px solid var(--border);border-radius:var(--radius);">
    <h3 id="ptz-controls-title">Controles PTZ</h3>
    <div class="ptz-controls">
        <button class="button-mini ptz-btn" data-pan="-0.5" data-tilt="0.5" title="↖">↖</button>
        <button class="button-mini ptz-btn" data-pan="0" data-tilt="0.5" title="↑">↑</button>
        <button class="button-mini ptz-btn" data-pan="0.5" data-tilt="0.5" title="↗">↗</button>
        <button class="button-mini ptz-btn" data-pan="-0.5" data-tilt="0" title="←">←</button>
        <button class="button-mini ptz-btn" data-pan="0" data-tilt="0" title="Stop">⏹</button>
        <button class="button-mini ptz-btn" data-pan="0.5" data-tilt="0" title="→">→</button>
        <button class="button-mini ptz-btn" data-pan="-0.5" data-tilt="-0.5" title="↙">↙</button>
        <button class="button-mini ptz-btn" data-pan="0" data-tilt="-0.5" title="↓">↓</button>
        <button class="button-mini ptz-btn" data-pan="0.5" data-tilt="-0.5" title="↘">↘</button>
        <button class="button-mini ptz-btn" data-zoom="0.3" title="Zoom +">🔍+</button>
        <button class="button-mini ptz-btn" data-zoom="-0.3" title="Zoom −">🔍−</button>
    </div>
    <div class="ptz-presets" style="margin-top:0.5rem;">
        <button class="button-mini" id="ptz-save-preset">Salvar posição</button>
        <div id="ptz-preset-list"></div>
    </div>
</div>
```

- [ ] **Step 3: Add PTZ CSS**

In `src/static/css/style.css` (or the appropriate CSS file), add:

```css
.ptz-controls {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 0.25rem;
    max-width: 200px;
}
.ptz-btn {
    font-size: 1.2rem;
    padding: 0.5rem;
}
.ptz-presets {
    display: flex;
    flex-wrap: wrap;
    gap: 0.25rem;
    align-items: center;
}
.ptz-preset-btn {
    cursor: pointer;
}
```

- [ ] **Step 4: Add PTZ JS logic**

In `src/static/sections/cameras.js`, add PTZ functions:

```javascript
// PTZ Controls
function initPTZControls(cameraId) {
    const panel = document.getElementById("ptz-controls-panel");
    if (!panel) return;
    panel.classList.remove("hidden-panel");

    // Direction buttons
    document.querySelectorAll(".ptz-btn").forEach(btn => {
        btn.addEventListener("mousedown", () => {
            const pan = parseFloat(btn.dataset.pan || 0);
            const tilt = parseFloat(btn.dataset.tilt || 0);
            const zoom = parseFloat(btn.dataset.zoom || 0);
            ptzMove(cameraId, pan, tilt, zoom);
        });
        btn.addEventListener("mouseup", () => ptzStop(cameraId));
        btn.addEventListener("mouseleave", () => ptzStop(cameraId));
    });

    // Load presets
    loadPTZPresets(cameraId);
}

async function ptzMove(cameraId, pan, tilt, zoom) {
    await fetch(`/api/cameras/${cameraId}/ptz/move`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({pan, tilt, zoom})
    });
}

async function ptzStop(cameraId) {
    await fetch(`/api/cameras/${cameraId}/ptz/stop`, {method: "POST"});
}

async function loadPTZPresets(cameraId) {
    const resp = await fetch(`/api/cameras/${cameraId}/ptz/presets`);
    const presets = await resp.json();
    const list = document.getElementById("ptz-preset-list");
    if (!list) return;
    list.innerHTML = presets.map(p =>
        `<button class="button-mini ptz-preset-btn" data-preset-id="${p.id}">${p.name}</button>`
    ).join("");
    list.querySelectorAll(".ptz-preset-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            fetch(`/api/cameras/${cameraId}/ptz/presets/${btn.dataset.presetId}/goto`, {method: "POST"});
        });
    });
}

// Toggle PTZ config fields
document.getElementById("camera-ptz-enabled")?.addEventListener("change", (e) => {
    const fields = document.getElementById("ptz-config-fields");
    if (fields) fields.classList.toggle("hidden-panel", !e.target.checked);
});
```

- [ ] **Step 5: Commit**

```bash
git add src/templates/sections/cameras.html src/static/sections/cameras.js
git commit -m "feat(ptz): add PTZ controls to dashboard"
```

---

### Task 6: Autotracking Module

**Files:**
- Create: `src/ptz/autotracking.py`
- Test: `tests/test_autotracking.py`

**Interfaces:**
- Consumes: `PTZManager`, YOLO detections from worker
- Produces: `AutotrackingEngine(manager)` → `.start()`, `.stop()`, `.process_frame()`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_autotracking.py
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from ptz.autotracking import AutotrackingEngine

def test_autotracking_init():
    engine = AutotrackingEngine(manager=None, speed=0.5, threshold=0.05)
    assert engine.speed == 0.5
    assert engine.threshold == 0.05

def test_calculate_delta():
    engine = AutotrackingEngine(manager=None)
    # Person at right side of frame
    delta = engine._calculate_delta(
        person_center=(0.8, 0.5),
        frame_size=(640, 480)
    )
    assert delta[0] < 0  # Should move left (negative pan)
    assert abs(delta[0]) > 0.1

def test_should_move():
    engine = AutotrackingEngine(manager=None, threshold=0.05)
    assert engine._should_move((0.1, 0.0)) is True
    assert engine._should_move((0.02, 0.0)) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_autotracking.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement autotracking**

`src/ptz/autotracking.py`:
```python
"""Autotracking engine — follows detected persons via PTZ."""
import logging
import time
import threading
from typing import Optional, Tuple, List

logger = logging.getLogger(__name__)


class AutotrackingEngine:
    """Follows detected persons using PTZ movement."""

    def __init__(self, manager, speed: float = 0.5, threshold: float = 0.05,
                 interval_ms: int = 500):
        self.manager = manager
        self.speed = speed
        self.threshold = threshold
        self.interval_ms = interval_ms
        self._active_cameras = set()
        self._lock = threading.Lock()

    def start(self, camera_id: int):
        """Enable autotracking for a camera."""
        with self._lock:
            self._active_cameras.add(camera_id)
        logger.info(f"Autotracking enabled for camera {camera_id}")

    def stop(self, camera_id: int):
        """Disable autotracking for a camera."""
        with self._lock:
            self._active_cameras.discard(camera_id)
        logger.info(f"Autotracking disabled for camera {camera_id}")

    def process_frame(self, camera_id: int, frame_size: Tuple[int, int],
                      detections: List[dict]):
        """Process detections and move camera if needed.

        detections: list of dicts with 'class' and 'bbox' (x1,y1,x2,y2)
        """
        if camera_id not in self._active_cameras:
            return
        if not self.manager:
            return

        # Find person detections
        persons = [d for d in detections if d.get("class") == "person"]
        if not persons:
            return

        # Select person closest to frame center
        frame_w, frame_h = frame_size
        center_x, center_y = frame_w / 2, frame_h / 2
        best_person = None
        best_dist = float("inf")
        for p in persons:
            bbox = p.get("bbox", (0, 0, 0, 0))
            px = (bbox[0] + bbox[2]) / 2
            py = (bbox[1] + bbox[3]) / 2
            dist = ((px - center_x) ** 2 + (py - center_y) ** 2) ** 0.5
            if dist < best_dist:
                best_dist = dist
                best_person = (px, py)

        if not best_person:
            return

        delta = self._calculate_delta(best_person, frame_size)
        if self._should_move(delta):
            pan = max(-1.0, min(1.0, delta[0] * self.speed))
            tilt = max(-1.0, min(1.0, delta[1] * self.speed))
            try:
                self.manager.move(camera_id, pan, tilt, 0.0)
            except Exception as e:
                logger.warning(f"Autotracking move failed: {e}")
        else:
            try:
                self.manager.stop(camera_id)
            except Exception:
                pass

    def _calculate_delta(self, person_center: Tuple[float, float],
                         frame_size: Tuple[int, int]) -> Tuple[float, float]:
        """Calculate normalized delta from frame center to person."""
        frame_w, frame_h = frame_size
        center_x, center_y = frame_w / 2, frame_h / 2
        px, py = person_center
        dx = (center_x - px) / frame_w
        dy = (center_y - py) / frame_h
        return (dx, dy)

    def _should_move(self, delta: Tuple[float, float]) -> bool:
        """Check if delta exceeds threshold."""
        return abs(delta[0]) > self.threshold or abs(delta[1]) > self.threshold
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_autotracking.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/ptz/autotracking.py tests/test_autotracking.py
git commit -m "feat(ptz): add autotracking engine"
```

---

### Task 7: Integration — Wire PTZ into App and Worker

**Files:**
- Modify: `src/app.py`
- Modify: `src/worker.py` (add hook for autotracking)

**Interfaces:**
- Consumes: `PTZManager`, `AutotrackingEngine`
- Produces: PTZ manager initialized on app startup, worker sends frames to autotracking

- [ ] **Step 1: Initialize PTZ manager on app startup**

In `src/app.py`, in the `create_app()` function, after storage initialization:

```python
# Initialize PTZ manager
from .ptz import PTZManager
from .ptz.autotracking import AutotrackingEngine

app.ptz_manager = PTZManager(storage)
app.autotracking = AutotrackingEngine(
    manager=app.ptz_manager,
    speed=float(os.environ.get("PTZ_AUTOTRACKING_SPEED", "0.5")),
    threshold=float(os.environ.get("PTZ_AUTOTRACKING_THRESHOLD", "0.05")),
    interval_ms=int(os.environ.get("PTZ_AUTOTRACKING_INTERVAL_MS", "500")),
)

# Init PTZ for cameras that have config
for cam in storage.list_cameras():
    ptz_config = storage.get_camera_ptz(cam["id"])
    if ptz_config and ptz_config.get("ptz_enabled"):
        app.ptz_manager.init_camera(cam["id"])
        if ptz_config.get("autotracking"):
            app.autotracking.start(cam["id"])
```

- [ ] **Step 2: Add autotracking hook in worker**

In `src/worker.py`, after YOLO detection, add:

```python
# Send to autotracking if enabled
autotracking = getattr(self, '_autotracking', None)
if autotracking:
    autotracking.process_frame(
        camera_id=self.camera_id,
        frame_size=(frame.shape[1], frame.shape[0]),
        detections=detections  # list of {'class': 'person', 'bbox': (x1,y1,x2,y2)}
    )
```

- [ ] **Step 3: Commit**

```bash
git add src/app.py src/worker.py
git commit -m "feat(ptz): wire PTZ manager and autotracking into app"
```

---

### Task 8: Final Tests and Verification

**Files:**
- All test files

- [ ] **Step 1: Run all PTZ tests**

Run: `.venv/bin/python -m pytest tests/test_ptz_storage.py tests/test_ptz_module.py tests/test_ptz_manager.py tests/test_ptz_api.py tests/test_autotracking.py -v`
Expected: All tests PASS

- [ ] **Step 2: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: No regressions

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "feat(ptz): complete PTZ integration with autotracking"
```
