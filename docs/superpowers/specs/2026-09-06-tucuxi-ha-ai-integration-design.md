# Integração Tucuxi + Home Assistant + AI Preditiva — Design

> **Status:** RASCUNHO — P1 decidida: predictor como **submodule** desacoplado (ver §6-7).
> **Data:** 2026-09-06
> **Autor:** brainstorming Tucuxi
> **Base:** `SPEC.md`, `docs/roadmap.md`, `docs/technical.md`, `src/alerts.py`, `src/events.py`, `src/notifications.py`
> **Decisão 2026-09-06:** predictor será um **submodule** (pacote Python independente) consumido pelo Tucuxi e/ou como addon HA — contrato MQTT estável.

---

## 1. Problema

O Tucuxi hoje é **reativo**: detecta movimento → classifica (YOLO) → aplica regra de zona/horário → dispara alerta (Telegram/MQTT/HA) — `src/alerts.py:14`, `src/event_rules.py`. O Home Assistant consome esses eventos como sensores binários (`secur/{id}/state` motion/idle, `secur/{id}/alert_state`).

Falta camada **preditiva e propositiva**:
- Usuário não sabe *quando* algo tende a acontecer (padrão temporal por câmera/zona).
- HA não recebe *probabilidade futura*, só evento passado — não consegue pré-armar automação (acender luz, fechar portão, irrigar).
- Não há *sugestão de automação* acionável no HA (notificação interativa aceitar/recusar).

Sem isso, Tucuxi permanece um NVR inteligente isolado, não um **motor de inteligência distribuída** (edge + predição + orquestração).

---

## 2. Objetivo

Transformar o Tucuxi em motor distribuído:

```
[Tucuxi Edge AI] --MQTT eventos--> [Módulo AI Preditivo] --MQTT sensores virtuais--> [Home Assistant]
       |                                      |                                    |
  visão local                          séries temporais                    sensores + notificações
  100% offline                         local ou cloud opcional             automações sugeridas
```

**Valor para o usuário (ordem de prioridade — AGENTS.md):**
1. Segurança proativa (antecipar janela de risco, reduzir falso-positivo).
2. Economia/conforto (automatizar luz/portão com base em rotina real, não horário fixo).
3. Extensibilidade (mesmo barramento serve para agrícola/energia depois).

**Fora de escopo deste design:** treinamento de YOLO customizado, LPR/facial dedicado, 80 câmeras (tratado em `docs/architecture-80-cameras.md`).

---

## 3. O que já existe (não reinventar)

| Componente | Onde está | Reuso |
|---|---|---|
| Captura RTSP/HTTP + detecção movimento | `src/camera.py`, `src/motion.py` | Mantém |
| YOLO + tracking + behavior (loitering, direção, queda) | `src/detector.py`, `src/tracking.py`, `src/behavior.py` | Mantém; predição consome eventos já classificados |
| `CameraEvent` + `LocalEventQueue` | `src/events.py:11` | Preditor assina a fila ou lê SQLite |
| `AlertService` + handlers `telegram/mqtt/HA/siren` | `src/alerts.py:14`, `src/notifications.py:3` | `mqtt_handler` já publica `homeassistant/secur/alert` e `secur/{id}/alert_state`; sirene em `secur/automation/siren` |
| MQTT broker env vars | `src/config.py` / `docs/technical.md:160` | Mesmo broker (Mosquitto) para predições |
| Persistência SQLite `events` + thumbnails/clips | `src/storage.py` | Fonte histórica para séries temporais |
| Integração HA HTTP `POST /api/events/secur_alert` | `src/alerts.py:176` | Complementar ao MQTT; manter |

**Lacuna:** não há tópico de *predição* nem sensor virtual de *probabilidade futura*; não há loop de feedback aceitar/recusar automação.

---

## 4. O que construir — Visão geral

### 4.1 Componentes

**A. Tucuxi Edge (existente, leve ajuste)**
- Publica evento enriquecido por câmera em MQTT (compatível com atual, só adiciona campos).
- Opcional: publica métricas de frequência local (contadores por hora) se preditor rodar externo.

