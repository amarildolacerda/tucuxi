# Tucuxi HA AI Integration (MVP) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the MVP predictor (embalagem A, in-process) that publishes enriched events, EWMA predictions, and rosa→aspersor deterrence with alarm modes, all 100% local.

**Architecture:** New `src/predictor/` package (pip-installable layout, future `tucuxi-predictor` submodule extraction) with schemas, EWMA model, SQLite store, MQTT publisher, entity_map/actuator, and ha_client; Tucuxi dual-publishes `tucuxi/camera/+/event` and subscribes the predictor to `LocalEventQueue`; HA consumes via `mqtt.sensor`, virtual switches, and one automation.

**Tech Stack:** Python 3.11, paho-mqtt, SQLite (`src/storage.py` `events` table), pytest, Home Assistant MQTT discovery.

## Global Constraints

- 100% local, no cloud, no PII in prediction topics; thumbnail NEVER in `tucuxi/predictions/+` (spec §10).
- `schema_version: 1` in every payload; subscribers ignore unknown versions (spec §10).
- Topics: `tucuxi/camera/{slug}/event` (retain=false, QoS 0), `tucuxi/predictions/{slug}` (retain=true, QoS 0), `tucuxi/ha/alarm_mode` (retain=true, QoS 0), `tucuxi/automation/actuator` (retain=false, QoS 0), `tucuxi/mode/alarme|viagem/set|state`, legacy `secur/*` untouched (spec §8).
- `PREDICTION_THRESHOLD=0.75`, `PREDICTOR_INTERVAL_SECONDS=900`, `PREDICTOR_DETER_COOLDOWN_SEC=900` (15 min irrigation), `PREDICTOR_HISTORY_DAYS=7` (spec §9/§11).
- Fail-secure: stale `alarm_mode` (>60s) or HA offline → assume last armed mode, never `disarmed` (spec §4.4).
- Todo comando `tucuxi/automation/actuator` e notificação de dissuasão carrega `motivo` legível + base (spec §4.7-A).
- MVP decisions locked (reversible): P2 dual-publish legacy+novo; P3 `sensor` 0-1; P5 local time ISO with offset; P8 `tucuxi/` novos + `secur/` legado; P10 `rosa` operacional com alias `acesso_jardim`; P11/P12 sem câmera em social/internos (só PIR via entity_map futuro); D1 por câmera; D2 janela fixa 1h publicada a cada 15min; D3 só hora do dia; D4 `person`/`motion_detected`; D5 sensor por câmera; D7 SQLite.
- TDD: failing test first, minimal implementation, run tests, commit per task.
- Imports in tests use `from src.predictor.<module> import ...`; run pytest from repo root: `python -m pytest tests/<file> -v`.
- Never use hardcoded dashboard colors; this plan touches no CSS.

**Spec coverage map:** §4.3 rosa→aspersor → Tasks 6+7; §4.4 modos → Tasks 6+7; §4.5 L1→L2 escada → Tasks 6+7 (luz + aspersor, sirene/TTS ficam V3); §4.7-A motivo → Tasks 1+7+8+9; §5.1 evento enriquecido → Task 4; §5.2 predição → Task 5; §5.5 atuação → Task 7; §5.6 alarm_mode → Task 7; §5.7 entity_map → Task 6; §5.8 switch voz → Task 8; §6-7 submodule layout → Task 1; §8 tópicos → Tasks 4+5+7+8. V2/V3/V4 explicitly OUT: suggester, feedback, histograma dia_semana, REST `/predictions`, embalagem B/addon, desejos §4.7 B/C/D (V2) e E (V4).

---

### Task 1: Predictor package scaffolding + schemas

**Files:**
- Create: `src/predictor/__init__.py`
- Create: `src/predictor/pyproject.toml`
- Create: `src/predictor/predictor/__init__.py`
- Create: `src/predictor/predictor/schemas.py`
- Test: `tests/test_predictor_schemas.py`

**Interfaces:**
- Consumes: nothing (new package).
- Produces: `src.predictor.predictor.schemas.EnrichedEvent` (dataclass, `to_dict() -> dict`), `Prediction` (dataclass, `to_dict() -> dict`), `ActuatorCommand` (dataclass, `to_dict() -> dict`), `validate_schema_version(payload: dict) -> bool`. Later tasks import these exact names.

- [ ] **Step 1: Write the failing test**

```python
from src.predictor.predictor.schemas import (
    EnrichedEvent, Prediction, ActuatorCommand, validate_schema_version,
)


def test_enriched_event_to_dict_has_schema_version_1():
    e = EnrichedEvent(camera="rosa", camera_id="2", zone="rosa",
                      zone_classification="seguranca", event_type="motion_detected")
    d = e.to_dict()
    assert d["schema_version"] == 1
    assert d["camera"] == "rosa"
    assert "thumbnail_path" not in d


def test_prediction_to_dict_never_has_thumbnail():
    p = Prediction(camera="rosa", zone="rosa", janela="19:00-20:00",
                   evento_previsto="pessoa", probabilidade=0.82,
                   confianca_modelo=0.71, modelo="ewma-7d", amostras=142)
    d = p.to_dict()
    assert d["schema_version"] == 1
    assert d["probabilidade"] == 0.82
    assert "thumbnail" not in str(d)


def test_actuator_command_to_dict():
    c = ActuatorCommand(action="turn_on", camera="rosa", zone="rosa",
                        event_type="motion_detected",
                        target_entity="switch.aspersor_rosa", duration_sec=300,
                        alarm_mode="armed_home",
                        motivo="pessoa na rosa + alarme armado (base 7 dias, 142 amostras)")
    d = c.to_dict()
    assert d["target_entity"] == "switch.aspersor_rosa"
    assert d["duration_sec"] == 300
    assert d["motivo"] == "pessoa na rosa + alarme armado (base 7 dias, 142 amostras)"


def test_validate_schema_version_rejects_unknown():
    assert validate_schema_version({"schema_version": 1}) is True
    assert validate_schema_version({"schema_version": 999}) is False
    assert validate_schema_version({}) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_predictor_schemas.py -v`
Expected: FAIL with "No module named 'src.predictor.predictor'" (package does not exist yet).

- [ ] **Step 3: Write minimal implementation**

`src/predictor/__init__.py`:
```python
"""tucuxi-predictor seed package (embalagem A in-process; extract to submodule later)."""
```

`src/predictor/pyproject.toml`:
```toml
[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "tucuxi-predictor"
version = "0.1.0"
description = "Preditor EWMA para Tucuxi (submodule futuro)."
requires-python = ">=3.11"
dependencies = ["paho-mqtt"]

[tool.setuptools.packages.find]
include = ["predictor*"]
```

