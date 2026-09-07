# Tucuxi Monitor — Roadmap

> Backlog técnico completo do projeto. O README principal traz apenas o resumo comercial.
> Convenção: marque os itens (`- [x]`) conforme forem implementados.

## 1. MVP ✅

- [x] Conectar 1 câmera IP
- [x] Detectar movimento com OpenCV
- [x] Exibir stream e gerar evento básico

## 2. IA de detecção ✅

- [x] Integrar YOLO para reconhecimento de pessoas, carros e animais
- [ ] Validar acurácia e desempenho no Raspberry Pi

## 3. Multi-câmeras ✅

- [x] Suportar 4 câmeras simultâneas
- [x] Melhorar paralelismo e estabilidade

## 4. Alertas e dashboard ✅

- [x] Notificações via Telegram
- [x] Integração MQTT
- [x] Integração Home Assistant (HTTP events)
- [x] Dashboard web com histórico
- [x] CRUD de câmeras (adicionar/editar/excluir)
- [x] CRUD de zonas com classificação (pública/segurança/privativa)
- [x] Severidade de alertas baseada na classificação da zona
- [x] Evento `no_motion` após 60s sem movimento (todas as zonas, configurável via `NO_MOTION_ALERT_SECONDS`)
- [x] Estilo adaptado (ESP-NOW Hub pattern)

## 5. Expansão

- [ ] Suportar até 8 câmeras
- [ ] Treinamentos customizados de modelos
- [ ] Integração com automação residencial (já parcial com HA)

## Melhorias futuras

- [ ] **Snapshot inteligente** — usar snapshots capturados para identificar pessoas, animais e veículos de forma amigável; notificar informações sem gerar alertas de segurança
- [ ] Armazenamento em nuvem para backup e análise
- [ ] Notificações push via e-mail
- [ ] Detecção de comportamentos e anomalias
- [ ] Módulo móvel para notificações e controle remoto
- [ ] Validação completa de performance em Raspberry Pi

## 6. Recursos candidatos (inspirados no Frigate NVR)

