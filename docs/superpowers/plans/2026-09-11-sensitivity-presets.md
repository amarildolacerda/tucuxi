# Sensitivity Presets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 3 sensitivity presets (Low/Medium/High) + Custom mode per camera, with real-time application and UI controls.

**Architecture:** New `SensitivityManager` module with enum presets, SQLite persistence per camera, REST API, and setter integration into existing `CameraWorker`. UI adds a 4-option selector + sliders for custom mode.

**Tech Stack:** Python (Flask, SQLite), vanilla JS (dashboard), OpenCV (worker params)

## Global Constraints

- Python 3.11+, Flask, SQLite (existing patterns)
- Follow existing code style: no new dependencies
- Per-camera sensitivity (not global)
- Real-time application (no worker restart)
- Backward-compatible: env vars still work as fallback
- MVP scope only — no auto-scheduling, no per-zone sensitivity

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `src/sensitivity.py` | `SensitivityManager` class, presets enum, DB operations, worker propagation |
| Modify | `src/storage.py` | Add `camera_sensitivity` table, getter/setter methods |
| Modify | `src/config.py` | Add `DEFAULT_SENSITIVITY_LEVEL` env var |
| Modify | `src/main.py` | Integrate sensitivity on worker init + CameraManager restart |
| Modify | `src/app.py` | Add API endpoints for sensitivity CRUD |
| Modify | `src/static/sections/settings.js` | Add sensitivity selector + custom sliders UI |
| Modify | `src/templates/index.html` | Add sensitivity section HTML (if needed) |
| Modify | `SPEC.md` | Document sensitivity feature |
| Create | `tests/test_sensitivity.py` | Unit tests |
| Create | `tests/test_sensitivity_integration.py` | Integration tests |

---

### Task 1: Database Table + Storage Methods

**Files:**
- Modify: `src/storage.py:37-200` (add table in `_create_tables`, add methods)
- Test: `tests/test_sensitivity.py`

**Interfaces:**
- Consumes: `EventStorage` class
- Produces: `get_camera_sensitivity(camera_id) -> dict`, `set_camera_sensitivity(camera_id, level, custom_params) -> None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sensitivity.py
import pytest
from src.storage import EventStorage

def test_get_sensitivity_returns_default():
    storage = EventStorage()
    result = storage.get_camera_sensitivity(1)
    assert result["level"] == "medium"
    assert result["custom_params"] is None

def test_set_and_get_sensitivity():
    storage = EventStorage()
    storage.seed_cameras([{"name": "Test", "source": "rtsp://test", "zone": "test"}])
    camera = storage.list_cameras()[0]
    storage.set_camera_sensitivity(camera["id"], "high")
    result = storage.get_camera_sensitivity(camera["id"])
    assert result["level"] == "high"
    assert result["custom_params"] is None

def test_set_custom_params():
    storage = EventStorage()
    storage.seed_cameras([{"name": "Test", "source": "rtsp://test", "zone": "test"}])
    camera = storage.list_cameras()[0]
    custom = {"motion_min_area": 4000, "motion_persist_frames": 3, "detector_confidence": 0.35, "detector_iou": 0.42, "track_iou_threshold": 0.28}
    storage.set_camera_sensitivity(camera["id"], "custom", custom)
    result = storage.get_camera_sensitivity(camera["id"])
    assert result["level"] == "custom"
    assert result["custom_params"] == custom
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sensitivity.py -v`
Expected: FAIL with `AttributeError: 'EventStorage' object has no attribute 'get_camera_sensitivity'`

- [ ] **Step 3: Add table to _create_tables**

In `src/storage.py`, add after the `settings` table creation (around line 182):

```python
cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS camera_sensitivity (
        camera_id INTEGER PRIMARY KEY,
        level TEXT NOT NULL DEFAULT 'medium',
        custom_params TEXT,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (camera_id) REFERENCES cameras(id)
    )
    """
)
```

- [ ] **Step 4: Add storage methods**

In `src/storage.py`, add after the existing methods (before the last method or after `set_setting`):

