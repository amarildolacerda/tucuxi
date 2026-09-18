# Perfis de Sensibilidade: Nível "Padrão" + Seletor no Cadastro da Câmera — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Substituir o modo "Personalizado" (sliders) pelo perfil "Padrão" (usa `.env`) e adicionar o seletor de sensibilidade ao formulário de cadastro/edição de câmera, além de mantê-lo em Configurações.

**Architecture:** Refatora o nível `CUSTOM` → `DEFAULT` em `src/sensitivity.py`, `src/storage.py` e `src/app.py`. O seletor (4 botões: Baixa/Média/Alta/Padrão) é renderizado no `cameras.html` com wiring em `cameras.js`; `settings.js` perde todo o código de sliders. Backend enxuto, sem migração de schema.

**Tech Stack:** Python 3, Flask, SQLite, JavaScript (ES modules), CSS variables do style guide (`var(--primary)`, `var(--surface)`, etc.).

## Global Constraints

- Rodar testes com `py -3.14 -m pytest` (Windows). Não usar `pytest` direto.
- Níveis válidos da API: `low | medium | high | default` (o nível `default` significa "usa `.env`").
- A coluna `custom_params` da tabela `camera_sensitivity` é **mantida** no schema, mas nunca mais é usada; o código deixa de lê-la/escrevê-la.
- Linhas legadas com `level='custom'` viram `default` na leitura.
- Não mudar `GET /api/sensitivity/presets` (retorna só os 3 presets).
- `get_camera_sensitivity` sem registro retorna `{"level": "default", "configured": False}`.
- `set_camera_sensitivity(camera_id, "default")` **deleta** a linha da tabela.
- Antes de mexer em HTML/CSS, seguir o style guide (`.opencode/skills/style/SKILL.md`): usar CSS variables, nunca cores fixas. Remover CSS morto sem arrastar regras usadas por outras seções.
- Commits: pequenos, mensagem `feat:`/`test:`/`refactor:`/`fix:` conforme o conteúdo, em português ou inglês como no histórico.

---

### Task 1: Backend — storage retorna `default` e suporta delete

**Files:**
- Modify: `src/storage.py:1339-1372`

**Interfaces:**
- Consumes: nada novo (usa `self.lock`, `self.connection`, tabela `camera_sensitivity`).
- Produces:
  - `get_camera_sensitivity(camera_id) -> {"level": str, "configured": bool}` — nível em `{low,medium,high,default}`; sem registro ou nível legado → `{"level": "default", "configured": False}`; registro válido → `{"level": row["level"], "configured": True}` (sem `custom_params` no retorno).
  - `set_camera_sensitivity(camera_id, level)` — virou delete se `level == "default"`; caso contrário upsert gravando `custom_params = NULL`.

- [ ] **Step 1: Escrever os testes falhando** (adicione no fim de `tests/test_sensitivity.py`, substituindo os antigos de custom):

