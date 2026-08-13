---
type: build-report
area: ai-for-data-engineering
domain: agentic-knowledge-acquisition
status: in-progress
created: 2026-07-21
updated: 2026-08-13
tags: [workflow/build, topic/knowledge-acquisition, evidence/traceability]
related: [TASKS_AGENTIC_KNOWLEDGE_ACQUISITION, DESIGN_AGENTIC_KNOWLEDGE_ACQUISITION]
---

# Build Report - Agentic Knowledge Acquisition

## Status

O primeiro incremento foi mergeado no PR #1, commit `4bead6b`. O segundo incremento foi mergeado no PR #2, commit `817cd08`. O terceiro incremento foi mergeado no PR #3, commit `d75d118`. O quarto incremento foi mergeado no PR #4, commit `43b7dba`. A quinta rodada foi mergeada no PR #5, commit `9cdf33b`. O sexto incremento foi mergeado no PR #6, commit `60a2bef`. O setimo incremento foi mergeado no PR #7, commit `7dc7f5d`. O oitavo incremento foi mergeado no PR #8, commit `fe74727`. O nono incremento foi executado na branch `codex/increment-9-sqs-worker`: T-012 esta concluida com gates offline verdes; T-013 e todas as tarefas posteriores permanecem pendentes. Nenhuma integracao AWS/live, eval, deploy, URL real ou credencial real foi usada.

## Escopo do primeiro incremento

| Campo | Valor |
|---|---|
| Branch | `codex/increment-1-bootstrap-domain` |
| Commit base | `f5aae25` |
| Tarefas autorizadas | `T-001`, `T-002` |
| Tarefas executadas | `T-001`, `T-002` |
| Tarefas fora do escopo | `T-003` a `T-017` |
| Rede de aplicacao | nao usada |
| Testes live/eval | excluidos explicitamente |
| Deploy | nao executado |
| Credenciais reais | nao usadas |

## Escopo do segundo incremento

| Campo | Valor |
|---|---|
| Branch | `codex/increment-2-local-foundations` |
| Commit base | `4bead6b` |
| Tarefas autorizadas | `T-003`, `T-004`, `T-005` |
| Tarefas executadas | `T-003`, `T-004`, `T-005` |
| Tarefas fora do escopo | `T-006` a `T-017` |
| Rede de aplicacao | nao usada |
| Testes live/eval | excluidos explicitamente |
| Deploy | nao executado |
| Credenciais reais | nao usadas |

## Escopo do terceiro incremento

| Campo | Valor |
|---|---|
| Branch | `codex/increment-3-langgraph-fakes` |
| Commit base | `817cd08` |
| Tarefas autorizadas | `T-006` |
| Tarefas executadas | `T-006` |
| Tarefas fora do escopo | `T-007` a `T-017` |
| Rede de aplicacao | nao usada |
| Testes live/eval | excluidos explicitamente |
| Deploy | nao executado |
| Credenciais reais | nao usadas |

## Escopo do quarto incremento

| Campo | Valor |
|---|---|
| Branch | `codex/increment-4-vault-core` |
| Commit base | `d75d118` |
| Tarefas autorizadas | `T-007` |
| Tarefas executadas | `T-007` |
| Tarefas fora do escopo | `T-008` a `T-017` |
| Vault usado | somente fixtures em diretorios temporarios |
| Rede de aplicacao | nao usada |
| Testes live/eval | excluidos explicitamente |
| Deploy | nao executado |
| Credenciais reais | nao usadas |

## Escopo da quinta rodada

| Campo | Valor |
|---|---|
| Branch | `codex/increment-5-qdrant-local` |
| Commit base | `43b7dba` |
| Tarefas autorizadas | `T-008` |
| Tarefas executadas | `T-008` |
| Tarefas fora do escopo | `T-009` a `T-017` |
| Qdrant | somente adapter com fake; container nao iniciado |
| OpenAI | somente adapter com client fake; API nao chamada |
| Vault usado | somente Markdown em diretorios temporarios |
| Rede de aplicacao | nao usada |
| Testes live/eval | excluidos explicitamente |
| Deploy | nao executado |
| Credenciais reais | nao usadas |

## Escopo do sexto incremento

| Campo | Valor |
|---|---|
| Branch | `codex/increment-6-openai-agents` |
| Commit base | `9cdf33b` |
| Tarefas autorizadas | `T-009` |
| Tarefas executadas | `T-009` |
| Tarefas fora do escopo | `T-010` a `T-017` |
| OpenAI | SDK exercitado somente com client fake; API nao chamada |
| Prompts | quatro recursos versionados e dados sinteticos |
| Rede de aplicacao | nao usada |
| Testes live/eval | excluidos explicitamente |
| Deploy | nao executado |
| Credenciais reais | nao usadas |

## Escopo do setimo incremento

| Campo | Valor |
|---|---|
| Branch | `codex/increment-7-web-provider` |
| Commit base | `60a2bef` |
| Tarefas autorizadas | `T-010` |
| Tarefas executadas | `T-010` |
| Tarefas fora do escopo | `T-011` a `T-017` |
| Web | HTTPX/HTTPCore e Trafilatura exercitados somente com resolver/fetcher offline |
| Fonte | fixture HTML publica sanitizada e sintetica |
| Rede de aplicacao | nao usada |
| Testes live/eval | excluidos explicitamente |
| Deploy | nao executado |
| Credenciais reais | nao usadas |

## Escopo do oitavo incremento

| Campo | Valor |
|---|---|
| Branch | `codex/increment-8-notebooklm-provider` |
| Commit base | `7dc7f5d` |
| Tarefas autorizadas | `T-011` |
| Tarefas executadas | `T-011` |
| Tarefas fora do escopo | `T-012` a `T-017` |
| MCP | cliente stdio e provider exercitados com fake/subprocesso Python local |
| NotebookLM | proxy, browser, sessao e conta reais nao iniciados |
| Registry | runtime 2.1.0 permitido em `evaluating` somente com supervisao |
| Rede de aplicacao | nao usada |
| Testes live/eval | excluidos explicitamente; smoke NotebookLM permaneceu `skip` |
| Deploy | nao executado |
| Credenciais reais | nao usadas |

## Escopo do nono incremento

| Campo | Valor |
|---|---|
| Branch | `codex/increment-9-sqs-worker` |
| Commit base | `fe74727` |
| Tarefas autorizadas | `T-012` |
| Tarefas executadas | `T-012` |
| Tarefas fora do escopo | `T-013` a `T-017` |
| SQS | adapter exercitado somente com client fake |
| Worker | lifecycle exercitado com `FakeQueue`, `FakeRunStore` e SQLite temporario |
| Rede de aplicacao | nao usada; indice de pacotes usado somente para resolver boto3 |
| Testes live/eval | excluidos explicitamente; dois smokes permaneceram desmarcados |
| Deploy | nao executado |
| Credenciais reais | nao usadas |

## Proveniencia do handoff

| Campo | Valor |
|---|---|
| Repositorio de origem | `JpOlstan/data-engineering-knowledge-base` |
| Branch de origem | `main` |
| Merge commit verificado | `6a43af3` |
| Commit SDD aceito | `35903a8` |
| Data do handoff | `2026-07-21` |
| Repositorio de destino | `JpOlstan/agentic-knowledge-pipeline` |

## Snapshot das specs

