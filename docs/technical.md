# Tucuxi Monitor — Referência técnica

> Código-fonte em `src/` (importações: `from src.main import main`). O comando CLI continua `secur`. O nome comercial é Tucuxi Monitor.

## Visão geral

O projeto captura vídeo de câmeras IP, realiza detecção de movimento e classificação de objetos em tempo real usando IA, e gera alertas configuráveis para eventos de segurança. Desenvolvido inicialmente em Linux, com deploy planejado para Raspberry Pi.

## Escopo do MVP

- Captura de vídeo de até 4 câmeras IP simultâneas.
- Detecção de movimento e classificação básica de objetos.
- Definição de zonas de interesse e regras configuráveis.
- Alertas por Telegram.
- Dashboard web simples para visualização e histórico.

## Requisitos

### Funcionais

- Capturar streams RTSP/HTTP de câmeras IP.
- Detectar movimento em cada stream.
- Classificar objetos em pessoas, veículos e animais.
- Configurar zonas de interesse e horários sensíveis.
- Gerar alertas quando regras de segurança forem violadas.
- Registrar eventos com timestamp, câmera, tipo de evento e imagem de evidência.
- Expor dashboard web para monitoramento em tempo real.

### Não funcionais

- Processamento em tempo real com latência baixa (<2s de atraso aceitável no MVP).
- Uso eficiente de CPU/RAM para funcionar em Raspberry Pi 4.
- Modularidade para trocar modelos de IA e adicionar canais de alerta.
- Operação local sem depender exclusivamente da nuvem.
- Persistência de eventos em banco leve para buscas rápidas.

## Arquitetura proposta

- Captura de vídeo: OpenCV + ffmpeg/RTSP.
- IA: modelo YOLOv5/YOLOv8 ou TensorFlow Lite para inferência de objetos.
- Orquestração de câmeras: multiprocessing ou asyncio para cada stream.
- Persistência: SQLite para eventos; opcional InfluxDB para séries temporais.
- Backend: Flask ou FastAPI para APIs e dashboard.
- Frontend: interface web leve com gráficos e visualização de câmeras.
- Alertas: Telegram (e-mail/webhook em melhorias futuras) e integração futura com Home Assistant.

## Requisitos de sistema

### Hardware recomendado

- PC/Linux para desenvolvimento inicial.
- Raspberry Pi 4 com 4GB ou 8GB de RAM para deploy final.
- Módulo de armazenamento rápido (SSD USB ou cartão microSD de alta classe).
- Fonte de energia adequada para Pi e periféricos.
- Rede estável via Ethernet preferencialmente; Wi-Fi como alternativa.
- Câmeras IP com RTSP/HTTP e resolução compatível (720p recomendado).

### Software recomendado

- Linux (Ubuntu, Debian, Fedora) para desenvolvimento inicial.
- Raspberry Pi OS 64-bit para o deploy final.
- Python 3.11+.
- OpenCV.
- PyTorch, TensorFlow Lite ou ONNX Runtime.
- Flask ou FastAPI.
- SQLite.

## Como rodar

### Com Docker

1. Certifique-se de que o Docker Desktop está instalado e o daemon está rodando.
2. Construa a imagem:
   ```bash
   docker build -t secur-app .
   ```
3. Execute o container:
   ```bash
   docker run --rm -p 8000:8000 -v "${PWD}:/app" -v "${PWD}/data:/app/data" \
     -e SERVER_HOST=0.0.0.0 \
     -e SERVER_PORT=8000 \
     -e TELEGRAM_BOT_TOKEN=your_bot_token \
     -e TELEGRAM_CHAT_ID=your_chat_id \
     -e HOME_ASSISTANT_URL=http://192.162.1.12:8123 \
     -e HOME_ASSISTANT_TOKEN=your_ha_token \
     -e HOME_ASSISTANT_EVENT_TYPE=secur_alert \
     secur-app
   ```
4. Opcionalmente, use docker compose:
   ```bash
   docker compose up --build
   ```
5. Acesse:
   - `http://localhost:8000/health`
   - `http://localhost:8000/status`
   - `http://localhost:8000/cameras`
   - `http://localhost:8000/events`

### Localmente

1. Instale dependências:
   ```bash
   py -m pip install -r requirements.txt
   ```
2. Baixe um vídeo de teste:
   ```bash
   py scripts/download_sample_video.py
   ```
   Ou execute o arquivo de atalho:
   ```bash
   download_sample_video.bat
   ```
   Se ainda houver erro HTTP 403, baixe manualmente um MP4 de exemplo para `data/sample.mp4`.
3. Configure as câmeras no dashboard usando o arquivo local:
   - `source`: `C:\git\tucuxi\data\sample.mp4` (Windows)
   - ou `/path/to/project/data/sample.mp4` (Linux)
