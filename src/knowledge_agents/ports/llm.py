from dataclasses import dataclass
from typing import Any, Protocol, TypeVar, runtime_checkable

from knowledge_agents.domain.budgets import CallUsage
from knowledge_agents.domain.contracts import ContractModel
from knowledge_agents.domain.enums import AgentRole

OutputT = TypeVar("OutputT", bound=ContractModel)


@dataclass(frozen=True, slots=True)
class StructuredResult[ResultT: ContractModel]:
    output: ResultT
    usage: CallUsage
    response_id: str
    model: str = "fake-model"
    prompt_version: str = "v1"
    contract_repaired: bool = False


@runtime_checkable
class StructuredLLMPort(Protocol):
    async def parse(
        self,
        *,
        agent: AgentRole,
        prompt_version: str,
        prompt: tuple[dict[str, Any], ...],
        output_type: type[OutputT],
    ) -> StructuredResult[OutputT]: ...
