# Design: Perfis de Sensibilidade de Detecção por Câmera

## 1. Objetivo

Permitir que o usuário ajuste a sensibilidade de detecção do Secur **por câmera** com **3 presets prontos** (Baixa, Média, Alta) e um perfil **Padrão** que usa a configuração geral do sistema (env `MOTION_MIN_AREA`, `MOTION_PERSIST_FRAMES`, `DETECTOR_CONFIDENCE`, `DETECTOR_IOU`, `TRACK_IOU_THRESHOLD` — ou seja, os valores do `.env`/`config.py`).

**Problema atual:** existem 5+ parâmetros isolados que interagem entre si. Usuários comuns não sabem o que "IOU 0.45" significa na prática, e ajustar um sem entender os outros gera comportamento imprevisível.

**Decisão de UX:** a configuração é **por câmera**, então o seletor principal fica no **formulário de cadastro/edição da câmera** (junto de zona, classes de alerta e máscara). Um atalho de ajuste rápido continua disponível em **Configurações** (um seletor por câmera). Sliders manuais ("Personalizado") foram **removidos** para reduzir complexidade — quem quer valores específicos ajusta o `.env`.

## 2. Escopo (MVP)

- 3 presets prontos (Baixa/Média/Alta) + 1 perfil Padrão (usa `.env`)
- Aplicável **per câmera**
- Mudança em tempo real (não reinicia o sistema)
- Persistência no SQLite; env vars como fallback global
- API REST para leitura/escrita
- UI no dashboard: seletor no formulário da câmera + listagem por câmera em Configurações
- **Sem** sliders manuais (YAGNI)

## 3. Presets

### 3.1 Baixa sensibilidade (poucos falsos positivos)

**Ideal para:** áreas movimentadas (vendas, calçadas), vielas com trânsito de pedestres, áreas com árvores/folhas que balançam, vento forte.

| Parâmetro | Valor | Efeito |
|-----------|-------|--------|
| `motion_min_area` | 8000 px | Ignora movimentos pequenos (folhas, sombras) |
| `motion_persist_frames` | 4 | Exige 4 frames consecutivos de movimento |
| `detector_confidence` | 0.55 | Só aceita detecções com alta confiança |
| `detector_iou` | 0.50 | NMS mais agressivo, menos caixas sobrepostas |
| `track_iou_threshold` | 0.4 | Rastreamento mais exigente |

### 3.2 Média (equilibrado)

**Ideal para:** uso geral, residências, escritórios, quintais sem muito vento.

| Parâmetro | Valor |
|-----------|-------|
| `motion_min_area` | 5000 px |
| `motion_persist_frames` | 3 |
| `detector_confidence` | 0.40 |
| `detector_iou` | 0.45 |
| `track_iou_threshold` | 0.3 |

### 3.3 Alta sensibilidade (mais alertas)

**Ideal para:** perímetros críticos, áreas isoladas, monitoramento noturno.

| Parâmetro | Valor |
|-----------|-------|
| `motion_min_area` | 3000 px |
| `motion_persist_frames` | 2 |
| `detector_confidence` | 0.30 |
| `detector_iou` | 0.40 |
| `track_iou_threshold` | 0.25 |

### 3.4 Padrão

Usa `CONFIG_DEFAULT_PARAMS` — os valores de `config.py` (env vars / defaults), seguindo a prioridade do SPEC §8.1/§8.2. Sem registro no DB = Padrão.

## 4. Modelo de Dados

### 4.1 Enum de níveis

```python
class SensitivityLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    DEFAULT = "default"
```

`CUSTOM` e `validate_custom_params`/`PARAM_RANGES` são **removidos**.

### 4.2 Presets

`SENSITIVITY_PRESETS` com `low`/`medium`/`high` (valores da seção 3). `CONFIG_DEFAULT_PARAMS` continua em `sensitivity.py` importando de `config.py`.

### 4.3 Tabela `camera_sensitivity`

```sql
CREATE TABLE IF NOT EXISTS camera_sensitivity (
    camera_id INTEGER PRIMARY KEY,
    level TEXT NOT NULL DEFAULT 'low' | 'medium' | 'high',
    custom_params TEXT,        -- coluna legada, SEM uso
    updated_at TEXT NOT NULL,
    FOREIGN KEY (camera_id) REFERENCES cameras(id)
);
```

> O nível `custom` e o `custom_params` não são mais usados pelo código, mas a coluna é **mantida** (sem migração de schema — a tabela já existe com essa coluna). Novas escritas gravam `custom_params = NULL`. Linhas legadas com `level='custom'` são tratadas como Padrão na leitura (`get_effective_params` retorna `CONFIG_DEFAULT_PARAMS`).

**Padrão = sem registro:** `set_camera_sensitivity(camera_id, "default")` **deleta** a linha; ler câmera sem registro retorna `level="default"`, `configured: False`.

## 5. API

| Método | Rota | Descrição |
|--------|------|-----------|
| `GET` | `/api/cameras/<id>/sensitivity` | Nível atual + parâmetros efetivos |
| `PUT` | `/api/cameras/<id>/sensitivity` | Define nível (`low`/`medium`/`high`/`default`) |
| `GET` | `/api/sensitivity/presets` | Valores dos 3 presets |

### Request/Response

**GET /api/cameras/1/sensitivity**

```json
{
  "camera_id": 1,
  "level": "high",
  "effective_params": { "motion_min_area": 3000, "motion_persist_frames": 2, "detector_confidence": 0.30, "detector_iou": 0.40, "track_iou_threshold": 0.25 }
}
```