**B. Módulo AI Preditivo (novo)**
- Consome histórico de eventos (SQLite ou subscribe MQTT).
- Roda modelos leves: (1) série temporal por câmera/zona/hora, (2) classificador probabilístico por tipo de evento.
- Publica sensores virtuais em MQTT em intervalo fixo (ex: a cada 5-15 min) + sob demanda após evento.

**C. Home Assistant (consumidor + orquestrador de atuadores)**
- `mqtt.sensor` / `mqtt.binary_sensor` para predição + `mqtt.device_automation` ou `persistent_notification` interativa para sugestão.
- Automação criada só após aceite explícito do usuário (sem auto-criação silenciosa).
- **Integração com sensores e atuadores HA:** predictor lê estado do HA (ex: `alarm_control_panel`, `binary_sensor.presenca_rosa`) e propõe/executa ação em atuador mapeado (ex: `switch.aspersor_rosa` por 5 min). Ver §4.3 exemplo concreto.

### 4.2 Fluxo de dados

```
1. Detecção: Tucuxi detecta pessoa em portao 19:02 → MQTT tucuxi/camera/portao/event
2. Histórico: Preditor acumula (janela 7-30 dias) → calcula P(movimento | hora, dia_semana, zona)
3. Predição: Preditor publica tucuxi/predictions/portao {probabilidade, janela, confianca, modelo}
4. Sensor virtual: HA cria sensor.tucuxi_portao_predicao (0.82, atributos: janela, evento)
5. Sugestão: Se prob > threshold e sem automação existente → HA notifica "Deseja automatizar luz 19h?"
6. Ação: Usuário aceita → HA cria automação (trigger: sensor predicao > 0.7 + condição horária);
         recusa → feedback volta ao preditor (tucuxi/feedback) para ajustar threshold
```

### 4.3 Exemplo concreto — sensor + câmera + atuador (requisito 2026-09-06)

> **Regra:** *Se modo alarme = armado E sensor de presença "rosa" (câmera/zona Tucuxi) detectar movimento → ligar aspersor do jardim "aspersor rosa" por 5 minutos.*

Fluxo reativo (sem predição, valor imediato):
```
Tucuxi (zona rosa, cam 2) —motion→ tucuxi/camera/rosa/event {event_type: motion_detected}
HA: automation trigger = state tucuxi/camera/rosa/event + condition alarm_control_panel = armed
HA: action = switch.turn_on aspersor_rosa + delay 5min + switch.turn_off
```

Fluxo preditivo (proativo, com submodule):
```
Preditor (submodule) lê histórico rosa → P(movimento 19h) = 0.78
→ publica tucuxi/predictions/rosa {prob 0.78, janela 19:00-20:00}
HA: suggester propõe "Detectamos padrão na rosa 19h. Criar: se alarme armado + movimento rosa → aspersor 5min?"
→ usuário aceita → HA cria automação (blueprint Tucuxi) vinculada a switch.aspersor_rosa
```

**O que o predictor precisa enxergar para isso:**
- Estado do alarme (HA → `tucuxi/ha/alarm_mode` via MQTT ou `GET /api/states/alarm_control_panel.*` com `HOME_ASSISTANT_TOKEN` — `src/alerts.py:176`).
- Mapeamento configurável **zona/câmera Tucuxi → entidade HA** (ex: `rosa → binary_sensor.presenca_rosa` e `switch.aspersor_rosa`) — tabela `predictor_entity_map` no submodule.
- Atuação com **timer auto-off** (HA `delay` ou `tucuxi/automation/actuator` com `duration_sec: 300`). Generaliza `siren_handler` (`src/alerts.py:215`) para atuador genérico.

### 4.4 Modos de operação (requisito 2026-09-06)

Dois modos, mapeados para `alarm_control_panel` nativo do HA (sem entidade custom):

