# Telegram Commands — Design Spec

## Problema

O bot Telegram atual é unidirecional: envia alertas mas não responde a comandos. O usuário precisa de interatividade básica para consultar status e capturar snapshots remotamente.

## O que já existe

- `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID` configurados via `.env`
- `telegram_handler` em `src/alerts.py` — envia alertas (texto e foto)
- `init_telegram` — mensagem de startup
- `alarm_mode_telegram_handler` — notifica mudanças de modo de alarme
- API Telegram acessível via `requests` (já dependência do projeto)

## O que construir

### Comandos

| Comando | Descrição |
|---------|-----------|
| `/start` | Mensagem de boas-vindas com lista de comandos |
| `/status` | Resumo: câmeras ativas, modo de alarme, último evento |
| `/snapshot <id\|nome>` | Captura e envia snapshot da câmera especificada |

### Arquitetura

1. **Nova função `telegram_command_handler`** em `src/alerts.py`
   - Usa `getUpdates` do Telegram API para polling
   - Processa comandos: `/start`, `/status`, `/snapshot`
   - Valida `chat_id` contra `TELEGRAM_CHAT_ID`

2. **Thread de polling** em `src/main.py`
   - Roda em background com `threading.Thread(daemon=True)`
   - Intervalo de polling: 1-2 segundos
   - Não bloqueia o app principal

3. **Captura de snapshot**
   - Acessa `CameraWorker` correspondente via `CameraManager`
   - Captura frame atual do vídeo
   - Envia como foto via `sendPhoto`

### Segurança

- Apenas o `TELEGRAM_CHAT_ID` configurado pode usar os comandos
- Outros chat_ids recebem mensagem de acesso negado
- Comandos são processados apenas uma vez (offset tracking)

## Modelo de dados

Não há mudança de schema. Os dados necessários já existem:
- `camera_sensitivity` — status das câmeras
- `EventStorage` — último evento
- `CameraManager` — workers ativos

## Rotas API

Não há novas rotas HTTP. Comunicação é via Telegram API (polling).

## Riscos

- **Performance**: polling constante pode consumir recursos → mitigado com intervalo de 1-2s
- **Segurança**: chat_id pode ser falsificado → mitigado com validação strict
- **Snapshots**: câmera pode estar offline → tratamento de erro com mensagem amigável

## Testes

- Testes unitários para parsing de comandos
- Testes de integração com mocks do Telegram API
- Teste de validação de chat_id
