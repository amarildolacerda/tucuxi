# Deduplicação por cena estável — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminar imagens quase-idênticas no grid de eventos e reduzir armazenamento, suprimindo eventos de baixo-valor em cena estável e salvando thumbnail truthful no `no_motion`.

**Architecture:** Adiciona um estado "representante de cena" por câmera no `CameraWorker` (`src/main.py`) e usa `frames_similar` (já existente) com uma janela de tempo para decidir se a cena mudou. Thumbnails e eventos de baixo-valor (`snapshot_info`/`motion_detected`) são suprimidos quando a cena não muda; eventos de segurança (identidade/intruso/queda/loitering/direção) e `no_motion` nunca são suprimidos. Sem mudança de schema ou novas dependências.

**Tech Stack:** Python 3, OpenCV (cv2), pytest, SQLite (storage existente).

## Global Constraints

- Não criar eventos em `main` (apenas produz; decisão N2–N4 é do `AlertRuleEngine`).
- Eventos de segurança (identidade/intruso/queda/loitering/direção) NUNCA são suprimidos.
- Reusar `frames_similar` e `THUMBNAIL_DIFF_THRESHOLD` (sem nova dependência de hash).
- `motion_reported` deve continuar `True` após movimento detectado, mesmo que o evento de baixo-valor seja suprimido (para não quebrar o gatilho de `no_motion`).
- Commits frequentes, um por task. Branch alvo: `dev`.
- Não alterar detector de movimento, retenção/prune, nem grid no cliente.

---

### Task 1: Config — janela de dedup

**Files:**
- Modify: `src/config.py:99` (após `THUMBNAIL_HISTORY_SIZE`)
- Modify: `src/main.py:23` (import de `THUMBNAIL_DIFF_THRESHOLD` → adicionar `EVENT_DEDUP_WINDOW_SECONDS`)
- Test: `tests/test_event_dedup.py` (novo)

**Interfaces:**
- Consumes: env var `EVENT_DEDUP_WINDOW_SECONDS` (opcional).
- Produces: `config.EVENT_DEDUP_WINDOW_SECONDS` (float, padrão 300.0) usado por `CameraWorker`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_event_dedup.py
import importlib
import src.config as cfg


def test_event_dedup_window_default():
    # Recarrega para garantir default limpo (sem env var setada)
    importlib.reload(cfg)
    assert isinstance(cfg.EVENT_DEDUP_WINDOW_SECONDS, float)
    assert cfg.EVENT_DEDUP_WINDOW_SECONDS > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_event_dedup.py::test_event_dedup_window_default -v`
Expected: FAIL — `AttributeError: module 'src.config' has no attribute 'EVENT_DEDUP_WINDOW_SECONDS'`

- [ ] **Step 3: Write minimal implementation**

Em `src/config.py`, após a linha `THUMBNAIL_HISTORY_SIZE = ...` (linha 99), adicionar:

```python
# Janela de deduplicação por cena estável: uma cena estável é representada
# por no máximo 1 thumbnail/evento por este período (5–10 min). Após a janela,
# um refresh é salvo mesmo sem mudança de cena.
EVENT_DEDUP_WINDOW_SECONDS = float(os.getenv("EVENT_DEDUP_WINDOW_SECONDS", "300"))
```

Em `src/main.py`, na tupla de import (linha 7-38), alterar o import de `THUMBNAIL_DIFF_THRESHOLD` para incluir a nova config:

```python
    THUMBNAIL_DIFF_THRESHOLD,
    THUMBNAIL_HISTORY_SIZE,
    EVENT_DEDUP_WINDOW_SECONDS,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_event_dedup.py::test_event_dedup_window_default -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/config.py src/main.py tests/test_event_dedup.py
