from __future__ import annotations

from typing import Any

from knowledge_agents.application.agents.prompts import load_prompt
from knowledge_agents.application.graph.nodes import (
    GraphDependencies,
    ensure_agent_budget,
    read_contract,
    write_contract,
)
from knowledge_agents.application.graph.state import (
    RunState,
    append_llm_record,
    append_usage,
    decode_artifact_ref,
)
from knowledge_agents.domain.contracts import (
    AcquisitionPacket,
    DraftPackage,
    RevisionRequest,
)
from knowledge_agents.domain.enums import AgentRole
from knowledge_agents.domain.errors import DomainError, ErrorCode
from knowledge_agents.domain.hashing import canonical_sha256


async def run_curation_agent(
    state: RunState,
    dependencies: GraphDependencies,
) -> dict[str, Any]:
    packet = await read_contract(
        state,
        "acquisition_packet_ref",
        AcquisitionPacket,
        dependencies,
    )
    if state["revision_count"] == 0:
        retrieval_ref = decode_artifact_ref(state["retrieval_context_ref"])
        retrieval = await dependencies.artifacts.read_json(retrieval_ref)
        prompt_payload = {
            "run_id": state["run_id"],
            "acquisition_packet": packet.model_dump(mode="json"),
            "retrieval_context": retrieval,
        }
        previous = None
        revision = None
    else:
        previous = await read_contract(
            state,
            "draft_package_ref",
            DraftPackage,
            dependencies,
        )
        revision = await read_contract(
            state,
            "revision_request_ref",
            RevisionRequest,
            dependencies,
        )
        blocked = set(revision.blocked_note_ids)
        prompt_payload = {
            "run_id": state["run_id"],
            "revision_request": revision.model_dump(mode="json"),
            "blocked_drafts": [
                draft.model_dump(mode="json")
                for draft in previous.drafts
                if draft.note_id in blocked
            ],
        }

    prompt = load_prompt(AgentRole.CURATION, revision=state["revision_count"] > 0)
    messages = prompt.messages(prompt_payload)
    ensure_agent_budget(state, agent=AgentRole.CURATION, payload=messages)
    result = await dependencies.llm.parse(
        agent=AgentRole.CURATION,
        prompt_version=prompt.version,
        prompt=messages,
        output_type=DraftPackage,
    )
    candidate = result.output
    if candidate.run_id != state["run_id"]:
        raise DomainError(ErrorCode.CONTRACT_VALIDATION_FAILED, "agent_2.output")
    package = (
        _combine_revision(state, previous, revision, candidate)
        if previous is not None and revision is not None
        else candidate
    )
    encoded = await write_contract(
        state=state,
        artifact_type=f"draft-package-r{state['revision_count']}",
        contract=package,
        dependencies=dependencies,
    )
    return {
        "draft_package_ref": encoded,
        "usage_entries": append_usage(state, result.usage),
        "llm_records": append_llm_record(
            state,
            agent=AgentRole.CURATION,
            response_id=result.response_id,
            model=result.model,
            prompt_name=prompt.name,
            prompt_version=result.prompt_version,
            contract_repaired=result.contract_repaired,
        ),
    }


def _combine_revision(
    state: RunState,
    previous: DraftPackage,
    revision: RevisionRequest,
    candidate: DraftPackage,
) -> DraftPackage:
    blocked = set(revision.blocked_note_ids)
    candidate_drafts = {draft.note_id: draft for draft in candidate.drafts}
    if set(candidate_drafts) != blocked:
        raise DomainError(ErrorCode.CONTRACT_VALIDATION_FAILED, "agent_2.revision_scope")

    previous_drafts = {draft.note_id: draft for draft in previous.drafts}
    for note_id, approved_hash in state["approved_note_hashes"].items():
        original = previous_drafts.get(note_id)
        if original is None or original.content_hash != approved_hash:
            raise DomainError(ErrorCode.CONTRACT_VALIDATION_FAILED, "agent_2.frozen_draft")

    previous_decisions = {decision.note_id: decision for decision in previous.curation_decisions}
    candidate_decisions = {decision.note_id: decision for decision in candidate.curation_decisions}
    if not blocked.issubset(candidate_decisions):
        raise DomainError(ErrorCode.CONTRACT_VALIDATION_FAILED, "agent_2.revision_decisions")

    combined_drafts = tuple(candidate_drafts.get(draft.note_id, draft) for draft in previous.drafts)
    combined_decisions = tuple(
        candidate_decisions.get(draft.note_id, previous_decisions[draft.note_id])
        for draft in previous.drafts
    )
    retrieval_refs = candidate.retrieval_refs or previous.retrieval_refs
    package_hash = canonical_sha256(
        {
            "run_id": state["run_id"],
            "drafts": [draft.model_dump(mode="json") for draft in combined_drafts],
            "curation_decisions": [
                decision.model_dump(mode="json") for decision in combined_decisions
            ],
            "retrieval_refs": [item.model_dump(mode="json") for item in retrieval_refs],
        }
    )
    return DraftPackage(
        run_id=state["run_id"],
        drafts=combined_drafts,
        curation_decisions=combined_decisions,
        retrieval_refs=retrieval_refs,
        package_hash=package_hash,
        created_at=candidate.created_at,
    )