> Backlog avaliado a partir do [Frigate](https://github.com/amarildolacerda/frigate) e da [pesquisa de desejos de usuários](research-user-wants.md).
> Marque os que deseja implementar em uma próxima fase. CPU-leve = adequado ao Raspberry Pi.

### Alta prioridade (CPU-leve, encaixe direto no pipeline atual)

- [ ] Filtros de objeto por score (min_score/threshold com mediana) — suprime falsos positivos
- [ ] Máscaras de movimento vs. máscaras de filtro de objeto por classe (bottom-center)
- [ ] Objetos estacionários — pausar detecção em objeto parado (~10s) para economizar CPU
- [ ] Re-streaming RTSP — reduz número de conexões à câmera (importante com 4-8 câmeras)
- [ ] Exportação de clipes permanentes (fora da retenção)

### Alta prioridade — promovidos pela pesquisa de usuários

- [ ] Gravação contínua 24/7 com retenção em camadas (ex.: tudo 3d, movimento 7d, alertas 30d)
- [ ] Pré-gravação (pre-roll) — contexto antes do evento (ex.: 10s antes da detecção)
- [ ] PWA — dashboard instalável como app + notificações push (manifest + service worker)
- [ ] Retenção por espaço em disco (ex.: "use até 3TB") + múltiplos locais de armazenamento

### Média prioridade (bom valor, custo moderado)

- [ ] Timeline de revisão agrupando eventos sobrepostos (review items)
- [ ] UI de revisão simplificada ("por que este evento?") + ações em lote (multiselect/delete)
- [ ] Armar/desarmar câmera/zona por horário (ex.: desarmar quando estou em casa)
- [x] Permissões/roles — modo visualização (view-only) para não-admin (Fase 1-5 do spec user-access-control)
- [ ] Birdseye — visão geral que mostra apenas câmeras com atividade
- [ ] Detecção de áudio (sirene, alarme, vidro quebrando) — leve na CPU

### Backlog (dependem de hardware/infra)

- [ ] Autotracking PTZ via ONVIF
- [ ] Reconhecimento de placas (LPR) — OCR local
- [ ] Face recognition dedicada (sub_label em pessoa conhecida)
- [ ] WebRTC/MSE live view de baixa latência (via go2rtc)
- [ ] Áudio bidirecional (two-way) em doorbell
- [ ] Integração com portaria remota / app do morador (contexto Brasil)
- [ ] Semantic search (embeddings locais) — requer 8GB+ RAM e AVX2; não roda no Pi

## 7. Escala 80 câmeras (condomínio — fibra óptica)

> Projeto real: condomínio com 80 câmeras IP em rede de fibra óptica.
> **A gravação 24/7 fica nos NVRs; a borda só faz triagem leve (movimento); a central de análise decide a providência (informar/alertar/perigo eminente).**
> Triagem em níveis (funil N0-N4): borda separa candidatos (movimento + heurísticas); central decide.
> Proposta completa em [architecture-80-cameras.md](architecture-80-cameras.md).

### Fase A — Nó de borda (triagem leve N0-N1)

- [ ] N0: movimento (OpenCV) + N1: pré-seleção heurística (área/posição/duração/exclusões)
- [ ] Captura seletiva de frames/ROI candidatos; envio MQTT/HTTPS; fila offline; heartbeat

### Fase B — Transporte de candidatos

- [ ] Eventos com UUID (MQTT) + upload de frame/ROI via HTTPS multipart
- [ ] Consumidor central deduplica por event_id; prioridade na fila p/ zonas críticas

### Fase C — Central de análise e decisão (N2-N4)

- [ ] N2: detecção rápida (YOLO-tiny/ONNX no ROI) → N3: tracking/comportamento/identidade/regras
- [ ] N4: classificação de providência: informar / alertar / perigo eminente (novo nível crítico)
- [ ] PostgreSQL central (particionamento mensal); storage plugável (SQLite p/ single-node)

### Fase D — Integração com NVR e evidência

- [ ] Descoberta de câmeras via ONVIF + sub-stream RTSP do NVR para a borda
- [ ] Export sob demanda: central baixa clipe do NVR e anexa ao evento/alerta
- [ ] Retenção por espaço em disco para evidência curta; exports fora da retenção

### Fase E — Resiliência e operação

- [ ] Heartbeat/watchdog por nó remoto; fila offline + dedup (MQTT QoS 1)
- [ ] HA da central (active/standby); backup do banco e verificação de mídia

## 8. Situações monitoráveis (além de intrusão)

> O Secur monitora **situações**, não só presença/intrusão — via visão (funil N0-N4) e/ou sensores (MQTT/Home Assistant).
> Matriz completa em [architecture-80-cameras.md](architecture-80-cameras.md) (seção 1.2).

### Visão (central de análise N2-N4)

- [ ] Fogo/fumaça (modelo YOLO fire/smoke) — perigo eminente
- [ ] Objeto abandonado em área de circulação (stationary + zona) — ex.: carrinho
- [ ] Aglomeração/multidão em área comum (contagem de pessoas)
- [ ] Veículo parado/obstruindo em local proibido
- [ ] Pichação/vandalismo suspeito
- [ ] Porta/janela aberta fora de horário

### Sensores (via MQTT/Home Assistant — entram direto na central)

- [ ] Alagamento/vazamento (bóia, umidade, condutivo) — alerta imediato
- [ ] Fumaça/calor/CO (reforço ao fogo por visão)
- [ ] Porta/janela (contato) — cruzar com horário
- [ ] Qualquer sensor MQTT como "candidato já confirmado" no N4

### Regras de negócio

- [ ] Thresholds e providência configuráveis por situação + zona
- [ ] Cooldown por situação (reaproveitar mecanismo atual)

### Alta circulação (shopping, rodoviária/terminal, varejo)

- [ ] Bagagem/objeto abandonado (stationary + owner association) — alertar em área crítica
- [ ] Aglomeração/densidade (capacidade excedida) — alertar
- [ ] Filas e tempo de espera (caixa, portaria, guichê) — operacional
- [ ] Fluxo/contagem de pessoas (footfall) — analytics
- [ ] Queda em escada/elevador — perigo eminente
- [ ] Superlotação de elevador — informar/alertar
- [ ] Furto na portaria/encomenda (loitering + zona) — alertar
- [ ] Movimento suspeito na garagem (loitering perto de veículo) — alertar
- [ ] Self-checkout/caixa fraud (área de caixa + POS) — alertar (prevenção de perdas)

> Pesquisa completa: [research-monitoring-venues.md](research-monitoring-venues.md).

### Prioridade recomendada (valor para o usuário)

1. **Alagamento/vazamento via sensores MQTT** — custo ~zero (já há MQTT/HA), impacto altíssimo (garagem subterrânea), entrega rápida
2. **Fogo/fumaça por visão** — maior impacto (vidas+patrimônio), modelo YOLO fire/smoke maduro, complementa sensores obrigatórios
3. **Objetos estacionários** — multiplicador: desbloqueia carrinho abandonado, veículo obstruindo, bagagem, vandalismo
4. **Loitering contextual (portaria/garagem)** — furto é a dor nº1 em condomínio BR; `check_loitering` já existe no código
5. Aglomeração/footfall/filas — só quando entrar em shopping/terminal (outro público)
## 9. Portaria inteligente — notificação de visita/entrega

> Detecção automática por visão: alguém chega à portaria → notifica o morador → registra entrada e saída do domínio.
> Avaliação completa em [feature-portaria-visitante.md](feature-portaria-visitante.md).

- [ ] Cadastro morador ↔ unidade ↔ canal de notificação (app/Telegram)
- [ ] Zona "portaria" + linha de entrada/saída (direction_line) — já suportado
- [ ] Evento `visitor_arrived` (chegada + snapshot) — começar com notificação geral (Opção C)
- [ ] Vínculo visitante → unidade por tracking (Opção A — automática)
- [ ] Evento `visitor_departed` (saída do domínio) + notificação de fechamento
- [ ] Alerta de desconhecido persistente na portaria (já coberto por intruder/unknown)

## Preditor Tucuxi (MVP, 2026-09-06) ✅ IMPLEMENTADO
- Embalagem A in-process (`src/predictor/`, flag `PREDICTOR_ENABLED=true` no `.env`).
- Evento enriquecido `tucuxi/camera/+/event` + predição `tucuxi/predictions/+` + `tucuxi/automation/actuator`.
- HA pack em `hass/tucuxi_mvp.yaml` (sensores, switches de voz, automação rosa→aspersor 5min).
- V2: suggester/feedback, histograma dia_semana, REST `/predictions`, embalagem B/addon (mesma lib).

