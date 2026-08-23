# Design: Deduplicação por cena estável (thumbnails + eventos de baixo-valor)

- **Data:** 2026-08-22
- **Status:** Aprovado (design)
- **Autor:** workflow (brainstorming → design)
- **Escopo:** Reduzir imagens quase-idênticas no grid de eventos e armazenamento desnecessário, sem perder eventos relevantes.

## 1. Problema

O grid de eventos (`/events`, renderizado em `src/static/sections/events.js`) está sendo poluído por
capturas com imagens altamente semelhantes que não adicionam nenhum movimento ou ação em relação à
anterior. Dois sintomas foram confirmados no código:

1. **Imagens quase-idênticas no grid.** O grid NÃO usa `event.thumbnail_path`. Ele busca
   `GET /camera/{id}/thumbnails` (`camera_thumbnails`) e casa cada evento ao thumbnail de timestamp
   mais próximo (`events.js:12-30`, `_pickThumb`). O `camera_thumbnails` é populado a cada frame de
   movimento via `_capture_thumbnail`. O dedup atual (`_should_save_thumbnail`, `main.py:124`) só
   compara com o **último** thumbnail salvo e não tem janela de tempo — então uma cena quase-estática
   (ruído do detector, artefato de compressão, leve oscilação) gera vários thumbnails quase-idênticos.
   Como o grid casa por timestamp, todos os cards de um período estável acabam mostrando a mesma imagem.

2. **`no_motion` mostra imagem stale.** O evento `no_motion` é enfileirado com `thumbnail_path=None`
   (`main.py:440-444`) e nunca salva um thumbnail próprio. O grid casa ao thumbnail anterior (da época
   do movimento), então o `no_motion` "aparenta ser a última" imagem, não a cena quieta real.

Além disso, eventos de baixo-valor (`snapshot_info`, `motion_detected`) são criados a cada frame com
movimento, independentemente do cooldown de alerta (que só throttleia o *envio*, não a criação). Isso
aumenta o número de cards e o armazenamento sem valor perceptível.

## 2. O que já existe

- `frames_similar(a, b, threshold)` (`main.py:553`): redimensiona para 64×64 grayscale, absdiff,
  média <= threshold → similar. Calibrado: idêntico=0.0, ruído sigma3≈0.97, objeto forte≈9.1.
- `_should_save_thumbnail` / `_capture_thumbnail` (`main.py:124-161`): dedup de thumbnail contra
  `_last_saved_thumb` + intervalo mínimo `THUMBNAIL_INTERVAL_SECONDS`.
- `THUMBNAIL_DIFF_THRESHOLD` (`config.py:98`, default 3.0) e `THUMBNAIL_INTERVAL_SECONDS`.
- `triage_n1` (`main.py:450`): mantém evento se há detecções ou é `no_motion`.
- `decide_worker_event` (`event_rules.py:24`): decide o tipo final (snapshot_info vs motion_detected
  vs identidade/intruso/etc.) — roda no `AlertRuleEngine`, NÃO no worker.
- `should_send_no_motion` (`main.py:458`): emite `no_motion` uma vez por período de quietude.
- Testes: `tests/test_thumbnail_dedup.py` (cobre `frames_similar`, `_should_save_thumbnail`,
  `_capture_thumbnail`).

## 3. O que construir

Tudo localizado no `CameraWorker` (`src/main.py`), reusando `frames_similar`. Nenhuma nova dependência.

### 3.1 Estado "representante" por câmera

Substitui o uso de `_last_saved_thumb` como referência de dedup por um representante de cena com janela:

```python
def _scene_changed(self, frame, now):
    """True se devemos tratar a cena como nova (salvar/suprimir)."""
    if self._repr_frame is None:
        return True
    if now - self._repr_time >= EVENT_DEDUP_WINDOW_SECONDS:
        return True  # janela expirou -> refresh obrigatório
    return not frames_similar(self._repr_frame, frame, THUMBNAIL_DIFF_THRESHOLD)

def _update_repr(self, frame, now):
    self._repr_frame = _thumbnail_mini(frame)
    self._repr_time = now
```

Atributos novos no `__init__` do worker: `_repr_frame = None`, `_repr_time = 0.0`.
(`_last_saved_thumb` / `_last_thumb_time` permanecem para o caminho de fallback de alerta Telegram e
compatibilidade; `_update_repr` também atualiza `_last_saved_thumb` para não quebrar o fallback.)

### 3.2 Dedup de thumbnails

`_should_save_thumbnail` passa a usar o representante + janela:

```python
def _should_save_thumbnail(self, frame, now):
    if not should_capture_thumbnail(self._last_thumb_time, now, THUMBNAIL_INTERVAL_SECONDS):
        return False
    if not self._scene_changed(frame, now):
        return False
    return True
```

`_capture_thumbnail` (após salvar com sucesso) chama `self._update_repr(storage_frame, now)` em vez de
apenas `self._last_saved_thumb = _thumbnail_mini(...)`. Adiciona parâmetro `force=False`: quando
`force=True`, bypassa `_should_save_thumbnail` e salva sempre (usado pelo `no_motion`).

**Efeito:** cena estável → no máximo 1 thumbnail por `EVENT_DEDUP_WINDOW_SECONDS`; cena muda de fato →
salva imediatamente. Isso elimina as imagens quase-idênticas no `camera_thumbnails`.

### 3.3 Supressão de eventos de baixo-valor