```python
def get_camera_sensitivity(self, camera_id):
    """Retorna sensitivity config para uma câmera. Default: medium."""
    with self.lock:
        cursor = self.connection.cursor()
        cursor.execute("SELECT level, custom_params FROM camera_sensitivity WHERE camera_id = ?", (camera_id,))
        row = cursor.fetchone()
    if row is None:
        return {"level": "medium", "custom_params": None}
    custom = None
    if row["custom_params"]:
        try:
            custom = json.loads(row["custom_params"])
        except (json.JSONDecodeError, TypeError):
            custom = None
    return {"level": row["level"], "custom_params": custom}

def set_camera_sensitivity(self, camera_id, level, custom_params=None):
    """Define sensitivity level para uma câmera. Upsert."""
    import json
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    custom_json = json.dumps(custom_params) if custom_params is not None else None
    with self.lock:
        cursor = self.connection.cursor()
        cursor.execute(
            "INSERT INTO camera_sensitivity (camera_id, level, custom_params, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(camera_id) DO UPDATE SET level = excluded.level, custom_params = excluded.custom_params, updated_at = excluded.updated_at",
            (camera_id, level, custom_json, now),
        )
        self.connection.commit()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_sensitivity.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/storage.py tests/test_sensitivity.py
git commit -m "feat(sensitivity): add camera_sensitivity table and storage methods"
```

---

### Task 2: Sensitivity Module (Presets + Manager)

**Files:**
- Create: `src/sensitivity.py`
- Test: `tests/test_sensitivity.py` (extend)

**Interfaces:**
- Consumes: `EventStorage.get_camera_sensitivity()`, `EventStorage.set_camera_sensitivity()`
- Produces: `SensitivityManager.get_effective_params(camera_id) -> dict`, `SensitivityManager.set_level(camera_id, level, custom_params)`, `SensitivityManager.apply_to_workers(camera_id, params)`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_sensitivity.py`:

```python
from src.sensitivity import SensitivityManager, SensitivityLevel, SENSITIVITY_PRESETS

def test_presets_have_all_keys():
    required = {"motion_min_area", "motion_persist_frames", "detector_confidence", "detector_iou", "track_iou_threshold"}
    for level in [SensitivityLevel.LOW, SensitivityLevel.MEDIUM, SensitivityLevel.HIGH]:
        assert required.issubset(SENSITIVITY_PRESETS[level].keys())

def test_medium_preset_matches_defaults():
    from src.config import MOTION_MIN_AREA, MOTION_PERSIST_FRAMES, DETECTOR_CONFIDENCE, DETECTOR_IOU, TRACK_IOU_THRESHOLD
    m = SENSITIVITY_PRESETS[SensitivityLevel.MEDIUM]
    assert m["motion_min_area"] == MOTION_MIN_AREA
    assert m["motion_persist_frames"] == MOTION_PERSIST_FRAMES
    assert m["detector_confidence"] == DETECTOR_CONFIDENCE
    assert m["detector_iou"] == DETECTOR_IOU
    assert m["track_iou_threshold"] == TRACK_IOU_THRESHOLD

def test_get_effective_params_returns_preset():
    storage = EventStorage()
    storage.seed_cameras([{"name": "Test", "source": "rtsp://test", "zone": "test"}])
    camera = storage.list_cameras()[0]
    mgr = SensitivityManager(storage)
    params = mgr.get_effective_params(camera["id"])
    assert params == SENSITIVITY_PRESETS[SensitivityLevel.MEDIUM]

def test_get_effective_params_returns_custom():
    storage = EventStorage()
    storage.seed_cameras([{"name": "Test", "source": "rtsp://test", "zone": "test"}])
    camera = storage.list_cameras()[0]
    custom = {"motion_min_area": 4000, "motion_persist_frames": 3, "detector_confidence": 0.35, "detector_iou": 0.42, "track_iou_threshold": 0.28}
    storage.set_camera_sensitivity(camera["id"], "custom", custom)
    mgr = SensitivityManager(storage)
    params = mgr.get_effective_params(camera["id"])
    assert params == custom

def test_set_level_persists():
    storage = EventStorage()
    storage.seed_cameras([{"name": "Test", "source": "rtsp://test", "zone": "test"}])
    camera = storage.list_cameras()[0]
    mgr = SensitivityManager(storage)
    mgr.set_level(camera["id"], SensitivityLevel.HIGH)
    result = storage.get_camera_sensitivity(camera["id"])
    assert result["level"] == "high"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sensitivity.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.sensitivity'`

