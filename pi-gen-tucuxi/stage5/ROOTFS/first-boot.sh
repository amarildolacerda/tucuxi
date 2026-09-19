#!/bin/bash
set -euo pipefail

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

PROJECT_DIR="/home/tucuxi/tucuxi-monitor"
ENV_FILE="${PROJECT_DIR}/.env"
REPO_URL="https://github.com/seu-usuario/tucuxi.git"

echo -e "${GREEN}=== Configuração do Tucuxi Monitor ===${NC}"
echo ""

# Verificar se já foi configurado
if [ -f "$ENV_FILE" ] && grep -q "TELEGRAM_BOT_TOKEN" "$ENV_FILE"; then
    echo -e "${YELLOW}Tucuxi Monitor já configurado.${NC}"
    echo "Para reconfigurar, delete $ENV_FILE e reinicie."
    echo ""
    echo "Iniciando container..."
    cd "$PROJECT_DIR"
    docker compose up -d
    echo ""
    echo -e "${GREEN}Tucuxi Monitor rodando em: http://192.168.1.15:8000${NC}"
    exit 0
fi

# Configurar senha SSH (se necessário)
echo -e "${YELLOW}Configure a senha do usuário tucuxi:${NC}"
passwd tucuxi

# Clonar repositório
echo ""
echo -e "${YELLOW}Clonando Tucuxi Monitor...${NC}"
if [ ! -d "$PROJECT_DIR" ]; then
    git clone "$REPO_URL" "$PROJECT_DIR"
fi
cd "$PROJECT_DIR"

# Configurar .env interativamente
echo ""
echo -e "${YELLOW}Configure as credenciais:${NC}"
echo ""

read -p "Telegram Bot Token: " TELEGRAM_BOT_TOKEN
read -p "Telegram Chat ID: " TELEGRAM_CHAT_ID
read -p "MQTT Broker URL [192.168.1.12]: " MQTT_BROKER_URL
MQTT_BROKER_URL=${MQTT_BROKER_URL:-192.168.1.12}
read -p "MQTT Broker Port [1883]: " MQTT_BROKER_PORT
MQTT_BROKER_PORT=${MQTT_BROKER_PORT:-1883}
read -p "MQTT Username: " MQTT_USERNAME
read -p "MQTT Password: " MQTT_PASSWORD
read -p "Home Assistant URL [http://192.168.1.12:8123]: " HOME_ASSISTANT_URL
HOME_ASSISTANT_URL=${HOME_ASSISTANT_URL:-http://192.168.1.12:8123}
read -p "Home Assistant Token: " HOME_ASSISTANT_TOKEN

# Criar arquivo .env
cat > "$ENV_FILE" << EOF
# Configuração do Tucuxi Monitor
SERVER_HOST=0.0.0.0
SERVER_PORT=8000

# Telegram
TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID}

# MQTT
MQTT_BROKER_URL=${MQTT_BROKER_URL}
MQTT_BROKER_PORT=${MQTT_BROKER_PORT}
MQTT_USERNAME=${MQTT_USERNAME}
MQTT_PASSWORD=${MQTT_PASSWORD}
MQTT_TOPIC=homeassistant/secur/alert

# Home Assistant
HOME_ASSISTANT_URL=${HOME_ASSISTANT_URL}
HOME_ASSISTANT_TOKEN=${HOME_ASSISTANT_TOKEN}
HOME_ASSISTANT_EVENT_TYPE=secur_alert

# Detector
DETECTOR_MODEL_PATH=
DETECTOR_CONFIDENCE=0.25
DETECTOR_IOU=0.45

# Sensitivity
MOTION_MIN_AREA=5000
EOF

echo ""
echo -e "${GREEN}Arquivo .env criado com sucesso!${NC}"

# Iniciar containers
echo ""
echo -e "${YELLOW}Iniciando containers...${NC}"
docker compose up -d

echo ""
echo -e "${GREEN}=== Configuração concluída ===${NC}"
echo -e "${GREEN}Acesse: http://192.168.1.15:8000${NC}"
echo ""
echo "Para acessar via SSH:"
echo "  ssh tucuxi@192.168.1.15"