No branch de movimento (`main.py`, bloco `if motion_detected:`), antes de enfileirar o evento:

```python
low_value = (
    identity_info is None
    and not fall
    and loitering is None
    and direction is None
)
if low_value and not self._scene_changed(storage_frame, now):
    # cena estável + evento sem relevância -> suprimir (não cria card duplicado,
    # não salva thumbnail, não grava clipe)
    pass
else:
    thumb_path = self._capture_thumbnail(storage_frame, None, time.time(), thumb_keep, thumb_days, event_id=event.event_id)
    event.thumbnail_path = thumb_path or self._latest_thumbnail_path()
    self.event_bus.enqueue(event)
    self._update_repr(storage_frame, now)
    self.start_clip(event.event_id)
```

Regra de ouro: **eventos com identidade / intruso / queda / loitering / direção NUNCA são suprimidos**
(`low_value=False`), independente da cena. Apenas `snapshot_info` e `motion_detected` (sem relevância)
são candidatos à supressão.

**Correção de regressão:** `motion_reported = True` deve ser setado sempre que há movimento detectado
(`motion_detected=True`), e NÃO apenas quando o evento é emitido. Caso contrário, suprimir
`motion_detected` impediria o `no_motion` de disparar. Ajuste: mover/duplicar o `motion_reported = True`
para logo após `motion_detected = motion_detector.detect(...)` (antes do bloco de supressão).

### 3.4 Thumbnail truthful do `no_motion`

No branch `else` (sem movimento), quando `should_send_no_motion(...)` retorna True:

```python
no_motion_alerted = True
ev = self.build_candidate_event([], None, None, zone_name, zone_classification, zone_schedule,
                                time.time(), False, None, None, None, no_motion=True)
# força salvar o frame atual (cena quieta) -> grid mostra a cena real, não a anterior
thumb_path = self._capture_thumbnail(storage_frame, "no_motion", time.time(),
                                     thumb_keep, thumb_days, event_id=None, force=True)
ev.thumbnail_path = thumb_path or self._latest_thumbnail_path()
self.event_bus.enqueue(ev)
self._update_repr(storage_frame, time.time())
motion_reported = False
```

Como o grid casa por timestamp, o thumbnail do `no_motion` (salvo em `t_quiet` com a cena quieta real)
será o escolhido para o card → imagem correta.

## 4. Modelo de dados

Nenhuma mudança de schema. O `camera_thumbnails` e `events` permanecem iguais; apenas a *frequência* de
inserção muda (menos linhas). `EVENT_DEDUP_WINDOW_SECONDS` é config em `src/config.py` (env var).

## 5. Rotas / APIs afetadas

- `GET /camera/{id}/thumbnails` — retorna menos thumbnails (sem duplicatas de cena estável). Sem mudança
  de contrato.
- `GET /events` — menos eventos de baixo-valor em cenas estáveis. Sem mudança de contrato.
- `GET /events` continua retornando `dropped` e `disposition`; eventos suprimidos simplesmente NÃO são
  criados (não vão para o grid nem para o storage).

## 6. Segurança

- Sem exposição de novos dados sensíveis.
- Supressão só atinge eventos de baixo-valor; eventos de segurança (intruso, identidade, queda) são
  sempre preservados.
- `force=True` no `no_motion` é local e não contorna nenhuma checagem de permissão.

## 7. Riscos e mitigações

| Risco | Mitigação |
|-------|-----------|
| Limiar `THUMBNAIL_DIFF_THRESHOLD=3.0` muito apertado → cenas "altamente semelhantes" ainda passam como diferentes e são salvas. | Reusar o mesmo threshold (configurável via env). Se após teste ainda houver duplicatas, subir o default. A janela garante refresh periódico mesmo assim. |
| Suprimir `motion_detected` quebra o gatilho de `no_motion`. | `motion_reported=True` setado no momento do movimento, independente da supressão (seção 3.3). |
| Cena muda sutilmente mas de forma relevante dentro da janela e é suprimida. | Supressão exige `not _scene_changed` (ou seja, cena efetivamente igual). Mudança real (frames_similar=False) sempre emite. |
| Regressão em `_latest_thumbnail_path` (fallback Telegram). | `_update_repr` também atualiza `_last_saved_thumb`/`_last_saved_thumb_path`. |

## 8. Testes

- **Atualizar `tests/test_thumbnail_dedup.py`**: trocar referências a `_last_saved_thumb` por
  `_repr_frame`/`_repr_time` onde couber; manter cobertura de `frames_similar` e `_capture_thumbnail`.
- **Novo `tests/test_event_dedup.py`**:
  - `_scene_changed` retorna True no primeiro frame, após janela, e quando cena muda; False para cena
    estável dentro da janela.
  - Supressão: worker com cena estável e evento de baixo-valor NÃO enfileira evento nem salva thumbnail;
    evento com `identity_info` SEMPRE enfileira.
  - `motion_reported` continua `True` após movimento mesmo quando o evento de baixo-valor é suprimido.
  - `no_motion` força salvamento de thumbnail com o frame atual (truthful) e atualiza representante.

## 9. Fora de escopo (YAGNI)

- Hash perceptual (dHash/aHash) — `frames_similar` já cobre o caso "quase-idêntico".
- Alteração do detector de movimento (`MotionDetector`) ou de thresholds de área.
- Mudança de política de retenção/prune (`EVENT_PRUNE_*`).
- Deduplicação no lado do cliente (grid) — resolvido na origem (captura).
