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

Três estados, canônico em `alarm_control_panel` + **espelho em switch virtual on/off para voz** (Alexa/Google/Assist):

| Modo Tucuxi | Estado HA canônico | Switch virtual (voz) | Quando usar | Comportamento |
|---|---|---|---|---|
| **Alarme desarmado** | `disarmed` | `switch.tucuxi_alarme` OFF | Em casa, rotina normal | Monitoramento leve: só eventos críticos (`intruder`, `fall`, `loitering`) geram alerta; atuadores (aspersor) **não** disparam; predição continua aprendendo mas não sugere |
| **Alarme armado** | `armed_home` | `switch.tucuxi_alarme` ON | Presente, mas com pontos de segurança ativos | Monitora pontos de segurança mapeados (ex: rosa): movimento → atua (aspersor 5min) + alerta; demais zonas só registram |
| **Viagem** | `armed_away` | `switch.tucuxi_viagem` ON (override) | Casa vazia | **Qualquer ponto alerta** (sensibilidade máxima, sem filtro de zona) + **simulação de presença** (luzes ligam/desligam por rotina aprendida) + notificação imediata Telegram/HA |

Detalhes:
- **Alarme armado (presente):** evita disparo contra morador — só zonas `segurança/privativa` no `entity_map` com `alarm_required: true` atuam. Ex: rosa → aspersor; portão → luz; quintal interno ignora.
- **Viagem:** `suggester` suprimido (sem "deseja automatizar?"); tudo vira ação direta. Simulação de presença usa `tucuxi/predictions/+` invertido: publica `tucuxi/automation/actuator` para `light.*` nos horários de maior P(movimento) histórico — parece que há gente em casa.
- **Switch virtual para voz:** `switch.tucuxi_alarme` (MQTT switch, retain) espelha `armed_home/disarmed`; `switch.tucuxi_viagem` espelha `armed_away`. Voz: *"Alexa, ligar alarme"* → ON; *"desligar alarme"* → OFF; *"ativar modo viagem"* → ON viagem. HA expõe via `cloud: alexa/google` ou Assist sem PIN (atuador, não alarme com código).
- Troca de modo: voz/HA (`switch` ou `alarm_control_panel`) ou dashboard Tucuxi (`PUT /api/mode` futuro → espelha em `tucuxi/ha/alarm_mode` retain). Predictor subscreve `tucuxi/ha/alarm_mode` e condiciona P(evento | modo). `switch` ↔ `alarm_control_panel` sincronizados por automação bidirecional (§5.8).
- Fallback: se `tucuxi/ha/alarm_mode` stale (>60s) ou HA offline, predictor assume **último modo armado** (fail-secure) e loga; nunca assume `disarmed` por ausência de mensagem.

Exemplo viagem:
```
HA: alarm = armed_away → tucuxi/ha/alarm_mode {alarm_mode: armed_away}
Tucuxi cam quintal (zona pública, normalmente ignorada) —motion→ tucuxi/camera/quintal/event
→ modo viagem: publica tucuxi/automation/actuator {target: light.sala, action: turn_on, duration_sec: 1800}
→ Telegram: "Movimento quintal em modo viagem 22:14 + luz sala ligada (simulação)"
```

### 4.5 Composição do sistema + dissuasão perimetral (requisito 2026-09-06)

Objetivo: **dispersar o intruso antes do ambiente interno** — agir nas camadas externas com dissuasão progressiva, não só alertar quando já entrou.

**Camadas de defesa:**

```
[L0 entorno/rua] → [L1 perímetro (muro/portão)] → [L2 pontos de segurança (rosa, lateral, fundos)] → [L3 ambiente interno (porta/sala)]
     observar            detectar + dissuadir leve              dissuadir forte                    alarme total
```

**Sensores por camada (Tucuxi + HA):**