| Documento | Status no handoff | Custodia atual |
|---|---|---|
| `BRAINSTORM_AGENTIC_KNOWLEDGE_ACQUISITION.md` | validated | este repositorio |
| `DEFINE_AGENTIC_KNOWLEDGE_ACQUISITION.md` | validated | este repositorio |
| `DESIGN_AGENTIC_KNOWLEDGE_ACQUISITION.md` | validated | este repositorio |
| `TASKS_AGENTIC_KNOWLEDGE_ACQUISITION.md` | validated | este repositorio |

## Estado dos incrementos

| Incremento | Status | Evidencia |
|---|---|---|
| I0 | completed | T-001, bootstrap e gates reproduziveis |
| I1 | completed | T-002 a T-006 concluidas; pipeline provado integralmente com fakes |
| I2 | completed | T-007 e T-008 concluidas; vault e indice local validados offline |
| I3 | completed | T-009 concluida; adapter e tres agentes validados offline |
| I4 | completed | T-010 e T-011 concluidas; dois providers validados offline |
| I5 | in-progress | T-012 concluida offline; T-013 pendente |
| I6 | pending | nenhuma |
| I7 | pending | nenhuma |

## Registro de execucao

### 2026-07-21 - Handoff das specs

- specs copiadas da versao mergeada na `main` do repositorio de origem;
- custodia canonica transferida para este repositorio;
- T-001 esclarecida como bootstrap do repositorio ja criado;
- nenhum requisito, componente ou criterio de aceite foi alterado;
- nenhuma credencial, URL privada, conteudo-fonte integral ou dado do vault foi transferido.

### 2026-07-21 - Primeiro incremento: T-001 e T-002

- criada a branch `codex/increment-1-bootstrap-domain` a partir de `f5aae25`;
- criado o bootstrap Python 3.12 em layout `src`, com lockfile, grupos `main`, `dev`, `live` e `eval`, markers offline e configuracao Ruff/Pytest;
- criado o pacote `knowledge_agents` e configurado o entry point futuro `knowledge-agents`;
- implementados settings `KA_`, contratos Pydantic imutaveis, enums, taxonomia segura de erros, hashing canonico, usage ledger e budgets;
- adicionados testes de contratos, outputs estruturados, hashing, limites operacionais, paths relativos e representacao segura de erros;
- executados somente gates offline; nenhum provider, SDK cloud, fila, banco externo, deploy, teste live ou eval foi chamado.

### 2026-07-21 - Segundo incremento: T-003, T-004 e T-005

- PR #1 confirmado como mergeado e `main` sincronizada por fast-forward para `4bead6b`;
- criada a branch `codex/increment-2-local-foundations` a partir da `main` mergeada;
- definidos sete ports assincronos e fakes deterministicos com failure plans e call logs;
- implementados SQLiteRunStore, migrations, leases, idempotencia, resume, replay e registro de artifacts;
- implementado FilesystemArtifactStore com JSON canonico, escrita atomica e validacao de paths;
- implementada arvore Typer e doctor local com registry extensivel, JSON sanitizado e exit codes previsiveis;
- executados somente gates offline e filesystem/SQLite temporarios; nenhum provider real, cloud SDK, fila ou LLM foi chamado.

### 2026-08-04 - Terceiro incremento: T-006

- PR #2 confirmado como mergeado e `main` sincronizada por fast-forward para `817cd08`;
- criada a branch `codex/increment-3-langgraph-fakes` a partir da `main` mergeada;
- clarificada a boundary ja implicada pelo DESIGN: somente `application/graph` pode importar
  LangGraph, o checkpointer e o transporte SQLite; dominio, ports, agents e services continuam
  independentes desses frameworks;
- implementado parent graph com 13 nodes, tres subgrafos estaticos per-invocation e
  `AsyncSqliteSaver` em banco separado, usando `thread_id=run_id` e serializer estrito;
- implementados A1, A2 e A3 sobre contratos e ports, sem SDK real, com budgets e usage ledger;
- implementado loop editorial A3 -> A2 somente para drafts bloqueados, freeze de aprovados por
  hash, maximo de dois ciclos e progress fingerprint;
- implementado terminal seguro para evidencia insuficiente, rejeicao e falhas secundarias;
- implementado RunService para execute, state e resume a partir do checkpoint;
- toda a execucao usou fakes e SQLite/filesystem temporarios, sem rede de aplicacao.

### 2026-08-05 - Quarto incremento: T-007

- PR #3 confirmado como mergeado e `main` sincronizada por fast-forward para `d75d118`;
- criada a branch `codex/increment-4-vault-core` a partir da `main` mergeada;
- implementado inventario Markdown reduzido e ordenado, limitado a roots relativas allowlisted e
  sem transportar corpos de notas;
- implementado renderer deterministico de frontmatter e secoes Markdown com hash revisado, status,
  proveniencia por claim e recomendacao de promocao apenas informativa;
- implementado writer restrito a `01-inbox/agent-runs/<run_id>`, com preflight de todos os targets,
  temp file, flush, fsync, replace atomico e idempotencia por bytes;
- preservados drafts `ready`, `partially_ready` e `enrichment_required`; drafts `rejected` ou com
  decisao `discard` sao registrados como omitidos;
- implementados manifest JSON canonico e review summary sem issues, required changes ou conteudo
  integral dos drafts;
- todos os testes usaram apenas vaults temporarios e contracts locais, sem ler ou alterar o vault
  real.

### 2026-08-13 - Quinta rodada: T-008

- PR #4 confirmado como mergeado e `main` sincronizada por fast-forward para `43b7dba`;
- criada a branch `codex/increment-5-qdrant-local` a partir da `main` mergeada;
- implementado chunker v1 deterministico com heading path, source locator, target 800, maximo 1.200,
  overlap 120 e preservacao de estruturas Markdown indivisiveis quando cabem;
- implementado adapter de embeddings em lote com deduplicacao exata por SHA-256 e dimensao
  configuravel; testes usam client injetado e nao chamam OpenAI;
- implementado adapter Qdrant com cosine, tres collections versionadas, sete payload indexes,
  validacao de schema e operacoes de consulta, validacao, remocao e rebuild;
- implementado `IndexService` com fingerprint de modelo/dimensao/chunker/schema, point IDs
  deterministicos, no-op, troca segura de geracao e bloqueio de delecao/rebuild sob scan incompleto;
- ativados `index status`, `index sync` e `index rebuild --yes`, com precondicoes fechadas e saida
  sanitizada;
- estendidos RunStore, SQLite e fakes para persistir `IndexRecord` e `RepairTask` sobre o schema ja
  criado em T-004, sem migration adicional;
- fixado `qdrant/qdrant:v1.18.2` em Compose com bind somente em loopback e volume ignorado;
- nenhum container, endpoint Qdrant, API OpenAI, vault real ou outra integracao foi executado.

### 2026-08-13 - Sexto incremento: T-009

- PR #5 confirmado como mergeado e `main` sincronizada por fast-forward para `9cdf33b`;
- criada a branch `codex/increment-6-openai-agents` a partir da `main` mergeada;
- implementado `OpenAIStructuredClient` sobre `responses.parse`, mantendo OpenAI confinado ao
  adapter e `StructuredLLMPort` neutro;
- configurados model ID, reasoning effort e max output por agente; o factory do SDK fixa timeout
  de 120 segundos e dois retries de transporte;
- implementado contract repair unico para parse ausente ou schema incorreto, sem confundir retry
  tecnico com ciclo editorial;
- recusas e segunda falha contratual terminam com erro seguro; excecoes de transporte permanecem
  sob ownership do SDK e nao recebem retry na application layer;
- agregados tokens, custo estimado e duracao do retorno do SDK; response ID, model, prompt e repair
  flag permanecem em metadata compacta do state;
