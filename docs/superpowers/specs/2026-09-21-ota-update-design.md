# OTA Update Mechanism — Design Spec

## Problema

O Tucuxi roda em Raspberry Pi (IP fixo 192.168.1.15) via Docker Compose ou instalação bare metal. Atualmente, atualizar o sistema requer acesso SSH manual, `git pull`, rebuild e restart. Isso é frágil, requer conhecimento técnico e não é acessível para usuários não-desenvolvedores.

## O que já existe

- `APP_VERSION = "1.0.0"` em `src/config.py` — versão atual do sistema
- Versão exposta via `/status`, `/api/system-status`, footer do dashboard
- Deploy via Docker Compose no Pi (image customizada `pi-gen-tucuxi`)
- Botão de Reboot existente na Settings page (`/api/system/reboot`)
- Repositório público no GitHub: `https://github.com/amarildolacerda/tucuxi.git`
- Branch `main` para releases (semver tags `v0.0.0`), branch `dev` para desenvolvimento
- Sem credenciais git no Pi (repo público)

## O que construir

### 1. Backend — `src/update.py`

**Responsabilidades:**
- `check_for_update()` — consulta API pública do GitHub (`/repos/amarildolacerda/tucuxi/git/refs/tags`) para pegar a tag mais recente, compara com `APP_VERSION`
- `apply_update(tag)` — executa `git fetch`, `git checkout <tag>`, detecta modo de deploy, rebuild/restart
- `detect_deploy_mode()` — verifica se existe `docker-compose.yml`/`compose.yaml` no diretório → Docker; senão → bare metal
- Estado em memória: `update_available`, `latest_version`, `last_check`, `updating`, `update_log`

**Timer de checagem:**
- 1x no startup do app
- Depois a cada 24 horas

**Segurança do update:**
- Backup de `.env` antes do git pull
- Se Docker: `docker compose pull && docker compose up -d`
- Se bare metal: `pip install -e .` + restart do serviço
- Log de cada passo retornado ao frontend
- Em caso de falha: rollback via `git checkout` do commit anterior

### 2. Endpoints API

| Método | Rota | Descrição | Permissão |
|--------|------|-----------|-----------|
| `GET` | `/api/system/update-check` | Retorna versão atual, latest disponível, se há update, timestamp da última checagem | `manage_settings` |
| `POST` | `/api/system/update` | Aplica update: git checkout tag + rebuild. Retorna log do processo. | `manage_settings` |

**GET /api/system/update-check response:**
```json
{
  "current_version": "1.0.0",
  "latest_version": "1.1.0",
  "update_available": true,
  "last_check": "2026-09-21T15:00:00Z",
  "tag": "v1.1.0"
}
```

**POST /api/system/update request:**
```json
{
  "tag": "v1.1.0"
}
```

**POST /api/system/update response (sucesso):**
```json
{
  "success": true,
  "message": "Atualizado com sucesso. Reiniciando...",
  "log": ["git fetch OK", "checkout v1.1.0", "docker compose pull", "docker compose up -d"]
}
```

**POST /api/system/update response (erro):**
```json
{
  "success": false,
  "message": "Falha ao atualizar",
  "log": ["git fetch OK", "checkout v1.1.0", "ERRO: docker compose pull falhou"]
}
```

### 3. Frontend — Dashboard

**Localização:** Card "Atualização" na `settings.html`, abaixo do botão de Reboot.

**Estados da UI:**

| Estado | O que mostra |
|--------|-------------|
| Checando... | Spinner + "Verificando atualizações..." |
| Sem update | Versão atual + "Sistema atualizado" (verde) |
| Update disponível | Versão atual → versão nova + botão "Atualizar para vX.Y.Z" (azul) |
| Atualizando | Spinner + log ao vivo do processo + "Não desligue o Pi" (amarelo) |
| Sucesso | "Atualizado com sucesso! Reiniciando..." → reload após 10s |
| Erro | Mensagem de erro + botão "Tentar novamente" |

**Fluxo JS:**
1. `settings.html` carrega → chama `GET /api/system/update-check` (1x no startup)
2. Se `update_available=true` → mostra banner amarelo no topo do dashboard (via `core.js`) + card na settings
3. Botão "Atualizar" → `POST /api/system/update` → poll `/api/system/update-check` a cada 2s para status
4. Sucesso → setTimeout 10s → `location.reload()`

### 4. Dados / Persistência

- Nenhuma tabela nova no SQLite — estado do update fica em memória (`update.py`)
- `.env` é preservado via backup antes do git pull
- `data/` (SQLite, thumbnails, clips) não é afetado pelo update (está em volume Docker ou fora do repo)

### 5. Segurança

- Endpoints requerem permissão `manage_settings` (mesmo do reboot)
- Rate limit: 1 update a cada 5 minutos (evitar updates acidentais)
- Log de cada update no SQLite (tabela existente `events` ou nova tabela `update_log`)
- Rollback automático se `git checkout` ou `docker compose` falhar

## Riscos

| Risco | Mitigação |
|-------|-----------|
| GitHub API rate limit (60/h sem token) | 1 check a cada 24h = ~1 req/dia, bem dentro do limite |
| Update interrompe vigilância | Mostrar aviso "Não desligue o Pi", delay antes de restart |
| Git pull falha (conflito, rede) | Rollback automático + mensagem de erro clara |
| Docker compose pull falha | Log detalhado + botão retry |
| `.env` perdido no git pull | Backup automático antes do update |

## Fora do escopo (desta versão)

- Atualização automática sem intervenção do usuário
- Atualização de firmware da câmera
- Rollback para versão específica (apenas rollback para commit anterior)
- Notificação Telegram sobre disponibilidade de update