`src/predictor/predictor/__init__.py`:
```python
"""Public interface: Predictor pieces used by Tucuxi embalagem A."""
from .schemas import EnrichedEvent, Prediction, ActuatorCommand, validate_schema_version

__all__ = ["EnrichedEvent", "Prediction", "ActuatorCommand", "validate_schema_version"]
```

`src/predictor/predictor/schemas.py`:
```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import uuid

SCHEMA_VERSION = 1


def validate_schema_version(payload: dict) -> bool:
    return isinstance(payload, dict) and payload.get("schema_version") == SCHEMA_VERSION


def _now_local_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass
class EnrichedEvent:
    camera: str
    camera_id: str
    zone: str
    zone_classification: str
    event_type: str
    evento: str = "pessoa"
    probabilidade: float = 0.0
    timestamp: str = field(default_factory=_now_local_iso)
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "camera": self.camera,
            "camera_id": self.camera_id,
            "zone": self.zone,
            "zone_classification": self.zone_classification,
            "evento": self.evento,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "probabilidade": self.probabilidade,
            "event_id": self.event_id,
        }


@dataclass
class Prediction:
    camera: str
    zone: str
    janela: str
    evento_previsto: str
    probabilidade: float
    confianca_modelo: float
    modelo: str
    amostras: int
    threshold_sugestao: float = 0.75
    gerado_em: str = field(default_factory=_now_local_iso)
    expira_em: str = ""

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "camera": self.camera,
            "zone": self.zone,
            "janela": self.janela,
            "evento_previsto": self.evento_previsto,
            "probabilidade": self.probabilidade,
            "confianca_modelo": self.confianca_modelo,
            "modelo": self.modelo,
            "gerado_em": self.gerado_em,
            "expira_em": self.expira_em,
            "amostras": self.amostras,
            "threshold_sugestao": self.threshold_sugestao,
        }


@dataclass
class ActuatorCommand:
    action: str
    camera: str
    zone: str
    event_type: str
    target_entity: str
    duration_sec: int
    alarm_mode: str
    motivo: str = ""
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: str = field(default_factory=_now_local_iso)

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "action": self.action,
            "camera": self.camera,
            "zone": self.zone,
            "event_type": self.event_type,
            "target_entity": self.target_entity,
            "duration_sec": self.duration_sec,
            "condition": {"alarm_mode": self.alarm_mode},
            "motivo": self.motivo,
            "event_id": self.event_id,
            "timestamp": self.timestamp,
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_predictor_schemas.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/predictor tests/test_predictor_schemas.py
git commit -m "feat: scaffold tucuxi-predictor package with schemas v1"
```

---

### Task 2: EWMA model (hour-of-day only)

**Files:**
- Create: `src/predictor/predictor/ewma.py`
- Test: `tests/test_predictor_ewma.py`

**Interfaces:**
- Consumes: ` Prediction` type name only for `modelo="ewma-7d"` string convention.
- Produces: `src.predictor.predictor.ewma.EWMAModel` with `__init__(alpha: float = 0.3)`, `update(bucket: int, count: int) -> float`, `predict(bucket: int) -> float`, `to_histogram() -> dict[int, float]`. Task 8 loop calls `update`/`predict`.

- [ ] **Step 1: Write the failing test**

```python
from src.predictor.predictor.ewma import EWMAModel


def test_predict_unknown_bucket_returns_zero():
    m = EWMAModel(alpha=0.3)
    assert m.predict(19) == 0.0


def test_update_converges_toward_repeated_count():
    m = EWMAModel(alpha=0.5)
    m.update(19, 0)
    v1 = m.update(19, 10)
    v2 = m.update(19, 10)
    assert v1 == 5.0
    assert v2 == 7.5
    assert m.predict(19) == 7.5


def test_buckets_are_independent():
    m = EWMAModel(alpha=0.5)
    m.update(19, 10)
    assert m.predict(3) == 0.0
    assert m.to_histogram() == {19: 5.0}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_predictor_ewma.py -v`
Expected: FAIL with "No module named 'src.predictor.predictor.ewma'".

- [ ] **Step 3: Write minimal implementation**

`src/predictor/predictor/ewma.py`:
```python
from __future__ import annotations


class EWMAModel:
    """EWMA per hour-bucket (0-23). O(1) per event; MVP uses hour-of-day only."""

    def __init__(self, alpha: float = 0.3):
        if not 0.0 < alpha <= 1.0:
            raise ValueError("alpha must be in (0, 1]")
        self.alpha = alpha
        self._values: dict[int, float] = {}

    def update(self, bucket: int, count: int) -> float:
        prev = self._values.get(bucket, 0.0)
        value = self.alpha * float(count) + (1.0 - self.alpha) * prev
        self._values[bucket] = value
        return value

    def predict(self, bucket: int) -> float:
        return self._values.get(bucket, 0.0)

    def to_histogram(self) -> dict[int, float]:
        return dict(self._values)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_predictor_ewma.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/predictor/predictor/ewma.py tests/test_predictor_ewma.py
git commit -m "feat: add EWMA hour-bucket model"
```

---

### Task 3: SQLite store (counts per hour bucket)

**Files:**
- Create: `src/predictor/predictor/store.py`
- Test: `tests/test_predictor_store.py`

**Interfaces:**
- Consumes: `events` table columns `camera_id TEXT`, `timestamp TEXT` (ISO, from `src/storage.py:40-54`).
- Produces: `src.predictor.predictor.store.PredictorStore` with `__init__(db_path)`, `count_by_bucket(camera_slug: str, days: int = 7) -> dict[int, int]`, `total_events(camera_slug: str, days: int = 7) -> int`. Task 8 loop calls `count_by_bucket`.

- [ ] **Step 1: Write the failing test**

```python
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from src.predictor.predictor.store import PredictorStore


def _seed(tmp_path: Path) -> Path:
    db = tmp_path / "events.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, camera_id TEXT NOT NULL, zone TEXT, event_type TEXT NOT NULL, details TEXT, level INTEGER DEFAULT 0, dropped INTEGER DEFAULT 0, source TEXT DEFAULT 'local', disposition TEXT)")
    now = datetime.now().astimezone()
    for i in range(3):
        ts = (now.replace(hour=19, minute=5) - timedelta(days=i)).isoformat(timespec="seconds")
        con.execute("INSERT INTO events (timestamp, camera_id, event_type) VALUES (?, ?, ?)", (ts, "rosa", "motion_detected"))
    old = (now - timedelta(days=30)).isoformat(timespec="seconds")
    con.execute("INSERT INTO events (timestamp, camera_id, event_type) VALUES (?, ?, ?)", (old, "rosa", "motion_detected"))
    con.execute("INSERT INTO events (timestamp, camera_id, event_type) VALUES (?, ?, ?)", (now.isoformat(timespec="seconds"), "portao", "motion_detected"))
    con.commit()
    con.close()
    return db


def test_count_by_bucket_filters_camera_and_window(tmp_path):
    store = PredictorStore(_seed(tmp_path))
    buckets = store.count_by_bucket("rosa", days=7)
    assert buckets == {19: 3}
    assert store.total_events("rosa", days=7) == 3


def test_unknown_camera_returns_empty(tmp_path):
    store = PredictorStore(_seed(tmp_path))
    assert store.count_by_bucket("inexistente", days=7) == {}
    assert store.total_events("inexistente", days=7) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_predictor_store.py -v`