```python
def test_get_sensitivity_unconfigured_returns_default(tmp_path):
    storage = _storage(tmp_path)
    result = storage.get_camera_sensitivity(1)
    assert result["level"] == "default"
    assert result["configured"] is False


def test_set_level_default_clears_record(tmp_path):
    storage = _storage(tmp_path)
    storage.seed_cameras([{"name": "Test", "source": "rtsp://test", "zone": "test"}])
    camera = storage.list_cameras()[0]
    storage.set_camera_sensitivity(camera["id"], "high")
    assert storage.get_camera_sensitivity(camera["id"])["configured"] is True
    storage.set_camera_sensitivity(camera["id"], "default")
    result = storage.get_camera_sensitivity(camera["id"])
    assert result["configured"] is False
    assert result["level"] == "default"


def test_get_sensitivity_legacy_custom_treated_as_default(tmp_path):
    storage = _storage(tmp_path)
    storage.seed_cameras([{"name": "Test", "source": "rtsp://test", "zone": "test"}])
    camera = storage.list_cameras()[0]
    with storage.lock:
        cur = storage.connection.cursor()
        cur.execute(
            "INSERT INTO camera_sensitivity (camera_id, level, custom_params, updated_at) VALUES (?, 'custom', NULL, ?)",
            (camera["id"], "2026-09-11T00:00:00+00:00"),
        )
        storage.connection.commit()
    result = storage.get_camera_sensitivity(camera["id"])
    assert result["level"] == "default"
    assert result["configured"] is False
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `py -3.14 -m pytest tests/test_sensitivity.py -q`
Expected: 3 falhas (nível `medium` ainda retornado, sem delete, sem tratamento legado).

- [ ] **Step 3: Implementar** — substitua `get_camera_sensitivity` e `set_camera_sensitivity` em `src/storage.py:1339-1372`:

```python
    VALID_SENSITIVITY_LEVELS = {"low", "medium", "high", "default"}

    def get_camera_sensitivity(self, camera_id):
        """Retorna sensitivity config para uma câmera.

        ``configured`` é True quando existe registro válido (low/medium/high);
        quando False (sem registro, ou nível legado tipo 'custom'), o nível é
        ``default`` e os parâmetros efetivos vêm de config.py/.env.
        """
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute("SELECT level, custom_params FROM camera_sensitivity WHERE camera_id = ?", (camera_id,))
            row = cursor.fetchone()
        if row is None or row["level"] not in self.VALID_SENSITIVITY_LEVELS:
            return {"level": "default", "configured": False}
        return {"level": row["level"], "configured": True}

    def set_camera_sensitivity(self, camera_id, level):
        """Define sensitivity level para uma câmera.

        ``level == "default"`` remove o registro (a câmera passa a usar os
        valores de config.py/.env). Outros níveis fazem upsert.
        """
        from datetime import datetime, timezone
        if level == "default":
            with self.lock:
                self.connection.execute("DELETE FROM camera_sensitivity WHERE camera_id = ?", (camera_id,))
                self.connection.commit()
            return
        now = datetime.now(timezone.utc).isoformat()
        with self.lock:
            cursor = self.connection.cursor()
            cursor.execute(
                "INSERT INTO camera_sensitivity (camera_id, level, custom_params, updated_at) VALUES (?, ?, NULL, ?) "
                "ON CONFLICT(camera_id) DO UPDATE SET level = excluded.level, custom_params = NULL, updated_at = excluded.updated_at",
                (camera_id, level, now),
            )
            self.connection.commit()
```

- [ ] **Step 4: Rodar e ver passar**

Run: `py -3.14 -m pytest tests/test_sensitivity.py -q`
Expected: novos testes passam; os testes antigos de `custom`/`medium`-fallback ainda falham (vão ser reescritos na Task 2).

- [ ] **Step 5: Commit**

```bash
git add src/storage.py tests/test_sensitivity.py
git commit -m "feat(sensitivity): storage returns default level and clears record on default"
```

---

### Task 2: Backend — `sensitivity.py` remove CUSTOM, adiciona DEFAULT

**Files:**
- Modify: `src/sensitivity.py` (todo o arquivo)

**Interfaces:**
- Consumes: `CONFIG_DEFAULT_PARAMS` de `sensitivity.py` (já existe); `storage.get_camera_sensitivity`/`set_camera_sensitivity` da Task 1.
- Produces:
  - `SensitivityLevel` com `LOW/MEDIUM/HIGH/DEFAULT = "default"` (sem `CUSTOM`).
  - `SENSITIVITY_PRESETS` (low/medium/high) e `CONFIG_DEFAULT_PARAMS` inalterados.
  - `get_effective_params(camera_id) -> dict` (default/desconfigurado → cópia de `CONFIG_DEFAULT_PARAMS`).
  - `set_level(camera_id, level) -> Optional[str]` (sem `custom_params`; retorna None ou mensagem de erro).
  - Remove `validate_custom_params` e `PARAM_RANGES`, e o import `Optional` se ficar sem uso.

- [ ] **Step 1: Reescrever testes** — reescreva `tests/test_sensitivity.py`. Remova `validate_custom_params` do import; remova `test_set_custom_params`, `test_get_effective_params_returns_custom`, `test_validate_custom_params_*`, `test_set_level_custom_without_params_returns_error`. Ajuste `test_get_sensitivity_returns_default` (agora espera `"default"`). Conteúdo final:

```python
# tests/test_sensitivity.py
import pytest
from src.storage import EventStorage
from src.sensitivity import SensitivityManager, SensitivityLevel, SENSITIVITY_PRESETS, CONFIG_DEFAULT_PARAMS
from src import config as config_module

DEFAULT_KEYS = {
    "motion_min_area",
    "motion_persist_frames",
    "detector_confidence",
    "detector_iou",
    "track_iou_threshold",
}


def _storage(tmp_path):
    return EventStorage(tmp_path / "events.db")


# ── Storage tests ──

def test_get_sensitivity_returns_default(tmp_path):
    storage = _storage(tmp_path)
    result = storage.get_camera_sensitivity(1)
    assert result["level"] == "default"
    assert result["configured"] is False