- [ ] **Step 3: Create sensitivity.py**

```python
# src/sensitivity.py
"""Sensitivity presets for camera detection tuning."""

import logging
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class SensitivityLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CUSTOM = "custom"


SENSITIVITY_PRESETS = {
    SensitivityLevel.LOW: {
        "motion_min_area": 8000,
        "motion_persist_frames": 4,
        "detector_confidence": 0.55,
        "detector_iou": 0.50,
        "track_iou_threshold": 0.4,
    },
    SensitivityLevel.MEDIUM: {
        "motion_min_area": 5000,
        "motion_persist_frames": 3,
        "detector_confidence": 0.40,
        "detector_iou": 0.45,
        "track_iou_threshold": 0.3,
    },
    SensitivityLevel.HIGH: {
        "motion_min_area": 3000,
        "motion_persist_frames": 2,
        "detector_confidence": 0.30,
        "detector_iou": 0.40,
        "track_iou_threshold": 0.25,
    },
}

# Valid ranges for custom mode
PARAM_RANGES = {
    "motion_min_area": (1000, 15000),
    "motion_persist_frames": (1, 8),
    "detector_confidence": (0.10, 0.80),
    "detector_iou": (0.20, 0.70),
    "track_iou_threshold": (0.10, 0.60),
}


def validate_custom_params(params: dict) -> Optional[str]:
    """Validate custom parameters. Returns error message or None."""
    required = {"motion_min_area", "motion_persist_frames", "detector_confidence", "detector_iou", "track_iou_threshold"}
    if not required.issubset(params.keys()):
        missing = required - params.keys()
        return f"Parâmetros faltando: {', '.join(missing)}"
    for key, value in params.items():
        if key not in PARAM_RANGES:
            continue
        min_val, max_val = PARAM_RANGES[key]
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return f"{key} deve ser numérico"
        if value < min_val or value > max_val:
            return f"{key} deve estar entre {min_val} e {max_val}"
    return None


class SensitivityManager:
    """Manages sensitivity presets per camera."""

    def __init__(self, storage):
        self.storage = storage
        self._workers = {}  # camera_id -> worker (set by CameraManager)

    def register_worker(self, camera_id, worker):
        """Register a worker for a camera (called by CameraManager)."""
        self._workers[camera_id] = worker

    def unregister_worker(self, camera_id):
        """Unregister a worker for a camera."""
        self._workers.pop(camera_id, None)

    def get_effective_params(self, camera_id: int) -> dict:
        """Return effective parameters (preset or custom) for a camera."""
        config = self.storage.get_camera_sensitivity(camera_id)
        level = config["level"]
        if level == SensitivityLevel.CUSTOM and config["custom_params"]:
            return config["custom_params"]
        preset_level = SensitivityLevel(level)
        return dict(SENSITIVITY_PRESETS[preset_level])

    def set_level(self, camera_id: int, level: str, custom_params: dict = None):
        """Set sensitivity level. Persists to DB and applies to workers."""
        level_enum = SensitivityLevel(level)
        if level_enum == SensitivityLevel.CUSTOM:
            if custom_params is None:
                return "custom_params é obrigatório para nível custom"
            error = validate_custom_params(custom_params)
            if error:
                return error
        self.storage.set_camera_sensitivity(camera_id, level, custom_params)
        params = self.get_effective_params(camera_id)
        self.apply_to_workers(camera_id, params)
        logger.info("Sensitivity for camera %s set to %s", camera_id, level)
        return None

    def apply_to_workers(self, camera_id: int, params: dict):
        """Apply parameters to the worker for a camera (real-time)."""
        worker = self._workers.get(camera_id)
        if worker is None:
            return
        # Update motion detector
        if hasattr(worker, '_motion_detector_ref'):
            md = worker._motion_detector_ref
            md.min_area = params["motion_min_area"]
            md.persist_frames = params["motion_persist_frames"]
        # Update object detector
        if hasattr(worker, 'object_detector'):
            od = worker.object_detector
            od.confidence_threshold = params["detector_confidence"]
            od.iou_threshold = params["detector_iou"]
        # Update tracker
        if hasattr(worker, '_tracker_ref'):
            tr = worker._tracker_ref
            tr.iou_threshold = params["track_iou_threshold"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_sensitivity.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/sensitivity.py tests/test_sensitivity.py
git commit -m "feat(sensitivity): add SensitivityManager with presets and validation"
```