4. Defina o caminho do modelo de detecção de objetos (opcional) em `DETECTOR_MODEL_PATH`.
5. Configure as variáveis de ambiente do Telegram:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
6. Configure o MQTT do Home Assistant (inicial):
   - `MQTT_BROKER_URL` (padrão: `192.162.1.12`)
   - `MQTT_BROKER_PORT` (padrão: `1883`)
   - `MQTT_USERNAME` (padrão: `kzuca`)
   - `MQTT_PASSWORD` (padrão: `123`)
   - `MQTT_TOPIC` (padrão: `homeassistant/secur/alert`)
7. Configure as variáveis de ambiente do Home Assistant HTTP opcional:
   - `HOME_ASSISTANT_URL` (ex: `http://192.162.1.12:8123`)
   - `HOME_ASSISTANT_TOKEN`
   - `HOME_ASSISTANT_EVENT_TYPE` (opcional, padrão `secur_alert`)
8. Inicie o servidor:
   ```bash
   python run.py
   ```
9. Alternativa com instalação do pacote:
   ```bash
   python -m pip install .
   secur
   ```
10. Acesse:
    - `http://localhost:8000/`
    - `http://localhost:8000/health`
    - `http://localhost:8000/status`
    - `http://localhost:8000/workers`
    - `http://localhost:8000/docs`
    - `http://localhost:8000/cameras`
    - `http://localhost:8000/events`

### Com Makefile

- Instalar dependências: `make install`
- Executar localmente: `make run`
- Executar testes unitários e de integração: `make test`
- Executar toda a verificação do projeto (build Docker + teste): `make check`
- Executar todos os passos de verificação e build: `make all`
- Construir imagem Docker: `make docker-build`
- Subir container Docker: `make docker-up`
- Parar container Docker: `make docker-down`

## Variáveis de ambiente (config.py)

| Variável | Padrão | Descrição |
|---|---|---|
| `SERVER_HOST` | `0.0.0.0` | Host do servidor web |
| `SERVER_PORT` | `8000` | Porta do servidor web |
| `DETECTOR_MODEL_PATH` | (vazio) | Caminho do modelo ONNX de detecção |
| `DETECTOR_CONFIDENCE` | `0.25` | Limiar de confiança da detecção |
| `DETECTOR_IOU` | `0.45` | Limiar IoU da detecção |
| `MOTION_MIN_AREA` | `5000` | Área mínima de movimento (px) |
| `FRAME_WAIT_SECONDS` | `0.1` | Intervalo entre frames processados |
| `WORKER_HEALTHY_TIMEOUT` | `15` | Segundos sem frame para câmera não-saudável |
| `NO_MOTION_ALERT_SECONDS` | `60` | Alerta "sem movimento" após N segundos |
| `ALERT_COOLDOWN_SECONDS` | `60` | Cooldown global entre alertas do mesmo tipo |
| `ALERT_COOLDOWN_INTRUDER` | `30` | Cooldown do evento intruder |
| `ALERT_COOLDOWN_UNKNOWN` | `30` | Cooldown do evento unknown |
| `ALERT_COOLDOWN_LOITERING` | `300` | Cooldown do evento loitering |
| `ALERT_COOLDOWN_DIRECTION` | `60` | Cooldown do evento direction_change |
| `ALERT_COOLDOWN_FALL` | `30` | Cooldown do evento fall |
| `THUMBNAIL_INTERVAL_SECONDS` | `20` | Intervalo mínimo entre thumbnails |
| `THUMBNAIL_DIFF_THRESHOLD` | `3.0` | Dedup: diferença mínima por pixel (grayscale 64x64) |
| `THUMBNAIL_HISTORY_SIZE` | `30` | Nº de thumbnails mantidos por câmera |
| `CLIP_PRE_SECONDS` | `10` | Pré-gravação do clipe (s) |
| `CLIP_POST_SECONDS` | `10` | Pós-gravação do clipe (s) |
| `CLIP_FPS` | `5` | FPS do clipe |
| `CLIP_HISTORY_SIZE` | `20` | Nº de clipes mantidos por câmera |
| `IDENTITY_ENABLED` | `false` | Habilita reconhecimento de identidade |
| `IDENTITY_FACE_MODEL_PATH` | (vazio) | Modelo de detecção facial |
| `IDENTITY_REID_MODEL_PATH` | (vazio) | Modelo ReID |
| `IDENTITY_MATCH_THRESHOLD` | `0.6` | Limiar de similaridade para identidade |
| `PRIVACY_MODE` | `false` | Modo privacidade (desliga identidade) |
| `HOME_ASSISTANT_URL` | `http://192.168.1.12:8123` | URL do Home Assistant |
| `HOME_ASSISTANT_TOKEN` | (vazio) | Token do Home Assistant |
| `HOME_ASSISTANT_EVENT_TYPE` | `secur_alert` | Tipo de evento no HA |
| `MQTT_BROKER_URL` | `192.168.1.12` | Broker MQTT |
| `MQTT_BROKER_PORT` | `1883` | Porta MQTT |
| `MQTT_USERNAME` | `kzuca` | Usuário MQTT |
| `MQTT_PASSWORD` | `123` | Senha MQTT |
| `MQTT_TOPIC` | `homeassistant/secur/alert` | Tópico MQTT |
| `SIREN_MQTT_TOPIC` | `secur/automation/siren` | Tópico MQTT para o comando de sirene/atuação externa (Fase 5.1) |
| `SIREN_EVENT_TYPES` | `intruder_detected,fall_detected,loitering,direction_change,unknown_detected` | Tipos de evento que disparam a sirene (Fase 5.1) |
| `TRACK_IOU_THRESHOLD` | `0.3` | IoU do tracking |
| `TRACK_MAX_AGE_SECONDS` | `2.0` | Idade máxima do track |
| `LOITERING_SECONDS` | `30` | Tempo para loitering |
| `LOITERING_MAX_DISTANCE` | `80` | Distância máxima para loitering |
| `LOITERING_LABELS` | pessoa/veículos | Labels considerados para loitering |
| `FALL_ASPECT_RATIO` | `1.2` | Razão w/h para heurística de queda |

