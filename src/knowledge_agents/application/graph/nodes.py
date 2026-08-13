from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from knowledge_agents.application.graph.routing import GraphRoute, ReviewPolicy
from knowledge_agents.application.graph.state import (
    RunState,
    context_budget,
    decode_artifact_ref,
    encode_artifact_ref,
    usage_ledger,
)
from knowledge_agents.domain.budgets import BudgetReservation, ContextBudgetManager
from knowledge_agents.domain.contracts import (
    AcquisitionPacket,
    AcquisitionRequest,
    ArtifactRef,
    DraftPackage,
    EvidenceBatch,
    ReviewPackage,
    RevisionRequest,
    RunManifest,
    SourceDescriptor,
    UsageSummary,
)
from knowledge_agents.domain.enums import AgentRole, RunOutcome, RunStatus
from knowledge_agents.domain.errors import DomainError, ErrorCode
from knowledge_agents.domain.hashing import canonical_json
from knowledge_agents.ports.artifacts import ArtifactStore
from knowledge_agents.ports.llm import StructuredLLMPort
from knowledge_agents.ports.providers import KnowledgeSourceProvider
from knowledge_agents.ports.run_store import RunStore
from knowledge_agents.ports.telemetry import TelemetryEvent, TelemetryPort
from knowledge_agents.ports.vector_index import VectorIndex, VectorQuery


@dataclass(frozen=True, slots=True)
class GraphDependencies:
    provider: KnowledgeSourceProvider
    llm: StructuredLLMPort
    run_store: RunStore
    artifacts: ArtifactStore
    vector_index: VectorIndex
    telemetry: TelemetryPort
    review_policy: ReviewPolicy = field(default_factory=ReviewPolicy)


async def read_contract[ContractT: BaseModel](
    state: RunState,
    key: str,
    contract_type: type[ContractT],
    dependencies: GraphDependencies,
) -> ContractT:
    encoded = state.get(key)
    if not isinstance(encoded, str):
        raise DomainError(ErrorCode.CONTRACT_VALIDATION_FAILED, f"graph.state.{key}")
    artifact = decode_artifact_ref(encoded)
    payload = await dependencies.artifacts.read_json(artifact)
    try:
        return contract_type.model_validate(payload)
    except ValueError as error:
        raise DomainError(
            ErrorCode.CONTRACT_VALIDATION_FAILED,
            f"graph.artifact.{key}",
            cause=error,
        ) from error


async def write_contract(
    *,
    state: RunState,
    artifact_type: str,
    contract: BaseModel,
    dependencies: GraphDependencies,
    schema_version: str | None = None,
) -> str:
    artifact = await dependencies.artifacts.write_json(
        run_id=state["run_id"],
        artifact_type=artifact_type,
        payload=contract.model_dump(mode="json"),
        schema_version=schema_version or getattr(type(contract), "schema_version", "external"),
    )
    await dependencies.run_store.record_artifact(run_id=state["run_id"], artifact=artifact)
    return encode_artifact_ref(artifact)


async def write_payload(
    *,
    state: RunState,
    artifact_type: str,
    payload: Any,
    dependencies: GraphDependencies,
    schema_version: str = "1",
) -> str:
    artifact = await dependencies.artifacts.write_json(
        run_id=state["run_id"],
        artifact_type=artifact_type,
        payload=payload,
        schema_version=schema_version,
    )
    await dependencies.run_store.record_artifact(run_id=state["run_id"], artifact=artifact)
    return encode_artifact_ref(artifact)


def ensure_agent_budget(state: RunState, *, agent: AgentRole, payload: Any) -> None:
    budget = context_budget(state)
    estimated_input = max(
        int(len(canonical_json(payload)) / 4 * (1 + budget.safety_margin_ratio)),
        1,
    )
    ContextBudgetManager(budget, usage_ledger(state)).ensure_can_call(
        BudgetReservation(
            agent=agent,
            estimated_input_tokens=estimated_input,
            reserved_output_tokens=budget.output_limit(agent),
        )
    )


