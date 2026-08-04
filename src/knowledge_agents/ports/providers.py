from typing import Protocol, runtime_checkable

from knowledge_agents.domain.budgets import ContextBudget
from knowledge_agents.domain.contracts import AcquisitionRequest, EvidenceBatch, SourceDescriptor


@runtime_checkable
class KnowledgeSourceProvider(Protocol):
    async def inspect(self, request: AcquisitionRequest) -> SourceDescriptor: ...

    async def acquire(
        self,
        source: SourceDescriptor,
        budget: ContextBudget,
    ) -> EvidenceBatch: ...
