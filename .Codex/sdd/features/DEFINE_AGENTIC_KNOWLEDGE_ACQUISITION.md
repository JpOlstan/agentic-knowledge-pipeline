---
type: spec
area: ai-for-data-engineering
domain: agentic-knowledge-acquisition
tools: [python, langgraph, openai, langfuse, qdrant, aws, terraform, mcp, sqlite]
status: validated
maturity: intermediate
created: 2026-07-18
updated: 2026-07-18
review_cycle: on-demand
tags: [workflow/define, topic/knowledge-acquisition, topic/multi-agent, risk/security]
aliases: [Define Agentic Knowledge Acquisition]
related: [BRAINSTORM_AGENTIC_KNOWLEDGE_ACQUISITION]
---

# Define - Agentic Knowledge Acquisition

## Status do documento

Este documento formaliza os requisitos da primeira versao publica a partir do brainstorm validado. Ele autoriza a fase de design, mas nao autoriza implementacao, deploy, promocao de notas ou publicacao de dados.

Documento de origem:

- [[BRAINSTORM_AGENTIC_KNOWLEDGE_ACQUISITION]]

## Problema

A aquisicao atual de conhecimento depende de execucoes manuais e nao oferece contratos estaveis, retomada confiavel, idempotencia, medicao consistente ou separacao verificavel entre draft, validacao e promocao. O projeto precisa transformar fontes heterogeneas em drafts rastreaveis para um vault Obsidian sem tornar NotebookLM uma dependencia obrigatoria e sem permitir publicacao autonoma.

## Usuarios e partes interessadas

### Usuario primario

O proprietario do vault e do projeto, atuando como AI Data Engineer ou AI Engineer, precisa executar, observar e revisar aquisicoes de conhecimento com baixo risco operacional.

Necessidades:

- iniciar uma aquisicao por URL;
- acompanhar estado, custo, latencia e falhas;
- revisar drafts antes de qualquer promocao;
- retomar runs sem repetir trabalho concluido;
- demonstrar o sistema de forma reproduzivel em portfolio.

### Usuarios secundarios

- revisores tecnicos, que precisam verificar arquitetura, testes, seguranca e rastreabilidade;
- avaliadores de portfolio, que precisam compreender o problema, as decisoes e o caso real sem acesso ao vault privado;
- o Codex, usado como supervisor humano-assistido para enriquecimento, promocao e operacoes Git explicitamente autorizadas.

## Proposta de valor

> A governed and evaluated multi-source knowledge ingestion pipeline with Agentic RAG, data contracts, provenance, observability, and evidence-driven cloud evolution.

## Objetivo principal

Entregar uma primeira versao publica que processe uma fonte por run, via NotebookLM ou URL direta de blog, e produza drafts governados no vault com proveniencia, validacao, retomada e rastreabilidade operacional.

## Objetivos secundarios

- Demonstrar que o nucleo dos agentes independe do NotebookLM.
- Comparar qualidade, custo e latencia entre dois providers.
- Preservar os contratos e artefatos historicos do vault.
- Manter promocao, Git e publicacao sob controle humano.
- Preparar fronteiras para evolucao orientada por metricas ate ECS e persistencia cloud.
- Expor competencias de AI Engineering e AI Data Engineering em um repositorio seguro.

## Escopo da primeira versao publica

### Incluido

- monolito modular Python 3.12 executado localmente;
- LangGraph como unico orquestrador;
- tres agentes logicos implementados como subgrafos;
- OpenAI como provider de LLM;
- NotebookLMProvider via MCP e WebArticleProvider deterministico;
- uma URL e uma fonte por run;
- CLI assinada, Lambda Function URL, Lambda, SQS e DLQ;
- SQLite para estado operacional, idempotencia e checkpoints;
- filesystem para artefatos grandes;
- Qdrant local como indice derivado;
- Langfuse Cloud para traces sanitizadas;
- Terraform para a infraestrutura AWS inicial;
- drafts e manifests em area de staging do vault;
- doctor, testes offline, testes live opt-in e eval comparativa;
- caso real com o post da CrewAI processado pelas duas rotas.

### Excluido

- agentes executados em ECS;
- DynamoDB, S3, Qdrant Cloud ou Secrets Manager no MVP;
- ingestao direta de PDF, EPUB, audio ou video;
- processamento de varias fontes por run;
- descoberta autonoma de fontes;
- browser web local ou crawler geral;
- Firecrawl no caminho principal;
- CrewAI como orquestrador;
- retorno automatico ao Agente 1 por falta de evidencia;
- thresholds automaticos de qualidade;
- promocao, commit, push, PR, merge ou deploy automaticos;
- suporte multiusuario ou declaracao de production readiness.