Expected: FAIL with "No module named 'src.predictor.predictor.store'".

- [ ] **Step 3: Write minimal implementation**

`src/predictor/predictor/store.py`:
```python
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path


class PredictorStore:
    """Read-only aggregates over the Tucuxi `events` table."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    def _since_iso(self, days: int) -> str:
        since = datetime.now().astimezone() - timedelta(days=days)
        return since.isoformat(timespec="seconds")

    def count_by_bucket(self, camera_slug: str, days: int = 7) -> dict[int, int]:
        con = sqlite3.connect(str(self.db_path))
        try:
            cur = con.execute(
                "SELECT timestamp FROM events WHERE camera_id = ? AND timestamp >= ?",
                (camera_slug, self._since_iso(days)),
            )
            buckets: dict[int, int] = {}
            for (ts,) in cur.fetchall():
                try:
                    hour = datetime.fromisoformat(ts).hour
                except ValueError:
                    continue
                buckets[hour] = buckets.get(hour, 0) + 1
            return buckets
        finally:
            con.close()

    def total_events(self, camera_slug: str, days: int = 7) -> int:
        return sum(self.count_by_bucket(camera_slug, days).values())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_predictor_store.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/predictor/predictor/store.py tests/test_predictor_store.py
git commit -m "feat: add predictor SQLite hour-bucket store"
```

---

### Task 4: Enriched event + dual MQTT publish

**Files:**
- Modify: `src/alerts.py` (append `to_enriched_event` + `publish_enriched_event`, call from `mqtt_handler`)
- Test: `tests/test_predictor_event.py`

**Interfaces:**
- Consumes: `EnrichedEvent` from Task 1; handler `payload` dict from `AlertService.send` (`src/alerts.py:26`).
- Produces: `src.alerts.to_enriched_event(payload: dict) -> dict`, `src.alerts.publish_enriched_event(enriched: dict) -> None` publishing to `tucuxi/camera/{slug}/event` (retain=false, QoS 0). Legacy `MQTT_TOPIC` publish untouched.

- [ ] **Step 1: Write the failing test**

```python
from src import alerts


def test_to_enriched_event_maps_payload():
    payload = {"camera_id": "2", "zone": "rosa", "event_type": "motion_detected",
               "zone_classification": "seguranca", "details": "pessoa",
               "thumbnail_path": "data/thumbnails/x.jpg"}
    d = alerts.to_enriched_event(payload, camera_slug="rosa")
    assert d["schema_version"] == 1
    assert d["camera"] == "rosa"
    assert d["camera_id"] == "2"
    assert d["event_type"] == "motion_detected"
    assert "thumbnail_path" not in d


def test_publish_enriched_event_uses_slug_topic(monkeypatch):
    calls = {}
    monkeypatch.setattr(alerts.publish, "single",
                        lambda topic, payload, **kw: calls.setdefault("t", []).append((topic, payload, kw)))
    alerts.publish_enriched_event({"schema_version": 1, "camera": "rosa"})
    topic, payload, kw = calls["t"][0]
    assert topic == "tucuxi/camera/rosa/event"
    assert kw.get("retain") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_predictor_event.py -v`
Expected: FAIL with "has no attribute 'to_enriched_event'".

- [ ] **Step 3: Write minimal implementation**

Append to `src/alerts.py` (after `mqtt_handler`, before siren section):
```python
def to_enriched_event(payload: Dict, camera_slug: str = None) -> Dict:
    from .predictor.predictor.schemas import EnrichedEvent
    slug = camera_slug or str(payload.get("zone") or payload.get("camera_id", "0"))
    return EnrichedEvent(
        camera=slug,
        camera_id=str(payload.get("camera_id", "0")),
        zone=str(payload.get("zone") or slug),
        zone_classification=str(payload.get("zone_classification") or "publica"),
        event_type=str(payload.get("event_type") or "motion_detected"),
        evento=str(payload.get("details") or payload.get("evento") or "pessoa"),
        probabilidade=float(payload.get("probabilidade") or 0.0),
    ).to_dict()


def publish_enriched_event(enriched: Dict) -> None:
    broker = os.getenv("MQTT_BROKER_URL", "192.168.1.12")
    port = int(os.getenv("MQTT_BROKER_PORT", "1883"))
    username = os.getenv("MQTT_USERNAME", "kzuca")
    password = os.getenv("MQTT_PASSWORD", "123")
    if not broker:
        logger.debug("Enriched event skipped: MQTT_BROKER_URL not configured")
        return
    topic = f"tucuxi/camera/{enriched.get('camera', 'unknown')}/event"
    publish.single(topic, json.dumps(enriched),
                   hostname=broker, port=port,
                   auth={"username": username, "password": password},
                   retain=False, qos=0)
```

And inside `mqtt_handler`, after the legacy publish block succeeds (same try scope), add:
```python
    try:
        publish_enriched_event(to_enriched_event(payload))
    except Exception:
        logger.exception("Enriched event publish failed")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_predictor_event.py tests/test_alerts.py -v`
Expected: PASS (all pass, no regression in legacy handler).

- [ ] **Step 5: Commit**

```bash
git add src/alerts.py tests/test_predictor_event.py
git commit -m "feat: dual-publish tucuxi/camera/+/event v1"
```

---

### Task 5: Prediction publisher + HA discovery

**Files:**
- Create: `src/predictor/predictor/publisher.py`
- Test: `tests/test_predictor_publisher.py`

**Interfaces:**
- Consumes: `Prediction` from Task 1; `PREDICTOR_INTERVAL_SECONDS` default 900 for `expire_after`.
- Produces: `src.predictor.predictor.publisher.build_prediction_payload(camera, zone, janela, evento_previsto, probabilidade, confianca_modelo, amostras, expira_em) -> dict`, `publish_prediction(broker, port, auth, slug, payload) -> None` (retain=true, QoS 0), `build_discovery_config(slug, expire_after_sec=1800) -> dict` for `homeassistant/sensor/tucuxi_{slug}_prediction/config`.

- [ ] **Step 1: Write the failing test**

