from __future__ import annotations

from typing import Any

from knowledge_agents.application.agents.prompts import load_prompt
from knowledge_agents.application.graph.nodes import (
    GraphDependencies,
    ensure_agent_budget,
    read_contract,
    write_contract,
)
from knowledge_agents.application.graph.state import RunState, append_llm_record, append_usage
from knowledge_agents.domain.contracts import DraftPackage, EvidenceBatch, ReviewPackage
from knowledge_agents.domain.enums import AgentRole
from knowledge_agents.domain.errors import DomainError, ErrorCode


async def run_validation_agent(
    state: RunState,
    dependencies: GraphDependencies,
) -> dict[str, Any]:
    package = await read_contract(state, "draft_package_ref", DraftPackage, dependencies)
    evidence = await read_contract(state, "evidence_batch_ref", EvidenceBatch, dependencies)
    expected_note_ids = (
        set(state["blocked_note_ids"])
        if state["revision_count"] > 0
        else {draft.note_id for draft in package.drafts}
    )
    drafts_to_review = tuple(
        draft for draft in package.drafts if draft.note_id in expected_note_ids
    )
    prompt_payload = {
        "run_id": state["run_id"],
        "drafts": [draft.model_dump(mode="json") for draft in drafts_to_review],
        "evidence": evidence.model_dump(mode="json"),
    }
    prompt = load_prompt(AgentRole.VALIDATION)
    messages = prompt.messages(prompt_payload)
    ensure_agent_budget(state, agent=AgentRole.VALIDATION, payload=messages)
    result = await dependencies.llm.parse(
        agent=AgentRole.VALIDATION,
        prompt_version=prompt.version,
        prompt=messages,
        output_type=ReviewPackage,
    )
    review = result.output
    reviewed_note_ids = {item.note_id for item in review.reviews}
    if review.run_id != state["run_id"] or reviewed_note_ids != expected_note_ids:
        raise DomainError(ErrorCode.CONTRACT_VALIDATION_FAILED, "agent_3.output")
    draft_hashes = {draft.note_id: draft.content_hash for draft in drafts_to_review}
    if any(draft_hashes[item.note_id] != item.reviewed_hash for item in review.reviews):
        raise DomainError(ErrorCode.CONTRACT_VALIDATION_FAILED, "agent_3.reviewed_hash")
    encoded = await write_contract(
        state=state,
        artifact_type=f"review-package-r{state['revision_count']}",
        contract=review,
        dependencies=dependencies,
    )
    await dependencies.run_store.update_stage(run_id=state["run_id"], stage="reviewing")
    return {
        "review_package_ref": encoded,
        "usage_entries": append_usage(state, result.usage),
        "llm_records": append_llm_record(
            state,
            agent=AgentRole.VALIDATION,
            response_id=result.response_id,
            model=result.model,
            prompt_name=prompt.name,
            prompt_version=result.prompt_version,
            contract_repaired=result.contract_repaired,
        ),
        "stage": "reviewing",
    }
