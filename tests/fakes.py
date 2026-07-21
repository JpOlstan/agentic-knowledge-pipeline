from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from knowledge_agents.domain.budgets import ContextBudget
from knowledge_agents.domain.contracts import (
    AcquisitionRequest,
    ArtifactRef,
    EvidenceBatch,
    SourceDescriptor,
)
from knowledge_agents.domain.enums import RunStatus
from knowledge_agents.domain.hashing import canonical_sha256
from knowledge_agents.ports.artifacts import ArtifactStore
from knowledge_agents.ports.llm import OutputT, StructuredLLMPort, StructuredResult
from knowledge_agents.ports.providers import KnowledgeSourceProvider
from knowledge_agents.ports.queue import QueueMessage, QueuePort
from knowledge_agents.ports.run_store import CreateRunResult, RunRecord, RunStore
from knowledge_agents.ports.telemetry import TelemetryEvent, TelemetryPort
from knowledge_agents.ports.vector_index import (
    IndexDocument,
    VectorHit,
    VectorIndex,
    VectorQuery,
)


@dataclass(frozen=True, slots=True)
class FakeCall:
    operation: str
    arguments: dict[str, Any]


class FakeBase:
    def __init__(self, *, failures: dict[str, BaseException] | None = None) -> None:
        self.calls: list[FakeCall] = []
        self.failures = dict(failures or {})

    def _record(self, operation: str, **arguments: Any) -> None:
        self.calls.append(FakeCall(operation, arguments))
        failure = self.failures.get(operation)
        if failure is not None:
            raise failure


class FakeKnowledgeSourceProvider(FakeBase, KnowledgeSourceProvider):
    def __init__(
        self,
        *,
        source: SourceDescriptor,
        evidence: EvidenceBatch,
        failures: dict[str, BaseException] | None = None,
    ) -> None:
        super().__init__(failures=failures)
        self.source = source
        self.evidence = evidence

    async def inspect(self, request: AcquisitionRequest) -> SourceDescriptor:
        self._record("inspect", request=request)
        return self.source

    async def acquire(
        self,
        source: SourceDescriptor,
        budget: ContextBudget,
    ) -> EvidenceBatch:
        self._record("acquire", source=source, budget=budget)
        return self.evidence


class FakeStructuredLLM(FakeBase, StructuredLLMPort):
    def __init__(
        self,
        results: list[StructuredResult[Any]],
        *,
        failures: dict[str, BaseException] | None = None,
    ) -> None:
        super().__init__(failures=failures)
        self.results = list(results)

    async def parse(
        self,
        *,
        prompt: tuple[dict[str, Any], ...],
        output_type: type[OutputT],
    ) -> StructuredResult[OutputT]:
        self._record("parse", prompt=prompt, output_type=output_type)
        if not self.results:
            raise LookupError("no fake LLM result configured")
        result = self.results.pop(0)
        if not isinstance(result.output, output_type):
            raise TypeError("configured fake result does not match output type")
        return result