## Premissas

- A chave OpenAI estara disponivel no momento dos testes live.
- O usuario manter-se-a autenticado no NotebookLM quando executar esse provider.
- O notebook compartilhado contera uma unica fonte no caso inicial.
- O vault Markdown permanece a fonte canonica; Qdrant e reconstruivel.
- Os agentes rodam localmente sem container; apenas Qdrant pode usar Docker.
- O repositorio publico da aplicacao sera separado do repositorio do vault.
- Dados, URLs privadas, credenciais e conteudo integral das fontes nao serao publicados.

## Requisitos funcionais

### RF-001 - Receber uma aquisicao por URL

O sistema deve aceitar exatamente uma URL por request, criar ou reutilizar um `run_id` idempotente no cliente e publicar a solicitacao em SQS por uma rota AWS autenticada com SigV4.

**Criterios de aceite:**

- request sem URL e rejeitado antes de entrar na fila;
- request com mais de uma fonte e rejeitado;
- o contrato externo inicial nao depende do nome do notebook;
- repeticao intencional com a mesma idempotency key nao cria dois runs ativos.

### RF-002 - Consumir a fila localmente

O worker local deve executar health checks, adquirir uma lease do run e consumir mensagens SQS com semantica at-least-once.

**Criterios de aceite:**

- entrega duplicada nao repete etapas concluidas;
- falha antes do checkpoint permite redelivery;
- mensagem permanentemente invalida termina na DLQ segundo a politica definida;
- o worker pode ser iniciado manualmente por CLI.

### RF-003 - Rotear providers substituiveis

O sistema deve selecionar NotebookLMProvider ou WebArticleProvider sem alterar os contratos consumidos pelo Agente 1.

**Criterios de aceite:**

- URL compartilhada do NotebookLM seleciona NotebookLMProvider;
- URL HTTP ou HTTPS publica suportada seleciona WebArticleProvider;
- provider desconhecido falha sem executar agentes;
- ambos produzem `SourceDescriptor` e `EvidenceBatch` versionados.

### RF-004 - Adquirir e estruturar evidencias

O Agente 1 deve transformar a saida do provider em um `AcquisitionPacket` estruturado, com proveniencia, cobertura e classificacao de alegacoes.

**Criterios de aceite:**

- uma chamada estruturada principal e usada por pacote no happy path;
- evidencias mantem referencia a fonte e hashes;
- alegacoes volateis ou sem suporte sao marcadas;
- instrucoes encontradas na fonte nao alteram ferramentas ou politicas do sistema.

### RF-005 - Criar drafts atomicos

O Agente 2 deve comparar o pacote com o indice do vault e gerar um `DraftPackage` com zero, um ou varios drafts atomicos e suas decisoes de create, merge, defer ou discard.

**Criterios de aceite:**

- nenhuma chamada por nota ocorre no happy path;
- cada draft recebe identificador estavel e hash de conteudo;
- duplicidade e destino de merge sao registrados;
- drafts nao sao gravados fora da area permitida.

### RF-006 - Validar drafts e elegibilidade

O Agente 3 deve produzir um `ReviewPackage` que classifique cada draft como aprovado, parcialmente pronto, dependente de enriquecimento ou rejeitado.

**Criterios de aceite:**

- a decisao referencia o hash exato do draft revisado;
- draft util pode ser preservado para enriquecimento posterior;
- enriquecimento fundamental bloqueia promocao;
- o Agente 3 encerra seu ciclo com drafts para avaliacao humana.

### RF-007 - Limitar correcoes editoriais

O LangGraph principal deve retornar somente notas bloqueadas e corrigiveis do Agente 3 ao Agente 2.

**Criterios de aceite:**

- notas aprovadas ficam congeladas por hash;
- existem no maximo dois ciclos editoriais condicionais;
- o segundo ciclo exige progresso verificavel;
- repeticao do mesmo problema encerra como `enrichment_required`;
- falta de evidencia nao retorna ao Agente 1 no MVP;
- reparo de schema e retry tecnico nao consomem ciclo editorial.

### RF-008 - Persistir drafts e manifest

O Vault Core deterministico deve persistir drafts e um `RunManifest` em `01-inbox/agent-runs`, usando escrita atomica e paths permitidos.

**Criterios de aceite:**

