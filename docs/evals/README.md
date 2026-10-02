# Evaluation method

## Current status

The offline preparation for T-016 is implemented. No CrewAI source was fetched, no provider was
called, and no comparative result has been produced. The controlled evaluation remains opt-in and
requires the user to be present for credentials, data, cost, and side-effect review.

The first evaluation compares two independent runs of the same approved public source:

- NotebookLM through the read-only MCP provider;
- the public article through the direct web provider.

Both routes use the same application commit, contract and prompt versions, model configuration,
index snapshot, operational budget, and cache policy. Metrics are presented side by side without an
automatic score, ranking, or pass threshold.

## Offline artifacts

| Artifact | Purpose |
|---|---|
| `knowledge_agents.application.evaluation` | strict plan, authorization, preflight, aggregate metrics, and public report contracts |
| `scripts/render_eval_report.py` | fail-closed renderer from private typed manifests to public Markdown |
| `tests/eval/test_crewai_comparison.py` | deterministic offline coverage for pins, budgets, sanitization, and route parity |
| `crewai-cognitive-memory-baseline.md` | public placeholder until the controlled run is reviewed |

Run the offline harness checks with:

```shell
uv run pytest tests/eval/test_crewai_comparison.py -q
```

The repository default remains `not live and not eval`; this command tests only the offline harness
and does not contact a provider.

## Private manifest custody

Private inputs and intermediate results belong under:

```text
.local/evals/crewai-cognitive-memory/
```

The directory is ignored by Git. It may contain approved source references and private run
artifacts, so its contents must not be pasted into chat, committed, attached to a PR, or included in
public logs. Credentials remain in the ignored local environment or an approved secret manager and
must not be copied into these manifests.

The renderer expects five strict JSON files:

```text
plan.json
authorization.json
external-readiness.json
notebooklm-route.json
web-article-route.json
```

`plan.json` pins the case ID, full Git commit, opaque source fingerprint, versions, models, index
snapshot, budget, and cache policy. `authorization.json` binds explicit approval and total cost to
the plan hash. `external-readiness.json` records the state of EXT-001 through EXT-008 and confirms
that private local storage is ready. Route files contain only aggregate metrics, opaque hashes,
usage, safe failure codes, and outcomes; they exclude URLs, source text, draft bodies, vault paths,
credentials, and raw prompts.

## Controlled preflight

Do not begin a real run until every item below is reviewed with the user:

1. checkout is clean and the full commit SHA is pinned in the plan;
2. EXT-001 through EXT-008 have recorded evidence;
3. the exact public source and NotebookLM notebook are approved;
4. the same prompt, contract, model, index, cache, and budget pins apply to both routes;
5. the maximum approved cost covers two complete route budgets;
6. credentials are present locally, ignored by Git, scoped minimally, and never displayed;
7. rollback and cleanup are defined for Qdrant, AWS, NotebookLM, OpenAI, and Langfuse;
8. `.local/evals/crewai-cognitive-memory/` exists and is verified as ignored;
9. live commands and EXT-009 receive explicit authorization in the active session.

`evaluate_preflight` reports deterministic blocker codes. `require_evaluation_ready` fails closed
until the authorization matches the exact plan, all required external items are complete, the
two-route cost ceiling is approved, and private storage is ready.

## Controlled execution sequence

The following sequence is documentation, not authorization to execute it:

1. run `knowledge-agents doctor` for every applicable external profile;
2. run the individual OpenAI, NotebookLM, and AWS smoke tests with their explicit opt-in markers;
3. freeze the Qdrant index snapshot and record its hash in `plan.json`;
4. execute the NotebookLM and web routes separately with caches disabled or explicitly reported;
5. validate each private `RunManifest`, `AcquisitionPacket`, `DraftPackage`, and `ReviewPackage`;
6. convert each route with `build_route_evaluation`, recording retries, safe failure codes, and
   human-edit counts without copying content;
7. render the public candidate:

```shell
uv run python scripts/render_eval_report.py \
  --private-dir .local/evals/crewai-cognitive-memory \
  --output docs/evals/crewai-cognitive-memory-baseline.md
```

The same renderer is exposed through the opt-in eval test when
`KA_RUN_EVAL_CREWAI=1`, `KA_EVAL_PRIVATE_DIR`, and `KA_EVAL_PUBLIC_REPORT` are all set. These
variables are authorization inputs, not defaults, and must be configured only during the supervised
session.

8. inspect the complete diff and run the secret scanner before accepting the report;
9. have a human write the qualitative conclusion without adding an automatic quality threshold;
10. update EXT-001 through EXT-009 and the build report with sanitized evidence.

## Public metrics

The generated report includes only:

- concept, covered-topic, missing-topic, supported-claim, unsupported-claim, and provenance counts,
  plus the aggregate coverage ratio;
- create, merge, defer, discard, useful-draft, blocked-draft, and review-status counts;
- human-edit count or `pending`;
- LLM calls, input/output tokens, cost, latency, retries, and safe failure codes;
- opaque run, acquisition, draft, review, private-manifest, source-case, plan, and index hashes;
- pinned versions, models, budget, cache state, and terminal outcome.

Full URLs, source content, evidence text, draft bodies, vault text, absolute paths, credentials,
cookies, browser profiles, and raw prompts are forbidden in the public report.

## Human review

The renderer intentionally leaves the conclusion pending. The reviewer decides whether the two
routes are useful, where they differ, which edits were required, and what should change next. Any
material requirement or architecture gap becomes an explicit DEFINE/DESIGN iteration before a
future baseline; it is not hidden by a numeric score.
