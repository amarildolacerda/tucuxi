# AGENTS

Este documento descreve agentes e padrões recomendados para o projeto Secur.

## Objetivo
Fornecer orientações claras sobre como dividir tarefas entre agentes de projeto quando se trabalha em automação, desenvolvimento e validação.

## Agentes sugeridos

### 1. Agente de especificação
- Responsável por documentar requisitos, casos de uso e arquitetura.
- Deve focar em clareza, escopo do MVP e diferenciação entre desenvolvimento em Linux e deploy no Raspberry Pi.
- Deve acompanhar alterações no `SPEC.md` e `README.md`.
- Para melhorar os SPEC, fazer pesquisa para indicar melhorias ou recursos que poderiam melhorar a socitalação apresentando como opção para incluisão no scopo;
- Sempre que precisar tomar uma decisão sobre ordem de execução, primeiro analisar valor para usuario, ações que reduzem custos e deixam valor perseptivel para usuário tem maior relevância;

### 2. Agente de implementação
- Responsável por criar a estrutura do projeto em Python e componentes principais.
- Deve priorizar modularidade, testes e compatibilidade com Linux e Raspberry Pi.
- Deve gerar códigos de captura de vídeo, inferência com IA, persistência e backend web.
- Usar subagents para implemenação;
- separar paginas para reduzir tempo de carga do dashboard;

### 3. Agente de testes e validação
- Responsável por escrever e rodar testes automatizados.
- Deve validar fluxo de captura de stream, detecção de movimento, inferência de IA e alertas.
- Deve sugerir casos de teste para diferentes tipos de câmeras, zonas de interesse e regras de segurança.

## Regras gerais para agentes do projeto

1. Sempre trabalhe com base no spec e no roadmap.
2. Mantenha o desenvolvimento incremental:
   - primeiro Linux local,
   - depois Raspberry Pi.
3. Priorize a reutilização de código e a modularidade.
4. Documente decisões importantes e dependências.
5. Garanta que qualquer mudança de arquitetura seja refletida em `SPEC.md` e `README.md`.
6. Evite dependências pesadas no início; use versões leves e compatíveis.

## Fluxo de branches e release

- Código deve ser integrado em `dev` via pull request.
- Não aplique alterações de código diretamente em `main`.
- Para mover mudanças para produção, crie uma nova versão com tag baseada em `main`.
- Use o formato de tag `v0.0.0` para a primeira versão e incremente conforme necessário.
- Apenas a branch `main` deve conter código já liberado para produção.

### Verificação obrigatória de branch (anti-push-direto-no-main)

Incidente recorrente: código subiu em `main` sem passar por `dev`. Antes de
qualquer `commit`, `push`, `merge` ou criação de PR, o agente DEVE:

1. Rodar `git branch --show-current` e confirmar que NÃO está em `main`.
2. Se estiver em `main`, parar e trocar para `dev` (ou branch de feature) antes de qualquer alteração.
3. Só fazer push para `dev` ou branch de feature; `main` só recebe merge via release + tag.
4. Nunca usar `--force`, `-f` ou bypass de hook sem pedido explícito do usuário.

Um hook local `pre-push` que bloqueia push direto a `main` complementa esta
regra (ver `.git/hooks/pre-push`), mas não substitui a verificação acima.

## Como aplicar no projeto

- Use o agente de especificação para planejar a próxima etapa antes de começar a codificar.
- Use o agente de implementação para criar módulos independentes: captura, IA, alertas, dashboard.
- Use o agente de testes para validar cada módulo individualmente e o fluxo integrado.
- Use o agente de revisão de código para validar aderência ao spec, qualidade e cobertura de testes.

## 4. Agente de revisão de código
- Responsável por revisar mudanças de código e pull requests.
- Deve avaliar alinhamento com `SPEC.md`, `README.md` e padrões de projeto.
- Deve checar qualidade de código, testes, documentação, performance e portabilidade.
- Deve sugerir melhorias claras e acionáveis.

## Padrões de estilo (OBRIGATÓRIO)

