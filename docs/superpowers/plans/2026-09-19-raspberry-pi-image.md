# Plano de Implementação: Imagem Customizada do Raspberry Pi

> **Para agentes:** SUB-SKILL OBRIGATÓRIO: Use superpowers:subagent-driven-development ou superpowers:executing-plans para implementar este plano.

**Objetivo:** Criar configuração do pi-gen para gerar imagem customizada do Raspberry Pi OS com Docker + Tucuxi Monitor pré-configurados.

**Arquitetura:** pi-gen com stages personalizados (stage3: rede, stage4: Docker, stage5: primeiro boot).

**Tech Stack:** pi-gen, Docker, Docker Compose, bash, systemd

## Restrições Globais

- Raspberry Pi OS Lite 64-bit (Bookworm)
- IP fixo: 192.168.1.15/24, gateway: 192.168.1.1
- SSH habilitado
- Docker + Docker Compose v2
- MQTT broker externo (192.168.1.12:1883)
- Dashboard na porta 8000

---

## Estrutura de Arquivos

```
pi-gen-tucuxi/
├── config/config
├── stage3/ROOTFS/etc/dhcpcd.conf
├── stage4/ROOTFS/install-docker.sh
├── stage5/ROOTFS/first-boot.sh
├── stage5/ROOTFS/first-boot.service
└── build.sh
```

---

### Tarefa 1: Criar estrutura e config principal

**Arquivos:** `pi-gen-tucuxi/config/config`, `pi-gen-tucuxi/build.sh`

- [ ] Criar estrutura de diretórios
- [ ] Criar config/config do pi-gen
- [ ] Criar build.sh
- [ ] Commit

### Tarefa 2: Configurar rede fixa (stage3)

**Arquivo:** `pi-gen-tucuxi/stage3/ROOTFS/etc/dhcpcd.conf`

- [ ] Criar dhcpcd.conf com IP fixo
- [ ] Commit

### Tarefa 3: Instalar Docker (stage4)

**Arquivo:** `pi-gen-tucuxi/stage4/ROOTFS/install-docker.sh`

- [ ] Criar script de instalação do Docker
- [ ] Commit

### Tarefa 4: Script de primeiro boot (stage5)

**Arquivos:** `first-boot.sh`, `first-boot.service`

- [ ] Criar script de configuração interativa
- [ ] Criar serviço systemd
- [ ] Commit

### Tarefa 5: Documentação

**Arquivo:** `pi-gen-tucuxi/README.md`

- [ ] Documentar uso do pi-gen
- [ ] Documentar processo de build
- [ ] Commit