class FakeRunStore(FakeBase, RunStore):
    def __init__(self, *, failures: dict[str, BaseException] | None = None) -> None:
        super().__init__(failures=failures)
        self.records: dict[str, RunRecord] = {}
        self.idempotency: dict[str, str] = {}
        self.artifacts: dict[str, list[ArtifactRef]] = {}

    async def migrate(self) -> tuple[int, ...]:
        self._record("migrate")
        return (1, 2)

    async def migration_versions(self) -> tuple[int, ...]:
        self._record("migration_versions")
        return (1, 2)

    async def create_or_get_run(
        self,
        *,
        run_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> CreateRunResult:
        self._record(
            "create_or_get_run",
            run_id=run_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        existing_id = self.idempotency.get(idempotency_key)
        if existing_id is not None:
            return CreateRunResult(self.records[existing_id], False)
        now = datetime.now(UTC)
        record = RunRecord(
            run_id=run_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            status=RunStatus.RECEIVED,
            stage="received",
            lease_owner=None,
            lease_expires_at=None,
            created_at=now,
            updated_at=now,
            terminal_at=None,
        )
        self.records[run_id] = record
        self.idempotency[idempotency_key] = run_id
        return CreateRunResult(record, True)

    async def get_run(self, run_id: str) -> RunRecord | None:
        self._record("get_run", run_id=run_id)
        return self.records.get(run_id)

    async def acquire_lease(
        self,
        *,
        run_id: str,
        owner: str,
        ttl_seconds: int,
        now: datetime | None = None,
    ) -> bool:
        self._record(
            "acquire_lease",
            run_id=run_id,
            owner=owner,
            ttl_seconds=ttl_seconds,
            now=now,
        )
        record = self.records[run_id]
        current = now or datetime.now(UTC)
        if (
            record.lease_owner is not None
            and record.lease_owner != owner
            and record.lease_expires_at is not None
            and record.lease_expires_at > current
        ):
            return False
        self.records[run_id] = _replace_run(
            record,
            lease_owner=owner,
            lease_expires_at=current + timedelta(seconds=ttl_seconds),
            updated_at=current,
        )
        return True

    async def renew_lease(
        self,
        *,
        run_id: str,
        owner: str,
        ttl_seconds: int,
        now: datetime | None = None,
    ) -> bool:
        self._record(
            "renew_lease",
            run_id=run_id,
            owner=owner,
            ttl_seconds=ttl_seconds,
            now=now,
        )
        record = self.records[run_id]
        current = now or datetime.now(UTC)
        if (
            record.lease_owner != owner
            or record.lease_expires_at is None
            or record.lease_expires_at <= current
        ):
            return False
        self.records[run_id] = _replace_run(
            record,
            lease_expires_at=current + timedelta(seconds=ttl_seconds),
            updated_at=current,
        )
        return True

    async def release_lease(self, *, run_id: str, owner: str) -> bool:
        self._record("release_lease", run_id=run_id, owner=owner)
        record = self.records[run_id]
        if record.lease_owner != owner:
            return False
        self.records[run_id] = _replace_run(
            record,
            lease_owner=None,
            lease_expires_at=None,
            updated_at=datetime.now(UTC),
        )
        return True

    async def update_stage(
        self,
        *,
        run_id: str,
        stage: str,
        status: RunStatus | None = None,
    ) -> RunRecord:
        self._record("update_stage", run_id=run_id, stage=stage, status=status)
        record = self.records[run_id]
        updated = _replace_run(
            record,
            stage=stage,
            status=status or record.status,
            updated_at=datetime.now(UTC),
        )
        self.records[run_id] = updated
        return updated

    async def record_artifact(self, *, run_id: str, artifact: ArtifactRef) -> None:
        self._record("record_artifact", run_id=run_id, artifact=artifact)
        self.artifacts.setdefault(run_id, []).append(artifact)

    async def replay_run(
        self,
        *,
        source_run_id: str,
        new_run_id: str,
        new_idempotency_key: str,
    ) -> RunRecord:
        self._record(
            "replay_run",
            source_run_id=source_run_id,
            new_run_id=new_run_id,
            new_idempotency_key=new_idempotency_key,
        )
        source = self.records[source_run_id]
        result = await self.create_or_get_run(
            run_id=new_run_id,
            idempotency_key=new_idempotency_key,
            request_hash=source.request_hash,
        )
        return result.record


class FakeArtifactStore(FakeBase, ArtifactStore):
    def __init__(self, *, failures: dict[str, BaseException] | None = None) -> None:
        super().__init__(failures=failures)
        self.payloads: dict[str, Any] = {}

    async def write_json(
        self,
        *,
        run_id: str,
        artifact_type: str,
        payload: Any,
        schema_version: str,
    ) -> ArtifactRef:
        self._record(
            "write_json",
            run_id=run_id,
            artifact_type=artifact_type,
            payload=payload,
            schema_version=schema_version,
        )
        relative_path = f"{run_id}/{artifact_type}.json"
        artifact = ArtifactRef(
            artifact_id=f"{run_id}:{artifact_type}",
            artifact_type=artifact_type,
            relative_path=relative_path,
            content_hash=canonical_sha256(payload),
            schema_version=schema_version,
        )
        self.payloads[relative_path] = payload
        return artifact

    async def read_json(self, artifact: ArtifactRef) -> Any:
        self._record("read_json", artifact=artifact)
        return self.payloads[artifact.relative_path]

    async def exists(self, artifact: ArtifactRef) -> bool:
        self._record("exists", artifact=artifact)
        return artifact.relative_path in self.payloads


class FakeQueue(FakeBase, QueuePort):
    def __init__(
        self,
        messages: list[QueueMessage] | None = None,
        *,
        failures: dict[str, BaseException] | None = None,
    ) -> None:
        super().__init__(failures=failures)
        self.messages = list(messages or [])
        self.acknowledged: list[str] = []
        self.released: list[str] = []

    async def receive(self, *, max_messages: int = 1) -> tuple[QueueMessage, ...]:
        self._record("receive", max_messages=max_messages)
        selected = tuple(self.messages[:max_messages])
        self.messages = self.messages[max_messages:]
        return selected

    async def extend_visibility(self, message: QueueMessage, *, seconds: int) -> None:
        self._record("extend_visibility", message=message, seconds=seconds)

    async def acknowledge(self, message: QueueMessage) -> None:
        self._record("acknowledge", message=message)
        self.acknowledged.append(message.message_id)

    async def release(self, message: QueueMessage) -> None:
        self._record("release", message=message)
        self.released.append(message.message_id)


class FakeVectorIndex(FakeBase, VectorIndex):
    def __init__(
        self,
        hits: tuple[VectorHit, ...] = (),
        *,
        failures: dict[str, BaseException] | None = None,
    ) -> None:
        super().__init__(failures=failures)
        self.documents: dict[str, IndexDocument] = {}
        self.hits = hits

    async def upsert(self, documents: tuple[IndexDocument, ...]) -> tuple[str, ...]:
        self._record("upsert", documents=documents)
        point_ids = tuple(document.document_id for document in documents)
        self.documents.update(zip(point_ids, documents, strict=True))
        return point_ids

    async def query(self, query: VectorQuery) -> tuple[VectorHit, ...]:
        self._record("query", query=query)
        return self.hits[: query.limit]

    async def delete(self, *, collection: str, point_ids: tuple[str, ...]) -> None:
        self._record("delete", collection=collection, point_ids=point_ids)
        for point_id in point_ids:
            self.documents.pop(point_id, None)


class FakeTelemetry(FakeBase, TelemetryPort):
    def __init__(self, *, failures: dict[str, BaseException] | None = None) -> None:
        super().__init__(failures=failures)
        self.events: list[TelemetryEvent] = []
        self.flushed = False

    async def record(self, event: TelemetryEvent) -> None:
        self._record("record", event=event)
        self.events.append(event)

    async def flush(self) -> None:
        self._record("flush")
        self.flushed = True


def _replace_run(record: RunRecord, **changes: Any) -> RunRecord:
    values = {
        "run_id": record.run_id,
        "idempotency_key": record.idempotency_key,
        "request_hash": record.request_hash,
        "status": record.status,
        "stage": record.stage,
        "lease_owner": record.lease_owner,
        "lease_expires_at": record.lease_expires_at,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "terminal_at": record.terminal_at,
    }
    values.update(changes)
    return RunRecord(**values)