## Privacidade (detalhes técnicos)

- **100% local**: todo o processamento (detecção, reconhecimento, gravação) roda no dispositivo; nada sai dele, exceto pelos canais configurados (Telegram, MQTT, Home Assistant).
- **Mascaramento de regiões**: polígonos de máscara por câmera (`mask_polygons`, formato JSON igual ao de `exclusion_zones`) no dashboard; o blur é aplicado antes de salvar thumbnail, clipe e snapshot — a detecção usa sempre o frame original.
- **Modo privacidade**: desliga o reconhecimento de identidade (movimento e objetos continuam ativos). Ative via env `PRIVACY_MODE=true`, pela API `PUT /api/settings` ou pelo toggle no dashboard (Configurações).
- **Retenção seletiva**: política por zona (`retention_policy` JSON com `thumbnails`, `clips` e `days`) controla o prune de thumbnails e clipes.

## Comportamento e anomalias

- **Loitering**: pessoa/veículo na mesma região por ≥ `LOITERING_SECONDS` (default 30s) dispara o evento `loitering` (cooldown próprio, env `ALERT_COOLDOWN_LOITERING`).
- **Direção de movimento**: linha virtual por zona (`direction_line` JSON: `{"axis":"vertical"|"horizontal","position":0-1}`) — cruzá-la dispara `direction_change` com a direção (entrando/saindo).
- **Zona restrita fora de horário**: desconhecido em zona privativa/segurança fora do schedule da zona → `intruder_detected` (prioridade); pessoa conhecida → `identity_recognized`.
- **Queda (heurística)**: pessoa com bbox deitada (`w/h ≥ FALL_ASPECT_RATIO`, default 1.2) → `fall_detected`. O ângulo do torso por modelo de pose local fica como backlog (custo de inferência no hardware).

## Casos de perigo

- Pessoa em área restrita.
- Veículo em área privada.
- Animal grande em local proibido.
- Movimento fora de horário autorizado.
- Intrusão em porteiro automático ou portão.

## Endpoints principais

| Método | Rota | Descrição |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/status` | Status geral |
| GET | `/workers` | Status dos workers de câmera |
| GET | `/camera/<id>/snapshot` | Snapshot da câmera |
| GET | `/camera/<id>/thumbnails` | Thumbnails da câmera |
| GET | `/thumbnails/<id>/image` | Imagem do thumbnail |
| GET | `/camera/<id>/clips` | Clipes da câmera |
| GET | `/clips/<id>/video` | Vídeo do clipe |
| GET/POST | `/cameras` | Listar/criar câmeras |
| PUT/DELETE | `/cameras/<id>` | Editar/excluir câmera |
| GET | `/events` | Histórico de eventos |
| GET/POST/PUT/DELETE | `/zones` | CRUD de zonas |
| GET | `/api/classes` | Classes de detecção |
| GET/PUT | `/api/settings` | Configurações |
| GET/POST/DELETE | `/identities` | Reconhecimento de identidade |
| GET/PUT | `/api/notifications/routing` | Roteamento de notificações |
| GET | `/docs` | Documentação do dashboard |