| Modo Tucuxi | Estado HA | Quando usar | Comportamento |
|---|---|---|---|
| **Alarme desarmado** | `disarmed` | Em casa, rotina normal | Monitoramento leve: só eventos críticos (`intruder`, `fall`, `loitering`) geram alerta; atuadores (aspersor) **não** disparam; predição continua aprendendo mas não sugere |
| **Alarme armado** | `armed_home` | Presente, mas com pontos de segurança ativos | Monitora pontos de segurança mapeados (ex: rosa): movimento → atua (aspersor 5min) + alerta; demais zonas só registram |
| **Viagem** | `armed_away` | Casa vazia | **Qualquer ponto alerta** (sensibilidade máxima, sem filtro de zona) + **simulação de presença** (luzes ligam/desligam por rotina aprendida) + notificação imediata Telegram/HA |

Detalhes:
- **Alarme armado (presente):** evita disparo contra morador — só zonas `segurança/privativa` no `entity_map` com `alarm_required: true` atuam. Ex: rosa → aspersor; portão → luz; quintal interno ignora.
- **Viagem:** `suggester` suprimido (sem "deseja automatizar?"); tudo vira ação direta. Simulação de presença usa `tucuxi/predictions/+` invertido: publica `tucuxi/automation/actuator` para `light.*` nos horários de maior P(movimento) histórico — parece que há gente em casa.
- Troca de modo: usuário arma/desarma no HA (`alarm_control_panel`) ou dashboard Tucuxi (`PUT /api/mode` futuro → espelha em `tucuxi/ha/alarm_mode` retain). Predictor subscreve e condiciona P(evento | modo).
- Fallback: se `tucuxi/ha/alarm_mode` stale (>60s) ou HA offline, predictor assume **último modo armado** (fail-secure) e loga; nunca assume `disarmed` por ausência de mensagem.

Exemplo viagem:
```
HA: alarm = armed_away → tucuxi/ha/alarm_mode {alarm_mode: armed_away}
Tucuxi cam quintal (zona pública, normalmente ignorada) —motion→ tucuxi/camera/quintal/event
→ modo viagem: publica tucuxi/automation/actuator {target: light.sala, action: turn_on, duration_sec: 1800}
→ Telegram: "Movimento quintal em modo viagem 22:14 + luz sala ligada (simulação)"
```

---

## 5. Modelo de dados / Formato de mensagens

### 5.1 Evento enriquecido (Tucuxi → MQTT)

Tópico: `tucuxi/camera/{camera_slug}/event` (novo, versionado) + mantém `homeassistant/secur/alert` por compatibilidade.

```json
{
  "schema_version": 1,
  "camera": "portao",
  "camera_id": 1,
  "zone": "entrada",
  "zone_classification": "privativa",
  "evento": "pessoa",
  "event_type": "intruder_detected",
  "timestamp": "2026-09-05T19:02:00-03:00",
  "probabilidade": 0.82,
  "bbox": [0.31, 0.42, 0.18, 0.45],
  "track_id": "abc123",
  "event_id": "uuid-hex",
  "thumbnail_path": "data/thumbnails/cam1_xxx.jpg"
}
```

Compatibilidade: `probabilidade` = confiança YOLO; `evento` alias de `event_type` para HA legado.

### 5.2 Predição (Preditor → HA)

Tópico: `tucuxi/predictions/{camera_slug}` (retain=true, QoS 0) + `tucuxi/predictions/{camera_slug}/attributes` opcional.

```json
{
  "schema_version": 1,
  "camera": "portao",
  "zone": "entrada",
  "janela": "19:00-20:00",
  "evento_previsto": "pessoa",
  "probabilidade": 0.82,
  "confianca_modelo": 0.71,
  "modelo": "ewma-7d",
  "gerado_em": "2026-09-05T18:45:00-03:00",
  "expira_em": "2026-09-05T20:00:00-03:00",
  "amostras": 142,
  "threshold_sugestao": 0.75
}
```

HA `mqtt.sensor`:
```yaml
mqtt:
  sensor:
    - name: "Tucuxi Portão Predição"
      state_topic: "tucuxi/predictions/portao"
      value_template: "{{ value_json.probabilidade }}"
      unit_of_measurement: "%"
      json_attributes_topic: "tucuxi/predictions/portao"
```

### 5.3 Sugestão de automação (HA → Usuário)

Tópico interno HA (não MQTT): `persistent_notification` com ações.

