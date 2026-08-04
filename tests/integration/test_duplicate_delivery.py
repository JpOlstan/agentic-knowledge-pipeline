import asyncio
from pathlib import Path

import pytest

from knowledge_agents.adapters.filesystem_artifacts import FilesystemArtifactStore
from knowledge_agents.adapters.sqlite_run_store import SqliteRunStore
from knowledge_agents.domain.errors import DomainError, ErrorCode


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