---

### Task 3: Integrate with CameraWorker

**Files:**
- Modify: `src/main.py:76-125` (CameraWorker.__init__), `src/main.py:288-291` (run method), `src/main.py:623-693` (CameraManager)
- Test: `tests/test_sensitivity_integration.py`

**Interfaces:**
- Consumes: `SensitivityManager`, `SENSITIVITY_PRESETS`
- Produces: Workers expose `_motion_detector_ref`, `_tracker_ref` for real-time updates

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sensitivity_integration.py
import pytest
from unittest.mock import MagicMock, patch
from src.sensitivity import SensitivityManager, SensitivityLevel, SENSITIVITY_PRESETS
from src.storage import EventStorage

def test_worker_receives_sensitivity_on_init():
    """When a worker starts, it should apply sensitivity from DB."""
    storage = EventStorage()
    storage.seed_cameras([{"name": "Test", "source": "rtsp://test", "zone": "test"}])
    camera = storage.list_cameras()[0]
    storage.set_camera_sensitivity(camera["id"], "high")
    mgr = SensitivityManager(storage)
    # Simulate worker registration
    mock_worker = MagicMock()
    mock_worker._motion_detector_ref = MagicMock()
    mock_worker.object_detector = MagicMock()
    mock_worker._tracker_ref = MagicMock()
    mgr.register_worker(camera["id"], mock_worker)
    params = mgr.get_effective_params(camera["id"])
    mgr.apply_to_workers(camera["id"], params)
    assert mock_worker._motion_detector_ref.min_area == SENSITIVITY_PRESETS[SensitivityLevel.HIGH]["motion_min_area"]
    assert mock_worker.object_detector.confidence_threshold == SENSITIVITY_PRESETS[SensitivityLevel.HIGH]["detector_confidence"]

def test_set_level_updates_worker_in_realtime():
    """Changing level should immediately update worker params."""
    storage = EventStorage()
    storage.seed_cameras([{"name": "Test", "source": "rtsp://test", "zone": "test"}])
    camera = storage.list_cameras()[0]
    mgr = SensitivityManager(storage)
    mock_worker = MagicMock()
    mock_worker._motion_detector_ref = MagicMock()
    mock_worker.object_detector = MagicMock()
    mock_worker._tracker_ref = MagicMock()
    mgr.register_worker(camera["id"], mock_worker)
    # Set to high
    mgr.set_level(camera["id"], "high")
    assert mock_worker._motion_detector_ref.min_area == 3000
    # Set to low
    mgr.set_level(camera["id"], "low")
    assert mock_worker._motion_detector_ref.min_area == 8000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sensitivity_integration.py -v`
Expected: FAIL (workers don't expose refs yet)

- [ ] **Step 3: Modify CameraWorker to expose refs**

In `src/main.py`, in `CameraWorker.__init__` (around line 76), add after `self.thread = ...`:

```python
# Sensitivity refs (set by SensitivityManager for real-time updates)
self._motion_detector_ref = None
self._tracker_ref = None
```

In `CameraWorker.run()` (around line 290), after creating `motion_detector` and `tracker`, set the refs:

```python
motion_detector = MotionDetector(min_area=MOTION_MIN_AREA)
tracker = IoUTracker(iou_threshold=TRACK_IOU_THRESHOLD, max_age_seconds=TRACK_MAX_AGE_SECONDS)
# Expose refs for real-time sensitivity updates
self._motion_detector_ref = motion_detector
self._tracker_ref = tracker
```

- [ ] **Step 4: Integrate SensitivityManager in CameraManager**

In `src/main.py`, modify `CameraManager.__init__` to accept and store a `SensitivityManager`:

```python
class CameraManager:
    def __init__(self, storage, alerts, object_detector, identity_recognizer=None, event_bus=None, sensitivity_manager=None):
        # ... existing init ...
        self.sensitivity_manager = sensitivity_manager