- criados quatro prompts versionados com trust boundary explicita para fonte, retrieval, drafts e
  evidence; nenhum tool e disponibilizado;
- Agentes 1, 2 e 3 carregam o prompt adequado, aplicam budget antes da chamada e preservam uma
  chamada principal por pacote no happy path;
- criado smoke test minimo e sanitizado sob marker `live`, mas ele nao foi selecionado nem
  executado nesta rodada.

### 2026-08-13 - Setimo incremento: T-010

- PR #6 confirmado como mergeado e `main` sincronizada por fast-forward para `60a2bef`;
- criada a branch `codex/increment-7-web-provider` a partir da `main` mergeada;
- implementado `WebArticleProvider` sobre `KnowledgeSourceProvider`, com HTTP/HTTPS, portas
  allowlisted, timeout, content types textuais e limite de 5 MiB;
- implementada validacao de todos os enderecos A/AAAA e transporte HTTPX/HTTPCore pinado ao IP
  publico aprovado, preservando Host e SNI sem segunda resolucao DNS;
- cada um dos no maximo cinco redirects passa novamente por validacao completa de URL e DNS;
- bloqueados IPv4/IPv6 private, loopback, link-local, multicast, reserved, unspecified, IPv4
  mapeado, credenciais embutidas, fragments e portas fora da allowlist;
- integrada Trafilatura 2.2 para texto e metadata deterministicos, executada fora do event loop;
- HTML bruto de sucesso nao e persistido e falhas de extracao usam runtime local ignorado, nome
  opaco e cleanup por TTL de 24 horas;
- adicionada fixture HTML sanitizada e provado o provider real no mesmo LangGraph com LLMs fake;
- nenhuma URL real, browser, JavaScript, cookie, credencial ou integracao live foi usada.

### 2026-08-13 - Oitavo incremento: T-011

- PR #7 confirmado como mergeado e `main` sincronizada por fast-forward para `7dc7f5d`;
- criada a branch `codex/increment-8-notebooklm-provider` a partir da `main` mergeada;
- implementado cliente JSON-RPC 2.0 stdio com lifecycle controlado, timeout, limite de mensagem,
  serializacao de requests, stderr descartado e encerramento forcado com timeout;
- ambiente filho reduzido a chaves operacionais e flags `HEADLESS=true`,
  `AUTO_LOGIN_ENABLED=false`, remote read e ask; secrets da aplicacao nao sao herdados;
- implementado `NotebookLMProvider` sobre o mesmo `KnowledgeSourceProvider`, com preflight de
  handshake, `tools/list` e `server_health` antes de acessar a fonte;
- allowlist do provider limitada as sete tools do DESIGN; as quatro leituras locais adicionais do
  registry podem ser anunciadas, mas nao sao invocaveis pelo provider;
- tool fora do registry read-only falha fechado antes do health; link compartilhado aceita somente
  HTTPS, host NotebookLM, porta default e path de notebook;
- runtime fixado semanticamente em `@roomi-fields/notebooklm-mcp` 2.1.0; status `evaluating`
  requer supervisao e uso nao supervisionado exige `approved-read-only`;
- doctor ganhou profile NotebookLM com checks offline sanitizados de Node, proxy, package, data dir
  e policy do registry;
- smoke live read-only foi criado sob marker `live`, mas permaneceu desmarcado;
- somente codigo do proxy e metadata do package/registry foram lidos; data dir, cookies, conta,
  browser, URL real e sessao nao foram acessados.

### 2026-08-13 - Nono incremento: T-012

- PR #8 confirmado como mergeado e branch criada a partir de `fe74727`;
- implementado `SqsQueue` sobre boto3 com chamadas sincronas deslocadas para thread, long polling de
  20 segundos, visibility inicial de 180 segundos, heartbeat, ack e release;
- resposta do SDK e validada antes de criar `QueueMessage`; falhas sao convertidas em
  `QUEUE_UNAVAILABLE` sem incluir queue URL ou corpo da mensagem;
- envelope nao confiavel limitado a 16 KiB e validado estritamente, inclusive versao, timestamp,
  campos extras e chaves JSON duplicadas;
- worker adquire lease duravel antes do executor, renova lease antes da visibility e reconhece a
  mensagem somente depois de reler estado terminal no `RunStore`;
- falha recuperavel libera visibility; perda de heartbeat cancela o trabalho em curso e deixa o
  timeout permitir redelivery e resume;
- entrega terminal duplicada foi testada com SQLite real sem segunda execucao; shutdown apos poll
  libera trabalho ainda nao iniciado;
- boto3 foi adicionado como dependencia direta e isolado no adapter; nenhum client AWS real foi
  criado durante os testes;
- AWS/SQS real, live/eval, deploy, T-013 e credenciais reais nao foram usados.

## Evidencias de T-001

### Manifesto realizado

| Verificacao | Resultado |
|---|---|
| Arquivos declarados | `13/13` presentes |
| Python requerido | `>=3.12,<3.13` |
| Python resolvido | CPython `3.12.12` |
| uv | `0.9.30` |
| Ambiente locked | 21 pacotes resolvidos e instalados |
| Package import | `knowledge_agents.__version__ == "0.1.0"` |
| Specs canonicas | BRAINSTORM, DEFINE, DESIGN e TASKS presentes |

### Comandos de verificacao

| Comando | Resultado |
|---|---|
| `uv lock` | sucesso; `uv.lock` gerado para Python 3.12 |
| `uv sync --locked` | sucesso; ambiente criado a partir do lockfile |
| `uv run python -c "import knowledge_agents; print(knowledge_agents.__version__)"` | sucesso; `0.1.0` |
| `uv run ruff format --check .` | sucesso; 12 arquivos formatados |
| `uv run ruff check .` | sucesso; `All checks passed!` |
| `uv run pytest -m "not live and not eval"` | sucesso; `27 passed in 0.51s` |
| scan `TODO|FIXME|XXX` em codigo e configuracao | nenhum match |
| scan de formatos comuns de AWS, OpenAI, GitHub, Slack e private keys | nenhum match |
| scan de URLs privadas NotebookLM/AWS de integracao | nenhum match |

## Evidencias de T-002

### Cobertura offline

| Suite | Casos | Resultado |
|---|---:|---|
| `tests/contracts/test_contracts.py` | 11 | passou |
| `tests/contracts/test_prompt_outputs.py` | 3 | passou |
| `tests/unit/test_budgets.py` | 9 | passou |
| `tests/unit/test_hashing.py` | 4 | passou |
| **Total** | **27** | **passou sem rede** |

Comportamentos cobertos:

- request externo exige somente URL HTTP/HTTPS valida e ignora campos extras;
- contratos internos rejeitam campos extras, sao frozen e usam datetimes com timezone;
- paths de artifacts rejeitam traversal e paths absolutos;
- outputs representativos dos tres agentes validam nos mesmos contratos de producao;
- hashes canonicos sao estaveis sob ordem de chaves e incluem a versao do contrato;
- hash de draft exclui o proprio campo `content_hash`;
- ledger reconcilia chamadas, input, output, custo e duracao;
- preflight bloqueia limites por chamada, call count, total de tokens, custo e duracao;
- erro seguro nao inclui causa, secret ou path absoluto.

### Matriz contrato-versao e JSON Schema

Os hashes abaixo foram calculados sobre `model_json_schema()` serializado canonicamente. Eles permitem detectar mudanca estrutural posterior sem registrar dados de runtime.

