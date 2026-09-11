# MQTT Alarm Mode Sync — Spec de funcionamento

**Data:** 2026-09-11
**Status:** Implementado
**Escopo:** Sincronização bidirecional de modos de alarme entre Home Assistant e Tucuxi via MQTT.

## 1. Propósito

O Tucuxi sincroniza o estado do alarme com Home Assistant via dois switches MQTT:
- **Tucuxi Alarme** → `armed_home` (alarme residencial)
- **Tucuxi Viagem** → `armed_away` (alarme de viagem)

O usuário alterna os switches no HA; o Tucuxi processa, deriva o modo, e notifica via Telegram.

## 2. Arquitetura de tópicos

```
┌─────────────┐     command_topic      ┌──────────────┐
│  HA Switch   │ ──────────────────────▶│  Tucuxi      │
│  (Alarme)    │ ◀──────────────────────│  Subscriber  │
│              │      state_topic       │  (_mqtt_     │
└─────────────┘                         │   client_sub)│
                                        └──────┬───────┘
                                               │
                                        ┌──────▼───────┐
                                        │  Predictor   │
                                        │  Loop        │
                                        └──────┬───────┘
                                               │
                                        ┌──────▼───────┐
                                        │  Telegram    │
                                        │  Notification│
                                        └──────────────┘
```

### Tópicos

| Tópico | Direção | Conteúdo | Retido? |
|--------|---------|----------|---------|
| `tucuxi/mode/alarme/set` | HA → Tucuxi | `ON` / `OFF` | não |
| `tucuxi/mode/alarme/state` | Tucuxi → HA | `ON` / `OFF` | sim |
| `tucuxi/mode/viagem/set` | HA → Tucuxi | `ON` / `OFF` | não |
| `tucuxi/mode/viagem/state` | Tucuxi → HA | `ON` / `OFF` | sim |
| `tucuxi/ha/alarm_mode` | Tucuxi → HA | `{"alarm_mode": "armed_home"}` | sim |

## 3. Lógica de derivação do modo

O modo é derivado dos estados dos dois switches:

```
viagem ON  → armed_away   (prioridade máxima)
alarme ON  → armed_home   (se viagem OFF)
ambos OFF  → disarmed
```

**Regra de desarme único:** `alarme OFF` força `viagem OFF` também.
Um único toque no switch Alarme desarma tudo.

## 4. Handlers MQTT (`src/main.py`)

### `_on_alarme_set_msg`
- Recebe `ON`/`OFF` de `tucuxi/mode/alarme/set`
- Atualiza `_predictor._alarme_on`
- Publica estado em `tucuxi/mode/alarme/state`
- Se OFF: força `_predictor._viagem_on = False` e publica `viagem/state = OFF`
- Deriva modo e publica em `tucuxi/ha/alarm_mode`
- Chama `alarm_mode_telegram_handler()` → notifica Telegram

### `_on_viagem_set_msg`
- Recebe `ON`/`OFF` de `tucuxi/mode/viagem/set`
- Atualiza `_predictor._viagem_on`
- Publica estado em `tucuxi/mode/viagem/state`
- Deriva modo e publica em `tucuxi/ha/alarm_mode`
- Chama `alarm_mode_telegram_handler()` → notifica Telegram

### `_on_alarm_msg` (handler genérico)
- Recebe mensagens de tópicos sem callback específico
- Usado para mensagens vindas do HA (ex.: `alarm_control_panel`)
- No startup, pula a primeira mensagem (sync inicial) para evitar Telegram duplicado

## 5. Notificação Telegram (`src/alerts.py`)

`alarm_mode_telegram_handler(payload)` envia uma mensagem quando o modo muda:

| Modo | Mensagem |
|------|----------|
| `armed_home` | 🔒 Alarme armado |
| `armed_away` | 🔒 Alarme Viagem armado |
| `disarmed` | 🔓 Alarme desarmado |

## 6. Auto-discovery HA (`mqtt_register_predictor_entities`)

Registra no HA via MQTT auto-discovery:
- **Sensor:** `Tucuxi Alarme Mode` → `tucuxi/ha/alarm_mode`
- **Switch:** `Tucuxi Alarme` → command/state topics
- **Switch:** `Tucuxi Viagem` → command/state topics

## 7. Estado inicial

No startup:
- `_predictor.alarm_mode = "armed_home"` (fail-secure)
- `_predictor._alarme_on = True`, `_predictor._viagem_on = False`
- Publica switch states iniciais para HA refletir estado correto
- Publica `{"alarm_mode": "armed_home"}` no sensor

## 8. Subscriptions MQTT

O `_mqtt_client_sub` subscreve apenas:
- `tucuxi/mode/alarme/set`
- `tucuxi/mode/viagem/set`

**NÃO** subscreve a `tucuxi/mode/alarme/state` nem `tucuxi/mode/viagem/state`
(porque o Tucuxi publica nesses tópicos — subscrever causaria loop de feedback).

## 9. Problemas resolvidos

### 9.1 Telegram duplicado (werkzeug reloader)
**Problema:** `app.run(debug=True)` causa fork do werkzeug, criando dois processos.
Cada processo cria `_mqtt_client_sub` → duas subscriptions → duas notificações.

**Solução:** `use_reloader=False` — mantém debug mode (pin, debugger) mas roda em
processo único.

### 9.2 Telegram duplicado (feedback loop)
**Problema:** `_mqtt_client_sub` subscrevia `viagem/state` — quando o handler publicava
o estado, o `_on_alarm_msg` capturava → segunda notificação.

**Solução:** Remover subscription de `viagem/state` e `alarme/state`. Tucuxi é produtor
desses tópicos, não consumidor.

### 9.3 Telegram duplicado (redundant subscribes)
**Problema:** Subscriptions diretas fora do `on_connect` callback duplicavam as
subscriptions já feitas no callback.

**Solução:** Remover subscribes diretas, manter apenas as no `on_connect`.

## 10. Commits

| Commit | Descrição |
|--------|-----------|
| `e40027f` | Adiciona `alarm_mode_telegram_handler` nos handlers de alarme/viagem |
| `ffbbca8` | Remove subscription `viagem/state` (feedback loop) |
| `259d843` | `use_reloader=False` (duplicate MQTT clients) |
| `d5b3c4a` | Simplifica mensagens Telegram |