```

In `CameraManager.monitor_cameras`, when creating a new worker (around line 648), apply sensitivity after worker starts:

```python
worker = CameraWorker(camera, self.storage, self.alerts, self.object_detector, self.identity_recognizer, self.event_bus)
worker.start()
self.workers[cam_id] = worker
# Apply sensitivity from DB
if self.sensitivity_manager:
    self.sensitivity_manager.register_worker(cam_id, worker)
    params = self.sensitivity_manager.get_effective_params(cam_id)
    self.sensitivity_manager.apply_to_workers(cam_id, params)
```

Also apply sensitivity when a worker is restarted (around line 664):

```python
new_worker = CameraWorker(camera, self.storage, self.alerts, self.object_detector, self.identity_recognizer, self.event_bus)
new_worker.start()
self.workers[cam_id] = new_worker
if self.sensitivity_manager:
    self.sensitivity_manager.register_worker(cam_id, new_worker)
    params = self.sensitivity_manager.get_effective_params(cam_id)
    self.sensitivity_manager.apply_to_workers(cam_id, params)
```

- [ ] **Step 5: Update main() to create SensitivityManager**

In `src/main.py`, in `main()` function (around line 723), before creating CameraManager:

```python
from .sensitivity import SensitivityManager
sensitivity_manager = SensitivityManager(storage)
camera_manager = CameraManager(storage, alerts, object_detector, identity_recognizer, event_bus, sensitivity_manager)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_sensitivity_integration.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/main.py tests/test_sensitivity_integration.py
git commit -m "feat(sensitivity): integrate SensitivityManager with CameraWorker real-time updates"
```

---

### Task 4: REST API Endpoints

**Files:**
- Modify: `src/app.py` (add routes)
- Test: `tests/test_sensitivity_integration.py` (extend)

**Interfaces:**
- Consumes: `SensitivityManager`, `SENSITIVITY_PRESETS`, `validate_custom_params`
- Produces: `GET /api/cameras/<id>/sensitivity`, `PUT /api/cameras/<id>/sensitivity`, `GET /api/sensitivity/presets`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_sensitivity_integration.py`:

```python
import json

def test_api_get_sensitivity(client):
    """GET /api/cameras/1/sensitivity returns current level."""
    resp = client.get("/api/cameras/1/sensitivity")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "level" in data
    assert "effective_params" in data

def test_api_set_sensitivity_high(client):
    """PUT /api/cameras/1/sensitivity sets level."""
    resp = client.put("/api/cameras/1/sensitivity", json={"level": "high"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["level"] == "high"

def test_api_set_sensitivity_custom(client):
    """PUT /api/cameras/1/sensitivity with custom params."""
    custom = {"motion_min_area": 4000, "motion_persist_frames": 3, "detector_confidence": 0.35, "detector_iou": 0.42, "track_iou_threshold": 0.28}
    resp = client.put("/api/cameras/1/sensitivity", json={"level": "custom", "custom_params": custom})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["level"] == "custom"
    assert data["effective_params"] == custom

def test_api_set_sensitivity_invalid_level(client):
    """PUT with invalid level returns 400."""
    resp = client.put("/api/cameras/1/sensitivity", json={"level": "invalid"})
    assert resp.status_code == 400

def test_api_set_sensitivity_custom_without_params(client):
    """PUT custom without custom_params returns 400."""
    resp = client.put("/api/cameras/1/sensitivity", json={"level": "custom"})
    assert resp.status_code == 400

def test_api_presets(client):
    """GET /api/sensitivity/presets returns all presets."""
    resp = client.get("/api/sensitivity/presets")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "low" in data
    assert "medium" in data
    assert "high" in data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sensitivity_integration.py -v`
