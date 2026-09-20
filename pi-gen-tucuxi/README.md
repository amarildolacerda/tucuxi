# Tucuxi Monitor - Imagem Customizada do Raspberry Pi

Imagem customizada do Raspberry Pi OS Lite 64-bit com Docker + Tucuxi Monitor pré-configurados.

## Pré-requisitos

Para buildar a imagem:
- Linux (Ubuntu/Debian) com Docker instalado
- ~10GB de espaço livre
- Conexão com internet

Para usar a imagem:
- Raspberry Pi 4 (4GB ou 8GB RAM)
- SSD ou SD card de alta classe
- Conexão Ethernet (recomendado)
- Câmeras IP com RTSP/HTTP

## Build da Imagem

```bash
# 1. Clonar este repositório
git clone https://github.com/seu-usuario/tucuxi.git
cd tucuxi/pi-gen-tucuxi

# 2. Executar build
./build.sh

# 3. Imagem gerada em pi-gen/output/
```

## Instalação no Pi

1. **Gravar a imagem:**
   ```bash
   # Usando Raspberry Pi Imager (recomendado)
   # Ou via dd:
   sudo dd if=output/tucuxi-monitor.img of=/dev/sdX bs=4M status=progress
   ```

2. **Inserir o SSD/SD no Pi e ligar**

3. **Aguardar primeiro boot:**
   - O Pi reiniciará uma vez
   - O script de configuração será executado automaticamente

4. **Configurar credenciais:**
   - Senha do SSH
   - Token do Telegram Bot
   - Chat ID do Telegram
   - Credenciais MQTT (broker existente no HA)
   - Token do Home Assistant

5. **Acessar o dashboard:**
   ```
   http://192.168.1.15:8000
   ```

## Configuração de Rede

| Parâmetro | Valor |
|-----------|-------|
| IP fixo | 192.168.1.15 |
| Máscara | 255.255.255.0 |
| Gateway | 192.168.1.1 |
| DNS | 192.168.1.1 |

## Acesso

- **Dashboard:** http://192.168.1.15:8000
- **SSH:** ssh tucuxi@192.168.1.15
- **API:** http://192.168.1.15:8000/docs

## Estrutura

```
pi-gen-tucuxi/
├── config/config           # Configuração principal do pi-gen
├── stage3/ROOTFS/etc/      # Rede fixa (dhcpcd.conf)
├── stage4/ROOTFS/          # Instalação do Docker
├── stage5/ROOTFS/          # Script de primeiro boot
└── build.sh                # Script de build
```

## Troubleshooting

### Docker não inicia
```bash
sudo systemctl status docker
sudo systemctl restart docker
```

### Reconfigurar o sistema
```bash
rm ~/tucuxi-monitor/.env
sudo reboot
```

### Ver logs do primeiro boot
```bash
journalctl -u first-boot
```

### Acessar logs do container
```bash
cd ~/tucuxi-monitor
docker compose logs -f
```

## Personalização

### Alterar IP fixo
Edite `stage3/ROOTFS/etc/dhcpcd.conf` e rebuild:

```bash
./build.sh
```

### Alterar repositório
Edite a variável `REPO_URL` em `stage5/ROOTFS/first-boot.sh`.

### Adicionar pacotes
Crie scripts de instalação nos stages apropriados (stage3, stage4 ou stage5).