```python
from src.predictor.predictor.publisher import (
    build_prediction_payload, build_discovery_config, publish_prediction,
)


def test_build_prediction_payload_shape():
    d = build_prediction_payload("rosa", "rosa", "19:00-20:00", "pessoa", 0.82, 0.71, 142, "2026-09-06T20:00:00-03:00")
    assert d["schema_version"] == 1
    assert d["modelo"] == "ewma-7d"
    assert d["threshold_sugestao"] == 0.75
    assert "thumbnail" not in str(d)


def test_build_discovery_config_points_to_state_topic():
    cfg = build_discovery_config("rosa")
    assert cfg["state_topic"] == "tucuxi/predictions/rosa"
    assert cfg["value_template"] == "{{ value_json.probabilidade }}"
    assert cfg["expire_after"] == 1800
    assert cfg["unique_id"] == "tucuxi_rosa_prediction"


def test_publish_prediction_retain_true(monkeypatch):
    calls = []
    import src.predictor.predictor.publisher as pub
    monkeypatch.setattr(pub.publish, "single",
                        lambda topic, payload, **kw: calls.append((topic, kw)))
    pub.publish_prediction("127.0.0.1", 1883, None, "rosa", {"schema_version": 1})
    assert calls[0][0] == "tucuxi/predictions/rosa"
    assert calls[0][1].get("retain") is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_predictor_publisher.py -v`
Expected: FAIL with "No module named 'src.predictor.predictor.publisher'".

- [ ] **Step 3: Write minimal implementation**

`src/predictor/predictor/publisher.py`:
```python
from __future__ import annotations

import json
import paho.mqtt.publish as publish

from .schemas import Prediction


def build_prediction_payload(camera: str, zone: str, janela: str, evento_previsto: str,
                             probabilidade: float, confianca_modelo: float,
                             amostras: int, expira_em: str) -> dict:
    return Prediction(
        camera=camera, zone=zone, janela=janela, evento_previsto=evento_previsto,
        probabilidade=probabilidade, confianca_modelo=confianca_modelo,
        modelo="ewma-7d", amostras=amostras, expira_em=expira_em,
    ).to_dict()


def publish_prediction(broker: str, port: int, auth: dict | None, slug: str, payload: dict) -> None:
    publish.single(f"tucuxi/predictions/{slug}", json.dumps(payload),
                   hostname=broker, port=port, auth=auth, retain=True, qos=0)


def build_discovery_config(slug: str, expire_after_sec: int = 1800) -> dict:
    return {
        "name": f"Tucuxi {slug} Predicao",
        "state_topic": f"tucuxi/predictions/{slug}",
        "value_template": "{{ value_json.probabilidade }}",
        "unit_of_measurement": "%",
        "json_attributes_topic": f"tucuxi/predictions/{slug}",
        "expire_after": expire_after_sec,
        "unique_id": f"tucuxi_{slug}_prediction",
    }


def publish_discovery(broker: str, port: int, auth: dict | None, slug: str,
                      expire_after_sec: int = 1800) -> None:
    publish.single(f"homeassistant/sensor/tucuxi_{slug}_prediction/config",
                   json.dumps(build_discovery_config(slug, expire_after_sec)),
                   hostname=broker, port=port, auth=auth, retain=True, qos=0)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_predictor_publisher.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/predictor/predictor/publisher.py tests/test_predictor_publisher.py
git commit -m "feat: add prediction publisher and HA discovery"
```

---

### Task 6: Config flags + entity_map with rosa MVP entries

**Files:**
- Modify: `src/config.py` (append `PREDICTOR_*` block)
- Create: `src/predictor/predictor/entity_map.py`
- Test: `tests/test_predictor_config_map.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `src.config.PREDICTOR_ENABLED: bool`, `PREDICTOR_HISTORY_DAYS=7`, `PREDICTOR_INTERVAL_SECONDS=900`, `PREDICTION_THRESHOLD=0.75`, `PREDICTOR_DETER_COOLDOWN_SEC=900`, `PREDICTOR_ENTITY_MAP_JSON=""`; `src.predictor.predictor.entity_map.DEFAULT_ENTITY_MAP: dict` (keys `rosa`, `acesso_jardim` alias, `portao_entrada`), `load_entity_map(raw_json: str) -> dict`, `resolve_zone(slug: str, entity_map: dict) -> dict | None` (alias-aware).

- [ ] **Step 1: Write the failing test**

```python
from src.predictor.predictor import entity_map as em


def test_default_map_has_rosa_and_alias():
    assert em.DEFAULT_ENTITY_MAP["rosa"]["ha_actuator"] == "switch.aspersor_rosa"
    assert em.DEFAULT_ENTITY_MAP["rosa"]["default_duration_sec"] == 300
    assert em.resolve_zone("acesso_jardim", em.DEFAULT_ENTITY_MAP)["ha_actuator"] == "switch.aspersor_rosa"


def test_l1_portao_needs_no_alarm():
    entry = em.resolve_zone("portao_entrada", em.DEFAULT_ENTITY_MAP)
    assert entry["alarm_required"] is False
    assert entry["ha_actuator"] == "light.perimetral"


def test_load_entity_map_overrides_default():
    raw = '{"rosa": {"ha_actuator": "switch.outro", "default_duration_sec": 60, "alarm_required": true, "modos_ativos": ["viagem"]}}'
    merged = em.load_entity_map(raw)
    assert merged["rosa"]["ha_actuator"] == "switch.outro"
    assert merged["portao_entrada"]["ha_actuator"] == "light.perimetral"


def test_config_defaults(monkeypatch):
    import importlib, src.config as cfg
    monkeypatch.delenv("PREDICTOR_ENABLED", raising=False)
    importlib.reload(cfg)
    assert cfg.PREDICTOR_ENABLED is False
    assert cfg.PREDICTOR_HISTORY_DAYS == 7
    assert cfg.PREDICTOR_INTERVAL_SECONDS == 900
    assert cfg.PREDICTION_THRESHOLD == 0.75
    assert cfg.PREDICTOR_DETER_COOLDOWN_SEC == 900
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_predictor_config_map.py -v`
Expected: FAIL with "No module named 'src.predictor.predictor.entity_map'".

- [ ] **Step 3: Write minimal implementation**

Append to `src/config.py`:
```python
# Preditor Tucuxi (MVP embalagem A): desabilitado por padrao; sem dependencia nova.
PREDICTOR_ENABLED = os.getenv("PREDICTOR_ENABLED", "false").lower() in ("1", "true", "yes", "on")
PREDICTOR_HISTORY_DAYS = int(os.getenv("PREDICTOR_HISTORY_DAYS", "7"))
PREDICTOR_INTERVAL_SECONDS = int(os.getenv("PREDICTOR_INTERVAL_SECONDS", "900"))
PREDICTION_THRESHOLD = float(os.getenv("PREDICTION_THRESHOLD", "0.75"))
PREDICTOR_DETER_COOLDOWN_SEC = int(os.getenv("PREDICTOR_DETER_COOLDOWN_SEC", "900"))
PREDICTOR_ENTITY_MAP_JSON = os.getenv("PREDICTOR_ENTITY_MAP", "")
```

`src/predictor/predictor/entity_map.py`:
```python
from __future__ import annotations

