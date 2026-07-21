from dataclasses import dataclass
from typing import Any, Protocol, TypeVar, runtime_checkable

from knowledge_agents.domain.budgets import CallUsage
from knowledge_agents.domain.contracts import ContractModel

OutputT = TypeVar("OutputT", bound=ContractModel)


@dataclass(frozen=True, slots=True)
class StructuredResult[ResultT: ContractModel]:
    output: ResultT
    usage: CallUsage
    response_id: str


@runtime_checkable
class StructuredLLMPort(Protocol):
    async def parse(
        self,
        *,
        prompt: tuple[dict[str, Any], ...],
        output_type: type[OutputT],
    ) -> StructuredResult[OutputT]: ...