| Contrato | Versao | JSON Schema SHA-256 |
|---|---|---|
| `AcquisitionRequest` | external | `d74d9e6d47b239f0cf0c154948af4757dc07b138cb91716a284f9eff82c4c894` |
| `SourceDescriptor` | 1 | `bef2b569bc0252735220b2539fa06acf915841d8fd0fb837c52c011a11467262` |
| `EvidenceBatch` | 1 | `54c7c836c04b88970b736cca7bbec0907bd2209d10ea4bafb19cc5030ca2a75e` |
| `AcquisitionPacket` | 1 | `3e0adb2e2ab349e8f20c3bbcd536017d735b1021bc7111731f67647524c1dc44` |
| `DraftPackage` | 1 | `c81756c5579114e4efcd8d6907f60ca001b51b8d0547408b65640f93ba188b50` |
| `ReviewPackage` | 1 | `184ea0f1091874c9b6f368bf4f3bb4a8061b08c6f08f088adcaef9e7cce3b35d` |
| `RunManifest` | 1 | `35cbd554333f17020817f3517abbfbede9eba325adaa10b070abeea06218a384` |
| `ContextBudget` | 1 | `d42124466a9ad942ce11c3938b2d8cedb90ea0c3832f002de231e8ca7c3701b3` |
| `RevisionRequest` | 1 | `4b2d326e7a75cf48bbb472f64b68f9b3e30e1d2a6ee1564301716680678f082e` |
| `IndexRecord` | 1 | `b9fe3132d6bcec53dec6861c2d1eace8b7b740ed580fd542c2a98dcedfd8800a` |
| `RepairTask` | 1 | `3f1eec73c916c03f104020dec09dcffbae3a81bbb6b7e14ab42b59a8304a244c` |

### Rastreabilidade parcial do incremento

| Requisito | Evidencia deste incremento | Estado |
|---|---|---|
| RF-001 | `AcquisitionRequest` e validacao de URL/extras | base contratual concluida; trigger posterior |
| RF-003 a RF-009 | contratos versionados para provider, evidencia, drafts, review, manifest, index e repair | base contratual concluida; fluxos posteriores |
| RF-011 | categorias de erro e budget ownership sem retry de infraestrutura | base de dominio concluida |
| RNF-001 | secrets tipados, `.gitignore`, paths relativos, erro seguro e scans | gate do incremento concluido |
| RNF-002 | modelos frozen, serializacao canonica e SHA-256 | gate do incremento concluido |
| RNF-003 | limites de chamadas, tokens, custo, duracao e tamanho | gate do incremento concluido |
| RNF-004 | suite default totalmente offline | gate do incremento concluido |
| RNF-006 | Python fixado, `uv.lock` e ambiente reproduzido | gate do incremento concluido |

### 2026-07-21 - Double check pre-publicacao

Uma segunda verificacao independente foi executada antes de stage, commit e push:

| Verificacao | Resultado |
|---|---|
| Escopo do worktree | 20 paths esperados, 20 encontrados, zero inesperados e zero ausentes |
| `uv lock --check` | 21 pacotes resolvidos; lockfile sincronizado |
| `uv sync --locked` | 21 pacotes auditados; nenhuma mudanca no ambiente |
| `uv run ruff format --check .` | 12 arquivos ja formatados |
| `uv run ruff check .` | todos os checks passaram |
| `uv run pytest -m "not live and not eval"` | 27 testes passaram em 0.45s |
| `uv build` | sdist e wheel `knowledge_agents-0.1.0` gerados com sucesso |
| JSON Schemas | 11 de 11 hashes conferem com este report |
| Scan de TODOs | zero matches |
| Scan de credenciais e URLs privadas | zero matches |
| Arquivos locais ignorados | `.venv`, `dist`, `.pytest_cache` e `__pycache__` confirmados pelo Git |

Conclusao: nenhum achado bloqueante ou desvio de escopo foi identificado. O incremento esta apto para commit e draft PR.

## Evidencias de T-003

| Evidencia | Resultado |
|---|---|
| Ports | provider, LLM, run store, artifact store, queue, vector index e telemetry |
| Fakes | sete implementacoes deterministicamente configuraveis |
| Call logs | operacao e argumentos registrados sem mocks de SDK |
| Failure plans | falhas configuradas por operacao e verificadas offline |
| Boundary dominio | bloqueia adapters, application, ports e SDKs externos |
| Boundary ports | permite somente stdlib e `knowledge_agents.domain` |
| Testes T-003 | 7 passaram |

## Evidencias de T-004

### Plano de migrations

| Migration | Estruturas |
|---|---|
| `001_initial.sql` | `runs`, `artifacts`, `attempts`, `index_records`, `repair_tasks` |
| `002_indexes.sql` | indexes de status, lease, artifacts, attempts e repairs |

As migrations sao numeradas, aplicadas sob `BEGIN IMMEDIATE`, registradas em `schema_migrations` e idempotentes. O wheel final contem os dois arquivos SQL.

| Comportamento | Evidencia |
|---|---|
| SQLite | WAL, foreign keys e busy timeout |
| Idempotencia | duplicate delivery reutiliza o run; hash conflitante falha fechado |
| Lease | aquisicao concorrente unica, renew por owner, expiracao e release condicional |
| Resume/replay | resume preserva ID; replay cria ID e key novos |
| ArtifactStore | temp file, flush, fsync, atomic replace e hash canonico |
| Seguranca de path | traversal, absoluto, symlink simulado e colisao bloqueados |
| Crash safety | falha de replace nao deixa arquivo parcial |
| Testes T-004 | 10 passaram, zero skips |

## Evidencias de T-005

| Check local | Comportamento |
|---|---|
| Python | exige baseline 3.12 |
| Configuration | valida roots distintos e allowlist relativa |
| Runtime | verifica diretorio local legivel e gravavel |
| Vault | valida root e containment dos paths permitidos |
| SQLite | aplica e confirma migrations 1 e 2 |

O entry point instalado exporta `trigger`, `doctor`, `worker`, `runs`, `repairs` e `index`. Somente `doctor --profile local` possui comportamento ativo neste incremento; comandos futuros retornam precondition exit code 2.

| Evidencia | Resultado |
|---|---|
| Saida humana e JSON | sem secrets ou paths absolutos |
| Exit codes | 0 sucesso, 2 precondicao, 3 dependencia, 4 execucao |
| Registry | profiles futuros configuraveis sem rede por default |
| Testes T-005 | 9 passaram |

## Evidencias de T-006

### Grafo e persistencia

| Elemento | Evidencia |
|---|---|
| Parent graph | 13 nodes na ordem validada pelo DESIGN |
| Subgrafos | `agent_1`, `agent_2` e `agent_3`, estaticos e per-invocation |
| Checkpointer | `AsyncSqliteSaver` assincrono, WAL e busy timeout |
| Serializer | `JsonPlusSerializer(allowed_msgpack_modules=None)` |
| Correlacao | `thread_id=run_id` |
| State | refs serializadas, hashes, counters, budget, usage e warnings |
| Conteudo grande | evidencia e corpos de drafts ausentes do snapshot |
| Resume | interrupcao e retomada validadas depois de cada um dos 13 nodes |

Fluxo exportado:

```text
prepare_run -> inspect_source -> acquire_evidence -> agent_1
-> validate_acquisition -> retrieve_vault_context -> agent_2
-> validate_drafts -> agent_3 -> route_review

route_review -- revise --> agent_2
route_review -- persist --> persist_terminal -> sync_index -> flush_telemetry
```

### Policy editorial e falhas