import copy
import json

DEFAULT_ENTITY_MAP: dict = {
    "rosa": {
        "camera_id": 2,
        "alias_of": None,
        "layer": "L2_seguranca",
        "ha_sensor": "binary_sensor.presenca_rosa",
        "ha_actuator": "switch.aspersor_rosa",
        "default_duration_sec": 300,
        "alarm_required": True,
        "modos_ativos": ["armed_home", "armed_away"],
        "cooldown_sec": 900,
    },
    "acesso_jardim": {
        "camera_id": 2,
        "alias_of": "rosa",
        "layer": "L2_seguranca",
        "ha_sensor": "binary_sensor.presenca_rosa",
        "ha_actuator": "switch.aspersor_rosa",
        "default_duration_sec": 300,
        "alarm_required": True,
        "modos_ativos": ["armed_home", "armed_away"],
        "cooldown_sec": 900,
    },
    "portao_entrada": {
        "camera_id": 1,
        "alias_of": None,
        "layer": "L1_perimetro",
        "ha_sensor": "binary_sensor.pir_portao",
        "ha_actuator": "light.perimetral",
        "default_duration_sec": 600,
        "alarm_required": False,
        "modos_ativos": ["armed_home", "armed_away"],
        "cooldown_sec": 600,
    },
}


def load_entity_map(raw_json: str = "") -> dict:
    merged = copy.deepcopy(DEFAULT_ENTITY_MAP)
    if raw_json:
        override = json.loads(raw_json)
        for slug, entry in override.items():
            merged.setdefault(slug, {}).update(entry)
    return merged


def resolve_zone(slug: str, entity_map: dict) -> dict | None:
    entry = entity_map.get(slug)
    if entry is None:
        return None
    if entry.get("alias_of"):
        return entity_map.get(entry["alias_of"])
    return entry
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_predictor_config_map.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/config.py src/predictor/predictor/entity_map.py tests/test_predictor_config_map.py
git commit -m "feat: add predictor config flags and rosa entity map"
```

---

### Task 7: ha_client (alarm_mode + fail-secure) + actuator decision + publish

**Files:**
- Create: `src/predictor/predictor/ha_client.py`
- Create: `src/predictor/predictor/actuator.py`
- Test: `tests/test_predictor_actuator.py`

**Interfaces:**
- Consumes: `resolve_zone` (Task 6), `ActuatorCommand` (Task 1), `validate_schema_version` (Task 1).
- Produces: `ha_client.parse_alarm_mode(payload: dict) -> str | None`, `ha_client.is_stale(timestamp_iso: str, now_ts: float, max_age_sec: int = 60) -> bool`, `ha_client.FAIL_SECURE_MODE = "armed_home"`; `actuator.decide_action(slug, alarm_mode, event_type, entity_map, inhibitors, last_trigger_ts, now_ts) -> dict | None`, `actuator.publish_actuator(broker, port, auth, command: dict) -> None` (topic `tucuxi/automation/actuator`, retain=false, QoS 0).

- [ ] **Step 1: Write the failing test**

```python
from src.predictor.predictor import actuator, ha_client
from src.predictor.predictor.entity_map import DEFAULT_ENTITY_MAP


def test_armed_rosa_motion_returns_aspersor_command():
    cmd = actuator.decide_action("rosa", "armed_home", "motion_detected",
                                 DEFAULT_ENTITY_MAP, {}, None, 1000.0,
                                 motivo="pessoa na rosa + alarme armado")
    assert cmd is not None
    assert cmd["target_entity"] == "switch.aspersor_rosa"
    assert cmd["duration_sec"] == 300
    assert cmd["condition"] == {"alarm_mode": "armed_home"}
    assert cmd["motivo"] == "pessoa na rosa + alarme armado"


def test_disarmed_suppresses_alarm_required():
    cmd = actuator.decide_action("rosa", "disarmed", "motion_detected",
                                 DEFAULT_ENTITY_MAP, {}, None, 1000.0)
    assert cmd is None


def test_l1_portao_fires_without_alarm_but_still_needs_armed_or_away():
    assert actuator.decide_action("portao_entrada", "armed_home", "motion_detected",
                                  DEFAULT_ENTITY_MAP, {}, None, 1000.0) is not None
    assert actuator.decide_action("portao_entrada", "disarmed", "motion_detected",
                                  DEFAULT_ENTITY_MAP, {}, None, 1000.0) is None


def test_inhibitors_block_action():
    cmd = actuator.decide_action("rosa", "armed_home", "motion_detected",
                                 DEFAULT_ENTITY_MAP,
                                 {"chuva": True}, None, 1000.0)
    assert cmd is None
    cmd2 = actuator.decide_action("rosa", "armed_home", "motion_detected",
                                  DEFAULT_ENTITY_MAP,
                                  {"identidade_conhecida": True}, None, 1000.0)
    assert cmd2 is None


def test_cooldown_blocks_repeat():
    cmd = actuator.decide_action("rosa", "armed_home", "motion_detected",
                                 DEFAULT_ENTITY_MAP, {}, 500.0, 1000.0)
    assert cmd is None


def test_fail_secure_parsing_and_stale():
    assert ha_client.parse_alarm_mode({"alarm_mode": "armed_away"}) == "armed_away"
    assert ha_client.parse_alarm_mode({"alarm_mode": "invalido"}) is None
    assert ha_client.parse_alarm_mode({"schema_version": 999, "alarm_mode": "armed_home"}) is None
    assert ha_client.FAIL_SECURE_MODE == "armed_home"
    assert ha_client.is_stale("2026-09-06T18:00:00-03:00", 9999999999.0) is True


def test_publish_actuator_topic(monkeypatch):
    calls = []
    import src.predictor.predictor.actuator as act
    monkeypatch.setattr(act.publish, "single",
                        lambda topic, payload, **kw: calls.append((topic, kw)))
    act.publish_actuator("127.0.0.1", 1883, None, {"schema_version": 1})
    assert calls[0][0] == "tucuxi/automation/actuator"
    assert calls[0][1].get("retain") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_predictor_actuator.py -v`
Expected: FAIL with "No module named 'src.predictor.predictor.ha_client'" (or actuator).

- [ ] **Step 3: Write minimal implementation**

`src/predictor/predictor/ha_client.py`:
```python
from __future__ import annotations

import time
from datetime import datetime

from .schemas import validate_schema_version

VALID_MODES = ("disarmed", "armed_home", "armed_away")
FAIL_SECURE_MODE = "armed_home"
STALE_AFTER_SEC = 60


def parse_alarm_mode(payload: dict) -> str | None:
    if not validate_schema_version(payload):
        if "alarm_mode" not in payload:
            return None
    mode = payload.get("alarm_mode")
    return mode if mode in VALID_MODES else None