def test_get_sensitivity_unconfigured_returns_default(tmp_path):
    storage = _storage(tmp_path)
    result = storage.get_camera_sensitivity(1)
    assert result["level"] == "default"
    assert result["configured"] is False


def test_set_and_get_sensitivity(tmp_path):
    storage = _storage(tmp_path)
    storage.seed_cameras([{"name": "Test", "source": "rtsp://test", "zone": "test"}])
    camera = storage.list_cameras()[0]
    storage.set_camera_sensitivity(camera["id"], "high")
    result = storage.get_camera_sensitivity(camera["id"])
    assert result["level"] == "high"
    assert result["configured"] is True


def test_set_level_default_clears_record(tmp_path):
    storage = _storage(tmp_path)
    storage.seed_cameras([{"name": "Test", "source": "rtsp://test", "zone": "test"}])
    camera = storage.list_cameras()[0]
    storage.set_camera_sensitivity(camera["id"], "high")
    assert storage.get_camera_sensitivity(camera["id"])["configured"] is True
    storage.set_camera_sensitivity(camera["id"], "default")
    result = storage.get_camera_sensitivity(camera["id"])
    assert result["configured"] is False
    assert result["level"] == "default"


def test_get_sensitivity_legacy_custom_treated_as_default(tmp_path):
    storage = _storage(tmp_path)
    storage.seed_cameras([{"name": "Test", "source": "rtsp://test", "zone": "test"}])
    camera = storage.list_cameras()[0]
    with storage.lock:
        cur = storage.connection.cursor()
        cur.execute(
            "INSERT INTO camera_sensitivity (camera_id, level, custom_params, updated_at) VALUES (?, 'custom', NULL, ?)",
            (camera["id"], "2026-09-11T00:00:00+00:00"),
        )
        storage.connection.commit()
    result = storage.get_camera_sensitivity(camera["id"])
    assert result["level"] == "default"
    assert result["configured"] is False


# ── Sensitivity module tests ──

def test_presets_have_all_keys():
    for level in [SensitivityLevel.LOW, SensitivityLevel.MEDIUM, SensitivityLevel.HIGH]:
        assert DEFAULT_KEYS.issubset(SENSITIVITY_PRESETS[level].keys())


def test_config_default_params_match_env_config():
    expected = {
        "motion_min_area": config_module.MOTION_MIN_AREA,
        "motion_persist_frames": config_module.MOTION_PERSIST_FRAMES,
        "detector_confidence": config_module.DETECTOR_CONFIDENCE,
        "detector_iou": config_module.DETECTOR_IOU,
        "track_iou_threshold": config_module.TRACK_IOU_THRESHOLD,
    }
    assert CONFIG_DEFAULT_PARAMS == expected


def test_unconfigured_camera_falls_back_to_config(tmp_path):
    storage = _storage(tmp_path)
    storage.seed_cameras([{"name": "Test", "source": "rtsp://test", "zone": "test"}])
    camera = storage.list_cameras()[0]
    mgr = SensitivityManager(storage)
    params = mgr.get_effective_params(camera["id"])
    assert params == CONFIG_DEFAULT_PARAMS


def test_default_level_uses_config_params(tmp_path):
    storage = _storage(tmp_path)
    storage.seed_cameras([{"name": "Test", "source": "rtsp://test", "zone": "test"}])
    camera = storage.list_cameras()[0]
    storage.set_camera_sensitivity(camera["id"], "default")
    mgr = SensitivityManager(storage)
    params = mgr.get_effective_params(camera["id"])
    assert params == CONFIG_DEFAULT_PARAMS


def test_get_effective_params_returns_preset(tmp_path):
    storage = _storage(tmp_path)
    storage.seed_cameras([{"name": "Test", "source": "rtsp://test", "zone": "test"}])
    camera = storage.list_cameras()[0]
    storage.set_camera_sensitivity(camera["id"], "medium")
    mgr = SensitivityManager(storage)
    params = mgr.get_effective_params(camera["id"])
    assert params == SENSITIVITY_PRESETS[SensitivityLevel.MEDIUM]


def test_set_level_persists(tmp_path):
    storage = _storage(tmp_path)
    storage.seed_cameras([{"name": "Test", "source": "rtsp://test", "zone": "test"}])
    camera = storage.list_cameras()[0]
    mgr = SensitivityManager(storage)
    mgr.set_level(camera["id"], SensitivityLevel.HIGH)
    result = storage.get_camera_sensitivity(camera["id"])
    assert result["level"] == "high"


