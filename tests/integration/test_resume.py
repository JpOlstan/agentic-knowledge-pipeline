import asyncio
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tests.graph_scenarios import (
    IDEMPOTENCY_KEY,
    RUN_ID,
    acquisition_packet,
    make_draft,
    make_draft_package,
    make_harness,
    make_review,
)

from knowledge_agents.adapters.sqlite_run_store import SqliteRunStore
from knowledge_agents.application.graph.builder import GRAPH_NODE_ORDER, open_graph
from knowledge_agents.application.services.run_service import RunService
from knowledge_agents.domain.enums import RunStatus


def run_store(path: Path) -> SqliteRunStore:
    return SqliteRunStore(path / "state" / "runs.db")


def test_migrations_are_clean_incremental_and_enable_wal(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = run_store(tmp_path)

        assert await store.migrate() == (1, 2)
        assert await store.migrate() == (1, 2)

        with sqlite3.connect(store.database_path) as connection:
            journal_mode = connection.execute("PRAGMA journal_mode").fetchone()
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            migration_count = connection.execute(
                "SELECT COUNT(*) FROM schema_migrations"
            ).fetchone()

        assert journal_mode == ("wal",)
        assert {
            "runs",
            "artifacts",
            "attempts",
            "index_records",
            "repair_tasks",
            "schema_migrations",
        }.issubset(tables)
        assert migration_count == (2,)

    asyncio.run(scenario())


def test_resume_preserves_run_id_and_replay_creates_a_new_run(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = run_store(tmp_path)
        await store.migrate()
        created = await store.create_or_get_run(
            run_id="run-0123456789abcdef",
            idempotency_key="idempotency-key-1",
            request_hash="a" * 64,
        )

        resumed = await store.update_stage(
            run_id=created.record.run_id,
            stage="acquisition_validated",
            status=RunStatus.RUNNING,
        )
        loaded = await store.get_run(created.record.run_id)
        replayed = await store.replay_run(
            source_run_id=created.record.run_id,
            new_run_id="run-fedcba9876543210",
            new_idempotency_key="idempotency-key-2",
        )

        assert resumed.run_id == created.record.run_id
        assert loaded is not None
        assert loaded.run_id == created.record.run_id
        assert loaded.stage == "acquisition_validated"
        assert replayed.run_id != created.record.run_id
        assert replayed.request_hash == created.record.request_hash
        assert replayed.stage == "received"

    asyncio.run(scenario())


def test_lease_is_conditional_renewable_and_recoverable_after_expiry(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = run_store(tmp_path)
        await store.migrate()
        await store.create_or_get_run(
            run_id="run-0123456789abcdef",
            idempotency_key="idempotency-key-1",
            request_hash="a" * 64,
        )
        now = datetime(2026, 7, 21, tzinfo=UTC)

        acquired = await asyncio.gather(
            store.acquire_lease(
                run_id="run-0123456789abcdef",
                owner="worker-1",
                ttl_seconds=60,
                now=now,
            ),
            store.acquire_lease(
                run_id="run-0123456789abcdef",
                owner="worker-2",
                ttl_seconds=60,
                now=now,
            ),
        )

        assert sorted(acquired) == [False, True]
        record = await store.get_run("run-0123456789abcdef")
        assert record is not None
        winner = record.lease_owner
        loser = "worker-2" if winner == "worker-1" else "worker-1"
        assert winner is not None
        assert await store.renew_lease(
            run_id=record.run_id,
            owner=winner,
            ttl_seconds=60,
            now=now + timedelta(seconds=30),
        )
        assert not await store.renew_lease(
            run_id=record.run_id,
            owner=loser,
            ttl_seconds=60,
            now=now + timedelta(seconds=30),
        )
        assert await store.acquire_lease(
            run_id=record.run_id,
            owner=loser,
            ttl_seconds=60,
            now=now + timedelta(seconds=91),
        )
        assert not await store.release_lease(run_id=record.run_id, owner=winner)
        assert await store.release_lease(run_id=record.run_id, owner=loser)

    asyncio.run(scenario())


def test_graph_resumes_after_every_node_without_repeating_completed_work(
    tmp_path: Path,
) -> None:
    async def interrupted_once(node: str, index: int) -> None:
        draft = make_draft("note-a")
        harness = make_harness(
            [
                acquisition_packet(),
                make_draft_package(draft),
                make_review((draft,)),
            ]
        )
        checkpoint_path = tmp_path / f"case-{index}" / "checkpoints.db"

        async with open_graph(
            checkpoint_path,
            harness.dependencies,
            interrupt_after=(node,),
        ) as graph:
            interrupted = await RunService(
                graph=graph,
                run_store=harness.run_store,
                artifacts=harness.artifacts,
            ).execute(
                harness.request,
                run_id=RUN_ID,
                idempotency_key=f"{IDEMPOTENCY_KEY}-{index}",
            )
            snapshot = await graph.aget_state({"configurable": {"thread_id": RUN_ID}})
            assert snapshot.values
            assert "PRIVATE_EVIDENCE_BODY" not in json.dumps(snapshot.values)

        calls_before_resume = len(harness.llm.calls)
        provider_calls_before_resume = len(harness.provider.calls)
        async with open_graph(checkpoint_path, harness.dependencies) as graph:
            completed = await RunService(
                graph=graph,
                run_store=harness.run_store,
                artifacts=harness.artifacts,
            ).resume(RUN_ID)

        assert completed["outcome"] == "completed"
        assert len(harness.llm.calls) == 3
        assert len(harness.provider.calls) == 2
        assert len(harness.llm.calls) >= calls_before_resume
        assert len(harness.provider.calls) >= provider_calls_before_resume
        assert interrupted["run_id"] == completed["run_id"] == RUN_ID

    async def scenario() -> None:
        for index, node in enumerate(GRAPH_NODE_ORDER):
            await interrupted_once(node, index)

    asyncio.run(scenario())