Payload notificação:
```json
{
  "title": "Sugestão Tucuxi",
  "message": "Portão tem 82% de chance de movimento entre 19h-20h (base 7 dias). Automatizar luz externa?",
  "data": {
    "actions": [
      {"action": "aceitar", "title": "Criar automação"},
      {"action": "recusar", "title": "Dispensar"},
      {"action": "ajustar", "title": "Ajustar horário"}
    ],
    "tag": "tucuxi_sugestao_portao_20260905"
  }
}
```

### 5.4 Feedback (HA → Preditor)

Tópico: `tucuxi/feedback/{camera_slug}`

```json
{"camera":"portao","acao":"aceitar|recusar|ajustar","sugestao_id":"...","timestamp":"...","ajuste":{"janela":"19:30-20:00"}}
```

Usado para aprendizado (ajustar threshold, suprimir sugestão repetida).

### 5.5 Atuação genérica (Preditor/Tucuxi → HA) — generaliza sirene

Tópico: `tucuxi/automation/actuator` (ou `secur/automation/siren` legado para sirene — `src/alerts.py:215`, `SIREN_MQTT_TOPIC`)

```json
{
  "schema_version": 1,
  "action": "turn_on",
  "camera": "rosa",
  "zone": "rosa",
  "event_type": "motion_detected",
  "target_entity": "switch.aspersor_rosa",
  "duration_sec": 300,
  "condition": {"alarm_mode": "armed"},
  "event_id": "uuid-hex",
  "timestamp": "2026-09-05T19:02:00-03:00"
}
```

HA consome com automação MQTT trigger:

```yaml
automation:
  - alias: "Tucuxi rosa → aspersor"
    trigger:
      - platform: mqtt
        topic: tucuxi/automation/actuator
    condition:
      - condition: template
        value_template: "{{ trigger.payload_json.target_entity == 'switch.aspersor_rosa' and trigger.payload_json.condition.alarm_mode == 'armed' }}"
    action:
      - service: switch.turn_on
        target: { entity_id: "{{ trigger.payload_json.target_entity }}" }
      - delay: "{{ trigger.payload_json.duration_sec }}"
      - service: switch.turn_off
        target: { entity_id: "{{ trigger.payload_json.target_entity }}" }
```

Alternativa REST (já existente `HOME_ASSISTANT_URL`/`HOME_ASSISTANT_TOKEN` — `docs/technical.md:160`): `POST /api/services/switch/turn_on` direto do predictor quando `PREDICTOR_HA_DIRECT_ACTION=true` (opt-in).

### 5.6 Estado do HA → Preditor (modo de operação)

Tópico: `tucuxi/ha/alarm_mode` (retain, HA publica; predictor subscreve) ou polling `GET /api/states/alarm_control_panel.tucuxi`

```json
{"alarm_mode": "disarmed|armed_home|armed_away", "modo_tucuxi": "alarme_desarmado|alarme_armado|viagem", "timestamp": "2026-09-05T18:00:00-03:00"}
```

Mapeamento: `disarmed` = alarme desarmado (rotina leve); `armed_home` = alarme armado presente (pontos de segurança ativos, ex: rosa → aspersor); `armed_away` = viagem (tudo alerta + simulação de presença). Ver matriz §4.4. Permite P(movimento | hora, modo) e suprimir sugestão quando desarmado; em viagem, sugestão vira ação direta.

### 5.7 Mapeamento zona/câmera → entidade HA (config do submodule)

```json
{
  "rosa": {
    "camera_id": 2,
    "ha_sensor": "binary_sensor.presenca_rosa",
    "ha_actuator": "switch.aspersor_rosa",
    "default_duration_sec": 300,
    "alarm_required": true,
    "modos_ativos": ["alarme_armado", "viagem"],
    "acao_viagem": "alertar_e_atuar"
  },
  "quintal": {
    "camera_id": 3,
    "ha_sensor": "binary_sensor.presenca_quintal",
    "ha_actuator": "light.sala",
    "default_duration_sec": 1800,
    "alarm_required": false,
    "modos_ativos": ["viagem"],
    "acao_viagem": "simular_presenca"
  }
}
```