git commit -m "feat: add EVENT_DEDUP_WINDOW_SECONDS config"
```

---

### Task 2: Estado representante + `_scene_changed` / `_update_repr`

**Files:**
- Modify: `src/main.py:73-99` (`__init__` do `CameraWorker`)
- Modify: `src/main.py` (adicionar métodos após `_should_save_thumbnail`, ~linha 132)
- Test: `tests/test_event_dedup.py`

**Interfaces:**
- Consumes: `frames_similar` (existente), `EVENT_DEDUP_WINDOW_SECONDS` (Task 1), `_thumbnail_mini` (existente).
- Produces:
  - `worker._repr_frame` (ndarray 64x64 ou None)
  - `worker._repr_time` (float, epoch)
  - `worker._scene_changed(frame, now) -> bool`
  - `worker._update_repr(frame, now) -> None`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_event_dedup.py (append)
import numpy as np
from src.main import CameraWorker, frames_similar, _thumbnail_mini
from src.config import THUMBNAIL_DIFF_THRESHOLD, EVENT_DEDUP_WINDOW_SECONDS


def _frame(fill=100, obj=None):
    frame = np.full((480, 640, 3), fill, np.uint8)
    if obj:
        y0, y1, x0, x1, val = obj
        frame[y0:y1, x0:x1] = val
    return frame


def _make_worker():
    return CameraWorker(
        {"id": "cam1", "name": "Cam", "zone": "entrada", "source": "rtsp://x"},
        storage=None, alerts=None, object_detector=None,
    )


def test_scene_changed_first_frame_true():
    w = _make_worker()
    assert w._scene_changed(_frame(), 1000.0) is True


def test_scene_changed_within_window_similar_false():
    w = _make_worker()
    w._repr_frame = _thumbnail_mini(_frame())
    w._repr_time = 1000.0
    # mesma cena, dentro da janela -> não mudou
    assert w._scene_changed(_frame(), 1000.0 + EVENT_DEDUP_WINDOW_SECONDS - 1) is False


def test_scene_changed_after_window_true():
    w = _make_worker()
    w._repr_frame = _thumbnail_mini(_frame())
    w._repr_time = 1000.0
    assert w._scene_changed(_frame(), 1000.0 + EVENT_DEDUP_WINDOW_SECONDS + 1) is True


def test_scene_changed_different_scene_true():
    w = _make_worker()
    w._repr_frame = _thumbnail_mini(_frame())
    w._repr_time = 1000.0
    assert w._scene_changed(_frame(obj=(100, 300, 200, 400, 255)), 1000.0 + 1) is True


def test_update_repr_sets_state():
    w = _make_worker()
    f = _frame(obj=(100, 300, 200, 400, 255))
    w._update_repr(f, 1234.0)
    assert w._repr_frame is not None
    assert w._repr_time == 1234.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_event_dedup.py -k "scene_changed or update_repr" -v`
Expected: FAIL — `AttributeError: 'CameraWorker' object has no attribute '_scene_changed'`

- [ ] **Step 3: Write minimal implementation**

Em `src/main.py`, no `__init__` (após `self._last_saved_thumb_path = None`, linha 85), adicionar:

```python
        self._repr_frame = None
        self._repr_time = 0.0
```

Após o método `_should_save_thumbnail` (fim da linha 132), adicionar:

```python
    def _scene_changed(self, frame, now):
        """True se a cena deve ser tratada como nova (salvar/suprimir).

        - sem representante: sempre nova;
        - janela expirada: refresh obrigatório;
        - frames_similar falha: cena mudou de fato.
        """
        if self._repr_frame is None:
            return True
        if now - self._repr_time >= EVENT_DEDUP_WINDOW_SECONDS:
            return True
        return not frames_similar(self._repr_frame, frame, THUMBNAIL_DIFF_THRESHOLD)

    def _update_repr(self, frame, now):
        """Atualiza o representante de cena (mini 64x64 + timestamp)."""
        self._repr_frame = _thumbnail_mini(frame)
        self._repr_time = now
        # Mantém fallback de alerta Telegram consistente
        self._last_saved_thumb = self._repr_frame
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_event_dedup.py -k "scene_changed or update_repr" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/main.py tests/test_event_dedup.py
git commit -m "feat: add scene representative state to CameraWorker"
```

