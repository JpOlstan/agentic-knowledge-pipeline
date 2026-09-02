import asyncio
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from tests.fakes import FakeRunStore
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
from knowledge_agents.application.graph.builder import open_graph
from knowledge_agents.application.services.repair_service import RepairService
from knowledge_agents.application.services.run_service import RunService
from knowledge_agents.domain.contracts import RepairTask
from knowledge_agents.domain.enums import RepairTarget, RunOutcome, RunStatus

NOW = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


def repair_task(
    repair_id: str,
    target: RepairTarget,
    *,
    attempts: int = 0,
) -> RepairTask:
    return RepairTask(
        repair_id=repair_id,
        run_id=RUN_ID,
        target=target,
        attempts=attempts,
        next_attempt_at=NOW,
        last_error=f"{target.value}_repair_required",
    )


def test_graph_secondary_failures_create_repairs_without_rerunning_agents(tmp_path: Path) -> None:
    async def scenario() -> None:
        drafts = (make_draft("note-a"),)
        harness = make_harness(
            [acquisition_packet(), make_draft_package(*drafts), make_review(drafts)],
            vector_failures={"upsert": RuntimeError("secret index detail")},
            telemetry_failures={"flush": RuntimeError("secret telemetry detail")},
        )

        async with open_graph(tmp_path / "checkpoints.db", harness.dependencies) as graph:
            state = await RunService(
                graph=graph,
                run_store=harness.run_store,
                artifacts=harness.artifacts,
            ).execute(
                harness.request,
                run_id=RUN_ID,
                idempotency_key=IDEMPOTENCY_KEY,
            )

        assert state["outcome"] == RunOutcome.COMPLETED_WITH_WARNINGS.value
        assert harness.run_store.records[RUN_ID].status is RunStatus.COMPLETED_WITH_WARNINGS
        assert {task.target for task in harness.run_store.repairs.values()} == {
            RepairTarget.QDRANT,
            RepairTarget.LANGFUSE,
        }
        assert len(harness.llm.calls) == 3
        assert all(
            "secret" not in (task.last_error or "") for task in harness.run_store.repairs.values()
        )

    asyncio.run(scenario())


def test_repair_service_completes_targets_without_agent_dependencies() -> None:
    async def scenario() -> None:
        store = FakeRunStore()
        qdrant = repair_task("repair-qdrant", RepairTarget.QDRANT)
        langfuse = repair_task("repair-langfuse", RepairTarget.LANGFUSE)
        await store.enqueue_repair(qdrant)
        await store.enqueue_repair(langfuse)
        calls: list[RepairTarget] = []

        async def handler(task: RepairTask) -> None:
            calls.append(task.target)

        result = await RepairService(
            run_store=store,
            handlers={
                RepairTarget.QDRANT: handler,
                RepairTarget.LANGFUSE: handler,
            },
            clock=lambda: NOW,
        ).run(RUN_ID)

        assert set(result.completed) == {"repair-qdrant", "repair-langfuse"}
        assert calls == [RepairTarget.LANGFUSE, RepairTarget.QDRANT]
        assert store.repairs == {}
        assert not any(call.operation == "parse" for call in store.calls)

    asyncio.run(scenario())


def test_repair_failure_uses_safe_bounded_backoff_and_exhausts() -> None:
    async def scenario() -> None:
        store = FakeRunStore()
        task = repair_task("repair-langfuse", RepairTarget.LANGFUSE)
        await store.enqueue_repair(task)

        async def fail_with_secret(_: RepairTask) -> None:
            raise RuntimeError("Bearer sk-private-value")

        service = RepairService(
            run_store=store,
            handlers={RepairTarget.LANGFUSE: fail_with_secret},
            clock=lambda: NOW,
        )
        first = await service.run(RUN_ID)
        pending = store.repairs[task.repair_id]

        assert first.rescheduled == (task.repair_id,)
        assert pending.attempts == 1
        assert pending.last_error == "telemetry_repair_required"
        assert 30 <= (pending.next_attempt_at - NOW).total_seconds() <= 37.5

        store.repairs[task.repair_id] = pending.model_copy(
            update={"attempts": 2, "next_attempt_at": NOW}
        )
        third = await service.run(RUN_ID)

        assert third.exhausted == (task.repair_id,)
        assert task.repair_id not in store.repairs
        assert "sk-private-value" not in repr(store.calls)

    asyncio.run(scenario())


def test_sqlite_repair_states_are_durable(tmp_path: Path) -> None:
    database = tmp_path / "runs.db"

    async def scenario() -> None:
        store = SqliteRunStore(database)
        await store.migrate()
        await store.create_or_get_run(
            run_id=RUN_ID,
            idempotency_key="repair-sqlite-idempotency",
            request_hash="a" * 64,
        )
        completed = repair_task("repair-completed", RepairTarget.QDRANT)
        failed = repair_task("repair-failed", RepairTarget.LANGFUSE, attempts=2)
        await store.enqueue_repair(completed)
        await store.enqueue_repair(failed)
        await store.complete_repair(completed.repair_id)
        await store.fail_repair(
            repair_id=failed.repair_id,
            attempts=3,
            last_error="telemetry_repair_required",
        )
        assert await store.list_repairs() == ()

    asyncio.run(scenario())

    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT repair_id, status, attempts, last_error FROM repair_tasks ORDER BY repair_id"
        ).fetchall()
    assert rows == [
        ("repair-completed", "completed", 0, None),
        ("repair-failed", "failed", 3, "telemetry_repair_required"),
    ]
