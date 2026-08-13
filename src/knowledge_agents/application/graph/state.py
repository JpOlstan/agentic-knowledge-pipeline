from __future__ import annotations

from typing import Any, NotRequired, TypedDict

from knowledge_agents.domain.budgets import CallUsage, ContextBudget, UsageLedger
from knowledge_agents.domain.contracts import ArtifactRef
from knowledge_agents.domain.enums import AgentRole


class RunState(TypedDict):
    run_id: str
    request_ref: str
    stage: str
    started_at: str
    source_ref: NotRequired[str]
    evidence_batch_ref: NotRequired[str]
    acquisition_packet_ref: NotRequired[str]
    retrieval_context_ref: NotRequired[str]
    draft_package_ref: NotRequired[str]
    review_package_ref: NotRequired[str]
    revision_request_ref: NotRequired[str]
    manifest_ref: NotRequired[str]
    revision_count: int
    blocked_note_ids: list[str]
    approved_note_hashes: dict[str, str]
    previous_issue_fingerprint: str | None
    context_budget: dict[str, int | float]
    usage_entries: list[dict[str, Any]]
    llm_records: list[dict[str, Any]]
    warnings: list[str]
    route: NotRequired[str]
    outcome: str | None


def initial_run_state(
    *,
    run_id: str,
    request_ref: ArtifactRef,
    budget: ContextBudget,
    started_at: str,
) -> RunState:
    return RunState(
        run_id=run_id,
        request_ref=encode_artifact_ref(request_ref),
        stage="received",
        started_at=started_at,
        revision_count=0,
        blocked_note_ids=[],
        approved_note_hashes={},
        previous_issue_fingerprint=None,
        context_budget=budget.model_dump(mode="json"),
        usage_entries=[],
        llm_records=[],
        warnings=[],
        outcome=None,
    )


def encode_artifact_ref(artifact: ArtifactRef) -> str:
    return artifact.model_dump_json()


def decode_artifact_ref(value: str) -> ArtifactRef:
    return ArtifactRef.model_validate_json(value)


def context_budget(state: RunState) -> ContextBudget:
    return ContextBudget.model_validate(state["context_budget"])


def usage_ledger(state: RunState) -> UsageLedger:
    return UsageLedger(
        entries=tuple(CallUsage.model_validate(entry) for entry in state["usage_entries"])
    )


def append_usage(state: RunState, usage: CallUsage) -> list[dict[str, Any]]:
    return [*state["usage_entries"], usage.model_dump(mode="json")]


def append_llm_record(
    state: RunState,
    *,
    agent: AgentRole,
    response_id: str,
    model: str,
    prompt_name: str,
    prompt_version: str,
    contract_repaired: bool,
) -> list[dict[str, Any]]:
    return [
        *state["llm_records"],
        {
            "agent": agent.value,
            "response_id": response_id,
            "model": model,
            "prompt_name": prompt_name,
            "prompt_version": prompt_version,
            "contract_repaired": contract_repaired,
        },
    ]