| Camada | Visão (Tucuxi) | Sensores HA (MQTT) | Atuadores de dissuasão |
|---|---|---|---|
| L1 perímetro | câmera portão/muro (YOLO pessoa/veículo) | PIR externo, beam infravermelho, contato de portão, LUX | luz perimetral ON, bip curto |
| L2 pontos de segurança | câmera rosa/lateral/fundos (zona segurança/privativa) | PIR + mmWave presença, contato janela lateral, vibração em grade | **irrigação/aspersor 5min** + sirene curta + holofote |
| L3 interno | câmera interna (privacidade: só em viagem/armado) | PIR interno, contato porta, sensor de vidro, fumaça/CO | sirene total + luzes + notificação + (futuro: fechadura) |

O que mais pode compor (backlog, mesmo barramento MQTT):
- Beam duplo perimetral (cerca virtual, menos falso-positivo que PIR sozinho).
- mmWave (presença parada — PIR falha com intruso imóvel).
- Sensor de vibração/quebra de vidro e contato de porta/janela (cruzam com visão: câmera diz "pessoa", contato diz "porta aberta" → confiança alta).
- LUX + clima (não ligar holofote de dia; não irrigar se chovendo — `weather.*` como inibidor).
- Áudio: buzzer/sirene TTS ("você está sendo filmado") como dissuasão verbal antes da sirene total.

**Escada de dissuasão (exemplo intruso vindo da rua):**
1. L1 (portão, 19:02): pessoa detectada → luz perimetral ON 10min + registra. Sem notificação (evita spam).
2. L2 (rosa, 19:04): cruzou ponto de segurança com alarme armado → **aspersor rosa 5min** + holofote + Telegram "dissuasão ativada na rosa".
3. L2 persistente (19:06, ainda presente/loitering): sirene curta 30s + TTS + `unknown/intruder` para HA.
4. L3 (porta, 19:07): contato + câmera → alarme total (sirene contínua, todas as luzes, Telegram + HA crítico).

Regras:
- Cada avanço de camada exige **confirmação cruzada** quando possível (visão + sensor físico) — reduz falso-positivo do aspersor (não molhar entregador/gato).
- Dissuasão L1-L2 **só com alarme armado ou viagem**; desarmado só observa (L1 registra, sem atuar).
- Cooldown por camada (`ALERT_COOLDOWN_*` + `PREDICTOR_DETER_COOLDOWN_SEC` default 15min p/ irrigação) evita aspersor ligado a cada gato.
- Inibidores: chuva (`weather`), dia claro (LUX alto → sem holofote), horário de visita/entrega conhecida (identidade reconhecida → nunca dissuade).

### 4.6 Inventário de ambientes (requisito 2026-09-06)

20 ambientes (13 externos + 7 internos) mapeados para camada + classificação de zona Tucuxi (pública/segurança/privativa — `src/event_rules.py`, CRUD `/zones`):

**Externos / perimetrais:**

| # | Ambiente | Slug | Camada | Classificação | Visão | Sensores HA | Dissuasão/atuador |
|---|---|---|---|---|---|---|---|
| 1 | Portão entrada | `portao_entrada` | L1 | segurança | cam pessoa/veículo | PIR externo, beam, contato portão, LUX | luz perimetral 10min, bip |
| 2 | Acesso ao jardim | `acesso_jardim` | L2 | segurança | cam pessoa | PIR + mmWave | holofote + aspersor jardim 5min |
| 3 | Rampa de acesso | `rampa` | L2 | segurança | cam pessoa/veículo | PIR, beam | luz rampa + sirene curta (persistente) |
| 4 | Estacionamento | `estacionamento` | L2 | segurança | cam veículo/pessoa | PIR, contato cancela/garagem | holofote + alerta |
| 5 | Firepit | `firepit` | L2/L3 social | segurança* | cam pessoa (máscara fogo p/ falso-positivo) | PIR, (futuro: calor/fumaça) | luz firepit, sem água |
| 6 | Entrada principal | `entrada_principal` | L3 | privativa | cam pessoa + identidade | PIR, contato porta, campainha | luz entrada + TTS + sirene (persistente) |
| 7 | Garagem | `garagem` | L2/L3 | segurança | cam veículo/pessoa | PIR, contato portão garagem | luz + alerta; sem aspersor |
| 8 | Lateral leste | `lateral_leste` | L1/L2 | segurança | cam pessoa | PIR + beam | holofote + aspersor leste 5min |
| 9 | Lateral norte | `lateral_norte` | L1/L2 | segurança | cam pessoa | PIR + beam | holofote + aspersor norte 5min |
| 10 | Lateral sul | `lateral_sul` | L1/L2 | segurança | cam pessoa | PIR + beam | holofote + aspersor sul 5min |
| 11 | Lateral oeste | `lateral_oeste` | L1/L2 | segurança | cam pessoa | PIR + beam | holofote + aspersor oeste 5min |
| 12 | Área social | `area_social` | L3 social | pública* | cam pessoa (modo privacidade respeitado) | PIR, (somente presença) | luz social, sem dissuasão agressiva |
| 13 | Piscina | `piscina` | L3 social | pública* | cam pessoa (máscara + retenção seletiva) | PIR, (futuro: sensor de queda na água) | luz piscina, sem aspersor/sirene direta |