Sem registro: `level: "default"`, `effective_params` = valores do `.env`.

**PUT /api/cameras/1/sensitivity**

```json
{ "level": "medium" }
```

- `level` fora de `{low, medium, high, default}` → `400` ("Nível inválido. Use: low, medium, high, default").
- `custom_params` em payload → **ignorado** no `PUT` (a rota não valida mais esse campo; só o nível).

## 6. Arquitetura

### 6.1 `sensitivity.py`

```python
class SensitivityManager:
    def get_effective_params(camera_id) -> dict:
        # nível default/sem registro → CONFIG_DEFAULT_PARAMS
        # low/medium/high → SENSITIVITY_PRESETS[level]

    def set_level(camera_id, level):
        # level == DEFAULT → storage.set_camera_sensitivity(camera_id, "default") → deleta linha
        # senão → upsert, aplica params nos workers

    def apply_to_workers(camera_id, params):
        # atualiza motion_detector / object_detector / tracker refs + pending fallback
```

- `get_effective_params`: linha com `level` desconhecido (ex.: `custom` legado) → trata como `default`.
- `set_level` não recebe mais `custom_params`.

### 6.2 Integração com CameraWorker

Inalterada (já implementada): `apply_to_workers` seta `min_area`, `persist_frames`, `confidence_threshold`, `iou_threshold`, `tracker.iou_threshold`; refs pendentes aplicadas no `run()`.

### 6.3 Fluxo de dados

```
Usuário edita câmera no formulário
  → PUT /cameras/<id> (update) + PUT /api/cameras/<id>/sensitivity (se nível ≠ Padrão)
  → SensitivityManager.set_level()
  → Persiste no SQLite (ou deleta linha se "default")
  → apply_to_workers() → workers aplicam no próximo frame
```

## 7. UI (Dashboard)

### 7.1 Formulário da câmera (principal)

- Seção "Sensibilidade" no modal de cadastro/edição (`cameras.html`/`cameras.js`).
- 4 botões: Baixa | Média | Alta | Padrão, com a descrição contextual abaixo.
- **Adicionar:** o seletor aparece com "Padrão" ativo. Após `POST /cameras` (que retorna o id), se o nível escolhido ≠ `default`, faz `PUT /api/cameras/<id>/sensitivity` com o nível.
- **Editar:** ao abrir, faz `GET /api/cameras/<id>/sensitivity` e marca o botão ativo. No submit, após `PUT /cameras/<id>`, salva `PUT /api/cameras/<id>/sensitivity` com o nível atual (inclui `default` para limpar registro).

### 7.2 Configurações (atalho)

- Mantém o bloco `#sensitivity-config` (adicionado no hotfix). Seletor por câmera com os mesmos 4 botões.
- **Remove** todo o código de sliders: `SLIDER_DEFS`, renderização de sliders, `saveCustom`, seção `sensitivity-sliders`.

### 7.3 Textos

- Baixa: "Menos alertas. Ideal para áreas movimentadas."
- Média: "Equilibrado. Padrão para uso geral."
- Alta: "Mais alertas. Ideal para perímetros críticos."
- Padrão: "Usa a configuração geral do sistema (.env)."

### 7.4 CSS

- Mantém as classes `.sensitivity-section`, `.sensitivity-camera-group`, `.sensitivity-selector`, `.sensitivity-btn`, `.sensitivity-desc`.
- Remove `.sensitivity-sliders`, `.slider-row`, `.slider-value` (se não usados em outro lugar).

## 8. Persistência e Fallback

1. `camera_sensitivity` no SQLite (per câmera; `low`/`medium`/`high`)
2. `CONFIG_DEFAULT_PARAMS` (env vars / defaults) — usado quando sem registro ou nível `default`
3. Valores padrão do código

Sem migração de schema (a tabela já existe). Linha legada `level='custom'` lida como Padrão.

## 9. Tratamento de erros

- Nível inválido → `400` com mensagem descritiva
- Câmera não encontrada → `404`
- Worker não registrado → grava no DB; aplica quando o worker iniciar (`_pending_sensitivity`)
- Falha ao persistir → loga; aplica em memória; retorna `500`

## 10. Testes

### `tests/test_sensitivity.py`

- Presets retornam valores corretos
- `get_effective_params`: prioridade DB > env; sem registro → `CONFIG_DEFAULT_PARAMS`
- `get_camera_sensitivity` sem registro → `level="default"`, `configured: False`
- `set_level("default")` apaga o registro
- Linha legada `custom` → tratada como Padrão
- Remover testes de `validate_custom_params` / `custom`

### `tests/test_sensitivity_integration.py`

- `PUT {level:"default"}` → GET retorna `default` + parâmetros do `.env`
- `PUT {level:"high"}` → worker atualizado em tempo real
- `PUT {level:"invalid"}` → `400`
- `PUT {level:"custom"}` → `400` (removido)
- Câmera sem registro → usa `.env`

### App

- `test_settings_section_renders_sensitivity_config` (já adicionado)
- Novo: `test_camera_form_section_renders_sensitivity` — `/section/cameras` contém o seletor de sensibilidade

## 11. Atualização do SPEC.md / README.md

- Substituir referências a modo "Personalizado"/`custom` por perfis Baixa/Média/Alta/Padrão.
- Documentar que sensibilidade é configurada por câmera no cadastro.

## 12. Fora de escopo (YAGNI)

- Sliders manuais (removidos)
- Presets por horário ("alta à noite, média de dia")
- Presets automáticos por estatísticas de falsos positivos
- Presets por zona
- Presets globais (pode ser feito repetindo o PUT por câmera)
- A/B testing