---

### Task 3: Dedup de thumbnails por cena estável + `force`

**Files:**
- Modify: `src/main.py:124-161` (`_should_save_thumbnail` e `_capture_thumbnail`)
- Modify: `tests/test_thumbnail_dedup.py` (atualizar referências `_last_saved_thumb` → `_repr_frame`/`_repr_time`)
- Test: `tests/test_thumbnail_dedup.py`, `tests/test_event_dedup.py`

**Interfaces:**
- Consumes: `_scene_changed`, `_update_repr` (Task 2), `should_capture_thumbnail`, `THUMBNAIL_INTERVAL_SECONDS`.
- Produces: `_capture_thumbnail(..., force=False)` — quando `force=True`, salva ignorando dedup; em todo save bem-sucedido chama `_update_repr`.

- [ ] **Step 1: Write the failing tests**

Em `tests/test_thumbnail_dedup.py`, substituir os 4 testes de `_should_save_thumbnail` (linhas 84-111) para usarem o representante:

```python
def test_should_save_thumbnail_first_frame_true():
    worker = _make_worker()
    assert worker._should_save_thumbnail(_frame(), 1000.0) is True


def test_should_save_thumbnail_within_interval_false():
    worker = _make_worker()
    worker._repr_frame = _thumbnail_mini(_frame())
    worker._repr_time = 1000.0
    now = 1000.0 + THUMBNAIL_INTERVAL_SECONDS - 1
    assert worker._should_save_thumbnail(_frame(obj=(100, 300, 200, 400, 255)), now) is False


def test_should_save_thumbnail_similar_within_window_false():
    worker = _make_worker()
    worker._repr_frame = _thumbnail_mini(_frame())
    worker._repr_time = 1000.0
    now = 1000.0 + THUMBNAIL_INTERVAL_SECONDS + 1
    # cena estática DENTRO da janela -> dedup (não salva)
    assert worker._should_save_thumbnail(_frame(), now) is False


def test_should_save_thumbnail_different_or_window_true():
    worker = _make_worker()
    worker._repr_frame = _thumbnail_mini(_frame())
    worker._repr_time = 1000.0
    # cena mudou -> salva
    assert worker._should_save_thumbnail(_frame(obj=(100, 300, 200, 400, 255)), 1000.0 + 1) is True
    # janela expirada -> salva mesmo cena igual
    worker2 = _make_worker()
    worker2._repr_frame = _thumbnail_mini(_frame())
    worker2._repr_time = 1000.0
    assert worker2._should_save_thumbnail(_frame(), 1000.0 + EVENT_DEDUP_WINDOW_SECONDS + 1) is True
```

Adicionar em `tests/test_event_dedup.py` (copiar `_FakeStorage` de `tests/test_thumbnail_dedup.py`):

```python
class _FakeStorage:
    def __init__(self):
        self.added = []
        self.pruned = []
    def add_camera_thumbnail(self, camera_id, path, event_type, event_id=None):
        self.added.append((camera_id, path, event_type))
    def prune_camera_thumbnails(self, camera_id, keep=None, max_age_days=None):
        self.pruned.append(camera_id)
    def list_zones(self):
        return []


def test_capture_thumbnail_force_bypasses_dedup(tmp_path, monkeypatch):
    import src.main as main_mod
    monkeypatch.setattr(main_mod, "THUMBNAILS_DIR", tmp_path)
    storage = _FakeStorage()
    w = _make_worker()
    w.storage = storage
    w._repr_frame = _thumbnail_mini(_frame())
    w._repr_time = 1000.0
    w._last_thumb_time = 1000.0
    # cena igual DENTRO da janela seria dedup normal; com force=True salva
    p = w._capture_thumbnail(_frame(), "no_motion", 1000.0 + 1, force=True)
    assert p is not None
    assert len(storage.added) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_thumbnail_dedup.py tests/test_event_dedup.py::test_capture_thumbnail_force_bypasses_dedup -v`