| Cenario | Resultado |
|---|---|
| Happy path | `completed`, 3 chamadas principais |
| Um ciclo editorial | somente draft bloqueado revisado; aprovado congelado por hash |
| Dois ciclos editoriais | `completed`, 7 chamadas dentro do budget |
| Mesmo fingerprint | termina `enrichment_required` sem segundo ciclo inutil |
| Evidencia insuficiente | termina `enrichment_required` sem retornar ao A1 |
| Falha de index | warning `index_repair_required`; agentes nao reexecutados |
| Falha de telemetry | warning `telemetry_repair_required`; agentes nao reexecutados |
| Causa sensivel simulada | detalhe da excecao nao aparece no state nem no manifest |

### Suites de T-006

| Suite | Casos novos | Resultado |
|---|---:|---|
| `tests/unit/test_routing.py` | 2 | passou |
| `tests/unit/test_review_policy.py` | 4 | passou |
| `tests/integration/test_graph_happy_path.py` | 2 | passou |
| `tests/integration/test_graph_revision.py` | 4 | passou |
| `tests/integration/test_resume.py` | 1 parametrizado pelos 13 nodes | passou |
| **Total T-006** | **13** | **passou sem rede** |

### Rastreabilidade parcial do terceiro incremento

| Requisito | Evidencia deste incremento | Estado |
|---|---|---|
| RF-004 | A1 produz `AcquisitionPacket` por port estruturado e fake | fluxo offline concluido; adapter real posterior |
| RF-005 | A2 produz e revisa `DraftPackage` somente no escopo bloqueado | fluxo offline concluido; Vault Core em T-007 |
| RF-006 | retrieval via vector port antes de A2 | orquestracao concluida; Qdrant em T-008 |
| RF-007 | A3 revisa hashes exatos e emite recomendacao terminal | fluxo offline concluido |
| RF-008 | manifest e artifacts registrados por refs | orquestracao concluida; escrita Vault em T-007 |
| RF-009 | checkpoint, resume e run state correlacionados por run ID | fluxo offline concluido |
| RF-011 | retry tecnico permanece fora do loop editorial; repair secundario vira warning | policy concluida |
| RNF-002 | freeze por hash, state compacto e artifacts canonicos | gate do incremento concluido |
| RNF-003 | budgets verificados antes de cada chamada e usage reconciliado | gate do incremento concluido |
| RNF-004 | providers e LLM totalmente substituidos por fakes | gate do incremento concluido |

## Evidencias de T-007

### Inventario e escrita

| Controle | Evidencia |
|---|---|
| Allowlist | scanner aceita somente paths relativos e ignora Markdown fora dos roots autorizados |
| Inventario reduzido | path relativo, note ID, titulo, status e hashes; nenhum corpo e retornado |
| Destino de escrita | constante `01-inbox/agent-runs/<run_id>` |
| Renderizacao | frontmatter e secoes derivados de contratos, sem Markdown final livre do LLM |
| Estados preservados | `ready`, `partially_ready`, `enrichment_required` |
| Estados omitidos | `rejected` e `discard`, registrados no resultado e summary |
| Idempotencia | segunda persistencia identica nao altera bytes nem mtime |
| Atomicidade | temp file, flush, fsync, replace e cleanup em falha |
| Colisoes | note ID canonico e conteudo divergente no mesmo run falham fechado |
| Paths | traversal, absoluto, filename inseguro e symlink bloqueados |
| Artefatos terminais | `manifest.json`, `review-summary.md` e `drafts/<note-id>.md` |
| Operacoes proibidas | nenhuma API de promote, delete, commit, push ou Git |

Arvore verificada por fixture:

```text
01-inbox/agent-runs/run-0123456789abcdef/
|- manifest.json
|- review-summary.md
`- drafts/
   |- note-enrichment.md
   |- note-partial.md
   `- note-ready.md
```

O review summary registra somente run ID, recomendacao, counts, note IDs, status e elegibilidade.
Issues, required changes e corpos dos drafts nao sao copiados para esse resumo.

### Suites de T-007

| Suite | Resultado |
|---|---|
| `tests/integration/test_vault_writer.py` | 4 passaram |
| `tests/security/test_path_traversal.py` | 10 passaram no arquivo combinado |
| **Gate direcionado** | **14 passaram em 0.48s** |
| **Suite offline total** | **75 passaram em 9.07s** |

### Rastreabilidade parcial do quarto incremento

| Requisito | Evidencia deste incremento | Estado |
|---|---|---|
| RF-005 | drafts atomicos renderizados a partir de `DraftPackage` e decisions | persistencia local concluida |
| RF-006 | status e reviewed hash determinam preservacao ou omissao | persistencia local concluida |
| RF-008 | staging fixo, escrita atomica, manifest e summary | Vault Core concluido |
| RNF-001 | allowlist, containment, symlink e ausencia de APIs de promocao/Git | gate concluido |
| RNF-002 | hash revisado, idempotencia por bytes e colisao fechada | gate concluido |

## Evidencias de T-008

### Chunking, embeddings e schema Qdrant

| Controle | Evidencia |
|---|---|
| Chunker v1 | heading + paragrafo, target 800, maximo 1.200 e overlap 120 adjacente |
| Estruturas Markdown | listas, tabelas e code blocks permanecem inteiros quando cabem |
| Metadados | document ID, heading path, source locator, document hash e chunk hash separados |
| Deduplicacao | textos identicos geram uma unica entrada no batch de embeddings |
| Collections | `knowledge_evidence_v1`, `knowledge_drafts_v1`, `knowledge_notes_v1` |
| Vetores | cosine e dimensao derivada da configuracao de embedding |
| Payload indexes | `document_id`, `run_id`, `source_type`, `status`, `path`, `content_hash`, `generation` |
| Container | `qdrant/qdrant:v1.18.2`, portas 6333/6334 somente em `127.0.0.1` |

### Sincronizacao geracional

| Cenario | Resultado |
|---|---|
| Documento inalterado | point IDs validados; zero novo upsert |
| Documento alterado | nova generation e point IDs deterministas |
| Validacao da nova generation falha | record e pontos anteriores permanecem ativos |
| Nova generation valida | record novo persiste antes da limpeza da anterior |
| Limpeza anterior falha | generation nova permanece valida e repair e registrado |
| Scan incompleto | nenhum documento ausente e removido |
| Scan completo | ausentes sao removidos do Qdrant e SQLite |
| Rebuild incompleto | operacao bloqueada antes de apagar collections |
| Qdrant indisponivel | repair sanitizado; Markdown e drafts permanecem inalterados |
| Alteracao no indice | nenhuma API de escrita no vault e invocada |

O `index_fingerprint` muda independentemente com alteracao do model ID, dimensao, configuracao ou
versao do chunker e schema da collection. `IndexRecord` e repair pendente foram reabertos por uma
segunda instancia de `SqliteRunStore`, provando durabilidade local.

### Suites de T-008

| Suite | Casos novos | Resultado |
|---|---:|---|
| `tests/unit/test_chunker.py` | 4 | passou |
| `tests/integration/test_index_sync.py` | 9 | passou |
| `tests/unit/test_cli.py` | 2 | passou |
| **Total T-008** | **15** | **passou sem rede** |
| **Suite offline total** | **90** | **passou sem skips** |

### Rastreabilidade parcial da quinta rodada

