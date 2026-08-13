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
from knowledge_agents.domain.contracts import AcquisitionPacket, EvidenceBatch
from knowledge_agents.domain.enums import AgentRole
from knowledge_agents.domain.errors import DomainError, ErrorCode


async def run_acquisition_agent(
    state: RunState,
    dependencies: GraphDependencies,
) -> dict[str, Any]:
    evidence = await read_contract(state, "evidence_batch_ref", EvidenceBatch, dependencies)
    prompt_payload = {
        "run_id": state["run_id"],
        "evidence": evidence.model_dump(mode="json"),
    }
    prompt = load_prompt(AgentRole.ACQUISITION)
    messages = prompt.messages(prompt_payload)
    ensure_agent_budget(state, agent=AgentRole.ACQUISITION, payload=messages)
    result = await dependencies.llm.parse(
        agent=AgentRole.ACQUISITION,
        prompt_version=prompt.version,
        prompt=messages,
        output_type=AcquisitionPacket,
    )
    packet = result.output
    if (
        packet.run_id != state["run_id"]
        or packet.source.content_hash != evidence.source.content_hash
    ):
        raise DomainError(ErrorCode.CONTRACT_VALIDATION_FAILED, "agent_1.output")
    encoded = await write_contract(
        state=state,
        artifact_type="acquisition-packet",
        contract=packet,
        dependencies=dependencies,
    )
    return {
        "acquisition_packet_ref": encoded,
        "usage_entries": append_usage(state, result.usage),
        "llm_records": append_llm_record(
            state,
            agent=AgentRole.ACQUISITION,
            response_id=result.response_id,
            model=result.model,
            prompt_name=prompt.name,
            prompt_version=result.prompt_version,
            contract_repaired=result.contract_repaired,
        ),
    }