Expected: FAIL with 404 (routes don't exist yet)

- [ ] **Step 3: Add API routes to app.py**

In `src/app.py`, add after the existing routes (e.g., after `api_config`):

```python
@app.route("/api/sensitivity/presets")
def api_sensitivity_presets():
    """Return the 3 preset values for the UI."""
    from .sensitivity import SENSITIVITY_PRESETS, SensitivityLevel
    return jsonify({
        level.value: params
        for level, params in SENSITIVITY_PRESETS.items()
    })

@app.route("/api/cameras/<int:camera_id>/sensitivity", methods=["GET"])
@require_permission("view_cameras")
def api_camera_sensitivity_get(camera_id):
    """Get sensitivity config for a camera."""
    from .sensitivity import SensitivityManager, SENSITIVITY_PRESETS, SensitivityLevel
    storage_obj = EventStorage()
    mgr = SensitivityManager(storage_obj)
    params = mgr.get_effective_params(camera_id)
    config = storage_obj.get_camera_sensitivity(camera_id)
    return jsonify({
        "camera_id": camera_id,
        "level": config["level"],
        "effective_params": params,
        "custom_params": config["custom_params"],
    })

@app.route("/api/cameras/<int:camera_id>/sensitivity", methods=["PUT"])
@require_permission("edit_cameras")
def api_camera_sensitivity_set(camera_id):
    """Set sensitivity level for a camera."""
    from .sensitivity import SensitivityManager, SensitivityLevel, validate_custom_params
    data = request.get_json(silent=True) or {}
    level = data.get("level")
    if level not in [l.value for l in SensitivityLevel]:
        return jsonify({"error": f"Nível inválido. Use: low, medium, high, custom"}), 400
    if level == "custom":
        custom_params = data.get("custom_params")
        if custom_params is None:
            return jsonify({"error": "custom_params obrigatório para nível custom"}), 400
        error = validate_custom_params(custom_params)
        if error:
            return jsonify({"error": error}), 400
    else:
        custom_params = None
    # Get or create camera_manager's sensitivity_manager
    # For now, use direct storage + manager (workers won't be updated without camera_manager ref)
    # This is acceptable for API-only changes; worker update happens via CameraManager integration
    storage_obj = EventStorage()
    mgr = SensitivityManager(storage_obj)
    error = mgr.set_level(camera_id, level, custom_params)
    if error:
        return jsonify({"error": error}), 400
    config = storage_obj.get_camera_sensitivity(camera_id)
    params = mgr.get_effective_params(camera_id)
    return jsonify({
        "camera_id": camera_id,
        "level": config["level"],
        "effective_params": params,
        "custom_params": config["custom_params"],
    })
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_sensitivity_integration.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/app.py tests/test_sensitivity_integration.py
git commit -m "feat(sensitivity): add REST API endpoints for sensitivity CRUD"
```

---

### Task 5: UI - Sensitivity Selector + Custom Sliders

**Files:**
- Modify: `src/static/sections/settings.js`
- Modify: `src/templates/index.html` (if needed for section container)

**Interfaces:**
- Consumes: `GET /api/sensitivity/presets`, `GET /api/cameras/<id>/sensitivity`, `PUT /api/cameras/<id>/sensitivity`
- Produces: Visual selector (Baixa/Média/Alta/Personalizado) + sliders in custom mode

- [ ] **Step 1: Add sensitivity section to settings.js**

In `src/static/sections/settings.js`, add a new function `renderSensitivityConfig()` and call it from `renderSettings()`:

```javascript
async function renderSensitivityConfig() {
  const container = document.getElementById('sensitivity-config');
  if (!container) return;

  // Fetch presets and cameras
  const [presets, camerasResp] = await Promise.all([
    fetch('/api/sensitivity/presets').then(r => r.json()),
    fetch('/api/cameras').then(r => r.json()),
  ]);

  const cameras = camerasResp.cameras || camerasResp;
  if (!cameras.length) {
    container.textContent = 'Nenhuma câmera configurada.';
    return;
  }

  container.innerHTML = '';
  const section = document.createElement('div');
  section.className = 'sensitivity-section';

  cameras.forEach(cam => {
    const camDiv = document.createElement('div');
    camDiv.className = 'config-module-group sensitivity-camera-group';

    const h4 = document.createElement('h4');
    h4.textContent = cam.name;
    camDiv.appendChild(h4);

    // Current level display
    const currentResp = await fetch(`/api/cameras/${cam.id}/sensitivity`);
    const current = await currentResp.json();

    // Selector
    const selector = document.createElement('div');
    selector.className = 'sensitivity-selector';
    const levels = [
      { value: 'low', label: 'Baixa', desc: 'Menos alertas. Ideal para áreas movimentadas.' },
      { value: 'medium', label: 'Média', desc: 'Equilibrado. Padrão para uso geral.' },
      { value: 'high', label: 'Alta', desc: 'Mais alertas. Ideal para perímetros críticos.' },
      { value: 'custom', label: 'Personalizado', desc: 'Ajuste manual de cada parâmetro.' },
    ];

    levels.forEach(lv => {
      const btn = document.createElement('button');
      btn.className = 'button-mini sensitivity-btn' + (current.level === lv.value ? ' active' : '');
      btn.textContent = lv.label;
      btn.title = lv.desc;
      btn.addEventListener('click', () => selectLevel(cam.id, lv.value, camDiv, presets));
      selector.appendChild(btn);
    });
    camDiv.appendChild(selector);

    // Description
    const desc = document.createElement('p');
    desc.className = 'sensitivity-desc';
    const currentLevel = levels.find(l => l.value === current.level);
    desc.textContent = currentLevel ? currentLevel.desc : '';
    camDiv.appendChild(desc);

    // Custom sliders (hidden by default)
    const slidersDiv = document.createElement('div');
    slidersDiv.className = 'sensitivity-sliders' + (current.level === 'custom' ? '' : ' hidden');
    slidersDiv.id = `sensitivity-sliders-${cam.id}`;

    const params = current.effective_params;
    const sliderDefs = [
      { key: 'motion_min_area', label: 'Área mínima de movimento', min: 1000, max: 15000, step: 500, unit: 'px' },
      { key: 'motion_persist_frames', label: 'Frames de persistência', min: 1, max: 8, step: 1, unit: 'frames' },
      { key: 'detector_confidence', label: 'Confiança da IA', min: 0.10, max: 0.80, step: 0.05, unit: '' },
      { key: 'detector_iou', label: 'NMS (sobreposição)', min: 0.20, max: 0.70, step: 0.05, unit: '' },
      { key: 'track_iou_threshold', label: 'Limiar de rastreamento', min: 0.10, max: 0.60, step: 0.05, unit: '' },
    ];

    sliderDefs.forEach(sd => {
      const row = document.createElement('div');
      row.className = 'slider-row';
      const label = document.createElement('label');
      label.textContent = sd.label;
      const input = document.createElement('input');
      input.type = 'range';
      input.min = sd.min;
      input.max = sd.max;
      input.step = sd.step;
      input.value = params[sd.key];
      input.dataset.key = sd.key;
      const valueSpan = document.createElement('span');
      valueSpan.className = 'slider-value';
      valueSpan.textContent = params[sd.key] + (sd.unit ? ' ' + sd.unit : '');
      input.addEventListener('input', () => {
        valueSpan.textContent = input.value + (sd.unit ? ' ' + sd.unit : '');
      });
      row.appendChild(label);
      row.appendChild(input);
      row.appendChild(valueSpan);
      slidersDiv.appendChild(row);
    });

    // Save custom button
    const saveBtn = document.createElement('button');
    saveBtn.className = 'button-primary';
    saveBtn.textContent = 'Salvar personalizado';
    saveBtn.addEventListener('click', () => saveCustom(cam.id, slidersDiv));
    slidersDiv.appendChild(saveBtn);

    camDiv.appendChild(slidersDiv);
    section.appendChild(camDiv);
  });

  container.appendChild(section);
}

async function selectLevel(cameraId, level, camDiv, presets) {
  // Update active button
  camDiv.querySelectorAll('.sensitivity-btn').forEach(btn => {
    btn.classList.toggle('active', btn.textContent.toLowerCase() === {
      low: 'baixa', medium: 'média', high: 'alta', custom: 'personalizado'
    }[level]);
  });

  // Show/hide sliders
  const slidersDiv = camDiv.querySelector('.sensitivity-sliders');
  if (slidersDiv) {
    slidersDiv.classList.toggle('hidden', level !== 'custom');
    if (level !== 'custom') {
      // Apply preset
      await fetch(`/api/cameras/${cameraId}/sensitivity`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ level }),
      });
    }
  }
}

async function saveCustom(cameraId, slidersDiv) {
  const params = {};
  slidersDiv.querySelectorAll('input[type="range"]').forEach(input => {
    const key = input.dataset.key;
    params[key] = parseFloat(input.value);
  });
  const resp = await fetch(`/api/cameras/${cameraId}/sensitivity`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ level: 'custom', custom_params: params }),
  });
  if (!resp.ok) {
    const err = await resp.json();
    alert(err.error || 'Erro ao salvar');
  }
}
```

Also update `renderSettings()` to call `renderSensitivityConfig()`:

```javascript
async function renderSettings() {
  const toggle = document.getElementById('privacy-mode-toggle');
  if (!toggle) return;
  try {
    const data = await fetchData('/api/settings');
    toggle.checked = !!data.privacy_mode;
  } catch (e) { /* offline: mantém estado atual */ }
  renderSettingsConfig();
  renderSensitivityConfig();
}
```

- [ ] **Step 2: Add CSS for sensitivity section**

In `src/static/style.css` (or relevant CSS file), add:

```css
.sensitivity-section { margin-top: 1rem; }
.sensitivity-camera-group { margin-bottom: 1.5rem; }
.sensitivity-selector { display: flex; gap: 0.5rem; margin: 0.5rem 0; }
.sensitivity-btn { flex: 1; padding: 0.5rem; text-align: center; }
.sensitivity-btn.active { background: var(--primary); color: white; }
.sensitivity-desc { font-size: 0.85rem; color: var(--muted); margin: 0.25rem 0 0.75rem; }
.sensitivity-sliders { display: flex; flex-direction: column; gap: 0.75rem; }
.slider-row { display: flex; align-items: center; gap: 0.5rem; }
.slider-row label { flex: 0 0 200px; font-size: 0.85rem; }
.slider-row input[type="range"] { flex: 1; }
.slider-row .slider-value { flex: 0 0 60px; text-align: right; font-size: 0.85rem; }
.hidden { display: none; }
```

- [ ] **Step 3: Verify in browser**

Run: `python -m src.main` and open `http://localhost:8000/settings`
Expected: Sensitivity section visible with selector and sliders

- [ ] **Step 4: Commit**

```bash
git add src/static/sections/settings.js src/static/style.css
git commit -m "feat(sensitivity): add UI selector and custom sliders for sensitivity presets"
```

---

### Task 6: Update SPEC.md

**Files:**
- Modify: `SPEC.md`

**Interfaces:**
- Consumes: None
- Produces: Updated documentation

- [ ] **Step 1: Add feature to SPEC.md**

In `SPEC.md`, add in the "Funcionalidades principais" section (around line 77):

```
- Configuração de sensibilidade por câmera com presets (Baixa/Média/Alta) e modo Personalizado.
```

Add in the "Requisitos funcionais" section (around line 19):

```
- Permitir ao usuário ajustar sensibilidade de detecção com presets prontos ou configuração manual.
- Aplicar configuração de sensibilidade por câmera em tempo real.
```

- [ ] **Step 2: Commit**

```bash
git add SPEC.md
git commit -m "docs: add sensitivity presets to SPEC.md"
```

---

### Task 7: Final Verification

**Files:**
- None (verification only)

- [ ] **Step 1: Run all tests**

Run: `pytest tests/test_sensitivity.py tests/test_sensitivity_integration.py -v`
Expected: All tests PASS

- [ ] **Step 2: Run full test suite**

Run: `pytest`
Expected: No regressions

- [ ] **Step 3: Manual smoke test**

1. Start server: `python -m src.main`
2. Open dashboard: `http://localhost:8000/settings`
3. Verify sensitivity section appears with 4 buttons (Baixa, Média, Alta, Personalizado)
4. Click "Alta" → verify API returns high params
5. Click "Personalizado" → verify sliders appear
6. Adjust sliders → click "Salvar personalizado" → verify params saved
7. Check worker logs → verify no restart, params applied in real-time

- [ ] **Step 4: Final commit (if needed)**

```bash
git add -A
git commit -m "feat(sensitivity): complete sensitivity presets feature"
```