| Requisito | Evidencia desta rodada | Estado |
|---|---|---|
| RF-010 | collections separadas, no-op, generation swap, incomplete scan e rebuild | concluido |
| RF-011 / CA-006 | falha secundaria cria repair seguro sem perder generation ou Markdown | base Qdrant concluida; executor generico de repairs em T-014 |
| RF-015 | comandos index status/sync/rebuild com precondicoes explicitas | concluido para indice |
| RNF-002 | fingerprint, point IDs, hashes e swap deterministicos | gate concluido |
| RNF-004 | Qdrant e OpenAI substituidos por fakes nos testes default | gate concluido |
| RNF-005 | application depende dos ports; SDKs permanecem nos adapters | gate concluido |

## Evidencias de T-009

### Structured Outputs e ownership

| Controle | Evidencia |
|---|---|
| API | `responses.parse` recebe o mesmo Pydantic contract usado pela aplicacao |
| Configuracao | model, reasoning e max output independentes para A1, A2 e A3 |
| Transporte | `AsyncOpenAI(timeout=120, max_retries=2)`; zero retry externo |
| Happy path | A1, A2 e A3 usam uma chamada principal por pacote |
| Contract repair | no maximo uma chamada separada por output ausente ou schema incorreto |
| Refusal | falha contratual imediata; nenhum repair cego |
| Usage | tokens de todas as respostas, custo configuravel e duracao agregados |
| Metadata | response ID, model resolvido, prompt name/version e repair flag no state |
| Manifest | model por agente e versao por recurso de prompt |

### Prompts e seguranca

| Prompt | Persona funcional | Escopo | Boundary principal |
|---|---|---|---|
| `agent_1/v1` | analista orientado a proveniencia | pacote completo de evidencia | fonte e evidence sao dados, nunca instrucoes |
| `agent_2/v1` | curador conservador de conhecimento | zero/multiplos drafts em uma resposta | retrieval nao autoriza escrita ou promocao |
| `agent_2_revision/v1` | editor corretivo de escopo estrito | somente drafts bloqueados | aprovados permanecem congelados por hash |
| `agent_3/v1` | validador independente de evidencia | review do pacote | draft nao pode autoaprovar ou alterar hash |

O adapter aceita somente uma mensagem `developer` confiavel e mensagens `user` delimitadas. Roles
adicionais falham fechado. O request do SDK nao recebe tools, usa `store=False` e mantem o schema
Pydantic como `text_format`. As personas sao funcionais e nao concedem autonomia adicional. Uma
fixture de prompt injection permaneceu integralmente no input nao confiavel e nao alterou
instructions, tools ou output contract.

### Suites de T-009

| Suite | Casos novos | Resultado |
|---|---:|---|
| `tests/contracts/test_prompt_outputs.py` | 6 | passou |
| `tests/security/test_prompt_injection.py` | 2 | passou |
| `tests/live/test_openai.py` | 1 live | nao selecionado |
| **Total offline novo** | **8** | **passou sem rede** |
| **Suite offline total** | **98** | **passou; 1 live deselected** |

### Rastreabilidade parcial do sexto incremento

| Requisito | Evidencia deste incremento | Estado |
|---|---|---|
| RF-004 | A1 Structured Output, proveniencia preservada e prompt boundary | concluido |
| RF-005 | A2 gera pacote com multiplos drafts numa chamada | concluido |
| RF-006 | A3 referencia hashes exatos e classifica drafts | concluido |
| RF-007 | prompt dedicado agrupa somente bloqueados; freeze/limites permanecem no graph | concluido |
| RF-012 | response/model/prompt/usage correlacionados no state e manifest | base OpenAI concluida; Langfuse posterior |
| RNF-003 | budget preflight, retry owner unico e contract repair limitado | gate concluido |
| CA-001 a CA-004 | mesmos tres agentes e contratos provados com fakes | fluxo offline concluido; providers live posteriores |

## Evidencias de T-010

### Controles de rede e extracao

| Controle | Evidencia |
|---|---|
| Schemes | somente HTTP e HTTPS; contrato tambem rejeita outros schemes |
| Autoridade | credenciais embutidas, fragments e hostname vazio bloqueados |
| Portas | HTTP 80 e HTTPS 443 por default, com allowlists configuraveis separadas |
| DNS | todos os A/AAAA devem ser globais e publicos |
| Rebinding | transporte conecta diretamente ao IP validado e mantem hostname para Host/SNI |
| Redirects | no maximo cinco; cada hop revalida URL, DNS e todos os IPs |
| Timeout | 30 segundos por default no HTTPX |
| Content type | somente `text/html` e `application/xhtml+xml` |
| Body | Content-Length e stream decodificado limitados a 5 MiB |
| Extracao | Trafilatura 2.2, precision mode, sem comments, images, links ou dedup global |
| Raw HTML | sucesso nao persiste; falha usa runtime ignorado, nome opaco e TTL de 24 horas |
| Erros | operation codes fixos; URL e body nao entram em mensagem ou `safe_dict` |

O default transport usa uma connection pool HTTPCore com network backend proprio. O pool recebe o
hostname original para verificacao TLS, mas `connect_tcp` aceita apenas o host/porta validados e
abre o socket usando um dos IPs publicos aprovados. Proxies de ambiente, cookies, auth e redirects
automaticos ficam desabilitados.

### Suites de T-010

| Suite | Casos novos | Resultado |
|---|---:|---|
| `tests/unit/test_web_provider.py` | 7 | passou |
| `tests/security/test_ssrf.py` | 20 | passou |
| **Total offline novo** | **27** | **passou sem rede** |
| **Suite offline total** | **125** | **passou; 1 live deselected** |

### Rastreabilidade parcial do setimo incremento

| Requisito | Evidencia deste incremento | Estado |
|---|---|---|
| RF-003 | WebArticleProvider implementa o mesmo port usado pelo graph | web concluido; NotebookLM em T-011 |
| RF-004 | EvidenceBatch com source, hashes, locators e texto extraido | base web concluida |
| RF-014 | fixture sanitizada e deterministica preparada para comparacao | provider web concluido; eval em T-016 |
| RNF-001 | SSRF IPv4/IPv6, redirects, rebinding, limits e erros seguros | gate concluido |
| RNF-005 | provider concreto percorreu o graph com os mesmos contratos e LLMs fake | gate concluido |
| CA-002 | fluxo blog direto provado integralmente offline | concluido para fixture |
| CA-007 | URL/DNS maliciosos bloqueados antes do fetch ou do segundo hop | gate concluido |

## Evidencias de T-011

### Controles MCP e NotebookLM

| Controle | Evidencia |
|---|---|
| Transporte | JSON-RPC 2.0 por stdio; nenhum listener HTTP ou shell |
| Lifecycle | start idempotente, timeout, stdin fechado, terminate e kill limitado |
| Ambiente | somente PATH/runtime basico e flags MCP; credenciais `KA_*` nao herdadas |
| Preflight | initialize, initialized notification, `tools/list` e `server_health` obrigatorios |
| Allowlist | sete tools do DESIGN invocaveis; extras read-only do registry apenas tolerados |
| Fail-closed | tool nao registrada ou com token mutavel bloqueia o provider antes do health |
| Runtime | package `@roomi-fields/notebooklm-mcp` versao 2.1.0 |
| Registry | `evaluating` aceito somente supervisionado; recorrencia exige `approved-read-only` |
| Fonte | `content_list` exige exatamente uma fonte por link compartilhado |
| Contratos | URL convertida em ID/ref opacos; session ID e URL nao entram no EvidenceBatch |
| Budget | resposta e citacoes medidas em UTF-8 contra `max_source_bytes` |
| Doctor | checks locais nao iniciam proxy, browser, sessao ou rede |

### Suites de T-011