Expected: FAIL — `_should_save_thumbnail` ainda compara com `_last_saved_thumb`; `force` não existe.

- [ ] **Step 3: Write minimal implementation**

Substituir `_should_save_thumbnail` (linhas 124-132):

```python
    def _should_save_thumbnail(self, frame, now):
        """Decisão de captura de thumbnail: intervalo mínimo + dedup por
        cena estável (representante + janela)."""
        if not should_capture_thumbnail(self._last_thumb_time, now, THUMBNAIL_INTERVAL_SECONDS):
            return False
        if not self._scene_changed(frame, now):
            return False
        return True
```

Substituir assinatura e corpo de `_capture_thumbnail` (linhas 134-161) para aceitar `force` e atualizar representante:

```python
    def _capture_thumbnail(self, storage_frame, event_type, now, keep=THUMBNAIL_HISTORY_SIZE, days=None, event_id=None, force=False):
        """Salva um thumbnail com dedup por similaridade (ou force=True).

        Retorna o path se gravou, ou None se pulado (intervalo não cumprido,
        cena estável já representada ou falha). Em todo save bem-sucedido
        atualiza o representante de cena.
        """
        if not force and not self._should_save_thumbnail(storage_frame, now):
            return None
        try:
            cam_dir = THUMBNAILS_DIR / f"cam{self.camera['id']}"
            cam_dir.mkdir(parents=True, exist_ok=True)
            filename = f"{int(now * 1000)}.jpg"
            path = cam_dir / filename
            ok, jpg = cv2.imencode(".jpg", storage_frame)
            if not ok:
                return None
            path.write_bytes(jpg.tobytes())
            self.storage.add_camera_thumbnail(self.camera["id"], str(path), event_type, event_id=event_id)
            self.storage.prune_camera_thumbnails(self.camera["id"], keep=keep, max_age_days=days)
        except Exception:
            logger.warning("Falha ao capturar thumbnail (câmera %s)", self.camera.get("name"))
            return None
        self._last_thumb_time = now
        self._update_repr(storage_frame, now)
        self._last_saved_thumb_path = str(path)
        return str(path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_thumbnail_dedup.py tests/test_event_dedup.py -v`
Expected: PASS (todos os testes de thumbnail dedup + novos)

- [ ] **Step 5: Commit**

```bash
git add src/main.py tests/test_thumbnail_dedup.py tests/test_event_dedup.py
git commit -m "feat: thumbnail dedup by stable scene + force flag"
```

---

### Task 4: Supressão de eventos de baixo-valor + correção `motion_reported`

**Files:**
- Modify: `src/main.py:363-445` (branch de movimento e branch `no_motion` no `run()`)
- Test: `tests/test_event_dedup.py` (teste de unidade de `_should_emit_event` + teste de integração com `CameraStream` mockado)

**Interfaces:**
- Consumes: `_scene_changed` (Task 2), `_capture_thumbnail(force=...)` (Task 3), `build_candidate_event`, `event_bus.enqueue`.
- Produces:
  - `worker._should_emit_event(identity_info, fall, loitering, direction, frame, now) -> bool`
  - Comportamento em `run()`: `motion_reported = True` é setado assim que `motion_detected` é True (independente de supressão); eventos de baixo-valor em cena estável não são enfileirados nem geram thumbnail/clipe.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_event_dedup.py (append)
