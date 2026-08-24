# Tucuxi Monitor

<p align="center">
  <img src="assets/tucuxi-logo.png" alt="Tucuxi Monitor" width="220">
</p>

> Análise inteligente de situações em câmeras IP — 100% local.

O **Tucuxi Monitor** é uma plataforma de monitoramento por vídeo com inteligência artificial que observa suas câmeras IP e detecta situações de segurança — presença, intrusão, fogo, alagamento, objetos abandonados e muito mais — gerando alertas na hora certa, sem depender de nuvem.

## Por que "Tucuxi"?

O tucuxi é o golfinho de rio amazônico que enxerga por ecolocalização: percebe o que o olho humano não vê, mesmo na escuridão total. É o que o Tucuxi Monitor faz com os seus vídeos — detecta o que passa despercebido, 24 horas por dia.

## Benefícios

- **100% local e privado** — todo o processamento roda no seu hardware; nada sai dele, exceto pelos canais que você configurar (Telegram, MQTT, Home Assistant). Alinhado à LGPD.
- **Menos falsos alarmes** — triagem em níveis (funil): a IA separa o que realmente importa e só o que passa vira alerta.
- **Escala real** — de uma câmera na sua casa a 80+ câmeras em condomínio com rede de fibra óptica.
- **Aproveita o que você já tem** — integra com NVRs existentes, Home Assistant, MQTT e Telegram.
- **Roda no Raspberry Pi** — leve o suficiente para hardware modesto.

## Funcionalidades

- Detecção de movimento e classificação de objetos (pessoas, veículos, animais) com IA
- Zonas de interesse (pública, segurança, privativa) com regras por horário
- Reconhecimento de identidade (conhecidos vs. desconhecidos)
- Comportamentos: permanência suspeita (loitering), direção proibida, detecção de queda
- Alertas com evidência (thumbnail e clipe) via Telegram, MQTT e Home Assistant
- Atuação externa automática: em evento crítico, aciona sirene/dispositivo via MQTT/Home Assistant
- Dashboard web com visualização ao vivo e histórico de eventos
- Privacidade: mascaramento de regiões, modo privacidade e retenção seletiva
- Base pronta para situações avançadas: fogo/fumaça, alagamento, objetos abandonados, aglomeração (veja o roadmap)

## Para quem é

- Condomínios residenciais e comerciais
- Residências
- Comércios e áreas de circulação (shoppings, terminais, lojas)
- Instalações com NVRs existentes que querem análise inteligente por cima

## Como começar

Guia completo de instalação e configuração em [docs/technical.md](docs/technical.md). O caminho rápido:

1. `docker compose up --build`
2. Acesse `http://localhost:8000` e cadastre suas câmeras
3. Configure os canais de alerta (Telegram, MQTT, Home Assistant) e pronto

## Atuação externa (sirene)

Em eventos críticos — intruso, queda, permanência suspeita (loitering), mudança de direção e desconhecido — o Tucuxi pode acionar automaticamente um dispositivo externo (sirene, buzina ou qualquer atuador no Home Assistant) publicando um comando MQTT.

- **Canal:** usa o canal `automation`, já habilitado para esses eventos por padrão.
- **Configuração** (variáveis de ambiente — ver [docs/technical.md](docs/technical.md)):
  - `SIREN_MQTT_TOPIC` — tópico onde o comando é publicado (padrão `secur/automation/siren`)
  - `SIREN_EVENT_TYPES` — tipos de evento que disparam a sirene (padrão: `intruder_detected, fall_detected, loitering, direction_change, unknown_detected`)
  - Reutiliza `MQTT_BROKER_URL`, `MQTT_BROKER_PORT`, `MQTT_USERNAME` e `MQTT_PASSWORD` do broker já configurado.
- **Comando publicado** (JSON): `{"action":"siren","camera_id":1,"zone":"entrada","event_type":"intruder_detected","timestamp":123.0}`
- **Como ligar uma sirene real:** no Home Assistant (ou qualquer cliente MQTT), crie uma automação que assina `secur/automation/siren` e, ao receber `{"action":"siren"}`, aciona o atuador (switch, script ou cena).

## Roadmap

O que está planejado — detalhes técnicos completos em [docs/roadmap.md](docs/roadmap.md):

- **Alta prioridade:** fogo/fumaça, alagamento via sensores, objetos estacionários, filtros anti-falso-alarme
- **Escala:** arquitetura para 80 câmeras em condomínio (borda leve + central de análise)
- **Plataforma:** PWA, exportação de evidência, integração com NVR/ONVIF
- **Portaria inteligente:** notificação automática ao morador quando chega visita/entrega, com registro de entrada e saída

## Documentação

- [docs/technical.md](docs/technical.md) — instalação, configuração e referência técnica
- [docs/roadmap.md](docs/roadmap.md) — roadmap completo (fases e backlog)
- [docs/architecture-80-cameras.md](docs/architecture-80-cameras.md) — arquitetura para 80 câmeras (condomínio/fibra)
- [docs/branding.md](docs/branding.md) — sobre o nome comercial
- [docs/research-user-wants.md](docs/research-user-wants.md) — pesquisa de desejos de usuários
- [docs/research-monitoring-venues.md](docs/research-monitoring-venues.md) — monitoramentos desejáveis por ambiente

## Licença

MIT