| Suite | Casos novos | Resultado |
|---|---:|---|
| `tests/unit/test_mcp_allowlist.py` | 18 | passou sem rede |
| `tests/unit/test_doctor.py` | 2 | passou sem iniciar MCP |
| `tests/live/test_notebooklm.py` | 1 | skipped sem flag opt-in |
| **Total offline novo** | **20** | **passou sem rede** |
| **Suite offline total** | **145** | **passou; 2 live deselected** |

### Rastreabilidade parcial do oitavo incremento

| Requisito | Evidencia deste incremento | Estado |
|---|---|---|
| RF-003 | NotebookLMProvider implementa o mesmo port e contratos do provider web | concluido offline |
| RF-004 | EvidenceBatch versionado, fonte unica, hashes e locators opacos | base NotebookLM concluida |
| RF-013 | profile doctor valida runtime e registry sem chamada paga | checks offline concluidos |
| RF-014 | segunda rota esta pronta para eval opt-in posterior | provider concluido; eval em T-016 |
| RNF-001 | allowlist fail-closed, ambiente minimo e sanitizacao de URL/session | gate concluido |
| CA-001 | fluxo provider provado com fake MCP | offline concluido; live manual pendente |

## Evidencias de T-012

### Controles SQS e worker

| Controle | Evidencia |
|---|---|
| Poll | `WaitTimeSeconds=20`, lote configuravel de 1 a 10 |
| Visibility | inicial de 180 segundos; release explicito usa zero |
| Entrada | JSON de ate 16 KiB, schema `1`, extras/duplicatas proibidos |
| Lease | `create_or_get_run` e `acquire_lease` precedem o executor |
| Heartbeat | a cada 60 segundos; SQLite renovado antes de SQS por 180 segundos |
| Ack | delete somente apos status terminal relido do armazenamento duravel |
| Falha | executor falho libera visibility; heartbeat perdido aguarda timeout |
| Duplicidade | estado terminal SQLite evita segunda execucao e permite novo ack |
| Shutdown | mensagem recebida apos stop e liberada sem iniciar run |
| SDK | boto3 confinado ao adapter; testes usam client fake |

### Suites de T-012

| Suite | Casos | Resultado |
|---|---:|---|
| `tests/integration/test_duplicate_delivery.py` | 3 | passou; SQLite temporario |
| `tests/integration/test_worker_lifecycle.py` | 7 | passou com fakes |
| **Casos novos** | **8** | **passaram sem AWS** |
| **Suite offline total** | **153** | **passou; 2 live deselected** |

### Rastreabilidade parcial do nono incremento

| Requisito | Evidencia deste incremento | Estado |
|---|---|---|
| RF-002 | poll, lease, heartbeat, duplicate delivery e ack terminal | concluido offline |
| RF-009 | redelivery reutiliza run duravel e entrega terminal nao reexecuta graph | concluido offline |
| RF-011 | ownership de retry e perda de lease falham de forma segura | concluido offline |
| RF-015 | inicio/processamento e shutdown sao operacoes explicitas do worker | lifecycle concluido |
| CA-005 | falha de heartbeat permite redelivery sem ack prematuro | concluido offline |
| CA-008 | SQLite e idempotency key preservam o run em entrega repetida | concluido offline |

## Gate combinado do segundo incremento

| Comando | Resultado |
|---|---|
| manifesto T-003 a T-005 | 20 de 20 arquivos declarados presentes |
| escopo do worktree | 29 paths esperados; nenhum path alheio ao incremento |
| `uv lock --check` | 22 pacotes resolvidos; lockfile sincronizado |
| `uv sync --locked` | 22 pacotes auditados |
| `uv run ruff format --check .` | 31 arquivos ja formatados |
| `uv run ruff check .` | todos os checks passaram |
| `uv run pytest -m "not live and not eval"` | 53 testes passaram em 2.27s, zero skips |
| `uv run knowledge-agents --help` | entry point e seis grupos de comandos exportados |
| `uv build` | sdist e wheel gerados |
| inspecao do wheel | duas migrations SQL presentes |
| scans de TODOs, credenciais e URLs privadas | zero matches |

### Rastreabilidade parcial do segundo incremento

| Requisito | Evidencia deste incremento | Estado |
|---|---|---|
| RF-002 | idempotencia, leases e duplicate delivery locais | base operacional concluida; SQS posterior |
| RF-003 | provider port e fake substituivel | boundary concluido; providers reais posteriores |
| RF-008 | ArtifactStore atomico e seguro | base local concluida; Vault Core posterior |
| RF-009 | migrations, run state, resume e replay | persistencia operacional concluida |
| RF-010 a RF-012 | vector, telemetry e queue ports/fakes | boundaries concluidos; adapters posteriores |
| RF-013 | doctor local e registry de profiles | profile local concluido; checks externos posteriores |
| RF-015 | arvore CLI e exit codes | base CLI concluida; side effects posteriores |
| RNF-002 | hashes, idempotencia e escrita atomica | gate do incremento concluido |
| RNF-004 | fakes e suite default offline | gate do incremento concluido |
| RNF-005 | ports sem SDKs externos | gate do incremento concluido |
| RNF-006 | lockfile, entry point e wheel reproduzivel | gate do incremento concluido |

## Gate combinado do terceiro incremento

| Comando | Resultado |
|---|---|
| manifesto T-006 | 13 de 13 arquivos declarados presentes; um helper de teste compartilhado |
| `uv lock --check` | 53 pacotes resolvidos; lockfile sincronizado |
| `uv sync --locked` | 53 pacotes auditados |
| `uv run ruff format --check .` | 44 arquivos ja formatados |
| `uv run ruff check .` | todos os checks passaram |
| `uv run pytest -m "not live and not eval" -q` | 66 testes passaram em 8.49s, zero skips |
| `uv build` | sdist e wheel gerados |
| scan de TODOs | zero matches em source, tests e configuracao |
| scan de credenciais comuns | zero matches fora de lockfile e metadados Git |

Conclusao: nenhum achado bloqueante, dado sensivel ou desvio de escopo foi identificado. O
incremento esta apto para revisao humana, commit e draft PR.

## Gate do quarto incremento

| Comando | Resultado |
|---|---|
| manifesto T-007 | 4 de 4 arquivos declarados criados/atualizados |
| `uv lock --check` | 53 pacotes resolvidos; lockfile sincronizado |
| `uv sync --locked` | 53 pacotes auditados |
| `uv run ruff format --check .` | 47 arquivos ja formatados |
| `uv run ruff check .` | todos os checks passaram |
| `uv run pytest -m "not live and not eval" -q` | 75 testes passaram em 9.07s, zero skips |
| `uv build` | sdist e wheel gerados |
| scan de TODOs | zero matches em source, tests e configuracao |
| scan de credenciais comuns | zero matches fora de lockfile, ambiente e metadados Git |

Conclusao: T-007 atende ao DESIGN sem acessar vault real, rede, SDK externo ou tarefas de T-008.
O incremento esta apto para revisao humana, commit e draft PR.

## Gate da quinta rodada

| Comando | Resultado |
|---|---|
| manifesto T-008 | 7 de 7 arquivos declarados presentes |
| `uv lock --check` | 65 pacotes resolvidos; lockfile sincronizado |
| `uv sync --locked` | 65 pacotes auditados |
| `uv run ruff format --check .` | 53 arquivos ja formatados |
| `uv run ruff check .` | todos os checks passaram |
| `uv run pytest -m "not live and not eval" -q` | 90 testes passaram em 18.07s, zero skips |
| `docker compose -f docker-compose.qdrant.yml config --quiet` | Compose valido; nenhum service iniciado |
| `uv build` | sdist e wheel gerados; quatro modulos T-008 presentes no wheel |
| scans de TODOs, credenciais e URLs privadas | zero matches |