def is_stale(timestamp_iso: str, now_ts: float | None = None, max_age_sec: int = STALE_AFTER_SEC) -> bool:
    try:
        ts = datetime.fromisoformat(timestamp_iso).timestamp()
    except (ValueError, TypeError):
        return True
    now = time.time() if now_ts is None else now_ts
    return (now - ts) > max_age_sec
```

`src/predictor/predictor/actuator.py`:
```python
from __future__ import annotations

import json
import paho.mqtt.publish as publish

from .entity_map import resolve_zone
from .schemas import ActuatorCommand

ARMED_MODES = ("armed_home", "armed_away")


def decide_action(slug: str, alarm_mode: str, event_type: str, entity_map: dict,
                  inhibitors: dict | None = None,
                  last_trigger_ts: float | None = None,
                  now_ts: float = 0.0, motivo: str = "") -> dict | None:
    entry = resolve_zone(slug, entity_map)
    if entry is None:
        return None
    if alarm_mode not in entry.get("modos_ativos", list(ARMED_MODES)):
        return None
    if entry.get("alarm_required") and alarm_mode not in ARMED_MODES:
        return None
    inhibitors = inhibitors or {}
    if inhibitors.get("chuva") or inhibitors.get("identidade_conhecida"):
        return None
    cooldown = int(entry.get("cooldown_sec", 900))
    if last_trigger_ts is not None and (now_ts - last_trigger_ts) < cooldown:
        return None
    return ActuatorCommand(
        action="turn_on",
        camera=slug,
        zone=slug,
        event_type=event_type,
        target_entity=entry["ha_actuator"],
        duration_sec=int(entry.get("default_duration_sec", 300)),
        alarm_mode=alarm_mode,
        motivo=motivo,
    ).to_dict()


def publish_actuator(broker: str, port: int, auth: dict | None, command: dict) -> None:
    publish.single("tucuxi/automation/actuator", json.dumps(command),
                   hostname=broker, port=port, auth=auth, retain=False, qos=0)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_predictor_actuator.py -v`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add src/predictor/predictor/ha_client.py src/predictor/predictor/actuator.py tests/test_predictor_actuator.py
git commit -m "feat: add alarm_mode fail-secure and actuator decision"
```

---

### Task 8: Predictor loop wiring (queue → EWMA → publish every 15 min)

**Files:**
- Create: `src/predictor/predictor/loop.py`
- Modify: `src/main.py` (wire loop when `PREDICTOR_ENABLED=true`; minimal: subscribe `LocalEventQueue` + threaded ticker)
- Test: `tests/test_predictor_loop.py`

**Interfaces:**
- Consumes: `EWMAModel` (Task 2), `PredictorStore` (Task 3), `build_prediction_payload` + `publish_prediction` (Task 5), `decide_action` + `publish_actuator` (Task 7), `parse_alarm_mode` + `is_stale` + `FAIL_SECURE_MODE` (Task 7), `LocalEventQueue.subscribe` (`src/events.py:56`), `PREDICTOR_*` (`src/config.py`).
- Produces: `loop.PredictorLoop` with `on_event(event) -> dict | None` (returns actuator command when fired), `tick(now_hour: int) -> list[dict]` (returns prediction payloads, one per tracked slug), `set_alarm_mode(mode: str, timestamp_iso: str) -> None`. `src/main.py` starts loop only if `PREDICTOR_ENABLED`.

- [ ] **Step 1: Write the failing test**

```python
from src.predictor.predictor.loop import PredictorLoop


def test_on_event_armed_rosa_fires_actuator():
    loop = PredictorLoop(broker="x", port=1883, auth=None, publish=False)
    loop.set_alarm_mode("armed_home", "2026-09-06T19:00:00-03:00")

    class E:
        camera_id = "rosa"
        zone = "rosa"
        event_type = "motion_detected"
    cmd = loop.on_event(E(), now_ts=1000.0)
    assert cmd["target_entity"] == "switch.aspersor_rosa"
    assert "rosa" in cmd["motivo"] and "armed_home" in cmd["motivo"]


def test_on_event_disarmed_returns_none():
    loop = PredictorLoop(broker="x", port=1883, auth=None, publish=False)
    loop.set_alarm_mode("disarmed", "2026-09-06T19:00:00-03:00")

    class E:
        camera_id = "rosa"
        zone = "rosa"
        event_type = "motion_detected"
    assert loop.on_event(E(), now_ts=1000.0) is None


def test_tick_returns_prediction_per_slug():
    loop = PredictorLoop(broker="x", port=1883, auth=None, publish=False)
    loop.ingest_count("rosa", 19, 6)
    payloads = loop.tick(now_hour=19)
    assert len(payloads) == 1
    assert payloads[0]["camera"] == "rosa"
    assert payloads[0]["janela"] == "19:00-20:00"
    assert payloads[0]["modelo"] == "ewma-7d"


def test_stale_alarm_mode_falls_back_to_armed():
    loop = PredictorLoop(broker="x", port=1883, auth=None, publish=False)
    loop.set_alarm_mode("disarmed", "2020-01-01T00:00:00-03:00")
    assert loop.effective_mode(now_ts=9999999999.0) == "armed_home"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_predictor_loop.py -v`
Expected: FAIL with "No module named 'src.predictor.predictor.loop'".

- [ ] **Step 3: Write minimal implementation**