async def prepare_run(state: RunState, dependencies: GraphDependencies) -> dict[str, Any]:
    request_artifact = decode_artifact_ref(state["request_ref"])
    if not await dependencies.artifacts.exists(request_artifact):
        raise DomainError(ErrorCode.INVALID_REQUEST, "graph.prepare_run")
    await dependencies.run_store.update_stage(
        run_id=state["run_id"],
        stage="preflight",
        status=RunStatus.RUNNING,
    )
    return {"stage": "preflight"}


async def inspect_source(state: RunState, dependencies: GraphDependencies) -> dict[str, Any]:
    request = await read_contract(state, "request_ref", AcquisitionRequest, dependencies)
    source = await dependencies.provider.inspect(request)
    encoded = await write_contract(
        state=state,
        artifact_type="source-descriptor",
        contract=source,
        dependencies=dependencies,
    )
    await dependencies.run_store.update_stage(run_id=state["run_id"], stage="acquiring")
    return {"source_ref": encoded, "stage": "acquiring"}


async def acquire_evidence(
    state: RunState,
    dependencies: GraphDependencies,
) -> dict[str, Any]:
    source = await read_contract(state, "source_ref", SourceDescriptor, dependencies)
    evidence = await dependencies.provider.acquire(source, context_budget(state))
    if evidence.source.content_hash != source.content_hash:
        raise DomainError(ErrorCode.CONTRACT_VALIDATION_FAILED, "graph.acquire_evidence")
    encoded = await write_contract(
        state=state,
        artifact_type="evidence-batch",
        contract=evidence,
        dependencies=dependencies,
    )
    return {"evidence_batch_ref": encoded}


async def validate_acquisition(
    state: RunState,
    dependencies: GraphDependencies,
) -> dict[str, Any]:
    packet = await read_contract(
        state,
        "acquisition_packet_ref",
        AcquisitionPacket,
        dependencies,
    )
    evidence = await read_contract(state, "evidence_batch_ref", EvidenceBatch, dependencies)
    evidence_ids = {item.evidence_id for item in evidence.evidence_items}
    referenced_ids = {evidence_id for claim in packet.claims for evidence_id in claim.evidence_ids}
    if packet.run_id != state["run_id"] or not referenced_ids.issubset(evidence_ids):
        raise DomainError(ErrorCode.CONTRACT_VALIDATION_FAILED, "graph.validate_acquisition")
    await dependencies.run_store.update_stage(run_id=state["run_id"], stage="acquisition_validated")
    return {"stage": "acquisition_validated"}


async def retrieve_vault_context(
    state: RunState,
    dependencies: GraphDependencies,
) -> dict[str, Any]:
    packet = await read_contract(
        state,
        "acquisition_packet_ref",
        AcquisitionPacket,
        dependencies,
    )
    query_text = " ".join(concept.name for concept in packet.concepts) or packet.source.title
    hits = await dependencies.vector_index.query(
        VectorQuery(
            collection="knowledge_notes_v1",
            text=query_text,
            limit=20,
            filters={"status": "promoted"},
        )
    )
    payload = {
        "hits": [
            {
                "point_id": hit.point_id,
                "score": hit.score,
                "content": hit.content,
                "metadata": hit.metadata,
            }
            for hit in hits
        ]
    }
    encoded = await write_payload(
        state=state,
        artifact_type="retrieval-context",
        payload=payload,
        dependencies=dependencies,
    )
    await dependencies.run_store.update_stage(run_id=state["run_id"], stage="curating")
    return {"retrieval_context_ref": encoded, "stage": "curating"}


