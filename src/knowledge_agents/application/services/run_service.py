from __future__ import annotations

from typing import Any, Protocol

from knowledge_agents.application.graph.state import RunState, initial_run_state
from knowledge_agents.domain.budgets import ContextBudget
from knowledge_agents.domain.contracts import AcquisitionRequest
from knowledge_agents.domain.enums import RunStatus
from knowledge_agents.domain.errors import DomainError, ErrorCode
from knowledge_agents.domain.hashing import canonical_sha256
from knowledge_agents.ports.artifacts import ArtifactStore
from knowledge_agents.ports.run_store import RunStore

TERMINAL_STATUSES = {
    RunStatus.COMPLETED,
    RunStatus.COMPLETED_WITH_WARNINGS,
    RunStatus.ENRICHMENT_REQUIRED,
    RunStatus.REJECTED,
    RunStatus.FAILED,
}


class GraphSnapshot(Protocol):
    values: dict[str, Any]


class AsyncRunGraph(Protocol):
    async def ainvoke(
        self,
        input: RunState | None,
        config: dict[str, Any],
    ) -> dict[str, Any]: ...

    async def aget_state(self, config: dict[str, Any]) -> GraphSnapshot: ...


class RunService:
    def __init__(
        self,
        *,
        graph: AsyncRunGraph,
        run_store: RunStore,
        artifacts: ArtifactStore,
        budget: ContextBudget | None = None,
    ) -> None:
        self.graph = graph
        self.run_store = run_store
        self.artifacts = artifacts
        self.budget = budget or ContextBudget()

    async def execute(
        self,
        request: AcquisitionRequest,
        *,
        run_id: str,
        idempotency_key: str,
    ) -> RunState:
        if request.run_id is not None and request.run_id != run_id:
            raise DomainError(ErrorCode.INVALID_REQUEST, "run_service.execute")
        request_hash = canonical_sha256(request)
        created = await self.run_store.create_or_get_run(
            run_id=run_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        if created.record.request_hash != request_hash:
            raise DomainError(ErrorCode.IDEMPOTENCY_CONFLICT, "run_service.execute")

        request_artifact = await self.artifacts.write_json(
            run_id=created.record.run_id,
            artifact_type="request",
            payload=request.model_dump(mode="json"),
            schema_version="external",
        )
        await self.run_store.record_artifact(
            run_id=created.record.run_id,
            artifact=request_artifact,
        )
        config = self._config(created.record.run_id)
        snapshot = await self.graph.aget_state(config)
        if snapshot.values:
            if created.record.status in TERMINAL_STATUSES:
                return RunState(**snapshot.values)
            graph_input = None
        else:
            graph_input = initial_run_state(
                run_id=created.record.run_id,
                request_ref=request_artifact,
                budget=self.budget,
                started_at=created.record.created_at.isoformat(),
            )
        result = await self.graph.ainvoke(graph_input, config)
        return RunState(**result)

    async def resume(self, run_id: str) -> RunState:
        record = await self.run_store.get_run(run_id)
        if record is None:
            raise DomainError(ErrorCode.INVALID_REQUEST, "run_service.resume")
        config = self._config(run_id)
        snapshot = await self.graph.aget_state(config)
        if not snapshot.values:
            raise DomainError(ErrorCode.INVALID_REQUEST, "run_service.resume")
        if record.status in TERMINAL_STATUSES:
            return RunState(**snapshot.values)
        result = await self.graph.ainvoke(None, config)
        return RunState(**result)

    async def state(self, run_id: str) -> RunState:
        snapshot = await self.graph.aget_state(self._config(run_id))
        if not snapshot.values:
            raise DomainError(ErrorCode.INVALID_REQUEST, "run_service.state")
        return RunState(**snapshot.values)

    @staticmethod
    def _config(run_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": run_id}}