`src/predictor/predictor/loop.py`:
```python
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta

from . import ha_client
from .actuator import decide_action, publish_actuator
from .entity_map import DEFAULT_ENTITY_MAP, load_entity_map
from .ewma import EWMAModel
from .publisher import build_prediction_payload, publish_prediction


class PredictorLoop:
    """Embalagem A: in-process, fed by LocalEventQueue + periodic tick."""

    def __init__(self, broker: str, port: int, auth: dict | None,
                 entity_map: dict | None = None, publish: bool = True):
        raw = os.getenv("PREDICTOR_ENTITY_MAP", "")
        self.entity_map = entity_map if entity_map is not None else load_entity_map(raw)
        self.models: dict[str, EWMAModel] = {s: EWMAModel() for s in self.entity_map}
        self.samples: dict[str, int] = {s: 0 for s in self.entity_map}
        self.last_trigger: dict[str, float] = {}
        self.broker = broker
        self.port = port
        self.auth = auth
        self.publish = publish
        self.alarm_mode = ha_client.FAIL_SECURE_MODE
        self.alarm_ts = ""

    def set_alarm_mode(self, mode: str, timestamp_iso: str) -> None:
        if mode in ha_client.VALID_MODES:
            self.alarm_mode = mode
            self.alarm_ts = timestamp_iso

    def effective_mode(self, now_ts: float | None = None) -> str:
        now = time.time() if now_ts is None else now_ts
        if self.alarm_ts and ha_client.is_stale(self.alarm_ts, now):
            return ha_client.FAIL_SECURE_MODE
        return self.alarm_mode

    def ingest_count(self, slug: str, hour: int, count: int) -> None:
        if slug in self.models:
            self.models[slug].update(hour, count)
            self.samples[slug] += count

    def on_event(self, event, now_ts: float | None = None) -> dict | None:
        now = time.time() if now_ts is None else now_ts
        slug = str(getattr(event, "zone", None) or getattr(event, "camera_id", ""))
        if slug in self.models:
            try:
                hour = datetime.now().astimezone().hour
                self.models[slug].update(hour, 1)
                self.samples[slug] += 1
            except Exception:
                pass
        mode = self.effective_mode(now)
        event_label = str(getattr(event, "event_type", "motion_detected"))
        history_days = os.getenv("PREDICTOR_HISTORY_DAYS", "7")
        motivo = (f"{event_label} em {slug} + modo {mode} "
                  f"({self.samples.get(slug, 0)} eventos em {history_days} dias)")
        cmd = decide_action(slug, mode, event_label,
                            self.entity_map, {}, self.last_trigger.get(slug), now,
                            motivo=motivo)
        if cmd is None:
            return None
        self.last_trigger[slug] = now
        if self.publish:
            publish_actuator(self.broker, self.port, self.auth, cmd)
        return cmd

    def tick(self, now_hour: int) -> list[dict]:
        payloads = []
        for slug, model in self.models.items():
            prob = round(min(1.0, model.predict(now_hour) / 10.0), 3)
            janela = f"{now_hour:02d}:00-{(now_hour + 1) % 24:02d}:00"
            expira = (datetime.now().astimezone().replace(minute=0, second=0, microsecond=0)
                      + timedelta(hours=1)).isoformat(timespec="seconds")
            payload = build_prediction_payload(slug, slug, janela, "pessoa", prob, 0.5,
                                               self.samples.get(slug, 0), expira)
            payloads.append(payload)
            if self.publish:
                publish_prediction(self.broker, self.port, self.auth, slug, payload)
        return payloads
```

`src/main.py` wiring (exact anchor: after `event_bus.subscribe(alert_engine.handle)` + `event_bus.start()` at lines 706-707 — insert before the `# Register device with HA` block at line 709):
```python
# Preditor MVP (embalagem A): gated by PREDICTOR_ENABLED, O(1) per event.
from .config import PREDICTOR_ENABLED, PREDICTOR_INTERVAL_SECONDS
if PREDICTOR_ENABLED:
    from .predictor.predictor.loop import PredictorLoop
    from .config import MQTT_BROKER_URL, MQTT_BROKER_PORT, MQTT_USERNAME, MQTT_PASSWORD
    _predictor = PredictorLoop(MQTT_BROKER_URL, MQTT_BROKER_PORT,
                               {"username": MQTT_USERNAME, "password": MQTT_PASSWORD})
    event_bus.subscribe(_predictor.on_event)

    def _predictor_ticker():
        import threading
        from datetime import datetime as _dt
        while True:
            try:
                _predictor.tick(_dt.now().astimezone().hour)
            except Exception:
                pass
            threading.Event().wait(PREDICTOR_INTERVAL_SECONDS)

    import threading as _th
    _th.Thread(target=_predictor_ticker, daemon=True).start()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_predictor_loop.py -v`
Expected: PASS (4 passed). Then regression: `python -m pytest tests/test_events.py tests/test_alerts.py -v` PASS.

- [ ] **Step 5: Commit**

```bash
git add src/predictor/predictor/loop.py src/main.py tests/test_predictor_loop.py
git commit -m "feat: wire predictor loop to event queue with 15min tick"
```

---

### Task 9: HA pack (sensors + voice switches + rosa automation)

**Files:**
- Create: `hass/tucuxi_mvp.yaml`
- Test: `tests/test_predictor_hass_pack.py` (YAML structural check, no HA instance needed)

**Interfaces:**
- Consumes: topics from Tasks 5+7+8 (`tucuxi/predictions/rosa`, `tucuxi/automation/actuator`, `tucuxi/mode/alarme|viagem/set|state`, `tucuxi/ha/alarm_mode`).
- Produces: `hass/tucuxi_mvp.yaml` — paste-ready HA package: 2 `mqtt.sensor` (rosa, portao_entrada), 2 `mqtt.switch` voice (alarme, viagem), 3 automations (mode sync alarme, mode sync viagem, rosa→aspersor with `delay` + `mode: single`).

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path
import yaml