Notas (externos):
- `* Firepit/área social/piscina`: classificação `pública` dentro do lote (convivência) mas com regras próprias — dissuasão agressiva (aspersor/sirene) **desligada** por padrão para não molhar convidados; em **viagem** viram `segurança` (qualquer presença alerta). Privacidade: `mask_polygons` + `PRIVACY_MODE` (`docs/technical.md:208`) e retenção seletiva por zona valem aqui.
- Laterais Leste/Norte/Sul/Oeste: mesma receita (PIR + beam + holofote + aspersor setorizado), só muda `slug` e `target_entity` (`switch.aspersor_leste` etc.) — permite confirmar direção do intruso (qual lateral cruzou primeiro).
- Rosa (exemplo anterior) = instância de `acesso_jardim` ou lateral — manter `rosa` como slug operacional ou renomear para `acesso_jardim`; decidir em P10.
- Cada ambiente = 1 zona Tucuxi (`/zones`) + 1 entrada no `entity_map` (§5.7) com `layer`, `modos_ativos`, `confirmacao_cruzada`, `inibidores`.

**Internos (L3 interno — privativa, sem câmera por padrão):**

| # | Ambiente | Slug | Camada | Classificação | Visão | Sensores HA | Ação |
|---|---|---|---|---|---|---|---|
| 14 | Dorm rosa | `dorm_rosa` | L3 interno | privativa | sem cam (só sensor) | PIR/mmWave, contato janela | alerta silencioso + luz corredor |
| 15 | Dorm azul | `dorm_azul` | L3 interno | privativa | sem cam | PIR/mmWave, contato janela | alerta silencioso + luz corredor |
| 16 | Dorm master | `dorm_master` | L3 interno | privativa | sem cam | PIR/mmWave, contato janela | alerta silencioso + luz corredor |
| 17 | Escritório | `escritorio` | L3 interno | privativa | sem cam (ou cam só em viagem) | PIR, contato janela, sensor PC/rede | alerta + luz |
| 18 | Sala social | `sala_social` | L3 interno | privativa | sem cam (ou cam só em viagem) | PIR/mmWave, contato porta | luz + sirene se persistir (armado/viagem) |
| 19 | Cozinha | `cozinha` | L3 interno | privativa | sem cam | PIR, contato porta, fumaça/CO/gás | luz + alerta; fumaça/gás = perigo eminente |
| 20 | Serviço | `servico` | L3 interno | privativa | sem cam | PIR, contato porta/janela, alagamento | luz + alerta; alagamento = imediato |