def test_should_emit_event_high_value_always():
    w = _make_worker()
    w._repr_frame = _thumbnail_mini(_frame())
    w._repr_time = 1000.0
    # identidade presente -> sempre emite, mesmo cena estável
    assert w._should_emit_event({"known": True, "name": "Jo"}, False, None, None, _frame(), 1000.0 + 1) is True
    # queda/loitering/direção -> sempre emitem
    assert w._should_emit_event(None, True, None, None, _frame(), 1000.0 + 1) is True
    assert w._should_emit_event(None, False, {"first_seen": 0}, None, _frame(), 1000.0 + 1) is True


def test_should_emit_event_low_value_suppressed_when_stable():
    w = _make_worker()
    w._repr_frame = _thumbnail_mini(_frame())
    w._repr_time = 1000.0
    # baixo-valor (sem identidade/fall/loiter/direction) + cena estável -> suprimir
    assert w._should_emit_event(None, False, None, None, _frame(), 1000.0 + 1) is False
    # baixo-valor mas cena mudou -> emitir
    assert w._should_emit_event(None, False, None, None, _frame(obj=(100, 300, 200, 400, 255)), 1000.0 + 1) is True
```

Teste de integração (mock de `CameraStream` + `ObjectDetector`):

```python
def test_run_suppresses_low_value_and_still_emits_no_motion(tmp_path, monkeypatch):
    import src.main as main_mod
    import threading
    import time

    # Frame com bloco que "pisca" (+30) a cada frame: dispara MotionDetector
    # (área > min_area) mas mantém média 64x64 <= THUMBNAIL_DIFF_THRESHOLD (cena similar).
    def make_frame(on):
        f = np.full((480, 640, 3), 100, np.uint8)
        val = 130 if on else 100
        f[200:300, 200:300] = val  # 100x100
        return f

    class FakeStream:
        def __init__(self, frames):
            self._it = iter(frames)
        def read(self):
            try:
                return next(self._it)
            except StopIteration:
                return None

    class FakeDetector:
        def detect(self, frame):
            return []  # sem objetos -> evento baixo-valor (motion_detected/snapshot_info)

    class FakeBus:
        def __init__(self):
            self.events = []
        def enqueue(self, ev):
            self.events.append(ev)

    storage = _FakeStorage()
    bus = FakeBus()
    w = CameraWorker(
        {"id": "cam1", "name": "Cam", "zone": "entrada", "source": "rtsp://x"},
        storage=storage, alerts=None, object_detector=FakeDetector(), event_bus=bus,
    )
    # 5 frames "piscando" (movimento ruído) + 3 frames idênticos estáticos (quiet)
    frames = [make_frame(i % 2 == 0) for i in range(5)] + [make_frame(False) for _ in range(3)]
    monkeypatch.setattr(main_mod, "CameraStream", lambda *a, **k: FakeStream(frames))
    monkeypatch.setattr(main_mod, "THUMBNAILS_DIR", tmp_path)
    # Reduz janela de "sem movimento" para o teste não precisar esperar 60s
    monkeypatch.setattr(main_mod, "NO_MOTION_ALERT_SECONDS", 0.05)

    t = threading.Thread(target=w.run, daemon=True)
    t.start()
    time.sleep(2.0)  # processa os 8 frames
    w.stop_event.set()
    t.join(timeout=3)

    # Apenas 1 evento de baixo-valor deve ter sido enfileirado (demais suprimidos)
    low_value = [e for e in bus.events if not e.no_motion]
    assert len(low_value) == 1, f"esperado 1 evento de baixo-valor, veio {len(low_value)}"
    # Após quietude, no_motion deve ser emitido (prova motion_reported funcionando)
    assert any(e.no_motion for e in bus.events), "no_motion não foi emitido"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_event_dedup.py -k "should_emit_event or run_suppresses" -v`
Expected: FAIL — `AttributeError: 'CameraWorker' object has no attribute '_should_emit_event'`

- [ ] **Step 3: Write minimal implementation**

Adicionar método `_should_emit_event` após `_update_repr` (Task 2):

```python
    def _should_emit_event(self, identity_info, fall, loitering, direction, frame, now):
        """Eventos de baixo-valor em cena estável são suprimidos para não
        poluir o grid com imagens quase-idênticas. Eventos de segurança
        (identidade/intruso/queda/loitering/direção) sempre emitem."""
        high_value = (
            identity_info is not None
            or fall
            or loitering is not None
            or direction is not None
        )
        if high_value:
            return True
        return self._scene_changed(frame, now)