Armazenado em `predictor/config/entity_map.json` (submodule) ou `PREDICTOR_ENTITY_MAP` env (JSON). Editável via `PUT /api/predictor/map` (futuro).

---

## 6. Abordagens possíveis (trade-offs) — P1 RESOLVIDA: submodule

### Decisão: predictor como **submodule** (pacote Python independente)

- **O que é:** repo/pacote `tucuxi-predictor` (Python) com interface estável, consumido como **git submodule** em `src/predictor/` **ou** instalado via `pip` (`requirements.txt`). Mesmo código roda em 3 embalagens sem duplicar lógica:
  1. **Embarcado no Tucuxi** (MVP) — importado por `src/main.py`, assina `LocalEventQueue` (`src/events.py:11`) e lê `src/storage.py`.
  2. **Serviço standalone** (`services/predictor/`) — container que consome `tucuxi/camera/+/event` via MQTT.
  3. **Addon HA** — mesmo container com `config.yaml` HA, publica `sensor.tucuxi_*_prediction` nativo.
- **Contrato estável (não quebra entre embalagens):** `tucuxi/camera/+/event` → `tucuxi/predictions/+` → `tucuxi/feedback/+` (MQTT, §5 e §8). Validação por `schema_version`.
- **Por que submodule e não só `src/predictor/` monolito:** desacopla ciclo de release (preditor evolui sem rebuild do Tucuxi), permite versionar modelo (tag `predictor-v0.1.0`), testar isolado, e reaproveitar na central N3/N4 de `docs/architecture-80-cameras.md` para 80 câmeras.

### Abordagem A — Preditor embarcado no Tucuxi (MVP com submodule)

- **Como:** `git submodule add <url> src/predictor` + `from predictor import Predictor, EWMAStore`; modelo EWMA/média móvel + histograma por hora; publica via `paho.mqtt.publish.single` no mesmo broker (`src/config.py`).
- **Prós:** 100% local/LGPD, sem infra extra, reusa `config.py`/`events.py`, funciona no Pi, deploy único (`docker compose`).
- **Contras:** limitado a modelos leves; não escala para 80 câmeras (mas MVP é 1-4).
- **Quando usar:** MVP residencial/pequeno condomínio — **é a embalagem inicial do submodule**.

### Abordagem B — Preditor como serviço separado (mesma lib, outra embalagem)

- **Como:** `services/predictor/Dockerfile` importa `tucuxi-predictor` via `pip install -e ./src/predictor` ou imagem própria; consome MQTT `tucuxi/camera/+/event` e SQLite via volume ou `GET /events`; publica em `tucuxi/predictions/+`.
- **Prós:** desacopla CPU do edge; troca modelo sem rebuild do Tucuxi; mesma lib testada.
- **Contras:** +1 container; discovery do broker; versionar `schema_version`.
- **Quando usar:** condomínio 8+ câmeras ou Pi no limite — **troca de embalagem, zero código novo**.

### Abordagem C — Preditor em nuvem opcional (futuro, opt-in)

- **Como:** edge publica eventos anonimizados (sem thumbnail) para HTTPS; cloud treina e devolve via MQTT bridge.
- **Prós:** modelos pesados (LSTM), analytics.
- **Contras:** fere "100% local" (`README.md:18`), LGPD, internet, custo.
- **Quando usar:** só com consentimento explícito; não no MVP.

**Recomendação mantida:** começar em **A com submodule** (interface desacoplada), pronto para **B** sem quebrar HA. **C** opt-in futuro.

---

## 7. Arquitetura sugerida — submodule desacoplado (com integração HA sensores/atuadores)