async def validate_drafts(state: RunState, dependencies: GraphDependencies) -> dict[str, Any]:
    package = await read_contract(state, "draft_package_ref", DraftPackage, dependencies)
    draft_ids = {draft.note_id for draft in package.drafts}
    decision_ids = {decision.note_id for decision in package.curation_decisions}
    if package.run_id != state["run_id"] or not draft_ids.issubset(decision_ids):
        raise DomainError(ErrorCode.CONTRACT_VALIDATION_FAILED, "graph.validate_drafts")
    await dependencies.run_store.update_stage(run_id=state["run_id"], stage="drafts_validated")
    return {"stage": "drafts_validated"}


async def route_review(state: RunState, dependencies: GraphDependencies) -> dict[str, Any]:
    review = await read_contract(state, "review_package_ref", ReviewPackage, dependencies)
    drafts = await read_contract(state, "draft_package_ref", DraftPackage, dependencies)
    drafts_by_id = {draft.note_id: draft for draft in drafts.drafts}
    for item in review.reviews:
        draft = drafts_by_id.get(item.note_id)
        if draft is None or draft.content_hash != item.reviewed_hash:
            raise DomainError(ErrorCode.CONTRACT_VALIDATION_FAILED, "graph.route_review")

    approved_hashes = dict(state["approved_note_hashes"])
    for note_id, content_hash in review.approved_note_hashes.items():
        draft = drafts_by_id.get(note_id)
        if draft is None or draft.content_hash != content_hash:
            raise DomainError(ErrorCode.CONTRACT_VALIDATION_FAILED, "graph.route_review")
        approved_hashes[note_id] = content_hash

    decision = dependencies.review_policy.evaluate(
        review=review,
        revision_count=state["revision_count"],
        previous_issue_fingerprint=state["previous_issue_fingerprint"],
    )
    update: dict[str, Any] = {
        "approved_note_hashes": approved_hashes,
        "blocked_note_ids": list(review.blocked_note_ids),
        "previous_issue_fingerprint": decision.issue_fingerprint,
        "revision_count": decision.revision_count,
        "route": decision.route.value,
        "outcome": decision.outcome.value if decision.outcome is not None else None,
        "stage": "route_decision",
    }
    if decision.route is GraphRoute.REVISE:
        reviews_by_id = {item.note_id: item for item in review.reviews}
        status = _remaining_budget(state)
        revision = RevisionRequest(
            run_id=state["run_id"],
            blocked_note_ids=review.blocked_note_ids,
            issues={note_id: reviews_by_id[note_id].issues for note_id in review.blocked_note_ids},
            draft_hashes={
                note_id: drafts_by_id[note_id].content_hash for note_id in review.blocked_note_ids
            },
            remaining_budget=status,
            created_at=datetime.fromisoformat(state["started_at"]),
        )
        update["revision_request_ref"] = await write_contract(
            state=state,
            artifact_type=f"revision-request-r{decision.revision_count}",
            contract=revision,
            dependencies=dependencies,
        )
    await dependencies.run_store.update_stage(run_id=state["run_id"], stage="route_decision")
    return update


async def persist_terminal(
    state: RunState,
    dependencies: GraphDependencies,
) -> dict[str, Any]:
    if state["outcome"] is None:
        raise DomainError(ErrorCode.CONTRACT_VALIDATION_FAILED, "graph.persist_terminal")
    await dependencies.run_store.update_stage(run_id=state["run_id"], stage="persisting")
    return {"stage": "persisting"}


async def sync_index(state: RunState, dependencies: GraphDependencies) -> dict[str, Any]:
    warnings = list(state["warnings"])
    outcome = RunOutcome(state["outcome"] or RunOutcome.FAILED.value)
    try:
        await dependencies.vector_index.upsert(())
    except Exception:
        warnings.append(ErrorCode.INDEX_REPAIR_REQUIRED.value)
        if outcome is RunOutcome.COMPLETED:
            outcome = RunOutcome.COMPLETED_WITH_WARNINGS
    await dependencies.run_store.update_stage(run_id=state["run_id"], stage="indexing")
    return {"stage": "indexing", "warnings": warnings, "outcome": outcome.value}


