# Especificação: Imagem Customizada do Raspberry Pi para Tucuxi Monitor

## Problema

O Tucuxi Monitor está funcional no Linux com Docker, mas não existe uma forma padronizada de instalar no Raspberry Pi. O usuário precisa de uma imagem de SO minimalista que venha com Docker pré-configurado e um processo simples de primeiro boot.

## O que já existe

- Docker Compose funcional no projeto (`docker-compose.yml`)
- Suporte a variáveis de ambiente para configuração
- Documentação de instalação local e Docker

## O que construir

Imagem customizada do Raspberry Pi OS Lite 64-bit (Bookworm) usando pi-gen, contendo:

1. **Sistema Operacional:** Raspberry Pi OS Lite 64-bit
2. **Docker + Docker Compose:** pré-instalados
3. **Rede:** IP fixo 192.168.1.15/24, gateway 192.168.1.1
4. **SSH:** habilitado para gerenciamento remoto
5. **Script de primeiro boot:** configuração interativa do Tucuxi Monitor
6. **Docker Compose:** configuração otimizada para Pi

## Arquitetura

```
┌─────────────────────────────────────────────┐
│  Raspberry Pi OS Lite 64-bit (Bookworm)     │
│  ┌───────────────────────────────────────┐  │
│  │  Docker + Docker Compose              │  │
│  │  ┌─────────────────────────────────┐  │  │
│  │  │  Tucuxi Monitor (container)     │  │  │
│  │  │  - FastAPI backend              │  │  │
│  │  │  - Dashboard web                │  │  │
│  │  │  - OpenCV + IA                  │  │  │
│  │  │  - SQLite                       │  │  │
│  │  └─────────────────────────────────┘  │  │
│  └───────────────────────────────────────┘  │
│  ┌───────────────────────────────────────┐  │
│  │  Script de primeiro boot              │  │
│  │  - Configura .env interativamente     │  │
│  │  - Inicia os containers               │  │
│  └───────────────────────────────────────┘  │
└─────────────────────────────────────────────┘
         │
         │ MQTT
         ▼
┌─────────────────────────────────────────────┐
│  Home Assistant (192.168.1.12)              │
│  - Mosquitto (broker MQTT existente)        │
└─────────────────────────────────────────────┘
```

## Configuração de Rede

| Parâmetro | Valor |
|-----------|-------|
| IP fixo | `192.168.1.15` |
| Máscara | `255.255.255.0` (`/24`) |
| Gateway | `192.168.1.1` |
| DNS | `192.168.1.1` |
| SSH | Habilitado |

## Estrutura do pi-gen

```
pi-gen-tucuxi/
├── config/
│   └── config              # Configuração principal do pi-gen
├── stage3/
│   └── ROOTFS/
│       └── etc/
│           └── dhcpcd.conf # Configuração de rede fixa
├── stage4/
│   └── ROOTFS/
│       └── install-docker.sh  # Instala Docker + Compose
├── stage5/
│   └── ROOTFS/
│       └── first-boot.sh      # Script de primeiro boot
│       └── first-boot.service # Systemd service
└── build.sh                    # Script de build da imagem
```

## Script de Primeiro Boot

O script `first-boot.sh` será executado automaticamente na primeira inicialização:

1. Configurar senha do SSH (se ainda não configurado)
2. Clonar repositório do Tucuxi
3. Criar arquivo `.env` interativamente:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `MQTT_BROKER_URL` (default: 192.168.1.12)
   - `MQTT_BROKER_PORT` (default: 1883)
   - `MQTT_USERNAME`
   - `MQTT_PASSWORD`
   - `HOME_ASSISTANT_URL`
   - `HOME_ASSISTANT_TOKEN`
4. Rodar `docker compose up -d`
5. Exibir IP e porta de acesso

## Docker Compose para o Pi

```yaml
version: '3.8'

services:
  tucuxi:
    build: .
    container_name: tucuxi-monitor
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data
      - ./.env:/app/.env
    environment:
      - SERVER_HOST=0.0.0.0
      - SERVER_PORT=8000
    restart: unless-stopped
    network_mode: host
```

## Processo de Build

### Pré-requisitos (no Linux)
- Docker instalado e rodando
- Git
- ~10GB de espaço livre
- Conexão com internet

### Comandos
```bash
# 1. Clonar pi-gen
git clone --depth 1 https://github.com/RPi-Distro/pi-gen.git
cd pi-gen

# 2. Copiar configurações customizadas
cp -r /caminho/para/pi-gen-tucuxi/config .
cp -r /caminho/para/pi-gen-tucuxi/stage3 .
cp -r /caminho/para/pi-gen-tucuxi/stage4 .
cp -r /caminho/para/pi-gen-tucuxi/stage5 .

# 3. Build da imagem
sudo ./build.sh -c config/config

# 4. Imagem gerada em output/
```

### Uso pelo usuário final
1. Baixar a imagem `.img`
2. Gravar no SSD/SD com Raspberry Pi Imager ou `dd`
3. Inserir no Pi e ligar
4. Seguir instruções do script de primeiro boot

## Segurança

- SSH com senha (configurada no primeiro boot)
- MQTT com autenticação (credenciais do HA)
- Telegram com token e chat ID
- Dashboard sem autenticação (acesso局域网)

## Riscos

- Build da imagem pode falhar em ambientes com pouco espaço
- Primeira inicialização depende de internet (clone do repo)
- Docker no Pi pode ser lento para builds de imagem

## Validação

1. Build da imagem em ambiente Linux
2. Gravação em SSD/SD
3. Boot no Pi 4
4. Configuração interativa do primeiro boot
5. Acesso ao dashboard em `http://192.168.1.15:8000`
6. Teste de detecção com câmera IP
7. Teste de alertas via Telegram e MQTT
