# Manual do usuário — Tucuxi Monitor

> Como usar o sistema no dia a dia: acessar o painel, visualizar câmeras, consultar eventos, receber e agir sobre alertas, e exportar evidências.

## 1. O que é o Tucuxi Monitor

O Tucuxi Monitor observa suas câmeras IP com inteligência artificial e avisa quando algo importante acontece — presença, intrusão, queda, permanência suspeita, desconhecidos e mais. Todo o processamento é **100% local**: nada sai do seu equipamento, exceto pelos canais de alerta que você (ou o administrador) configurar.

Este manual cobre o **uso diário**. Para instalação, deploy e configuração avançada (variáveis de ambiente, MQTT, Home Assistant, sirene, usuários), veja [docs/technical.md](docs/technical.md).

## 2. Acesso e login

1. Abra no navegador: `http://<servidor>:8000` (em geral `http://localhost:8000` no equipamento onde roda).
2. Na tela de **login**, informe usuário e senha.
3. Se for o primeiro acesso, um administrador precisa criar seu usuário (detalhes em `docs/technical.md`).

> Dica: mantenha sua senha segura. As sessões são registradas em auditoria.

## 3. Visão geral (Overview)

Ao entrar, o painel mostra **cartões de resumo** (nº de câmeras, eventos recentes, etc.) e o **status do sistema** (saúde das câmeras e do processamento). Use essa tela para confirmar rapidamente que tudo está operando.

- Câmeras offline aparecem destacadas — verifique a fonte/conexão.
- O status do sistema indica se a análise está saudável.

## 4. Câmeras

Na seção **Câmeras**, você vê as câmeras cadastradas e seu estado.

- Visualize a pré-visualização/estado de cada câmera.
- Câmeras com região de privacidade aplicam *blur* automaticamente em thumbnails, clipes e snapshots.
- O cadastro e a configuração de zonas/exclusão são feitos pelo administrador (veja `docs/technical.md`).

## 5. Eventos (histórico)

A seção **Eventos** é onde você consulta tudo o que o sistema detectou.

### Filtros

Use a barra de filtros para encontrar o que importa:

- **Câmera** — restringe a uma câmera específica.
- **Zona** — por área monitorada (ex.: entrada, garagem).
- **Tipo** — o tipo de evento (movimento, intruso, queda, desconhecido, etc.).
- **Nível** — severidade do evento.
- **Período** — eventos desde uma data/hora.
- **Só alertas** — mostra apenas eventos classificados como alerta.
- **Só retidos** — mostra apenas eventos mantidos (não podados por retenção).
- **Limpar** — remove os filtros.

### Detalhe do evento

Cada evento traz a **evidência**: uma thumbnail e, quando disponível, o **clipe** do momento (vídeo curto antes/depois do evento). Abrir um evento permite revisar o que aconteceu e, se aplicável, reproduzir o clipe para avaliar a situação.

## 6. Alertas

O Tucuxi gera alertas em eventos relevantes. Como você recebe e age:

- **Recebimento**: os alertas chegam pelos canais configurados (Telegram, MQTT, Home Assistant) — definidos pelo administrador.
- **Na tela**: eventos de alerta também aparecem destacados na seção Eventos (use o filtro "Só alertas").
- **Agir**: ao receber um alerta, abra o evento correspondente para ver a evidência (thumbnail + clipe) e avaliar a situação.

### Configurar quais eventos viram alerta

Na seção **Notificações**, você (ou o administrador) escolhe, para cada tipo de evento, em quais canais ele é notificado. Assim você evita ruído e recebe só o que importa.

> Em eventos críticos (intruso, queda, permanência suspeita, mudança de direção, desconhecido), se o sistema estiver integrado com uma sirene/atuação externa, o dispositivo pode ser acionado automaticamente. Essa integração é configurada pelo instalador — veja a seção "Atuação externa (sirene)" no [README](README.md) e em `docs/technical.md`.

## 7. Exportação de evidências

Para backup ou encaminhamento (ex.: para a polícia), o sistema exporta um pacote completo de eventos:

- A exportação gera um arquivo **ZIP** contendo `events.json` (dados dos eventos), as **thumbnails** e os **clipes** associados.
- É possível filtrar por **câmera** e por **período** (data/hora inicial e final).
- O download é feito pelo recurso de exportação (`/export`) — consulte o administrador ou a referência técnica para acioná-lo a partir da sua interface.

> A exportação respeita a autenticação: apenas usuários logados podem baixar o pacote.

## 8. Dicas e onde encontrar mais

- **Muito ruído de alertas?** Ajuste o roteamento na seção Notificações para receber só os tipos que importam.
- **Câmera offline?** Veja o status do sistema na Visão geral e revise a fonte no cadastro de câmeras.
- **Instalação, deploy, MQTT/Home Assistant, sirene, usuários e permissões**: [docs/technical.md](docs/technical.md).
- **Roadmap** (próximas funcionalidades): [docs/roadmap.md](docs/roadmap.md).