- nenhum LLM possui acesso direto de escrita ao vault;
- draft aprovado ou util para enriquecimento e preservado;
- nota canonica existente nao e sobrescrita;
- nenhuma promocao ocorre automaticamente;
- manifest registra versoes, artefatos, decisoes, warnings e estado final.

### RF-009 - Manter estado e retomada

SQLite deve armazenar estado do run, etapa, tentativas, leases, idempotencia, referencias de artefatos, checkpoints e estado do indexador.

**Criterios de aceite:**

- um run interrompido retoma da ultima etapa concluida;
- artefatos grandes permanecem fora do estado do grafo;
- replay cria novo `run_id`;
- resume preserva o `run_id` existente;
- migrations sao versionadas e verificadas pelo doctor.

### RF-010 - Sincronizar o indice vetorial

O indexador deve sincronizar Markdown para Qdrant de forma unidirecional, incremental e reconstruivel.

**Criterios de aceite:**

- evidencias, drafts e notas promovidas usam collections separadas;
- nota sem mudanca nao e reindexada;
- nova geracao e validada antes da remocao da anterior;
- scan incompleto nunca confirma delecoes;
- mudanca de modelo, dimensao, chunker ou schema altera o `index_fingerprint`;
- alteracoes no Qdrant nunca escrevem de volta no repositorio.

### RF-011 - Aplicar retries e reparos com ownership unico

Cada integracao deve possuir um unico owner de retry e falhas secundarias devem ser reparadas sem repetir chamadas de LLM concluidas.

**Criterios de aceite:**

- erros transitorios usam ate tres tentativas com backoff e jitter;
- erros de contrato permitem uma tentativa de reparo;
- sessao expirada, acesso negado, SSRF e path traversal nao usam retry cego;
- falha de Qdrant ou Langfuse apos persistencia gera `completed_with_warnings` e `pending_repair`;
- CLI permite resume, repair e replay como operacoes distintas.

### RF-012 - Fornecer observabilidade por run

O sistema deve registrar uma trace Langfuse por `run_id` e estado operacional consultavel por CLI e manifest.

**Criterios de aceite:**

- custo, tokens, latencia, modelo, prompt, tools, erros e transicoes sao observaveis;
- URLs privadas, credenciais, paths absolutos e conteudo desnecessario sao mascarados;
- falha de telemetria nao invalida drafts persistidos;
- Lambda, SQS e DLQ possuem logs, metricas e alarmes basicos no CloudWatch.

### RF-013 - Diagnosticar o ambiente

O comando `knowledge-agents doctor` deve verificar dependencias e configuracoes sem consumir mensagens ou executar geracoes pagas.

**Criterios de aceite:**

- verifica Python, Node, configuracao, AWS, SQS, MCP, NotebookLM, OpenAI, Langfuse, Qdrant, vault e SQLite;
- reutiliza checks do startup do worker;
- sanitiza a saida;
- retorna codigo diferente de zero para falhas criticas.

### RF-014 - Avaliar as duas rotas

O sistema deve processar o post da CrewAI por NotebookLMProvider e WebArticleProvider e produzir um relatorio comparativo revisavel.

**Criterios de aceite:**

- as duas execucoes usam a mesma versao de contratos e prompts;
- o relatorio compara cobertura, suporte, proveniencia, duplicidade, drafts uteis, edicao humana, custo, tokens e latencia;
- a primeira baseline nao aplica threshold automatico de aprovacao;
- nenhuma URL privada ou conteudo integral da fonte aparece no relatorio publico.

### RF-015 - Expor operacao por CLI

A CLI deve oferecer comandos para trigger, worker, doctor, consulta de runs, resume, repair, replay e sincronizacao do indice.

**Criterios de aceite:**

- comandos possuem exit codes previsiveis;
- saidas podem ser consumidas por humano e teste automatizado;
- operacoes com side effect exigem comando explicito;
- nenhum comando promove nota ou executa Git automaticamente.

## Requisitos nao funcionais

### RNF-001 - Seguranca por padrao

- credenciais temporarias e least privilege na AWS;
- nenhum secret, URL privada, cookie ou perfil de navegador no Git, trace ou manifest publico;
- validacao de SSRF, redirects, DNS/IP e path traversal;
- fontes e outputs de tools tratados como nao confiaveis;
- LLMs sem shell, Git ou escrita arbitraria.

### RNF-002 - Idempotencia e consistencia

- processamento correto sob entrega at-least-once;
- contratos versionados e validados por Pydantic;
- escrita atomica;
- hashes ligam evidencias, drafts, reviews e indice;
- Qdrant sempre reconstruivel a partir das fontes canonicas.

### RNF-003 - Controle operacional