- **Antes de criar ou modificar qualquer HTML/CSS**, ler `.opencode/skills/style/SKILL.md`.
- Usar **sempre** as CSS variables do style guide (`var(--primary)`, `var(--muted)`, `var(--radius)`, etc.).
- **Nunca** usar cores hardcoded (`#666`, `#ddd`) ou valores fixos (`border-radius:8px`).
- **Nunca** usar `var(--text-secondary)` — o correto é `var(--muted)` ou `var(--muted-subtle)`.
- Botões: `button-primary` (ações principais), `button-secondary` (secundárias), `button-mini` (tabelas/cards).
- Tabelas: `thead th` com `var(--surface-2)`, `0.75rem`, uppercase.
- Cards: `var(--surface)`, `border: 1px solid var(--border)`, `border-radius: var(--radius)`.
- Forms: `label` com `var(--muted-subtle)`, `input/select` com `border-radius: var(--radius-sm)`.
- Validar CSS contra o skill guide antes de commit (sem lixo, sem duplicações).

## Padrões relevantes para Secur

- Dividir a lógica de captura de câmeras e inferência de IA em componentes separados.
- Adotar um simples pipeline de processamento: captura → detecção de movimento → inferência → regras → alerta.
- Priorizar compatibilidade local e operação offline.
- Projetar a arquitetura para suportar até 8 câmeras no futuro.

## Retroalimentar conhecimento
- Quando encontra solução para um problema, documentar o problema e como resolver;
- Se um recurso novo for requerido, avaliar o que já existe pesquisando na web para propor melhores práticas na implementação e focar no "valor" para o usuário;
- Avaliar riscos, aqueles ligados a pessoas, cultura e legislação antes de implementar
  
## Documentação de especificações e planos

- Specs e planos de features ficam em `docs/superpowers/specs/` e `docs/superpowers/plans/`.
- Convenção de nomes: `YYYY-MM-DD-nome-do-feature.md` (kebab-case, com data).
- Specs usam sufixo `-design` no nome: `YYYY-MM-DD-nome-design.md`.
- Planos usam o header do superpowers: `For agentic workers: REQUIRED SUB-SKILL...`.
- Cada spec deve incluir: problema, o que já existe, o que construir, modelo de dados, rotas, segurança, riscos.
- Cada plano deve incluir: Goal, Architecture, Tech Stack, Global Constraints, e tarefas checklistadas.

## Skills disponíveis (`.opencode/skills/`)

Skills locais do projeto, disponíveis para agentes via OpenCode:

| Skill | Arquivo | Uso |
|-------|---------|-----|
| `code-review` | `.opencode/skills/code-review/SKILL.md` | Revisão de código: checklist de alinhamento com spec, qualidade, segurança, performance |
| `style` | `.opencode/skills/style/SKILL.md` | Style guide do dashboard: paleta de cores, layout, componentes CSS, padrões responsivos |

### Superpowers (plugin OpenCode)

Skills do plugin [superpowers](https://github.com/obra/superpowers), instalado via `opencode.json`:

| Skill | Uso |
|-------|-----|
| `brainstorming` | Design iterativo: refina ideias via perguntas, valida em seções |
| `writing-plans` | Planos detalhados: tarefas de 2-5 min com caminhos de arquivo e código completo |
| `subagent-driven-development` | Desenvolvimento com subagentes: uma task por subagent, com review duplo |
| `executing-plans` | Execução em batches com checkpoints humanos |
| `test-driven-development` | Ciclo RED-GREEN-REFACTOR: teste falha → implementa → passa → commit |
| `requesting-code-review` | Review pré-tarefa: verifica contra o plano, reporta por severidade |
| `using-git-worktree` | Branches isoladas para trabalho paralelo |
| `finishing-a-development-branch` | Verifica testes, apresenta opções de merge/PR/keep/discard |

### Como usar skills

- Agentes devem checar skills relevantes antes de iniciar qualquer tarefa.
- Skills são workflows obrigatórios, não sugestões.
- Para planos em `docs/superpowers/plans/`, usar `superpowers:executing-plans` ou `superpowers:subagent-driven-development`.

## Melhorias futuras

- Incluir um agente de integração com automação residencial.
- Incluir um agente de desempenho para otimização em Raspberry Pi.
- Incluir um agente de deploy para preparar instalação e configuração em Linux/Pi.