```
tucuxi/                          # repo principal
  src/
    events.py                    # CameraEvent (adicionar campos predição opcional)
    predictor/                   # ← git submodule → github.com/<org>/tucuxi-predictor
      pyproject.toml             # pacote `tucuxi-predictor` (pip installable)
      predictor/
        __init__.py              # interface Predictor: predict(camera, window) -> Prediction
        ewma.py                  # EWMA 7/30 dias por (camera, zona, hora, event_type)
        store.py                 # leitura agregada de storage (contagem por bucket horário)
        publisher.py             # publica tucuxi/predictions/+ via MQTT
        suggester.py             # decide se notifica HA (threshold + cooldown + feedback)
        schemas.py               # dataclasses + validação schema_version
        ha_client.py             # lê estado HA (alarm_mode, sensor) via MQTT/REST
        entity_map.py            # mapeamento zona/câmera → entidade HA (rosa → aspersor)
        actuator.py              # publica tucuxi/automation/actuator (generaliza siren_handler)
      tests/
  services/predictor/            # embalagem B (opcional, reusa submodule)
    Dockerfile
    main.py                      # loop MQTT → Predictor → publisher
  hass-addon/                    # embalagem HA (opcional)
    config.yaml
    Dockerfile
```

Dependência:

```
# requirements.txt (Tucuxi)
-e src/predictor        # dev (submodule)
# ou
tucuxi-predictor==0.1.0 # prod (pip)
paho-mqtt
```

Princípios (AGENTS.md):
- **Submodule com contrato estável:** Tucuxi e HA dependem de tópicos MQTT (`§5, §8`) e `schemas.py`, não de internals. Trocar embalagem não quebra.
- Cada unidade com uma responsabilidade, interface bem definida, testável isolada (`pytest` dentro do submodule, CI próprio).
- **Preditor integrado ao HA mas sem acoplamento forte:** `ha_client.py` lê `tucuxi/ha/alarm_mode` (MQTT retain) ou REST `HOME_ASSISTANT_TOKEN`; `actuator.py` generaliza `siren_handler` (`src/alerts.py:215`) para qualquer `target_entity` + `duration_sec`. HA continua orquestrador final (pode ignorar comando se condição não bater).
- `AlertRuleEngine` existente continua para eventos reativos; preditor é paralelo, não substitui.
- Versionamento: `tucuxi` referencia `predictor` por tag (`git submodule update --remote` + `APP_VERSION` em `src/config.py` para log).

Diagrama lógico (com sensores/atuadores HA):

```
[Camera workers] → [EventQueue] → [AlertRuleEngine] → handlers (MQTT/HA/Telegram)
                      ↓
                 [Predictor Store] → [EWMA Model] → [Publisher] → MQTT tucuxi/predictions/+
                      ↑                                      ↓
                 [SQLite events]                      [HA mqtt.sensor + suggester]
                      ↑                                      ↓
[HA alarm_mode/sensor] → [ha_client + entity_map] → [actuator] → MQTT tucuxi/automation/actuator → HA switch.aspersor_rosa (5min)
                                                         ↓
                                                   [feedback] → tucuxi/feedback/+
Ex: rosa (cam 2, zona rosa) + alarm=armed → turn_on switch.aspersor_rosa duration 300s
```

---

## 8. Tópicos MQTT — sumário

| Tópico | Direção | Retain | QoS | Payload |
|---|---|---|---|---|
| `homeassistant/secur/alert` | Tucuxi → HA (legado) | false | 0 | evento atual |
| `tucuxi/camera/{slug}/event` | Tucuxi → Preditor/HA | false | 0 | evento enriquecido v1 |
| `tucuxi/predictions/{slug}` | Preditor → HA | true | 0 | predição v1 |
| `tucuxi/predictions/{slug}/available` | Preditor → HA | true | 1 | birth/will |
| `tucuxi/feedback/{slug}` | HA → Preditor | false | 0 | aceitar/recusar |
| `tucuxi/ha/alarm_mode` | HA → Preditor | true | 0 | armed/disarmed |
| `tucuxi/automation/actuator` | Preditor → HA | false | 0 | turn_on + target_entity + duration_sec (generaliza sirene) |
| `secur/automation/siren` | Tucuxi → HA | false | 0 | siren legado (`SIREN_MQTT_TOPIC`) |
| `secur/{id}/state` | Tucuxi → HA | true | 0 | motion/idle (existente) |

Auto-discovery HA para predição: publicar `homeassistant/sensor/tucuxi_{slug}_prediction/config` com `state_topic: tucuxi/predictions/{slug}`.

---

## 9. Roadmap incremental (alinhado ao `docs/roadmap.md`) — com submodule + atuadores HA