Notas (internos):
- **Sem câmera por padrão** — internos usam sensor físico (PIR/mmWave/contato) como fonte; visão só entra em **viagem** e mesmo assim opt-in por ambiente (P12). Motivo: LGPD/privacidade + `PRIVACY_MODE` + retenção seletiva.
- Comportamento por modo: **desarmado** = internos silenciosos (morador circula, só fumaça/gás/alagamento alertam); **alarme armado** (ex: noite) = contato/PIR interno alerta + luz, sem sirene total de imediato; **viagem** = qualquer PIR/contato interno = intrusão confirmada (já passou L1-L3) → sirene total + luzes + Telegram crítico.
- Cozinha/serviço acumulam **sensores ambientais** (fumaça/CO/gás, alagamento) — entram direto como "candidato confirmado" no N4 (`docs/roadmap.md:137`), independente de modo.
- Escritório: cruzar PIR + atividade de rede/PC fora de horário reforça confiança antes de alarmar.

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
  },
  "portao_l1": {
    "camera_id": 1,
    "layer": "L1_perimetro",
    "ha_sensor": "binary_sensor.pir_portao",
    "ha_actuator": "light.perimetral",
    "default_duration_sec": 600,
    "alarm_required": false,
    "modos_ativos": ["alarme_armado", "viagem"],
    "escalada": "luz_10min_sem_notificar"
  },
  "rosa_l2": {
    "camera_id": 2,
    "layer": "L2_seguranca",
    "ha_sensor": "binary_sensor.presenca_rosa",
    "ha_actuator": "switch.aspersor_rosa",
    "default_duration_sec": 300,
    "alarm_required": true,
    "modos_ativos": ["alarme_armado", "viagem"],
    "confirmacao_cruzada": ["camera", "pir"],
    "inibidores": ["chuva", "identidade_conhecida"],
    "escalada": "aspersor_5min__depois_sirene_30s",
    "cooldown_sec": 900
  }
}
```

Armazenado em `predictor/config/entity_map.json` (submodule) ou `PREDICTOR_ENTITY_MAP` env (JSON). Editável via `PUT /api/predictor/map` (futuro).

### 5.8 Switch virtual de modo para voz (HA ↔ Predictor)

Dois MQTT switches com discovery (retain) — espelho do `alarm_control_panel`, sem PIN, expostos para Alexa/Google/Assist:

| Entidade | ON | OFF | Tópicos |
|---|---|---|---|
| `switch.tucuxi_alarme` | `armed_home` (alarme armado) | `disarmed` | `tucuxi/mode/alarme/set` (cmd) / `tucuxi/mode/alarme/state` (state) |
| `switch.tucuxi_viagem` | `armed_away` (viagem) | volta ao anterior | `tucuxi/mode/viagem/set` / `tucuxi/mode/viagem/state` |

Discovery (publicado pelo predictor/Tucuxi, mesmo padrão de `mqtt_register_device` em `src/alerts.py:313`):

```json
// homeassistant/switch/tucuxi_alarme/config (retain)
{"name": "Tucuxi Alarme", "command_topic": "tucuxi/mode/alarme/set",
 "state_topic": "tucuxi/mode/alarme/state", "payload_on": "ON", "payload_off": "OFF",
 "unique_id": "tucuxi_alarme", "icon": "mdi:shield"}