def test_hass_pack_has_sensors_switches_automations():
    text = Path("hass/tucuxi_mvp.yaml").read_text(encoding="utf-8")
    pack = yaml.safe_load(text)
    sensor_topics = [s["state_topic"] for s in pack["mqtt"]["sensor"]]
    assert "tucuxi/predictions/rosa" in sensor_topics
    switch_topics = [s["command_topic"] for s in pack["mqtt"]["switch"]]
    assert "tucuxi/mode/alarme/set" in switch_topics
    assert "tucuxi/mode/viagem/set" in switch_topics
    aliases = [a["alias"] for a in pack["automation"]]
    assert any("aspersor" in a for a in aliases)
    rosa_auto = next(a for a in pack["automation"] if "aspersor" in a)
    assert rosa_auto["mode"] == "single"
    assert "tucuxi/automation/actuator" in str(rosa_auto["trigger"])
    assert "motivo" in str(rosa_auto["action"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_predictor_hass_pack.py -v`
Expected: FAIL with "hass/tucuxi_mvp.yaml" not found (or yaml module — if `pyyaml` missing, `pip install pyyaml` first and note it in this step).

- [ ] **Step 3: Write minimal implementation**

`hass/tucuxi_mvp.yaml`:
```yaml
mqtt:
  sensor:
    - name: "Tucuxi Rosa Predicao"
      unique_id: "tucuxi_rosa_prediction"
      state_topic: "tucuxi/predictions/rosa"
      value_template: "{{ value_json.probabilidade }}"
      unit_of_measurement: "%"
      json_attributes_topic: "tucuxi/predictions/rosa"
      expire_after: 1800
    - name: "Tucuxi Portao Predicao"
      unique_id: "tucuxi_portao_entrada_prediction"
      state_topic: "tucuxi/predictions/portao_entrada"
      value_template: "{{ value_json.probabilidade }}"
      unit_of_measurement: "%"
      json_attributes_topic: "tucuxi/predictions/portao_entrada"
      expire_after: 1800
  switch:
    - name: "Tucuxi Alarme"
      unique_id: "tucuxi_alarme"
      command_topic: "tucuxi/mode/alarme/set"
      state_topic: "tucuxi/mode/alarme/state"
      payload_on: "ON"
      payload_off: "OFF"
      icon: "mdi:shield"
    - name: "Tucuxi Viagem"
      unique_id: "tucuxi_viagem"
      command_topic: "tucuxi/mode/viagem/set"
      state_topic: "tucuxi/mode/viagem/state"
      payload_on: "ON"
      payload_off: "OFF"
      icon: "mdi:airplane"

automation:
  - alias: "Tucuxi switch alarme -> alarm panel"
    mode: single
    trigger:
      - platform: mqtt
        topic: tucuxi/mode/alarme/set
    action:
      - choose:
          - conditions: "{{ trigger.payload == 'ON' }}"
            sequence:
              - service: alarm_control_panel.alarm_arm_home
                target: { entity_id: alarm_control_panel.tucuxi }
              - service: mqtt.publish
                data: { topic: tucuxi/ha/alarm_mode, retain: true,
                        payload: '{"schema_version": 1, "alarm_mode": "armed_home", "modo_tucuxi": "alarme_armado"}' }
        default:
          - service: alarm_control_panel.alarm_disarm
            target: { entity_id: alarm_control_panel.tucuxi }
          - service: mqtt.publish
            data: { topic: tucuxi/ha/alarm_mode, retain: true,
                    payload: '{"schema_version": 1, "alarm_mode": "disarmed", "modo_tucuxi": "alarme_desarmado"}' }

  - alias: "Tucuxi switch viagem -> armed_away"
    mode: single
    trigger:
      - platform: mqtt
        topic: tucuxi/mode/viagem/set
    action:
      - choose:
          - conditions: "{{ trigger.payload == 'ON' }}"
            sequence:
              - service: alarm_control_panel.alarm_arm_away
                target: { entity_id: alarm_control_panel.tucuxi }
              - service: mqtt.publish
                data: { topic: tucuxi/ha/alarm_mode, retain: true,
                        payload: '{"schema_version": 1, "alarm_mode": "armed_away", "modo_tucuxi": "viagem"}' }
        default:
          - service: mqtt.publish
            data: { topic: tucuxi/mode/viagem/state, retain: true, payload: "OFF" }

  - alias: "Tucuxi rosa -> aspersor 5min (armado)"
    mode: single
    trigger:
      - platform: mqtt
        topic: tucuxi/automation/actuator
    condition:
      - condition: template
        value_template: "{{ trigger.payload_json.target_entity == 'switch.aspersor_rosa' }}"
      - condition: state
        entity_id: alarm_control_panel.tucuxi
        state: ["armed_home", "armed_away"]
    action:
      - service: switch.turn_on
        target: { entity_id: "{{ trigger.payload_json.target_entity }}" }
      - service: persistent_notification.create
        data:
          title: "Tucuxi dissuasão"
          message: "{{ trigger.payload_json.motivo }}"
          notification_id: "tucuxi_rosa_{{ trigger.payload_json.event_id }}"
      - delay: "{{ trigger.payload_json.duration_sec }}"
      - service: switch.turn_off
        target: { entity_id: "{{ trigger.payload_json.target_entity }}" }
```

If `pyyaml` is not installed, add it: append `pyyaml` to `requirements.txt` in this task (test-only dependency, also useful for future `entity_map` YAML).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_predictor_hass_pack.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add hass/tucuxi_mvp.yaml requirements.txt tests/test_predictor_hass_pack.py
git commit -m "feat: add HA MVP pack with rosa automation and voice switches"
```

---

### Task 10: E2E integration test (evento rosa armado → atuador) + docs touch

**Files:**
- Test: `tests/test_predictor_e2e.py`
- Modify: `docs/roadmap.md` (append MVP predictor row) — doc-only, no code.

**Interfaces:**
- Consumes: all Tasks 1-8 public names.
- Produces: regression-proof E2E: enriched event → loop.on_event → actuator command for rosa when armed; silence when disarmed; prediction tick shape stable.

- [ ] **Step 1: Write the failing test**

```python
from src import alerts
from src.predictor.predictor.loop import PredictorLoop
from src.predictor.predictor.schemas import validate_schema_version


def test_e2e_rosa_armed_fires_aspersor():
    loop = PredictorLoop(broker="x", port=1883, auth=None, publish=False)
    loop.set_alarm_mode("armed_home", "2026-09-06T19:00:00-03:00")
    payload = {"camera_id": "2", "zone": "rosa", "event_type": "motion_detected",
               "zone_classification": "seguranca", "details": "pessoa"}

    class E:
        camera_id = "rosa"
        zone = "rosa"
        event_type = "motion_detected"

    enriched = alerts.to_enriched_event(payload)
    assert validate_schema_version(enriched)
    cmd = loop.on_event(E(), now_ts=2000.0)
    assert validate_schema_version(cmd)
    assert cmd["target_entity"] == "switch.aspersor_rosa"
    assert cmd["duration_sec"] == 300
    assert "rosa" in cmd["motivo"]


def test_e2e_disarmed_silence_and_tick_shape():
    loop = PredictorLoop(broker="x", port=1883, auth=None, publish=False)
    loop.set_alarm_mode("disarmed", "2026-09-06T19:00:00-03:00")

    class E:
        camera_id = "rosa"
        zone = "rosa"
        event_type = "motion_detected"

    assert loop.on_event(E(), now_ts=2000.0) is None
    payloads = loop.tick(now_hour=19)
    by_cam = {p["camera"]: p for p in payloads}
    assert set(by_cam) == {"rosa", "acesso_jardim", "portao_entrada"}
    assert all(validate_schema_version(p) for p in payloads)
    assert all("thumbnail" not in str(p) for p in payloads)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_predictor_e2e.py -v`
Expected: FAIL (loop module from Task 8 missing if tasks run out of order; within sequence, FAIL only if wiring regressed — either way red before green after touching docs/code in this task).

- [ ] **Step 3: Write minimal implementation**

No new source code (E2E proves existing wiring). Doc touch in `docs/roadmap.md` — append:

```markdown
## Preditor Tucuxi (MVP, 2026-09-06)
- Embalagem A in-process (`src/predictor/`, flag `PREDICTOR_ENABLED=false` default).
- Evento enriquecido `tucuxi/camera/+/event` + predição `tucuxi/predictions/+` + `tucuxi/automation/actuator`.
- HA pack em `hass/tucuxi_mvp.yaml` (sensores, switches de voz, automação rosa→aspersor 5min).
- V2+: suggester/feedback, histograma dia_semana, REST `/predictions`, embalagem B/addon (mesma lib).
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_predictor_e2e.py tests/test_predictor_schemas.py tests/test_predictor_ewma.py tests/test_predictor_store.py tests/test_predictor_event.py tests/test_predictor_publisher.py tests/test_predictor_config_map.py tests/test_predictor_actuator.py tests/test_predictor_loop.py tests/test_predictor_hass_pack.py -v`
Expected: PASS (full predictor suite green). Then full suite: `python -m pytest tests/ -x -q` — must be green before commit.

- [ ] **Step 5: Commit**

```bash
git add tests/test_predictor_e2e.py docs/roadmap.md
git commit -m "test: add predictor e2e and roadmap entry"
```