def test_set_level_default_applies_to_workers(tmp_path):
    storage = _storage(tmp_path)
    storage.seed_cameras([{"name": "Test", "source": "rtsp://test", "zone": "test"}])
    camera = storage.list_cameras()[0]
    storage.set_camera_sensitivity(camera["id"], "high")
    mgr = SensitivityManager(storage)
    mock_worker = MagicMock()
    mock_worker._motion_detector_ref = MagicMock()
    mock_worker.object_detector = MagicMock()
    mock_worker._tracker_ref = MagicMock()
    mgr.register_worker(camera["id"], mock_worker)
    mgr.set_level(camera["id"], "default")
    assert mock_worker._motion_detector_ref.min_area == CONFIG_DEFAULT_PARAMS["motion_min_area"]
```

Importante: `tmp_path` é uma fixture do pytest fornecida automaticamente, então o arquivo **não** precisa de `import pytest`. O único import de mock necessário é `MagicMock`. **Topo do arquivo:**

```python
from unittest.mock import MagicMock
from src.storage import EventStorage
from src.sensitivity import SensitivityManager, SensitivityLevel, SENSITIVITY_PRESETS, CONFIG_DEFAULT_PARAMS
from src import config as config_module
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `py -3.14 -m pytest tests/test_sensitivity.py -q`
Expected: falhas (`ValueError` de `SensitivityLevel("default")`/`"custom"` inexistentes, ou `MagicMock` não importado).

- [ ] **Step 3: Reescrever `src/sensitivity.py`** — remova `Optional` do import se ficar sem uso, remova `PARAM_RANGES`, `validate_custom_params`, o nível `CUSTOM`, e atualize `get_effective_params` e `set_level`:

```python
from enum import Enum

from .config import (
    DETECTOR_CONFIDENCE,
    DETECTOR_IOU,
    MOTION_MIN_AREA,
    MOTION_PERSIST_FRAMES,
    TRACK_IOU_THRESHOLD,
)

logger = logging.getLogger(__name__)

CONFIG_DEFAULT_PARAMS = {
    "motion_min_area": MOTION_MIN_AREA,
    "motion_persist_frames": MOTION_PERSIST_FRAMES,
    "detector_confidence": DETECTOR_CONFIDENCE,
    "detector_iou": DETECTOR_IOU,
    "track_iou_threshold": TRACK_IOU_THRESHOLD,
}


class SensitivityLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    DEFAULT = "default"


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


class SensitivityManager:
    """Gerencia perfis de sensibilidade per câmera."""

    def __init__(self, storage):
        self.storage = storage
        self._workers = {}

    def register_worker(self, camera_id, worker):
        self._workers[camera_id] = worker

    def unregister_worker(self, camera_id):
        self._workers.pop(camera_id, None)

    def get_effective_params(self, camera_id: int) -> dict:
        """Retorna parâmetros efetivos da câmera.

        Sem registro (ou nível ``default``) a câmera usa os valores do
        ambiente (config.py/.env) — preserva o comportamento atual.
        """
        config = self.storage.get_camera_sensitivity(camera_id)
        if not config.get("configured", True) or config["level"] == SensitivityLevel.DEFAULT:
            return dict(CONFIG_DEFAULT_PARAMS)
        preset_level = SensitivityLevel(config["level"])
        return dict(SENSITIVITY_PRESETS[preset_level])

    def set_level(self, camera_id: int, level: str):
        """Define o perfil da câmera. Persiste e aplica nos workers.

        ``default`` remove o registro; a câmera passa a usar config.py/.env.
        """
        level_enum = SensitivityLevel(level)
        self.storage.set_camera_sensitivity(camera_id, level_enum.value)
        params = self.get_effective_params(camera_id)
        self.apply_to_workers(camera_id, params)
        logger.info("Sensitivity for camera %s set to %s", camera_id, level)
        return None

    def apply_to_workers(self, camera_id: int, params: dict):
        worker = self._workers.get(camera_id)
        if worker is None:
            return
        md = getattr(worker, "_motion_detector_ref", None)
        if md is not None:
            md.min_area = params["motion_min_area"]
            md.persist_frames = params["motion_persist_frames"]
        od = getattr(worker, "object_detector", None)
        if od is not None:
            od.confidence_threshold = params["detector_confidence"]
            od.iou_threshold = params["detector_iou"]
        tr = getattr(worker, "_tracker_ref", None)
        if tr is not None:
            tr.iou_threshold = params["track_iou_threshold"]
        if md is None or tr is None:
            worker._pending_sensitivity = params
```