```

Sincronia bidirecional (automação HA, `mode: single`):
- `switch.tucuxi_alarme ON` → `alarm_control_panel.alarm_arm_home` + `tucuxi/ha/alarm_mode {armed_home}`.
- `alarm_control_panel → armed_home` → publica `ON` em `tucuxi/mode/alarme/state`.
- `switch.tucuxi_viagem ON` tem prioridade (override); OFF volta ao estado do alarme.
- Voz: *"ligar alarme"*, *"desligar alarme"*, *"ativar modo viagem"* — sem código, pois é switch e não alarme com PIN. PIN continua exigido se armar pelo `alarm_control_panel` direto.

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
| `tucuxi/ha/alarm_mode` | HA → Preditor | true | 0 | disarmed/armed_home/armed_away + modo_tucuxi |
| `tucuxi/mode/alarme/set` | HA/voz → Preditor | false | 0 | ON/OFF (switch virtual alarme) |
| `tucuxi/mode/alarme/state` | Preditor → HA | true | 0 | ON/OFF (retain, voz lê aqui) |
| `tucuxi/mode/viagem/set` | HA/voz → Preditor | false | 0 | ON/OFF (switch virtual viagem) |
| `tucuxi/mode/viagem/state` | Preditor → HA | true | 0 | ON/OFF (retain) |
| `tucuxi/automation/actuator` | Preditor → HA | false | 0 | turn_on + target_entity + duration_sec (generaliza sirene) |
| `secur/automation/siren` | Tucuxi → HA | false | 0 | siren legado (`SIREN_MQTT_TOPIC`) |
| `secur/{id}/state` | Tucuxi → HA | true | 0 | motion/idle (existente) |

Auto-discovery HA para predição: publicar `homeassistant/sensor/tucuxi_{slug}_prediction/config` com `state_topic: tucuxi/predictions/{slug}`. Para voz: `homeassistant/switch/tucuxi_alarme/config` + `homeassistant/switch/tucuxi_viagem/config` (§5.8).

---

## 9. Roadmap incremental (alinhado ao `docs/roadmap.md`) — com submodule + atuadores HA

1. **MVP (2-3 semanas):** criar repo `tucuxi-predictor` + `git submodule add src/predictor` + Tucuxi publica `tucuxi/camera/+/event` v1 + Preditor EWMA (embalagem A) + `tucuxi/predictions/+` + HA `mqtt.sensor` manual + **modos §4.4** (`tucuxi/ha/alarm_mode` + `entity_map.modos_ativos`) + **dissuasão L1→L2 §4.5** (luz perimetral + aspersor rosa com confirmação câmera+PIR e inibidor chuva). **Sem sugestão automática, mas já com `actuator.py` para "rosa → aspersor 5min" (alarme armado) e simulação de presença básica (viagem) via `tucuxi/automation/actuator`.**
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
- **Dissuasão contra inocente (entregador, gato, morador):** aspersor/sirene disparam sem necessidade. Mitigar com confirmação cruzada (visão + PIR/beam), identidade conhecida como inibidor total, LUX/clima como inibidor parcial, e escada L1→L2→L3 (luz antes de água, água antes de sirene).
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
| P10 | Slug `rosa` vs. inventário §4.6 | manter `rosa` como alias de `acesso_jardim` vs. renomear tudo | Compatibilidade entity_map/automações | Produto | V1 |
| P11 | Câmeras em área social/piscina | 1 cam por ambiente vs. cam compartilhada vs. sem cam (só PIR) | Privacidade/LGPD, custo | Produto/LGPD | V1 |
| P12 | Câmeras em internos (dorms/escritório/sala/cozinha/serviço) | sem cam (só sensor) vs. cam só em viagem (opt-in) vs. cam sempre | Privacidade/LGPD | Produto/LGPD | V1 |

**Critério de desempate (AGENTS.md):** priorizar valor perceptível + menor custo + operação 100% local.

---

## 15. Próximos passos para aprovar este design

1. Responder D1-D7 e decidir P2-P12 (P1 já decidida: submodule — ver §6) — sem isso o plano ficará com `TBD`.
2. Validar tópicos/payloads com um HA de teste (Mosquitto + `mqtt.sensor` manual + caso "rosa → aspersor 5min" §4.3).
3. Se aprovado, invocar `superpowers:writing-plans` para gerar plano com tasks 2-5 min (arquivos, testes, env vars).

---

## 16. Referências

- `SPEC.md` — escopo MVP, arquitetura, roadmap 80 câmeras (funil N0-N4)
- `docs/roadmap.md` — backlog Frigate, escala, portaria
- `docs/technical.md:160` — env vars MQTT/HA atuais
- `docs/architecture-80-cameras.md` — borda leve + central de análise (preditor futuro na central N3/N4)
- `src/notifications.py:3` — canais `telegram`/`automation`, `DEFAULT_ROUTING`