- limites configuraveis de chamadas, tokens, custo, ciclos, tempo e tamanho;
- uma fonte por run;
- no maximo dois ciclos editoriais;
- falhas secundarias nao repetem agentes;
- cancelamento ou falha preserva estado diagnosticavel.

### RNF-004 - Testabilidade

- testes default rodam sem rede, segredos ou custo;
- integracoes externas possuem ports e fakes;
- testes live e eval sao opt-in;
- CI executa lint, testes offline, validacao Terraform e secret scan.

### RNF-005 - Portabilidade

- agentes dependem de contratos, nao de providers concretos;
- armazenamento operacional, artefatos, fila e indice usam interfaces substituiveis;
- providers diretos podem migrar para ECS sem alterar os contratos dos agentes;
- NotebookLM pode permanecer local sem bloquear providers cloud.

### RNF-006 - Reprodutibilidade

- Python, dependencias, prompts, schemas e infraestrutura sao versionados;
- o repositorio publico inclui fixtures sanitizadas e `.env.example`;
- setup e caso demonstrativo sao documentados;
- nenhuma dependencia de container existe para os agentes locais.

## Cenarios de aceite ponta a ponta

### CA-001 - Happy path NotebookLM

**Dado** um link compartilhado valido de um notebook com uma fonte e ambiente saudavel  
**Quando** o usuario dispara a aquisicao e inicia o worker local  
**Entao** o sistema produz `AcquisitionPacket`, `DraftPackage`, `ReviewPackage`, drafts e manifest sem promover notas.

### CA-002 - Happy path blog direto

**Dado** uma URL publica permitida do post da CrewAI  
**Quando** o WebArticleProvider processa a fonte  
**Entao** os mesmos contratos e subgrafos usados pela rota NotebookLM produzem drafts rastreaveis.

### CA-003 - Correcao de nota bloqueada

**Dado** um `ReviewPackage` com uma nota bloqueada e corrigivel  
**Quando** a politica de transicao solicita revisao  
**Entao** somente essa nota retorna ao Agente 2, volta ao Agente 3 e respeita o limite de dois ciclos.

### CA-004 - Evidencia insuficiente

**Dado** um draft util cuja afirmacao essencial nao possui evidencia suficiente  
**Quando** o Agente 3 conclui a revisao  
**Entao** o draft e preservado como `enrichment_required`, sem retorno ao Agente 1 e sem promocao.

### CA-005 - Entrega duplicada

**Dado** que SQS entrega novamente uma mensagem ja processada  
**Quando** o worker consulta a idempotencia e os checkpoints  
**Entao** nenhuma chamada de agente nem escrita de draft e repetida indevidamente.

### CA-006 - Falha secundaria

**Dado** que drafts e manifest foram persistidos  
**Quando** Qdrant ou Langfuse falha  
**Entao** o run termina `completed_with_warnings`, registra reparo pendente e nao repete LLMs.

### CA-007 - Fonte web maliciosa

**Dado** uma URL que resolve para rede privada, excede redirects ou tenta prompt injection  
**Quando** o sistema valida ou processa a fonte  
**Entao** a aquisicao e bloqueada ou a instrucao e ignorada sem ampliar permissoes.

### CA-008 - Retomada apos interrupcao

**Dado** um worker interrompido depois de um checkpoint valido  
**Quando** o run e retomado  
**Entao** a execucao continua da ultima etapa concluida e preserva os artefatos existentes.

### CA-009 - Demonstracao de portfolio

**Dado** o repositorio publico sem dados privados  
**Quando** um avaliador segue o README e executa testes offline  
**Entao** ele compreende a arquitetura, valida o comportamento principal e consulta o relatorio comparativo sanitizado.

## Criterios de sucesso

1. Terraform provisiona Function URL, Lambda, SQS, DLQ, IAM, logs e alarmes basicos.
2. O worker local consome a fila com health checks, leases, idempotencia e resume.
3. Dois providers implementam o mesmo contrato e alimentam os mesmos tres subgrafos.
4. Drafts aprovados ou uteis para enriquecimento sao persistidos sem promocao.
5. Correcoes respeitam hashes, congelamento, budget e limite de ciclos.
6. SQLite e manifest permitem diagnostico e retomada da ultima etapa concluida.
7. Qdrant separa evidencias, drafts e notas promovidas e pode ser reconstruido.
8. Langfuse registra custo, tokens, latencia e transicoes sem dados sensiveis.
9. O post da CrewAI e processado pelas duas rotas e gera relatorio comparativo.
10. Testes cobrem contratos, retries, SSRF, prompt injection, duplicidade e falhas parciais.
11. O repositorio publico nao contem secrets, URLs privadas, vault real ou fontes completas.
12. README e diagramas explicam a arquitetura atual e a evolucao cloud.

