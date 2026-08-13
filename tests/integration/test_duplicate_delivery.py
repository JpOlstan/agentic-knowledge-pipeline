import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from tests.fakes import FakeQueue

from knowledge_agents.adapters.filesystem_artifacts import FilesystemArtifactStore
from knowledge_agents.adapters.sqlite_run_store import SqliteRunStore
from knowledge_agents.domain.contracts import AcquisitionRequest
from knowledge_agents.domain.enums import RunStatus
from knowledge_agents.domain.errors import DomainError, ErrorCode
from knowledge_agents.entrypoints.worker import MessageDisposition, Worker, WorkerConfig
from knowledge_agents.ports.queue import QueueMessage
from knowledge_agents.ports.run_store import RunStore


def test_duplicate_delivery_reuses_the_existing_active_run(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = SqliteRunStore(tmp_path / "state" / "runs.db")
        await store.migrate()

        first = await store.create_or_get_run(
            run_id="run-0123456789abcdef",
            idempotency_key="idempotency-key-1",
            request_hash="a" * 64,
        )
        duplicate = await store.create_or_get_run(
            run_id="run-fedcba9876543210",
            idempotency_key="idempotency-key-1",
            request_hash="a" * 64,
        )

        assert first.created
        assert not duplicate.created
        assert duplicate.record.run_id == first.record.run_id

        with pytest.raises(DomainError) as exc_info:
            await store.create_or_get_run(
                run_id="run-aaaaaaaaaaaaaaaa",
                idempotency_key="idempotency-key-1",
                request_hash="b" * 64,
            )
        assert exc_info.value.code is ErrorCode.IDEMPOTENCY_CONFLICT

    asyncio.run(scenario())


def test_artifact_and_database_registration_are_idempotent(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = SqliteRunStore(tmp_path / "state" / "runs.db")
        artifacts = FilesystemArtifactStore(tmp_path / "artifacts")
        await store.migrate()
        run = await store.create_or_get_run(
            run_id="run-0123456789abcdef",
            idempotency_key="idempotency-key-1",
            request_hash="a" * 64,
        )
        first = await artifacts.write_json(
            run_id=run.record.run_id,
            artifact_type="request",
            payload={"url": "https://example.com"},
            schema_version="1",
        )
        second = await artifacts.write_json(
            run_id=run.record.run_id,
            artifact_type="request",
            payload={"url": "https://example.com"},
            schema_version="1",
        )

        await store.record_artifact(run_id=run.record.run_id, artifact=first)
        await store.record_artifact(run_id=run.record.run_id, artifact=second)

        assert first == second
        assert await artifacts.read_json(first) == {"url": "https://example.com"}

    asyncio.run(scenario())


def test_duplicate_terminal_delivery_does_not_execute_completed_nodes_again(
    tmp_path: Path,
) -> None:
    class CompletingExecutor:
        def __init__(self, store: RunStore) -> None:
            self.store = store
            self.calls: list[str] = []

        async def execute(
            self,
            request: AcquisitionRequest,
            *,
            run_id: str,
            idempotency_key: str,
        ) -> dict[str, Any]:
            self.calls.append(run_id)
            await self.store.update_stage(
                run_id=run_id,
                stage="completed",
                status=RunStatus.COMPLETED,
            )
            return {"run_id": run_id}

    async def scenario() -> None:
        body = json.dumps(
            {
                "schema_version": "1",
                "run_id": "run-0123456789abcdef",
                "idempotency_key": "idempotency-key-1",
                "url": "https://example.com/source",
                "requested_at": "2026-07-18T00:00:00Z",
            }
        )
        messages = [
            QueueMessage("message-1", "receipt-1", body, 1),
            QueueMessage("message-1", "receipt-2", body, 2),
        ]
        queue = FakeQueue(messages)
        store = SqliteRunStore(tmp_path / "worker-state" / "runs.db")
        await store.migrate()
        executor = CompletingExecutor(store)
        worker = Worker(
            queue=queue,
            run_store=store,
            run_executor=executor,
            config=WorkerConfig(worker_id="worker-1"),
        )

        first = await worker.run_once()
        second = await worker.run_once()

        assert first == (MessageDisposition.ACKNOWLEDGED,)
        assert second == (MessageDisposition.ACKNOWLEDGED,)
        assert executor.calls == ["run-0123456789abcdef"]
        assert queue.acknowledged == ["message-1", "message-1"]

    asyncio.run(scenario())
