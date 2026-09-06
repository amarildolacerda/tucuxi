# Integração Tucuxi + Home Assistant + AI Preditiva — Design

> **Status:** RASCUNHO para amadurecimento — contém sugestões, dúvidas e decisões pendentes.
> **Data:** 2026-09-06
> **Autor:** brainstorming Tucuxi
> **Base:** `SPEC.md`, `docs/roadmap.md`, `docs/technical.md`, `src/alerts.py`, `src/events.py`, `src/notifications.py`

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

**C. Home Assistant (consumidor)**
- `mqtt.sensor` / `mqtt.binary_sensor` para predição + `mqtt.device_automation` ou `persistent_notification` interativa para sugestão.
- Automação criada só após aceite explícito do usuário (sem auto-criação silenciosa).

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

---

## 6. Abordagens possíveis (trade-offs)

### Abordagem A — Preditor embarcado no Tucuxi (Recomendada para MVP)

- **Como:** novo módulo `src/predictor.py` assina `LocalEventQueue` e lê `storage.py`; modelo EWMA/média móvel + histograma por hora (sem ML pesado); publica via `paho.mqtt.publish.single` no mesmo broker.
- **Prós:** 100% local/LGPD, sem infra extra, reusa `config.py` e `events.py`, funciona no Pi, deploy único (`docker compose`).
- **Contras:** limitado a modelos leves; não escala para 80 câmeras (mas MVP é 1-4).
- **Quando usar:** MVP e instalações residenciais/pequeno condomínio.

### Abordagem B — Preditor como serviço separado (container/VM)

- **Como:** serviço Python/Node isolado (`services/predictor/`), consome MQTT `tucuxi/camera/+/event` e SQLite via volume ou HTTP `GET /events`; modelos Prophet/ARIMA leves; publica em `tucuxi/predictions/+`.
- **Prós:** desacopla CPU do edge; pode rodar em NAS/servidor local; permite trocar modelo sem rebuild do Tucuxi.
- **Contras:** +1 container para operar; precisa discovery do broker; versionamento de schema entre serviços.
- **Quando usar:** condomínio com 8+ câmeras ou quando Pi fica no limite.

### Abordagem C — Preditor em nuvem opcional

- **Como:** edge publica eventos anonimizados (sem thumbnail) para endpoint HTTPS; cloud treina modelo e devolve predição via MQTT bridge ou webhook.
- **Prós:** modelos mais pesados (LSTM, transformers temporais), dashboard analytics.
- **Contras:** fere "100% local" do README, exige consentimento LGPD, depende de internet, custo.
- **Quando usar:** só se usuário opt-in explícito; não para MVP.

**Recomendação:** começar em **A** (módulo interno com interface `Predictor` desacoplada), desenhado para extrair para **B** sem quebrar HA (mesmos tópicos). **C** fica como extensão futura opt-in.

---

## 7. Arquitetura sugerida (isolamento e testabilidade)

```
src/
  events.py          # CameraEvent (adicionar campos predição opcional)
  predictor/
    __init__.py      # interface Predictor: predict(camera, window) -> Prediction
    ewma.py          # EWMA 7/30 dias por (camera, zona, hora, event_type)
    store.py         # leitura agregada de storage (contagem por bucket horário)
    publisher.py     # publica tucuxi/predictions/+ via MQTT
    suggester.py     # decide se notifica HA (threshold + cooldown + feedback)
```

Princípios (AGENTS.md):
- Cada unidade com uma responsabilidade, interface bem definida, testável isolada.
- Preditor não conhece HA; só publica MQTT. HA decide UI/automação.
- `AlertRuleEngine` existente continua para eventos reativos; preditor é paralelo, não substitui.

Diagrama lógico:

```
[Camera workers] → [EventQueue] → [AlertRuleEngine] → handlers (MQTT/HA/Telegram)
                      ↓
                 [Predictor Store] → [EWMA Model] → [Publisher] → MQTT tucuxi/predictions/+
                      ↑                                      ↓
                 [SQLite events]                      [HA mqtt.sensor]
                                                         ↓
                                                   [Suggester] → persistent_notification
                                                         ↓
                                                   [feedback] → tucuxi/feedback/+
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
| `secur/{id}/state` | Tucuxi → HA | true | 0 | motion/idle (existente) |

Auto-discovery HA para predição: publicar `homeassistant/sensor/tucuxi_{slug}_prediction/config` com `state_topic: tucuxi/predictions/{slug}`.

---

## 9. Roadmap incremental (alinhado ao `docs/roadmap.md`)

1. **MVP (2-3 semanas):** Tucuxi publica `tucuxi/camera/+/event` v1 + Preditor EWMA embarcado (A) + `tucuxi/predictions/+` + HA `mqtt.sensor` manual. Sem sugestão automática.
2. **V2 (predição robusta):** histograma por dia_semana, confiança do modelo, `expira_em`, threshold configurável por câmera/zona (`src/config.py`), extraível para serviço B.
3. **V3 (sugestão acionável):** `suggester.py` + `persistent_notification` com ações + tópico `tucuxi/feedback`; cooldown por sugestão (reuso `ALERT_COOLDOWN_*`).
4. **V4 (extensões):** agrícola (pragas, irrigação), energia, 80 câmeras (preditor na central N3/N4 de `architecture-80-cameras.md`), opt-in cloud.

Cada fase com flag `PREDICTOR_ENABLED=false` por padrão.

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
| P1 | Onde roda o preditor no MVP? | A embarcado / B serviço separado / C cloud opt-in | Infra, LGPD, Pi | Arquitetura | antes do plano |
| P2 | Tópico canônico de evento | manter `homeassistant/secur/alert` + novo `tucuxi/camera/+/event` vs. migrar tudo para `tucuxi/` | Compatibilidade HA existente | Produto | antes do plano |
| P3 | Tipo de sensor HA | `sensor` probabilidade 0-1 vs. `binary_sensor` com threshold | UX automação | HA/UX | V1 |
| P4 | Threshold e cooldown de sugestão | global (`PREDICTION_THRESHOLD=0.75`) vs. por câmera/zona vs. adaptativo por feedback | Falso-positivo | Produto | V3 |
| P5 | Formato de horário | UTC vs. local (`America/Sao_Paulo`) em `timestamp`/`janela` | Bug de fuso | Dev | V1 |
| P6 | Retenção para treino | 7 dias vs. 30 dias vs. configurável `PREDICTOR_HISTORY_DAYS` | Precisão vs. disco | Dev | V1 |
| P7 | Notificação sugestiva vs. criação automática | só notifica vs. cria automação rascunho vs. cria direto | Risco de automação indesejada | Produto/LGPD | V3 |
| P8 | Nome da marca em tópicos/entidades | `tucuxi` vs. `secur` | Branding | Branding | antes do plano |

**Critério de desempate (AGENTS.md):** priorizar valor perceptível + menor custo + operação 100% local.

---

## 15. Próximos passos para aprovar este design

1. Responder D1-D7 e decidir P1-P8 (tabela acima) — sem isso o plano ficará com `TBD`.
2. Validar tópicos/payloads com um HA de teste (Mosquitto + `mqtt.sensor` manual).
3. Se aprovado, invocar `superpowers:writing-plans` para gerar plano com tasks 2-5 min (arquivos, testes, env vars).

---

## 16. Referências

- `SPEC.md` — escopo MVP, arquitetura, roadmap 80 câmeras (funil N0-N4)
- `docs/roadmap.md` — backlog Frigate, escala, portaria
- `docs/technical.md:160` — env vars MQTT/HA atuais
- `docs/architecture-80-cameras.md` — borda leve + central de análise (preditor futuro na central N3/N4)
- `src/notifications.py:3` — canais `telegram`/`automation`, `DEFAULT_ROUTING`
