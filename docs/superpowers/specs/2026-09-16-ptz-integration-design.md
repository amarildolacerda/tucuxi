# Design: Integração PTZ no Secur

> Projeto: Secur/Tucuxi. Backend Flask + OpenCV; dashboard JS.
> Escopo: Controle PTZ via ONVIF, presets, autotracking (auto-follow).

## 1. Problema

A câmera IP (192.168.1.71) suporta PTZ via ONVIF (porta 8899), mas o projeto não tem integração com controle de movimento. O usuário precisa de controle remoto manual e autotracking para acompanhar pessoas detectadas.

## 2. O que já existe

- **Tabela `cameras`**: id, name, source (RTSP), zone, alert_classes, exclusion_zones, mask_polygons
- **API CRUD**: `/cameras`, `/cameras/<id>` (POST/PUT/DELETE)
- **Worker**: `CameraWorker` processa streams via OpenCV, detecta pessoas com YOLO
- **Dashboard**: tabela de câmeras + dialog de edição com preview
- **Sensibilidade**: tabela `camera_sensitivity` com níveis low/medium/high
- **Sem código ONVIF/PTZ** existente

## 3. O que construir

### 3.1 Modelo de Dados

**Tabela `cameras_ptz`** (1:1 com cameras):

```sql
CREATE TABLE IF NOT EXISTS cameras_ptz (
    camera_id INTEGER PRIMARY KEY,
    onvif_host TEXT NOT NULL,
    onvif_port INTEGER DEFAULT 80,
    onvif_user TEXT,
    onvif_pass TEXT,
    ptz_enabled BOOLEAN DEFAULT 0,
    autotracking BOOLEAN DEFAULT 0,
    updated_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (camera_id) REFERENCES cameras(id) ON DELETE CASCADE
);
```

**Tabela `ptz_presets`**:

```sql
CREATE TABLE IF NOT EXISTS ptz_presets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    position TEXT NOT NULL,  -- JSON: {"pan": 0.5, "tilt": -0.3, "zoom": 1.2}
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (camera_id) REFERENCES cameras(id) ON DELETE CASCADE
);
```

### 3.2 Módulo `src/ptz/`

| Arquivo | Responsabilidade |
|---------|------------------|
| `__init__.py` | Exporta PTZManager |
| `onvif_client.py` | Conexão ONVIF via `onvif-zeep`: move, stop, goto_preset, get_presets, get_capabilities |
| `manager.py` | Estado PTZ por câmera, cache de conexão, fila de comandos, lifecycle (init/shutdown) |
| `autotracking.py` | Thread async: recebe frame → detecta pessoa → calcula delta → envia move → stop quando centrada |

### 3.3 API REST

| Método | Rota | Descrição |
|--------|------|-----------|
| `POST` | `/api/cameras/<id>/ptz/move` | Move câmera. Body: `{"pan": -1..1, "tilt": -1..1, "zoom": -1..1}` |
| `POST` | `/api/cameras/<id>/ptz/stop` | Para movimento |
| `GET` | `/api/cameras/<id>/ptz/status` | Retorna posição atual e estado PTZ |
| `GET` | `/api/cameras/<id>/ptz/presets` | Lista presets da câmera |
| `POST` | `/api/cameras/<id>/ptz/presets` | Cria preset. Body: `{"name": "Entrada", "position": {...}}` |
| `DELETE` | `/api/cameras/<id>/ptz/presets/<preset_id>` | Remove preset |
| `POST` | `/api/cameras/<id>/ptz/presets/<preset_id>/goto` | Vai para preset |
| `PUT` | `/api/cameras/<id>/ptz/config` | Configura PTZ. Body: `{"onvif_port": 8899, "ptz_enabled": true}` |
| `PUT` | `/api/cameras/<id>/ptz/autotracking` | Liga/desliga autotracking. Body: `{"enabled": true}` |

### 3.4 Dashboard UI

Na página de câmeras (`cameras.html`), adicionar:

1. **Seção PTZ no dialog de edição** (abaixo de sensibilidade):
   - Checkbox "PTZ habilitado"
   - Campos: porta ONVIF, usuário, senha
   - Checkbox "Autotracking"

2. **Controles PTZ inline** (após linha da tabela, expandível):
   - Botões de seta (8 direções): ↑ ↗ → ↘ ↓ ↙ ← ↖
   - Botões zoom: + e -
   - Botão "Parar"
   - Barra de presets: botões de preset + "Salvar posição atual"

### 3.5 Autotracking (Auto-follow)

```
Frame do worker → autotracking.py:
  1. Recebe frame + lista de detecções (pessoas)
  2. Seleciona pessoa mais próxima do centro
  3. Calcula delta: (centro_frame - centro_pessoa) / frame_size
  4. Se |delta| > threshold (0.05):
     - Envia ContinuousMove com velocity = delta * speed_factor
  5. Se |delta| <= threshold:
     - Envia Stop
  6. Repete a cada N frames (configurável)
```

**Configuração:**
```env
PTZ_AUTOTRACKING_SPEED=0.5
PTZ_AUTOTRACKING_THRESHOLD=0.05
PTZ_AUTOTRACKING_INTERVAL_MS=500
```

## 4. Segurança

- Credenciais ONVIF armazenadas em `cameras_ptz` (criptografadas no futuro)
- Permissão `manage_cameras` necessária para todas operações PTZ
- Autotracking só ativa por usuário autenticado
- Rate limiting em comandos PTZ (máx 10 comandos/segundo)

## 5. Riscos

| Risco | Mitigação |
|-------|-----------|
| Câmera não responde ONVIF | Timeout de 5s, retry 1x, retorna erro 503 |
| Múltiplos autotracking em conflito | Último comando vence (stateless) |
| Latência ONVIF alta | Cache de conexão, fila de comandos assíncrona |
| Câmera sem PTZ real | Detecção de capabilities no cadastro, desabilita se não suporta |

## 6. Dependências

- `onvif-zeep` (já adicionado ao requirements.txt)
- YOLO (já existente para detecção de pessoas)
- Worker (já existe, precisa de hook para enviar frames ao autotracking)

## 7. Ordem de implementação

1. Storage: tabelas `cameras_ptz` e `ptz_presets` + CRUD
2. Módulo PTZ: `onvif_client.py` → `manager.py`
3. API REST: endpoints PTZ
4. Dashboard: controles inline + dialog
5. Autotracking: `autotracking.py` + integração com worker
6. Testes: unitários do módulo PTZ + integração ONVIF
