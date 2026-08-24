# Fase 5 (parte 1) — Sirene via MQTT + Export/Backup

> Design para as features 5.1 e 5.4 do roadmap (`docs/superpowers/specs/2026-08-13-secur-roadmap.md`).
> Escopo aprovado: implementar 5.1 + 5.4 primeiro; 5.2 (busca NL) e 5.3 (cross-camera) ficam para fase posterior.

## Problema

O roadmap define, para a Fase 5, a integração e experiência. Duas das quatro features
são concretas e de alto valor com esforço baixo/médio:

- **5.1** Acionar dispositivo externo (sirene/áudio) via MQTT/Home Assistant em evento crítico.
- **5.4** Exportar/backup de eventos + thumbnails + clipes em um arquivo ZIP sob demanda.

As outras duas (5.2 busca NL, 5.3 cross-camera) exigem decisões arquiteturais pesadas e
ficam fora deste escopo.

## O que já existe (reconcilado com `dev`)

- `notifications.py` já define o canal `"automation"` e `DEFAULT_ROUTING` com ele habilitado
  para eventos de alerta.
- `AlertService` (em `src/alerts.py`) despacha para handlers com atributo `.channel`; já há
  `mqtt_handler` e `home_assistant_handler` com `channel="automation"` (publicam o evento em
  MQTT/HA). Falta uma **atuação dedicada de sirene** em evento crítico.
- `storage.py` já persiste `clip_path` em `events` e tem a tabela `event_clips`; thumbnails
  ficam em `camera_thumbnails` ligados por `event_id` (TEXT). `events.timestamp` é ISO UTC.
- `paho.mqtt.publish` já é importado em `src/alerts.py`.

## O que construir

### 5.1 — Handler de sirene (`src/alerts.py`)

- `siren_handler(payload)` com `channel = "automation"`.
- Só age se `payload["event_type"]` ∈ `SIREN_EVENT_TYPES` (críticos: `intruder_detected`,
  `fall_detected`, `loitering`, `direction_change`, `unknown_detected` por padrão, configurável).
- Publica JSON `{"action": "siren", "camera_id", "zone", "event_type", "timestamp"}` no tópico
  `SIREN_MQTT_TOPIC` (default `secur/automation/siren`) via `paho.mqtt.publish.single`,
  reusando broker MQTT das env vars (`MQTT_BROKER_URL/PORT/USERNAME/PASSWORD`).
- Silencioso se broker não configurado.
- Registrado em `main.py` ao lado de `telegram_handler`/`mqtt_handler`/`home_assistant_handler`.

Config (`src/config.py`): `SIREN_MQTT_TOPIC`, `SIREN_EVENT_TYPES` (set, via env).

### 5.4 — Rota de export (`src/app.py` + `src/storage.py`)

- `storage.list_events` ganha parâmetros opcionais `start`/`end` (epoch float) — filtra em
  Python parseando o ISO (`datetime.fromisoformat`).
- Novo `storage.get_event_thumbnail_path(event_id) -> str | None` (consulta `camera_thumbnails`
  por `event_id` como string).
- Rota `GET /export` (query: `camera_id?`, `start?`, `end?`, `limit?` default 500, cap 2000):
  - Busca eventos (filtro por câmera + janela temporal).
  - Monta ZIP em memória: `events.json` (lista), `thumbnails/<id>.<ext>` (arquivo existe?),
    `clips/<basename>` (de `event.clip_path`, arquivo existe?).
  - Retorna via `send_file(..., mimetype="application/zip")` com nome
    `secur-export-<timestamp>.zip`.
  - Respeita autenticação (middleware existente).
- Entrada em `api_docs`.

## Modelo de dados

Sem novas tabelas. Reuso de `events` (`clip_path`), `camera_thumbnails` (`event_id`, `path`),
`event_clips`. O ZIP é gerado sob demanda a partir do filesystem (`THUMBNAILS_DIR`, `CLIPS_DIR`)
e dos paths persistidos.

## Rotas

- `GET /export` — download ZIP (autenticado).

## Segurança

- Herda autenticação existente (redirect 302 p/ /login ou 401 p/ /api/ conforme middleware).
- ZIP usa nomes derivados de IDs/event_id (sem path traversal: `os.path.basename` dos paths
  originais; arquivos lidos apenas se existirem).
- `limit` é limitado (cap 2000) para evitar export gigante.

## Riscos

- `camera_thumbnails.event_id` é TEXT enquanto `events.id` é INTEGER → comparar como string.
- Timestamp ISO pode vir com timezone; `datetime.fromisoformat` (Python 3.11+) lida com `+00:00`.
- Handler de sirene só dispara em evento crítico para não acionar sirene a cada movimento.

## Testes (TDD)

- `tests/test_alerts.py`: `siren_handler` publica no tópico certo p/ evento crítico (monkeypatch
  `paho.mqtt.publish.single`), não publica p/ evento não-crítico, silencia sem broker.
- `tests/test_app.py` (ou `tests/test_export.py`): `GET /export` autenticado retorna ZIP com
  `events.json` + thumbnail + clip dos eventos criados.