1. **MVP (2-3 semanas):** criar repo `tucuxi-predictor` + `git submodule add src/predictor` + Tucuxi publica `tucuxi/camera/+/event` v1 + Preditor EWMA (embalagem A) + `tucuxi/predictions/+` + HA `mqtt.sensor` manual + **modos §4.4** (`tucuxi/ha/alarm_mode` + `entity_map.modos_ativos`). **Sem sugestão automática, mas já com `actuator.py` para "rosa → aspersor 5min" (alarme armado) e simulação de presença básica (viagem) via `tucuxi/automation/actuator`.**
2. **V2 (predição robusta + modos):** histograma dia_semana, `confianca_modelo`, `expira_em`, threshold por câmera/zona/modo (`src/config.py: PREDICTION_THRESHOLD`), `GET /predictions?modo=` para debug + `ha_client.py` lê `tucuxi/ha/alarm_mode` (ou REST) para P(evento | modo); `entity_map.json` com `acao_viagem` por zona.
3. **V3 (sugestão acionável):** `suggester.py` + `persistent_notification` + `tucuxi/feedback`; cooldown (`ALERT_COOLDOWN_*`); blueprint HA "Tucuxi: sensor → atuador com duração"; **embalagem B** (`services/predictor/`) e **addon HA** como distribuição alternativa da mesma lib.
4. **V4 (extensões):** agrícola/energia, 80 câmeras (preditor na central N3/N4 de `architecture-80-cameras.md`), opt-in cloud.

Cada fase com flag `PREDICTOR_ENABLED=false` por padrão; `pyproject.toml` do submodule com `version` espelhada em tag Git. Exemplo "rosa" entra no MVP como teste de integração fim-a-fim.

---

## 10. Segurança, privacidade e LGPD

- Predição 100% local no MVP (sem exfiltração); thumbnail nunca em tópico de predição.
- Tópicos de predição sem PII; `camera_slug` não expõe endereço.
- Feedback do usuário é local; se cloud opt-in, anonimizar e pedir consentimento explícito no dashboard.
- Mesma autenticação MQTT do broker existente; tópicos com ACL por usuário se broker suportar.
- Validar `schema_version` em todo subscriber; ignorar versão desconhecida (compatibilidade futura).

---

## 11. Riscos

- **Pi sobrecarregado:** EWMA é O(1) por evento; risco baixo. Mitigar com `PREDICTOR_INTERVAL_SECONDS` (default 900s) e desabilitar por câmera.
- **Falsos positivos de predição:** usuário desacredita. Mitigar com `confianca_modelo` + `amostras` visíveis + threshold alto (0.75) + cooldown 24h por sugestão.
- **HA desatualizado (retain):** predição expirada mostra valor stale. Mitigar com `expira_em` e HA template que mostra `unavailable` após expiração.
- **Schema drift:** dois tópicos de evento (legado + novo) divergem. Mitigar com conversor único `to_enriched_event()` e testes de contrato.
- **Atuador preso ligado (aspersor):** falha no `delay`/`turn_off` deixa jardim alagado. Mitigar com HA `timer` + `retain` + `availability` e comando idempotente com `duration_sec`; predictor publica também `turn_off` agendado e HA usa `mode: single` + `timeout`.
- **Alarme dessincronizado:** predictor age com `alarm_mode` stale. Mitigar com `tucuxi/ha/alarm_mode` retain + LWT, e checar `timestamp` < 60s antes de atuar.

---

## 12. Sugestões (para amadurecer antes de implementar)

1. **Começar sem ML:** EWMA + histograma já entrega 80% do valor com 5% do custo; deixar Prophet/LSTM para V3+.
2. **Sensor virtual como `sensor` não `binary_sensor`:** probabilidade contínua permite automação por threshold no HA sem novo deploy.
3. **Reusar `THUMBNAIL_HISTORY_SIZE`/`CLIP_HISTORY_SIZE` como janela de treino:** evitar nova retenção; documentar.
4. **Expor predição também em `GET /predictions?camera_id=` (REST):** facilita debug sem MQTT.
5. **Notificação via `telegram` opcional:** mesma sugestão pode ir por Telegram se `DEFAULT_ROUTING` permitir; HA continua orquestrador.
6. **Métrica de acerto:** logar `predição vs. evento_real` em `predictor_metrics` (SQLite) para calibrar threshold — sem isso não há melhoria.
7. **Nome de tópico com `tucuxi/` não `secur/`:** marca nova vai para `tucuxi/`; manter `secur/` legado com bridge.