async def flush_telemetry(state: RunState, dependencies: GraphDependencies) -> dict[str, Any]:
    warnings = list(state["warnings"])
    outcome = RunOutcome(state["outcome"] or RunOutcome.FAILED.value)
    try:
        await dependencies.telemetry.record(
            TelemetryEvent(
                run_id=state["run_id"],
                name="run.terminal",
                occurred_at=datetime.fromisoformat(state["started_at"]),
                attributes={
                    "outcome": outcome.value,
                    "revision_count": state["revision_count"],
                    "warning_count": len(warnings),
                },
            )
        )
        await dependencies.telemetry.flush()
    except Exception:
        warnings.append(ErrorCode.TELEMETRY_REPAIR_REQUIRED.value)
        if outcome is RunOutcome.COMPLETED:
            outcome = RunOutcome.COMPLETED_WITH_WARNINGS

    manifest = _run_manifest(state, warnings=warnings, outcome=outcome)
    manifest_ref = await write_contract(
        state=state,
        artifact_type="run-manifest",
        contract=manifest,
        dependencies=dependencies,
    )
    status = _run_status(outcome)
    await dependencies.run_store.update_stage(
        run_id=state["run_id"],
        stage=status.value,
        status=status,
    )
    return {
        "manifest_ref": manifest_ref,
        "stage": status.value,
        "warnings": warnings,
        "outcome": outcome.value,
    }


def _remaining_budget(state: RunState) -> dict[str, int | float]:
    budget = context_budget(state)
    ledger = usage_ledger(state)
    status = ContextBudgetManager(budget, ledger).status()
    return {
        "remaining_calls": status.remaining_calls,
        "remaining_input_tokens": status.remaining_input_tokens,
        "remaining_output_tokens": status.remaining_output_tokens,
        "remaining_cost_usd": status.remaining_cost_usd,
        "remaining_duration_seconds": status.remaining_duration_seconds,
    }


def _run_manifest(
    state: RunState,
    *,
    warnings: list[str],
    outcome: RunOutcome,
) -> RunManifest:
    artifact_keys = (
        "request_ref",
        "source_ref",
        "evidence_batch_ref",
        "acquisition_packet_ref",
        "retrieval_context_ref",
        "draft_package_ref",
        "review_package_ref",
        "revision_request_ref",
    )
    artifacts: list[ArtifactRef] = []
    seen: set[str] = set()
    for key in artifact_keys:
        encoded = state.get(key)
        if not isinstance(encoded, str):
            continue
        artifact = decode_artifact_ref(encoded)
        if artifact.artifact_id not in seen:
            artifacts.append(artifact)
            seen.add(artifact.artifact_id)
    ledger = usage_ledger(state)
    return RunManifest(
        run_id=state["run_id"],
        versions={
            "application": "0.1.0",
            "contracts": "1",
            "graph": "1",
            **{
                f"prompt.{record['prompt_name']}": str(record["prompt_version"])
                for record in state["llm_records"]
            },
        },
        models={str(record["agent"]): str(record["model"]) for record in state["llm_records"]},
        artifacts=tuple(artifacts),
        transitions=(),
        usage=UsageSummary(
            call_count=ledger.call_count,
            input_tokens=ledger.input_tokens,
            output_tokens=ledger.output_tokens,
            cost_usd=ledger.cost_usd,
            duration_seconds=ledger.duration_seconds,
        ),
        warnings=tuple(warnings),
        outcome=outcome,
        created_at=datetime.fromisoformat(state["started_at"]),
    )


def _run_status(outcome: RunOutcome) -> RunStatus:
    return {
        RunOutcome.COMPLETED: RunStatus.COMPLETED,
        RunOutcome.COMPLETED_WITH_WARNINGS: RunStatus.COMPLETED_WITH_WARNINGS,
        RunOutcome.ENRICHMENT_REQUIRED: RunStatus.ENRICHMENT_REQUIRED,
        RunOutcome.REJECTED: RunStatus.REJECTED,
        RunOutcome.FAILED: RunStatus.FAILED,
    }[outcome]
