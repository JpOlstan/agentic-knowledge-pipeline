from __future__ import annotations

from typing import Any

from knowledge_agents.application.graph.nodes import (
    GraphDependencies,
    ensure_agent_budget,
    read_contract,
    write_contract,
)
from knowledge_agents.application.graph.state import RunState, append_usage
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
    ensure_agent_budget(state, agent=AgentRole.ACQUISITION, payload=prompt_payload)
    result = await dependencies.llm.parse(
        prompt=({"role": "user", "content": prompt_payload},),
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
    }