---

## 13. Dúvidas abertas

- D1: Predição por **câmera** ou por **zona**? Zona é mais acionável (ex: portão vs. quintal), mas câmera é mais simples no MVP.
- D2: Janela temporal fixa (ex: próxima 1h) ou deslizante (próximos 60 min a cada 15 min)?
- D3: Modelo deve considerar **dia da semana** desde o MVP ou só hora do dia?
- D4: Probabilidade é de **qualquer movimento** ou por **event_type** (pessoa vs. veículo vs. animal)?
- D5: HA deve criar **sensor por câmera** ou **sensor por zona** (multiplica entidades)?
- D6: Feedback `recusar` deve **suprimir para sempre**, por **N dias**, ou até **threshold mudar**?
- D7: Preditor consome **SQLite** (histórico persistido) ou **memória** (só eventos desde boot)?

---

## 14. Decisões pendentes (precisam de dono e data)

| # | Decisão | Opções | Impacto | Dono | Prazo |
|---|---|---|---|---|---|
| P1 | Onde roda o preditor no MVP? | **DECIDIDO: submodule `tucuxi-predictor` (A no MVP, embalagens B/HA reutilizam mesma lib)** | Infra, LGPD, Pi | Arquitetura | 2026-09-06 |
| P2 | Tópico canônico de evento | manter `homeassistant/secur/alert` + novo `tucuxi/camera/+/event` vs. migrar tudo para `tucuxi/` | Compatibilidade HA existente | Produto | antes do plano |
| P3 | Tipo de sensor HA | `sensor` probabilidade 0-1 vs. `binary_sensor` com threshold | UX automação | HA/UX | V1 |
| P4 | Threshold e cooldown de sugestão | global (`PREDICTION_THRESHOLD=0.75`) vs. por câmera/zona vs. adaptativo por feedback | Falso-positivo | Produto | V3 |
| P5 | Formato de horário | UTC vs. local (`America/Sao_Paulo`) em `timestamp`/`janela` | Bug de fuso | Dev | V1 |
| P6 | Retenção para treino | 7 dias vs. 30 dias vs. configurável `PREDICTOR_HISTORY_DAYS` | Precisão vs. disco | Dev | V1 |
| P7 | Notificação sugestiva vs. criação automática | só notifica vs. cria automação rascunho vs. cria direto | Risco de automação indesejada | Produto/LGPD | V3 |
| P8 | Nome da marca em tópicos/entidades | `tucuxi` vs. `secur` | Branding | Branding | antes do plano |
| P9 | Fail-secure sem HA | assumir último armado vs. desarmado vs. pausar atuação | Segurança em queda de rede | Arquitetura | V1 |

**Critério de desempate (AGENTS.md):** priorizar valor perceptível + menor custo + operação 100% local.

---

## 15. Próximos passos para aprovar este design

1. Responder D1-D7 e decidir P2-P8 (P1 já decidida: submodule — ver §6) — sem isso o plano ficará com `TBD`.
2. Validar tópicos/payloads com um HA de teste (Mosquitto + `mqtt.sensor` manual + caso "rosa → aspersor 5min" §4.3).
3. Se aprovado, invocar `superpowers:writing-plans` para gerar plano com tasks 2-5 min (arquivos, testes, env vars).

---

## 16. Referências

- `SPEC.md` — escopo MVP, arquitetura, roadmap 80 câmeras (funil N0-N4)
- `docs/roadmap.md` — backlog Frigate, escala, portaria
- `docs/technical.md:160` — env vars MQTT/HA atuais
- `docs/architecture-80-cameras.md` — borda leve + central de análise (preditor futuro na central N3/N4)
- `src/notifications.py:3` — canais `telegram`/`automation`, `DEFAULT_ROUTING`
