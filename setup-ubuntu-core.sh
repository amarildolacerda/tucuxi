#!/bin/bash
set -euo pipefail

echo "=== Setup do Tucuxi Monitor no Ubuntu Core ==="

# Verificar se é root
if [ "$(id -u)" -ne 0 ]; then
    echo "Execute como root: sudo ./setup-ubuntu-core.sh"
    exit 1
fi

# Configurar IP fixo via netplan
echo "Configurando IP fixo 192.168.1.15..."
cat > /etc/netplan/01-static-ip.yaml << EOF
network:
  version: 2
  ethernets:
    eth0:
      dhcp4: no
      addresses:
        - 192.168.1.15/24
      routes:
        - to: default
          via: 192.168.1.1
      nameservers:
        addresses:
          - 192.168.1.1
EOF

# Aplicar configuração de rede
netplan apply 2>/dev/null || echo "Aviso: netplan pode precisar de reinicialização"

# Instalar Docker via snap
echo "Instalando Docker via snap..."
snap install docker
# Aguardar Docker inicializar
sleep 5

# Habilitar SSH (já deve estar habilitado no Ubuntu Core)
echo "Verificando SSH..."
snap enable ssh 2>/dev/null || echo "SSH já habilitado"

# Criar diretório para o Tucuxi
echo "Preparando diretório..."
mkdir -p /home/tucuxi
cd /home/tucuxi

# Criar docker-compose.yml
echo "Criando docker-compose.yml..."
cat > docker-compose.yml << 'EOF'
version: '3.8'

services:
  tucuxi:
    image: ghcr.io/seu-usuario/tucuxi:latest
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
EOF

# Configurar .env interativamente
echo ""
echo "Configure as credenciais:"
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

cat > .env << EOF
SERVER_HOST=0.0.0.0
SERVER_PORT=8000
TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID}
MQTT_BROKER_URL=${MQTT_BROKER_URL}
MQTT_BROKER_PORT=${MQTT_BROKER_PORT}
MQTT_USERNAME=${MQTT_USERNAME}
MQTT_PASSWORD=${MQTT_PASSWORD}
MQTT_TOPIC=homeassistant/secur/alert
HOME_ASSISTANT_URL=${HOME_ASSISTANT_URL}
HOME_ASSISTANT_TOKEN=${HOME_ASSISTANT_TOKEN}
HOME_ASSISTANT_EVENT_TYPE=secur_alert
EOF

# Criar diretório de dados
mkdir -p data

# Iniciar containers
echo "Iniciando containers..."
docker compose up -d

echo ""
echo "=== Setup concluído ==="
echo "IP: 192.168.1.15"
echo "Dashboard: http://192.168.1.15:8000"
echo "SSH: ssh tucuxi@192.168.1.15"