```

No `run()`, no branch de movimento (após `motion_detected = motion_detector.detect(...)`, linhas 363-365), garantir `motion_reported = True` incondicionalmente ao detectar movimento. As linhas 363-365 atualmente são:

```python
                last_motion_time = time.time()
                no_motion_alerted = False
```

Adicionar `motion_reported = True` logo abaixo (antes do `try`):

```python
                last_motion_time = time.time()
                no_motion_alerted = False
                motion_reported = True
```

Substituir o bloco de emissão de evento (linhas ~405-424) por:

```python
                    now = time.time()
                    event = self.build_candidate_event(
                        detections, identity_info, identity_label, zone_name,
                        zone_classification, zone_schedule, now, fall, loitering,
                        direction, None, no_motion=False,
                    )
                    if self._should_emit_event(identity_info, fall, loitering, direction, storage_frame, now):
                        thumb_path = self._capture_thumbnail(
                            storage_frame, None, time.time(), thumb_keep, thumb_days,
                            event_id=event.event_id,
                        )
                        event.thumbnail_path = thumb_path or self._latest_thumbnail_path()
                        self.event_bus.enqueue(event)
                        self.start_clip(event.event_id)
```

No branch `else` (sem movimento), substituir o bloco `no_motion` (linhas ~435-445) por:

```python
                if should_send_no_motion(
                    last_motion_time, motion_reported, no_motion_alerted,
                    time.time(), NO_MOTION_ALERT_SECONDS,
                ):
                    no_motion_alerted = True
                    ev = self.build_candidate_event(
                        [], None, None, zone_name, zone_classification, zone_schedule,
                        time.time(), False, None, None, None, no_motion=True,
                    )
                    # Força salvar o frame atual (cena quieta) -> grid mostra a
                    # cena real, não a imagem anterior (stale).
                    thumb_path = self._capture_thumbnail(
                        storage_frame, "no_motion", time.time(),
                        thumb_keep, thumb_days, event_id=None, force=True,
                    )
                    ev.thumbnail_path = thumb_path or self._latest_thumbnail_path()
                    self.event_bus.enqueue(ev)
                    motion_reported = False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_event_dedup.py -v`
Expected: PASS (incluindo `test_run_suppresses_low_value_and_still_emits_no_motion`)

- [ ] **Step 5: Commit**

```bash
git add src/main.py tests/test_event_dedup.py
git commit -m "feat: suppress low-value events on stable scene; truthful no_motion thumbnail"
```

---

### Task 5: Verificação de regressão e lint

**Files:**
- Test: `tests/test_thumbnail_dedup.py`, `tests/test_event_dedup.py`, `tests/test_main_identity.py`, `tests/test_no_motion.py`, `tests/test_latest_frame.py`

**Interfaces:**
- Consumes: suíte de testes existente + nova.

- [ ] **Step 1: Run full relevant test suite**

Run: `pytest tests/test_thumbnail_dedup.py tests/test_event_dedup.py tests/test_main_identity.py tests/test_no_motion.py tests/test_latest_frame.py -v`
Expected: PASS (sem quebras de `_last_saved_thumb` / `_latest_thumbnail_path`)

- [ ] **Step 2: Run lint/import sanity**

Run: `python -c "import src.main, src.config; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit (se houver ajuste de teste necessário)**

```bash
git add -A
git commit -m "test: regression check for scene-stable dedup" || echo "nothing to commit"
```