> Importante: manter `import logging` no topo (o arquivo original tem) e `import logging` em uso via `logger`.

- [ ] **Step 4: Rodar e ver passar**

Run: `py -3.14 -m pytest tests/test_sensitivity.py -q`
Expected: PASS (conteúdo da Task 1 + Task 2).

- [ ] **Step 5: Commit**

```bash
git add src/sensitivity.py tests/test_sensitivity.py
git commit -m "feat(sensitivity): replace custom level with default (.env) profile"
```

---

### Task 3: Backend — API REST aceita `default` e remove `custom`

**Files:**
- Modify: `src/app.py:278-322`

**Interfaces:**
- Consumes: `SensitivityManager`, `SensitivityLevel`, `storage.get_camera_sensitivity` da Task 1/2.
- Produces: resposta GET/PUT sem campo `custom_params`; `PUT` aceita `{low,medium,high,default}` e rejeita `custom` com `400`.

- [ ] **Step 1: Atualizar testes de integração** — em `tests/test_sensitivity_integration.py`:
  - Remover imports alterados se necessário.
  - `test_api_get_sensitivity`: trocar para validar `level == "default"` quando não configurado.
  - Substituir `test_api_set_sensitivity_custom` por `test_api_set_sensitivity_default`.
  - `test_api_set_sensitivity_custom_without_params` → remover (sem custom, `PUT {level:"invalid"}` já cobre 400; manter `test_api_set_sensitivity_invalid_level`).
  - Ajustar `test_api_set_sensitivity_high` para validar que resposta não tem `custom_params`.

  Conteúdo final (substitua das linhas 122 em diante):

```python
def test_api_get_sensitivity(client):
    resp = client.get("/api/cameras/1/sensitivity")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["level"] == "default"
    assert "effective_params" in data
    assert "custom_params" not in data


def test_api_set_sensitivity_high(client):
    resp = client.put("/api/cameras/1/sensitivity", json={"level": "high"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["level"] == "high"
    assert "custom_params" not in data


def test_api_set_sensitivity_default(client):
    client.put("/api/cameras/1/sensitivity", json={"level": "high"})
    resp = client.put("/api/cameras/1/sensitivity", json={"level": "default"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["level"] == "default"
    assert data["effective_params"] == CONFIG_DEFAULT_PARAMS


def test_api_set_sensitivity_invalid_level(client):
    resp = client.put("/api/cameras/1/sensitivity", json={"level": "invalid"})
    assert resp.status_code == 400


def test_api_set_sensitivity_custom_rejected(client):
    resp = client.put("/api/cameras/1/sensitivity", json={"level": "custom"})
    assert resp.status_code == 400


def test_api_presets(client):
    resp = client.get("/api/sensitivity/presets")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "low" in data
    assert "medium" in data
    assert "high" in data
    assert "default" not in data
```

  Garanta que o import `CONFIG_DEFAULT_PARAMS` já está no topo do arquivo de teste (está, linha 5).

- [ ] **Step 2: Rodar e ver falhar**

Run: `py -3.14 -m pytest tests/test_sensitivity_integration.py -q`
Expected: falhas (API ainda retorna `custom_params`, aceita `custom`).

- [ ] **Step 3: Atualizar `src/app.py`** — substitua os dois handlers (linhas 278-322):

```python
    @app.route("/api/cameras/<int:camera_id>/sensitivity", methods=["GET"])
    @require_permission("view_cameras")
    def api_camera_sensitivity_get(camera_id):
        """Get sensitivity config for a camera."""
        from .sensitivity import SensitivityManager, SensitivityLevel
        mgr = SensitivityManager(storage)
        params = mgr.get_effective_params(camera_id)
        config = storage.get_camera_sensitivity(camera_id)
        return jsonify({
            "camera_id": camera_id,
            "level": config["level"],
            "effective_params": params,
        })

    @app.route("/api/cameras/<int:camera_id>/sensitivity", methods=["PUT"])
    @require_permission("edit_cameras")
    def api_camera_sensitivity_set(camera_id):
        """Set sensitivity level for a camera."""
        from .sensitivity import SensitivityManager, SensitivityLevel
        data = request.get_json(silent=True) or {}
        level = data.get("level")
        if level not in [l.value for l in SensitivityLevel]:
            return jsonify({"error": "Nível inválido. Use: low, medium, high, default"}), 400
        mgr = SensitivityManager(storage)
        error = mgr.set_level(camera_id, level)
        if error:
            return jsonify({"error": error}), 400
        config = storage.get_camera_sensitivity(camera_id)
        params = mgr.get_effective_params(camera_id)
        return jsonify({
            "camera_id": camera_id,
            "level": config["level"],
            "effective_params": params,
        })
```

