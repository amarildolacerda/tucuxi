
## 📋 Especificação do Projeto

### 🎯 Objetivo
Construir um sistema de vigilância inteligente inicialmente desenvolvido em PC/Linux, com deploy final planejado para Raspberry Pi. O sistema deve conectar câmeras IP, processar vídeo em tempo real com IA e gerar alertas para eventos de segurança.

### ✅ Escopo do MVP
- Prova de conceito em Linux com até 4 câmeras IP simultâneas.
- Detecção de movimento e classificação básica de objetos.
- Definição de zonas de interesse e regras configuráveis.
- Alertas por Telegram.
- Dashboard web simples para visualização e histórico.

---

## 📌 Requisitos

### Funcionais
- Capturar streams RTSP/HTTP de câmeras IP.
- Detectar movimento em cada stream.
- Classificar objetos em pessoas, veículos e animais.
- Configuração de sensibilidade por câmera com perfis **Baixa**, **Média**, **Alta** e **Padrão** (usa a configuração geral do `.env`), configurável no cadastro da câmera e em Configurações.
- Aplicar configuração de sensibilidade por câmera em tempo real.
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

---

## 🧩 Arquitetura proposta

### Componentes
- Captura de vídeo: OpenCV + ffmpeg/RTSP.
- IA: modelo YOLOv5/YOLOv8 ou TensorFlow Lite para inferência de objetos.
- Orquestração de câmeras: multiprocessing ou asyncio para cada stream.
- Persistência: SQLite para eventos; opcional InfluxDB para séries temporais.
- Backend: Flask ou FastAPI para APIs e dashboard.
- Frontend: interface web leve com gráficos e visualização de câmeras.
- Alertas: Telegram (e-mail/webhook em melhorias futuras) e integração futura com Home Assistant.

### Fluxo de dados
1. Captura do stream de cada câmera.
2. Pré-processamento e detecção de movimento.
3. Inferência de IA para classificação de objetos.
4. Aplicação de regras de zona/hora.
5. Registro do evento e disparo de alertas.
6. Exibição no dashboard.

---

## 🔧 Hardware recomendado
- PC/Linux para desenvolvimento inicial.
- Raspberry Pi 4 com 4GB ou 8GB de RAM para deploy final.
- Módulo de armazenamento rápido (SSD USB ou cartão microSD de alta classe).
- Fonte de energia adequada para Pi e periféricos.
- Rede estável via Ethernet preferencialmente; Wi-Fi como alternativa.
- Câmeras IP com RTSP/HTTP e resolução compatível (720p recomendado).

## 🖥️ Software recomendado
- Linux (Ubuntu, Debian, Fedora) para desenvolvimento inicial.
- Raspberry Pi OS 64-bit para o deploy final.
- Python 3.11+.
- OpenCV.
- PyTorch, TensorFlow Lite ou ONNX Runtime.
- Flask ou FastAPI.
- SQLite.

---

## 🛠️ Funcionalidades principais
- Detecção de movimento por câmera.
- Classificação de objetos em categorias chave.
- Configuração de sensibilidade por câmera com perfis **Baixa**, **Média**, **Alta** e **Padrão** (usa a configuração geral do `.env`), configurável no cadastro da câmera e em Configurações.
- Zonas de interesse personalizáveis (entrada, quintal, garagem).
- Regras de alerta baseadas em área, categoria e horário.
- Visualização de câmeras ao vivo e histórico de eventos.
- Exportação básica de logs e imagens de evidência.

## 🚨 Casos de perigo
- Pessoa em área restrita.
- Veículo em área privada.
- Animal grande em local proibido.
- Movimento fora de horário autorizado.
- Intrusão em porteiro automático ou portão.

---

## 📈 Roadmap
1. MVP
   - Conectar 1 câmera IP.
   - Detectar movimento com OpenCV.
   - Exibir stream e gerar evento básico.
2. IA de detecção
   - Integrar YOLO para reconhecimento de pessoas, carros e animais.
   - Validar acurácia e desempenho no Pi.
3. Multi-câmeras
   - Suportar 4 câmeras simultâneas.
   - Melhorar paralelismo e estabilidade.
4. Alertas e dashboard
   - Implementar notificações via Telegram/e-mail.
   - Criar dashboard web com histórico.
5. Expansão
   - Suportar até 8 câmeras.
   - Adicionar treinamentos customizados e integração com automação residencial.
6. Recursos candidatos (inspirados no Frigate NVR)
   - Backlog avaliado no README (seção Roadmap) e em docs/research-user-wants.md; marcar os pertinentes antes de planejar a próxima fase.
   - CPU-leve (alta prioridade): filtros de score, máscaras por classe, objetos estacionários, re-streaming RTSP, exports, gravação 24/7 com retenção em camadas, pre-roll, PWA/push, retenção por espaço em disco.
   - Média prioridade: review items, UI de revisão simplificada + ações em lote, armar/desarmar por horário, permissões/view-only, birdseye, detecção de áudio.
   - Backlog: autotracking PTZ, LPR, face dedicada, WebRTC/go2rtc, two-way audio, portaria remota/app do morador, semantic search (não roda no Pi).
7. Escala 80 câmeras (condomínio — fibra óptica)
   - Proposta de dimensionamento em docs/architecture-80-cameras.md; validar com o projeto real antes de implementar.
   - **Gravação 24/7 e retenção ficam nos NVRs existentes. A borda só faz triagem leve (movimento + candidatos). A central de análise decide a providência: informar / alertar / perigo eminente.**
   - Arquitetura distribuída: nós de borda (triagem leve) + central de análise (IA, tracking, identidade, regras, decisão) + PostgreSQL + MQTT como backbone + integração ONVIF/RTSP com NVRs.
   - **Triagem em níveis (funil N0-N4):** N0 movimento e N1 pré-seleção na borda; N2 detecção rápida, N3 análise completa e N4 decisão de providência (informar/alertar/perigo eminente) na central.
   - Fases: A) nó de borda (triagem N0-N1); B) transporte de candidatos; C) central de análise e decisão (N2-N4); D) integração com NVR e evidência; E) resiliência/HA.
8. Situações monitoráveis (além de intrusão)
   - Visão (central N2-N4): fogo/fumaça, objeto abandonado em circulação, aglomeração, veículo obstruindo, vandalismo, porta aberta.
   - Sensores via MQTT/HA (candidatos já confirmados): alagamento/vazamento, fumaça/calor/CO, contato de porta.
   - Matriz completa (fontes, níveis, eventos, providências) em docs/architecture-80-cameras.md (seção 1.2).
   - Alta circulação (shopping/rodoviária/varejo): bagagem abandonada, aglomeração/densidade, filas, footfall (analytics), queda em escada/elevador, superlotação de elevador, furto na portaria/encomenda, movimento suspeito na garagem, self-checkout fraud.
   - Pesquisa de desejos em docs/research-monitoring-venues.md; matriz ampliada em docs/architecture-80-cameras.md (seção 1.3).



---

## ⚠️ Riscos e restrições
- Raspberry Pi pode ficar limitado ao processar múltiplos streams com IA.
- Modelos grandes podem exigir otimização ou offloading para hardware dedicado.
- Latência de rede e qualidade das câmeras afetam a detecção.
- Instabilidades de Wi-Fi podem prejudicar a captura de vídeo.

---

## 💡 Melhoria futura
- Armazenamento em nuvem para backup e análise.
- Treinamento personalizado de modelos para objetos específicos.
- Integração com Home Assistant e sistemas de automação.
- Suporte a detecção de comportamentos e anomalias.
- Módulo móvel para notificações push e controle remoto.
