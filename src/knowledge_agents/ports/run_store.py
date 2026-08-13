from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from knowledge_agents.domain.contracts import ArtifactRef, IndexRecord, RepairTask
from knowledge_agents.domain.enums import RunStatus


@dataclass(frozen=True, slots=True)
class RunRecord:
    run_id: str
    idempotency_key: str
    request_hash: str
    status: RunStatus
    stage: str
    lease_owner: str | None
    lease_expires_at: datetime | None
    created_at: datetime
    updated_at: datetime
    terminal_at: datetime | None


@dataclass(frozen=True, slots=True)
class CreateRunResult:
    record: RunRecord
    created: bool


@runtime_checkable
class RunStore(Protocol):
    async def migrate(self) -> tuple[int, ...]: ...

    async def migration_versions(self) -> tuple[int, ...]: ...

    async def create_or_get_run(
        self,
        *,
        run_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> CreateRunResult: ...

    async def get_run(self, run_id: str) -> RunRecord | None: ...

    async def acquire_lease(
        self,
        *,
        run_id: str,
        owner: str,
        ttl_seconds: int,
        now: datetime | None = None,
    ) -> bool: ...

    async def renew_lease(
        self,
        *,
        run_id: str,
        owner: str,
        ttl_seconds: int,
        now: datetime | None = None,
    ) -> bool: ...

    async def release_lease(self, *, run_id: str, owner: str) -> bool: ...

    async def update_stage(
        self,
        *,
        run_id: str,
        stage: str,
        status: RunStatus | None = None,
    ) -> RunRecord: ...

    async def record_artifact(self, *, run_id: str, artifact: ArtifactRef) -> None: ...

    async def get_index_record(self, path: str) -> IndexRecord | None: ...

    async def list_index_records(self) -> tuple[IndexRecord, ...]: ...

    async def save_index_record(self, record: IndexRecord) -> None: ...

    async def delete_index_record(self, path: str) -> None: ...

    async def enqueue_repair(self, task: RepairTask) -> None: ...

    async def list_repairs(self) -> tuple[RepairTask, ...]: ...

    async def replay_run(
        self,
        *,
        source_run_id: str,
        new_run_id: str,
        new_idempotency_key: str,
    ) -> RunRecord: ...