- [ ] **Step 4: Rodar e ver passar**

Run: `py -3.14 -m pytest tests/test_sensitivity_integration.py tests/test_sensitivity.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/app.py tests/test_sensitivity_integration.py
git commit -m "feat(sensitivity): API accepts default level, drops custom"
```

---

### Task 4: UI — remover sliders de `settings.js` e atualizar perfis

**Files:**
- Modify: `src/static/sections/settings.js:157-301`

**Interfaces:**
- Consumes: nada novo (usa `fetch` nos endpoints da Task 3, `LEVEL_LABELS`/`LEVEL_DESCS`).
- Produces: `renderSensitivityConfig()` renderiza, por câmera, 4 botões (`default`/`low`/`medium`/`high`) + descrição; sem sliders; `selectLevel` faz só `PUT {level}`. Mantém `initSection`/`teardownSection` intactos.

- [ ] **Step 1: Atualizar o JS** — no arquivo `src/static/sections/settings.js`:

  1. Remova o bloco `SLIDER_DEFS` (linhas 164-170).
  2. Atualize `LEVEL_LABELS` e `LEVEL_DESCS` (linhas 157-163) para:

```js
const LEVEL_LABELS = { default: 'Padrão', low: 'Baixa', medium: 'Média', high: 'Alta' };
const LEVEL_DESCS = {
  default: 'Usa a configuração geral do sistema (.env).',
  low: 'Menos alertas. Ideal para áreas movimentadas.',
  medium: 'Equilibrado. Padrão para uso geral.',
  high: 'Mais alertas. Ideal para perímetros críticos.',
};
```

  3. Substitua `renderSensitivityConfig()` (linhas 172-264) pelo conteúdo abaixo (sem sliders, sem fetch de presets):

```js
async function renderSensitivityConfig() {
  const container = document.getElementById('sensitivity-config');
  if (!container) return;
  try {
    const resp = await fetch('/api/cameras');
    const list = await resp.json();
    if (!list.length) {
      container.textContent = 'Nenhuma câmera configurada.';
      return;
    }
    container.innerHTML = '';
    const section = document.createElement('div');
    section.className = 'sensitivity-section';

    for (const cam of list) {
      const camDiv = document.createElement('div');
      camDiv.className = 'config-module-group sensitivity-camera-group';

      const h4 = document.createElement('h4');
      h4.textContent = cam.name;
      camDiv.appendChild(h4);

      const currentResp = await fetch(`/api/cameras/${cam.id}/sensitivity`);
      const current = await currentResp.json();

      const selector = document.createElement('div');
      selector.className = 'sensitivity-selector';
      for (const [val, label] of Object.entries(LEVEL_LABELS)) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'button-mini sensitivity-btn' + (current.level === val ? ' active' : '');
        btn.textContent = label;
        btn.title = LEVEL_DESCS[val];
        btn.addEventListener('click', () => selectLevel(cam.id, val, camDiv));
        selector.appendChild(btn);
      }
      camDiv.appendChild(selector);

      const desc = document.createElement('p');
      desc.className = 'sensitivity-desc';
      desc.textContent = LEVEL_DESCS[current.level] || '';
      camDiv.appendChild(desc);

      section.appendChild(camDiv);
    }

    container.appendChild(section);
  } catch (e) {
    container.textContent = 'Falha ao carregar sensibilidade.';
  }
}
```

  4. Substitua `selectLevel()` (linhas 266-283) e remova `saveCustom()` (linhas 285-301) por:

```js
async function selectLevel(cameraId, level, camDiv) {
  camDiv.querySelectorAll('.sensitivity-btn').forEach(btn => {
    btn.classList.toggle('active', btn.textContent === LEVEL_LABELS[level]);
  });
  const desc = camDiv.querySelector('.sensitivity-desc');
  if (desc) desc.textContent = LEVEL_DESCS[level] || '';
  const resp = await fetch(`/api/cameras/${cameraId}/sensitivity`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ level }),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    showMenuMessage(err.error || 'Erro ao salvar sensibilidade', 'camera-form-message');
  } else {
    showMenuMessage('Sensibilidade salva', 'camera-form-message');
  }
}
```

