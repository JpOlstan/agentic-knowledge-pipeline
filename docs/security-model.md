# Security model

## Scope and security posture

This document describes the controls implemented for the local MVP. The application produces
reviewable drafts; it does not promote notes, execute Git operations, deploy infrastructure, or
claim production readiness. External integrations remain opt-in and are tracked as `EXT-*` work.

The default posture is deny-by-default:

- tests run without network, credentials, live providers, or evaluation workloads;
- every external system is behind a port and can be replaced by a fake;
- untrusted input is validated again at each trust boundary;
- Qdrant and Langfuse failures are secondary and cannot invalidate persisted drafts;
- only deterministic Vault Core code writes inside the allowlisted staging area.

## Assets and data classification

| Class | Examples | Repository/trace policy |
|---|---|---|
| Secret | API keys, AWS credentials, cookies, browser profiles | never committed, logged, traced, or pasted into reports |
| Private | vault content, private URLs, source bodies, prompts containing private data | local only; reduced before state, logs, or telemetry |
| Internal | run state, repair status, opaque IDs, hashes | allowed when needed and sanitized |
| Public | source fixtures, architecture, synthetic test data | review before commit |

The Markdown vault is the knowledge source of truth. SQLite and local artifacts are operational
sources of truth. Qdrant and Langfuse are rebuildable or repairable secondary systems.

## Trust boundaries

| Boundary | Threats | Enforced controls | Offline evidence |
|---|---|---|---|
| Internet to Lambda | malformed/oversized body, method abuse, multiple sources, log leakage | POST only, 16 KiB limit, strict JSON parsing, contract validation, reduced logs, IAM Function URL | Lambda unit and trust-boundary tests |
| SQS to worker | duplicate, malformed, oversized, replayed message | 16 KiB envelope, exact schema/version, duplicate-key rejection, lease and idempotency before execution | worker lifecycle and duplicate-delivery tests |
| Provider to agents | prompt injection, unsupported evidence, tool escalation | provider contracts, untrusted-data delimiters, trusted developer prompt, no tools in LLM request | prompt-injection and contract tests |
| LLM to application | malformed output, invented fields, unsafe state transition | Pydantic Structured Outputs, frozen contracts, one contract repair, deterministic routing | contract, graph, and trust-boundary tests |
| Application to vault | traversal, symlink escape, overwrite, partial write | canonical containment, allowlist, safe identifiers, collision checks, temp file + fsync + replace | path-traversal and vault integration tests |
| Application to Langfuse | secret, URL, path, or source-body disclosure | client-side allowlist and redaction before SDK, opaque deterministic trace ID | redaction and secondary-repair tests |

## Network and provider controls

The web provider accepts HTTP/HTTPS only, rejects embedded credentials, fragments, unsupported
ports, and every non-public DNS answer. All redirect targets are resolved and revalidated. The
transport connects to the validated IP rather than resolving the hostname again. Redirects, body
size, time, and content type are bounded; cookies and authorization headers are not reused.

The NotebookLM provider uses a local MCP stdio subprocess, not a listener. Startup compares
`tools/list` with an explicit read-only allowlist and rejects missing required tools or any mutable
tool. The subprocess receives a minimal environment and its data directory stays outside Git.
Registry status `evaluating` requires supervised use.

## Agent and output controls

Source text and tool output are data, never instructions. Prompts separate trusted developer rules
from delimited untrusted content. The OpenAI adapter sends no tools and requires the same Pydantic
types used by the application. Agents cannot access shell, Git, filesystem writes, queues, Qdrant,
or Langfuse directly. Routing, budgets, hashing, persistence, and repair ownership are deterministic.

## Filesystem and persistence controls

Artifact and vault paths are relative, canonical, contained by their configured roots, and checked
for symlink escapes. Writes are atomic and collisions with different content fail closed. The
application writes only to `01-inbox/agent-runs/<run_id>` and exposes no promotion command.

SQLite migrations run transactionally. Idempotency keys and leases protect at-least-once delivery.
Large payloads stay outside LangGraph checkpoints. Repair records persist only safe error codes, not
raw exceptions.

## Telemetry and logging

Allowed telemetry is limited to opaque IDs, provider/model/prompt identifiers, usage, latency,
counts, status, transitions, scores, and safe error codes. Full URLs, credentials, cookies, absolute
paths, source bodies, vault text, and private prompts are forbidden. Redaction occurs before the
Langfuse SDK. Lambda logs contain hostname, run ID, status, and safe error code only.

## CI gate

The default GitHub Actions workflow has `contents: read`, no cloud credentials, no OIDC permission,
and no deploy step. External actions are pinned to immutable commit SHAs. Every push and pull request
runs:

1. locked dependency synchronization;
2. local secret scan over tracked and candidate files;
3. Ruff formatting and lint checks;
4. tests excluding `live` and `eval` markers;
5. Terraform formatting, backend-disabled initialization, and validation.

The secret scanner reports only file, line, and rule; it never echoes the matched value. It covers
private-key headers, AWS access keys, GitHub tokens, provider secrets, credentials embedded in URLs,
and common assigned-secret forms. It complements review and platform scanning; it is not a proof
that every possible secret format is detectable.

## Accepted and deferred risks

- NotebookLM depends on a supervised local session and an external proxy whose registry status is
  still under evaluation.
- DNS validation reduces SSRF risk but cannot eliminate every upstream or network-layer attack.
- Local SQLite and filesystem state do not provide multi-host coordination or disaster recovery.
- The local secret scanner is pattern-based and may require new rules when providers change formats.
- GitHub-hosted CI confirmation is deferred to EXT-007; local workflow assertions do not prove the
  hosted runner result.
- Real Qdrant, OpenAI, web, NotebookLM, AWS, and Langfuse validation remains in EXT-001 to EXT-006.
- Security controls reduce risk but do not establish production readiness.

## Secret incident response

If a real secret is exposed:

1. stop the affected workflow and do not copy the value into chat, an issue, or a report;
2. revoke or rotate it at the provider before attempting repository cleanup;
3. identify scope through provider audit logs and the minimal Git metadata needed for response;
4. remove the value from the working tree and, when required, coordinate a history rewrite with all
   collaborators instead of rewriting shared history unilaterally;
5. invalidate caches, artifacts, releases, and logs that may contain the value;
6. add or improve a scanner rule using only a synthetic fixture;
7. record a sanitized incident summary, affected systems, rotation time, and follow-up controls.

Credentials must be created and stored by the user in ignored local environment files or a future
approved secret manager. They must never be requested in chat or committed for troubleshooting.

## Release review

Before a public release, verify the tracked-file list, fixture provenance, generated artifacts,
workflow permissions, dependency/provider locks, and all `EXT-*` statuses. Public reports may include
sanitized evidence and aggregate metrics, never private URLs, raw source content, or credentials.