Conclusao: T-008 atende ao DESIGN com doubles offline, sem executar Qdrant, OpenAI, vault real,
rede de aplicacao, live/eval, deploy ou tarefa T-009. A rodada esta apta para revisao humana.

## Gate do sexto incremento

| Comando | Resultado |
|---|---|
| manifesto T-009 | 8 de 8 arquivos declarados presentes |
| `uv lock --check` | 65 pacotes resolvidos; lockfile sincronizado |
| `uv sync --locked` | 65 pacotes auditados |
| `uv run ruff format --check .` | 58 arquivos ja formatados |
| `uv run ruff check .` | todos os checks passaram |
| `uv run pytest -m "not live and not eval" -q` | 98 testes passaram em 9.40s; 1 live deselected |
| `uv build` | sdist e wheel gerados; adapter e quatro prompts presentes no wheel |
| scans de TODOs e credenciais | zero matches; apenas o endpoint local esperado do Qdrant (`127.0.0.1`) |

Conclusao: T-009 atende ao DESIGN com client fake e contratos reais, sem chamada OpenAI, teste
live/eval, credencial real, deploy ou tarefa T-010. O incremento esta apto para revisao humana.

## Gate do setimo incremento

| Comando | Resultado |
|---|---|
| manifesto T-010 | 4 de 4 arquivos declarados presentes |
| `uv lock --check` | 80 pacotes resolvidos; lockfile sincronizado |
| `uv sync --locked` | 80 pacotes auditados |
| `uv run ruff format --check .` | 61 arquivos ja formatados |
| `uv run ruff check .` | todos os checks passaram |
| testes direcionados T-010 | 27 testes passaram em 2.45s |
| `uv run pytest -m "not live and not eval" -q` | 125 testes passaram em 14.37s; 1 live deselected |
| `uv build` | sdist e wheel gerados; WebArticleProvider presente no wheel |
| scans de TODOs e credenciais | zero matches em source, tests e `.env.example` |

Conclusao: T-010 atende ao DESIGN sem acessar URL real, rede de aplicacao, browser, OpenAI, vault
real, live/eval, credencial, deploy ou tarefa T-011. O incremento esta apto para revisao humana.

## Gate do oitavo incremento

| Comando | Resultado |
|---|---|
| manifesto T-011 | 4 de 4 arquivos declarados presentes |
| `uv lock --check --offline` | 80 pacotes resolvidos; lockfile sincronizado |
| `ruff format --check .` | 65 arquivos ja formatados |
| `ruff check .` | todos os checks passaram |
| testes direcionados MCP/provider | 18 testes passaram |
| testes direcionados com doctor | 25 testes passaram em 0.58s; 1 live deselected |
| `pytest -m "not live and not eval" -q` | 145 testes passaram em 14.20s; 2 live deselected |
| smoke `tests/live/test_notebooklm.py` | 1 skipped sem flag opt-in |
| `uv build --offline` | sdist e wheel gerados; os dois adapters presentes no wheel |
| scans de TODOs, credenciais e paths privados | zero matches |
| dependencias | nenhuma dependencia ou alteracao de lockfile necessaria |

Conclusao: T-011 atende ao DESIGN com fake MCP e subprocesso Python local, sem iniciar Node, proxy,
browser, NotebookLM, sessao real, rede, live/eval, credencial, deploy ou tarefa T-012. O incremento
esta apto para revisao humana.

## Gate do nono incremento

| Comando | Resultado |
|---|---|
| manifesto T-012 | 4 de 4 arquivos declarados presentes; `entrypoints/__init__.py` como suporte |
| `uv lock --check --offline` | 84 pacotes resolvidos; lockfile sincronizado |
| `uv sync --locked --offline` | 84 pacotes auditados |
| `ruff format --check .` | 69 arquivos ja formatados |
| `ruff check .` | todos os checks passaram |
| testes direcionados T-012 | 10 testes passaram em 0.43s |
| `pytest -m "not live and not eval" -q` | 153 testes passaram; 2 live deselected |
| `uv build --offline` | sdist e wheel gerados; adapter SQS e worker presentes no wheel |
| integracoes externas | nenhum client AWS, fila real, live/eval, deploy ou credencial usado |

Conclusao: T-012 atende ao DESIGN com client/queue fakes e SQLite temporario. Entrega duplicada,
lease, heartbeat, redelivery, ack terminal e shutdown foram provados offline sem antecipar T-013.
O incremento esta apto para revisao humana.

## Desvios

Nenhum desvio de requisito ou arquitetura registrado. No terceiro incremento, o DESIGN e o teste
de boundary foram clarificados para explicitar a excecao ja exigida por T-006: imports de
LangGraph, checkpoint e `aiosqlite` ficam confinados a `application/graph`. O helper
`tests/graph_scenarios.py`, `pyproject.toml` e `uv.lock` foram adicionados/atualizados apenas como
suporte necessario para os cenarios offline. Na T-007, o staging fixo e automaticamente incluido
na allowlist interna do writer para que idempotencia e colisao entre runs sejam sempre verificadas;
roots canonicos adicionais continuam explicitamente allowlisted pelo chamador. Nenhuma integracao
da aplicacao foi executada. Na T-008, `config.py`, `cli.py`, ports, SQLiteRunStore, VaultScanner,
fakes, `pyproject.toml` e `uv.lock` foram atualizados como suporte necessario aos arquivos declarados:
dimensao de embedding, comandos index, estado duravel, leitura Markdown allowlisted e dependencias
isoladas nos adapters. O schema SQLite existente ja continha `index_records` e `repair_tasks`, por
isso nenhuma migration nova foi necessaria. Na T-009, `.env.example`, config, LLM port, state,
manifest, agentes, fakes e testes de graph foram atualizados como suporte necessario aos arquivos
declarados: configuracao por agente, prompt boundary, metadata compacta e verificacao do fluxo real.
O helper `application/agents/prompts.py` e o package resource `prompts/__init__.py` foram adicionados
para carregar prompts do wheel sem introduzir SDK na application layer. Na T-010, `pyproject.toml`
e `uv.lock` foram atualizados como suporte aos quatro arquivos declarados, promovendo HTTPX/HTTPCore
a dependencias diretas e adicionando Trafilatura; nenhum wiring de CLI, provider T-011 ou integracao
live foi antecipado.
Na T-011, `.env.example`, `config.py`, `doctor_service.py` e seus testes foram atualizados como
suporte necessario aos quatro arquivos declarados, adicionando somente configuracao nominal e
checks offline do runtime/registry. O registry local permanece `evaluating`; por isso o provider
falha fechado quando `supervised=false` e uso recorrente nao supervisionado continua bloqueado ate
promocao humana para `approved-read-only`. Nenhuma dependencia foi adicionada e o lockfile nao mudou.
Na T-012, `pyproject.toml` e `uv.lock` foram atualizados para declarar boto3 como dependencia direta;
`entrypoints/__init__.py` foi criado para empacotar o novo modulo. O SDK permanece confinado ao adapter,
e sua interface foi exercitada apenas por fake. CLI composition root, Lambda, Terraform, SQS real e
teste live AWS permanecem para T-013 ou wiring posterior conforme o DESIGN.

## Proximo passo

Submeter T-012 a revisao humana. T-013 e a proxima tarefa do incremento I5, mas nao foi autorizada
nem iniciada nesta execucao.