## Contratos que o design deve especificar

- `AcquisitionRequest`
- `SourceDescriptor`
- `EvidenceBatch`
- `AcquisitionPacket`
- `DraftPackage`
- `ReviewPackage`
- `RunManifest`
- `RunState`
- `ContextBudget`
- `IndexRecord`
- `RepairTask`

Todos devem possuir versao explicita, validacao estrutural e regras de compatibilidade.

## Restricoes arquiteturais

- LangGraph e o unico orquestrador do MVP.
- Os agentes sao subgrafos, nao processos ou servicos independentes.
- O Vault Core, o indexador e as politicas de transicao sao deterministicos.
- Markdown e o vault sao a fonte de verdade do conhecimento.
- SQLite e o filesystem sao as fontes de verdade operacionais locais.
- Qdrant e Langfuse sao dependencias secundarias reparaveis.
- NotebookLM e um provider opcional e local.
- A AWS apenas recebe, autentica e enfileira no MVP.
- Nenhum deploy automatico faz parte da primeira versao.

## Decisoes delegadas ao design

- nome do repositorio e do pacote Python;
- modelo OpenAI baseline e politica de configuracao;
- schemas Pydantic completos e compatibilidade;
- layout exato de modulos e artefatos;
- implementacao do checkpointer e migrations SQLite;
- algoritmo inicial de chunking e batch de embeddings;
- limites default de contexto, custo, tempo e tamanho;
- severidade dos health checks;
- formato do relatorio de eval;
- naming e regiao default dos recursos AWS;
- politica de retencao e cleanup;
- estrategia de branch e PR do repositorio publico.

## Matriz de rastreabilidade

| Objetivo | Requisitos | Cenarios | Evidencia esperada |
|---|---|---|---|
| Pipeline governado ponta a ponta | RF-001 a RF-009 | CA-001 a CA-008 | manifests, drafts, estado e testes |
| Independencia do NotebookLM | RF-003, RF-004, RNF-005 | CA-001, CA-002 | execucoes comparaveis pelos dois providers |
| Qualidade e revisao humana | RF-005 a RF-008, RF-014 | CA-003, CA-004, CA-009 | reviews, hashes e relatorio de eval |
| Operacao recuperavel | RF-002, RF-009, RF-011, RF-013 | CA-005, CA-006, CA-008 | checkpoints, repair tasks e doctor |
| Portfolio seguro | RF-012 a RF-015, RNF-001, RNF-004, RNF-006 | CA-007, CA-009 | CI, secret scan, README e fixtures |
| Evolucao cloud preparada | RF-003, RF-009, RF-010, RNF-005 | CA-002, CA-008 | ports substituiveis e limites documentados |

## Clarity score

| Elemento | Pontuacao | Justificativa |
|---|---:|---|
| Problema | 3/3 | Problema atual, impacto e fronteira da solucao estao explicitos. |
| Usuarios | 3/3 | Usuario primario, revisores, avaliadores e seus objetivos estao identificados. |
| Objetivos | 3/3 | Resultados funcionais e de portfolio sao observaveis. |
| Sucesso | 3/3 | Criterios e cenarios de aceite sao testaveis. |
| Escopo | 3/3 | Incluidos, excluidos, premissas e restricoes estao delimitados. |
| **Total** | **15/15** | Gate minimo de 12/15 atendido. |

## Riscos aceitos nesta fase

- a integracao NotebookLM depende de sessao e automacao local fragil;
- thresholds de qualidade permanecem humanos ate existir baseline;
- dois ciclos editoriais podem elevar custo e latencia, controlados por progress gate;
- Qdrant e Langfuse podem falhar depois do sucesso principal;
- o caso CrewAI e suficiente para a primeira avaliacao, mas nao prova generalizacao para livros e midia;
- limites numericos iniciais serao defaults operacionais revisaveis, nao garantias de producao.

## Historico de revisoes

| Versao | Data | Responsavel | Alteracoes |
|---|---|---|---|
| 1.0 | 2026-07-18 | Codex com validacao humana herdada do brainstorm | Extracao e formalizacao dos requisitos, criterios de aceite e matriz de rastreabilidade. |

## Proximo passo

Executar a fase de design:

```text
/design .Codex/sdd/features/DEFINE_AGENTIC_KNOWLEDGE_ACQUISITION.md
```