- [ ] **Step 2: Remover CSS morto** — em `src/static/style.css` remova as linhas 2144-2148:

```css
.sensitivity-sliders { display: flex; flex-direction: column; gap: 0.75rem; }
.slider-row { display: flex; align-items: center; gap: 0.5rem; }
.slider-row label { flex: 0 0 200px; font-size: 0.85rem; }
.slider-row input[type="range"] { flex: 1; }
.slider-row .slider-value { flex: 0 0 60px; text-align: right; font-size: 0.85rem; }
```

- [ ] **Step 3: Verificar**

Run: `py -3.14 -m pytest tests -q`
Expected: nenhuma falha relacionada a settings; só as 4 pré-existentes (docker/mqtt).

- [ ] **Step 4: Commit**

```bash
git add src/static/sections/settings.js src/static/style.css
git commit -m "refactor(sensitivity): remove custom sliders, add default profile to settings UI"
```

---

### Task 5: UI — seletor de sensibilidade no formulário da câmera

**Files:**
- Modify: `src/templates/sections/cameras.html` (form, após a linha 48 — depois do campo Zona)
- Modify: `src/static/sections/cameras.js`

**Interfaces:**
- Consumes: endpoints `GET/PUT /api/sensitivity`/`/api/cameras/<id>/sensitivity` da Task 3.
- Produces:
  - Em `cameras.js`: estado `selectedSensitivityLevel` (default `'default'`), função `initCameraSensitivity(camera)` (marca botão ativo; no edit faz `GET`), e no submit após salvar a câmera, faz `PUT /api/cameras/<id>/sensitivity` com `{level}` (inclusive `default` para limpar).

- [ ] **Step 1: Adicionar o bloco HTML** — em `src/templates/sections/cameras.html`, após o `</div>` do campo Zona (linha 48) e antes do campo `camera-alert-classes` (linha 49):

```html
            <div class="form-row">
                <span class="form-label" id="camera-sensitivity-label">Sensibilidade</span>
                <div id="camera-sensitivity" class="sensitivity-selector">
                    <button type="button" class="button-mini sensitivity-btn active" data-sensitivity-level="default">Padrão</button>
                    <button type="button" class="button-mini sensitivity-btn" data-sensitivity-level="low">Baixa</button>
                    <button type="button" class="button-mini sensitivity-btn" data-sensitivity-level="medium">Média</button>
                    <button type="button" class="button-mini sensitivity-btn" data-sensitivity-level="high">Alta</button>
                </div>
                <p id="camera-sensitivity-desc" class="sensitivity-desc">Usa a configuração geral do sistema (.env).</p>
            </div>
```

> Padrão do formulário é `default`. A ordem visual: Padrão, Baixa, Média, Alta (independe da ordem do objeto em settings.js).

- [ ] **Step 2: Wiring em `cameras.js`** — do seguinte modo:

  1. Adicione uma variável de estado perto do topo (junto de `cameraEditId`):

```js
let selectedSensitivityLevel = 'default';
```

  2. Adicione esta função (coloque antes de `submitCameraForm`):

```js
function initCameraSensitivity(currentLevel = 'default') {
  selectedSensitivityLevel = currentLevel;
  document.querySelectorAll('#camera-sensitivity .sensitivity-btn').forEach(btn => {
    const active = btn.dataset.sensitivityLevel === currentLevel;
    btn.classList.toggle('active', active);
  });
  const desc = document.getElementById('camera-sensitivity-desc');
  if (desc) {
    const descriptions = {
      default: 'Usa a configuração geral do sistema (.env).',
      low: 'Menos alertas. Ideal para áreas movimentadas.',
      medium: 'Equilibrado. Padrão para uso geral.',
      high: 'Mais alertas. Ideal para perímetros críticos.',
    };
    desc.textContent = descriptions[currentLevel] || '';
  }
}

function bindSensitivityButtons() {
  document.querySelectorAll('#camera-sensitivity .sensitivity-btn').forEach(btn => {
    btn.addEventListener('click', () => initCameraSensitivity(btn.dataset.sensitivityLevel));
  });
}
```

  3. No `setCameraFormMode` (linha ~626): no ramo `edit`, após popular os inputs, dispare o carregamento assíncrono; no ramo `add`, resete para `default`:

```js
  if (mode === 'edit' && camera) {
    fetch(`/api/cameras/${camera.id}/sensitivity`)
      .then(r => r.json())
      .then(data => initCameraSensitivity(data.level || 'default'))
      .catch(() => initCameraSensitivity('default'));
  } else {
    initCameraSensitivity('default');
  }
```

  > `setCameraFormMode` é chamado por `showCameraForm` (add/edit) e por `hideCameraForm` (`mode='add'`). Não chame `bindSensitivityButtons` aqui — o dialog persiste no DOM e os listeners seriam duplicados a cada abertura.

  4. Vincule os botões **uma única vez** em `setupCameraForm()` (linhas ~944-975), que roda a cada `initSection`, junto com os demais listeners do formulário:

```js
function setupCameraForm() {
  const form = document.getElementById('camera-form');
  if (form) form.addEventListener('submit', submitCameraForm);
  bindSensitivityButtons();
  ...
```

  > Como o teardown comenta "lista recriada a cada initSection" via innerHTML, e o dialog é re-renderizado junto, `bindSensitivityButtons` dentro de `setupCameraForm` evita listeners acumulados.

  4. No `submitCameraForm` (linha ~754), dentro do `try`, após `if (!response.ok) { ... return; }` e antes de `hideCameraForm()`, salve a sensibilidade:

```js
    const saved = await response.json();
    const camId = cameraEditId || saved.id;
    if (camId && selectedSensitivityLevel !== 'default') {
      await fetch(`/api/cameras/${camId}/sensitivity`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ level: selectedSensitivityLevel }),
      });
    }
```

  > No edit, se o usuário escolheu `default`, o registro deve ser limpo (caso a câmera tinha outro perfil). Por isso, envie sempre (inclusive `default`, idempotente via DELETE na Task 1).

```js
    const saved = await response.json();
    const camId = cameraEditId || saved.id;
    if (camId) {
      await fetch(`/api/cameras/${camId}/sensitivity`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ level: selectedSensitivityLevel }),
      });
    }
```

- [ ] **Step 3: Teste de renderização** — adicione em `tests/test_app.py` (junto a `test_settings_section_renders_sensitivity_config`):

```python
def test_camera_form_section_renders_sensitivity(client):
    response = client.get("/section/cameras")
    assert response.status_code == 200
    assert b"camera-sensitivity" in response.data
    assert b'data-sensitivity-level="default"' in response.data
```

- [ ] **Step 4: Rodar e ver passar**

Run: `py -3.14 -m pytest tests/test_app.py::test_settings_section_renders_sensitivity_config tests/test_app.py::test_camera_form_section_renders_sensitivity tests/test_sensitivity.py tests/test_sensitivity_integration.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/templates/sections/cameras.html src/static/sections/cameras.js tests/test_app.py
git commit -m "feat(sensitivity): add per-profile selector to camera add/edit form"
```

---

### Task 6: Documentação — SPEC.md e README.md

**Files:**
- Modify: `SPEC.md`, `README.md`

**Interfaces:**
- Consumes: nada (docs).

- [ ] **Step 1: Atualizar referências** — localize em `SPEC.md` e `README.md` qualquer menção a "Personalizado", "modo custom", "sliders" ou "4 opções" na seção de sensibilidade, e ajuste para:

> Configuração de sensibilidade por câmera com perfis **Baixa**, **Média**, **Alta** e **Padrão** (usa a configuração geral do `.env`), configurável no cadastro da câmera e em Configurações.

- [ ] **Step 2: Verificar** — rode `git diff` nos dois arquivos e confira se as citações antigas sumiram.

- [ ] **Step 3: Commit**

```bash
git add SPEC.md README.md
git commit -m "docs(sensitivity): update docs for default profile and camera form selector"
```

---

### Task 7: Verificação final e pull request

**Files:**
- Nenhum novo.

- [ ] **Step 1: Rodar a suíte completa**

Run: `py -3.14 -m pytest tests -q`
Expected: 4 falhas pré-existentes apenas (docker do host + 2 do mqtt discovery). Nenhuma nova.

- [ ] **Step 2: Revisar diff**

Run: `git diff main...HEAD` e confira que:
- `custom_params` não aparece em nenhuma resposta de API nem em `settings.js`.
- `CUSTOM` / `validate_custom_params` / `PARAM_RANGES` não existem mais em `src/`.
- `default` é aceito nos 3 lugares (storage, manager, API) e renderizado nos 2 UIs.

- [ ] **Step 3: Integrar via PR**

```bash
git checkout dev
git merge --no-ff <branch-de-trabalho>
# criar PR para main, manter dev como branch de integração (AGENTS.md)
```