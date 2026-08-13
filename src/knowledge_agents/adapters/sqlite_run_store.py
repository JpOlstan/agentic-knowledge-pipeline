from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import aiosqlite

from knowledge_agents.domain.contracts import ArtifactRef, IndexRecord, RepairTask
from knowledge_agents.domain.enums import IndexStatus, RepairTarget, RunStatus
from knowledge_agents.domain.errors import DomainError, ErrorCode
from knowledge_agents.ports.run_store import CreateRunResult, RunRecord, RunStore

TERMINAL_STATUSES = {
    RunStatus.COMPLETED,
    RunStatus.COMPLETED_WITH_WARNINGS,
    RunStatus.ENRICHMENT_REQUIRED,
    RunStatus.REJECTED,
    RunStatus.FAILED,
}


class SqliteRunStore(RunStore):
    def __init__(self, database_path: Path, *, busy_timeout_ms: int = 5_000) -> None:
        self.database_path = database_path
        self.busy_timeout_ms = busy_timeout_ms
        self.migrations_path = Path(__file__).parents[1] / "sql"

    @asynccontextmanager
    async def _connection(self) -> AsyncIterator[aiosqlite.Connection]:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = await aiosqlite.connect(self.database_path)
        connection.row_factory = aiosqlite.Row
        await connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        await connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            await connection.close()

    async def migrate(self) -> tuple[int, ...]:
        async with self._connection() as connection:
            await connection.execute("PRAGMA journal_mode = WAL")
            await connection.execute("BEGIN IMMEDIATE")
            try:
                await connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        version INTEGER PRIMARY KEY,
                        name TEXT NOT NULL,
                        applied_at TEXT NOT NULL
                    )
                    """
                )
                cursor = await connection.execute("SELECT version FROM schema_migrations")
                applied = {int(row[0]) for row in await cursor.fetchall()}
                for path in sorted(self.migrations_path.glob("*.sql")):
                    version = int(path.stem.split("_", 1)[0])
                    if version in applied:
                        continue
                    for statement in _sql_statements(path.read_text(encoding="utf-8")):
                        await connection.execute(statement)
                    await connection.execute(
                        "INSERT INTO schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
                        (version, path.name, _utc_now().isoformat()),
                    )
                await connection.commit()
            except BaseException:
                await connection.rollback()
                raise
        return await self.migration_versions()

    async def migration_versions(self) -> tuple[int, ...]:
        if not self.database_path.exists():
            return ()
        async with self._connection() as connection:
            cursor = await connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
            )
            if await cursor.fetchone() is None:
                return ()
            cursor = await connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
            return tuple(int(row[0]) for row in await cursor.fetchall())

    async def create_or_get_run(
        self,
        *,
        run_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> CreateRunResult:
        now = _utc_now()
        async with self._connection() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            try:
                cursor = await connection.execute(
                    "SELECT * FROM runs WHERE idempotency_key = ?",
                    (idempotency_key,),
                )
                existing = await cursor.fetchone()
                if existing is not None:
                    if existing["request_hash"] != request_hash:
                        raise DomainError(
                            ErrorCode.IDEMPOTENCY_CONFLICT,
                            "run_store.create_or_get_run",
                        )
                    await connection.commit()
                    return CreateRunResult(_run_record(existing), False)

                cursor = await connection.execute(
                    "SELECT run_id FROM runs WHERE run_id = ?", (run_id,)
                )
                if await cursor.fetchone() is not None:
                    raise DomainError(
                        ErrorCode.IDEMPOTENCY_CONFLICT,
                        "run_store.create_or_get_run",
                    )
                await connection.execute(
                    """
                    INSERT INTO runs(
                        run_id, idempotency_key, request_hash, status, stage,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        idempotency_key,
                        request_hash,
                        RunStatus.RECEIVED.value,
                        "received",
                        now.isoformat(),
                        now.isoformat(),
                    ),
                )
                await connection.commit()
            except BaseException:
                await connection.rollback()
                raise
        record = await self.get_run(run_id)
        if record is None:
            raise DomainError(ErrorCode.INVALID_REQUEST, "run_store.create_or_get_run")
        return CreateRunResult(record, True)

    async def get_run(self, run_id: str) -> RunRecord | None:
        async with self._connection() as connection:
            cursor = await connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,))
            row = await cursor.fetchone()
            return _run_record(row) if row is not None else None

    async def acquire_lease(
        self,
        *,
        run_id: str,
        owner: str,
        ttl_seconds: int,
        now: datetime | None = None,
    ) -> bool:
        current = _as_utc(now or _utc_now())
        expires_at = current + timedelta(seconds=ttl_seconds)
        async with self._connection() as connection:
            cursor = await connection.execute(
                """
                UPDATE runs
                SET lease_owner = ?, lease_expires_at = ?, status = ?, updated_at = ?
                WHERE run_id = ?
                  AND (
                    lease_owner IS NULL
                    OR lease_expires_at IS NULL
                    OR lease_expires_at <= ?
                    OR lease_owner = ?
                  )
                """,
                (
                    owner,
                    expires_at.isoformat(),
                    RunStatus.RUNNING.value,
                    current.isoformat(),
                    run_id,
                    current.isoformat(),
                    owner,
                ),
            )
            await connection.commit()
            return cursor.rowcount == 1

    async def renew_lease(
        self,
        *,
        run_id: str,
        owner: str,
        ttl_seconds: int,
        now: datetime | None = None,
    ) -> bool:
        current = _as_utc(now or _utc_now())
        expires_at = current + timedelta(seconds=ttl_seconds)
        async with self._connection() as connection:
            cursor = await connection.execute(
                """
                UPDATE runs
                SET lease_expires_at = ?, updated_at = ?
                WHERE run_id = ? AND lease_owner = ? AND lease_expires_at > ?
                """,
                (
                    expires_at.isoformat(),
                    current.isoformat(),
                    run_id,
                    owner,
                    current.isoformat(),
                ),
            )
            await connection.commit()
            return cursor.rowcount == 1

    async def release_lease(self, *, run_id: str, owner: str) -> bool:
        async with self._connection() as connection:
            cursor = await connection.execute(
                """
                UPDATE runs
                SET lease_owner = NULL, lease_expires_at = NULL, updated_at = ?
                WHERE run_id = ? AND lease_owner = ?
                """,
                (_utc_now().isoformat(), run_id, owner),
            )
            await connection.commit()
            return cursor.rowcount == 1

    async def update_stage(
        self,
        *,
        run_id: str,
        stage: str,
        status: RunStatus | None = None,
    ) -> RunRecord:
        current = await self.get_run(run_id)
        if current is None:
            raise DomainError(ErrorCode.INVALID_REQUEST, "run_store.update_stage")
        next_status = status or current.status
        now = _utc_now()
        terminal_at = now.isoformat() if next_status in TERMINAL_STATUSES else None
        async with self._connection() as connection:
            await connection.execute(
                """
                UPDATE runs
                SET stage = ?, status = ?, updated_at = ?, terminal_at = ?
                WHERE run_id = ?
                """,
                (stage, next_status.value, now.isoformat(), terminal_at, run_id),
            )
            await connection.commit()
        updated = await self.get_run(run_id)
        if updated is None:
            raise DomainError(ErrorCode.INVALID_REQUEST, "run_store.update_stage")
        return updated

    async def record_artifact(self, *, run_id: str, artifact: ArtifactRef) -> None:
        async with self._connection() as connection:
            cursor = await connection.execute(
                "SELECT content_hash, relative_path FROM artifacts WHERE artifact_id = ?",
                (artifact.artifact_id,),
            )
            existing = await cursor.fetchone()
            if existing is not None:
                if (
                    existing["content_hash"] != artifact.content_hash
                    or existing["relative_path"] != artifact.relative_path
                ):
                    raise DomainError(
                        ErrorCode.IDEMPOTENCY_CONFLICT,
                        "run_store.record_artifact",
                    )
                return
            await connection.execute(
                """
                INSERT INTO artifacts(
                    artifact_id, run_id, artifact_type, relative_path,
                    content_hash, schema_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact.artifact_id,
                    run_id,
                    artifact.artifact_type,
                    artifact.relative_path,
                    artifact.content_hash,
                    artifact.schema_version,
                    _utc_now().isoformat(),
                ),
            )
            await connection.commit()

    async def get_index_record(self, path: str) -> IndexRecord | None:
        async with self._connection() as connection:
            cursor = await connection.execute(
                "SELECT * FROM index_records WHERE path = ?",
                (path,),
            )
            row = await cursor.fetchone()
            return _index_record(row) if row is not None else None

    async def list_index_records(self) -> tuple[IndexRecord, ...]:
        async with self._connection() as connection:
            cursor = await connection.execute("SELECT * FROM index_records ORDER BY path")
            return tuple(_index_record(row) for row in await cursor.fetchall())

    async def save_index_record(self, record: IndexRecord) -> None:
        async with self._connection() as connection:
            await connection.execute(
                """
                INSERT INTO index_records(
                    path, note_id, content_hash, index_fingerprint, collection,
                    point_ids_json, status, indexed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    note_id = excluded.note_id,
                    content_hash = excluded.content_hash,
                    index_fingerprint = excluded.index_fingerprint,
                    collection = excluded.collection,
                    point_ids_json = excluded.point_ids_json,
                    status = excluded.status,
                    indexed_at = excluded.indexed_at
                """,
                (
                    record.path,
                    record.note_id,
                    record.content_hash,
                    record.index_fingerprint,
                    record.collection,
                    json.dumps(record.point_ids, separators=(",", ":")),
                    record.status.value,
                    record.indexed_at.isoformat(),
                ),
            )
            await connection.commit()

    async def delete_index_record(self, path: str) -> None:
        async with self._connection() as connection:
            await connection.execute("DELETE FROM index_records WHERE path = ?", (path,))
            await connection.commit()

    async def enqueue_repair(self, task: RepairTask) -> None:
        async with self._connection() as connection:
            await connection.execute(
                """
                INSERT INTO repair_tasks(
                    repair_id, run_id, target, status, attempts, next_attempt_at, last_error
                ) VALUES (?, ?, ?, 'pending', ?, ?, ?)
                ON CONFLICT(repair_id) DO UPDATE SET
                    next_attempt_at = excluded.next_attempt_at,
                    last_error = excluded.last_error
                """,
                (
                    task.repair_id,
                    task.run_id,
                    task.target.value,
                    task.attempts,
                    task.next_attempt_at.isoformat(),
                    task.last_error,
                ),
            )
            await connection.commit()

    async def list_repairs(self) -> tuple[RepairTask, ...]:
        async with self._connection() as connection:
            cursor = await connection.execute(
                """
                SELECT repair_id, run_id, target, attempts, next_attempt_at, last_error
                FROM repair_tasks
                WHERE status = 'pending'
                ORDER BY next_attempt_at, repair_id
                """
            )
            return tuple(_repair_task(row) for row in await cursor.fetchall())

    async def replay_run(
        self,
        *,
        source_run_id: str,
        new_run_id: str,
        new_idempotency_key: str,
    ) -> RunRecord:
        source = await self.get_run(source_run_id)
        if source is None:
            raise DomainError(ErrorCode.INVALID_REQUEST, "run_store.replay_run")
        result = await self.create_or_get_run(
            run_id=new_run_id,
            idempotency_key=new_idempotency_key,
            request_hash=source.request_hash,
        )
        if not result.created or result.record.run_id != new_run_id:
            raise DomainError(ErrorCode.IDEMPOTENCY_CONFLICT, "run_store.replay_run")
        return result.record


def _sql_statements(script: str) -> tuple[str, ...]:
    return tuple(statement.strip() for statement in script.split(";") if statement.strip())


def _run_record(row: aiosqlite.Row) -> RunRecord:
    return RunRecord(
        run_id=row["run_id"],
        idempotency_key=row["idempotency_key"],
        request_hash=row["request_hash"],
        status=RunStatus(row["status"]),
        stage=row["stage"],
        lease_owner=row["lease_owner"],
        lease_expires_at=_parse_datetime(row["lease_expires_at"]),
        created_at=_parse_datetime(row["created_at"]),
        updated_at=_parse_datetime(row["updated_at"]),
        terminal_at=_parse_datetime(row["terminal_at"]),
    )


def _index_record(row: aiosqlite.Row) -> IndexRecord:
    return IndexRecord(
        path=row["path"],
        note_id=row["note_id"],
        content_hash=row["content_hash"],
        index_fingerprint=row["index_fingerprint"],
        collection=row["collection"],
        point_ids=tuple(json.loads(row["point_ids_json"])),
        status=IndexStatus(row["status"]),
        indexed_at=datetime.fromisoformat(row["indexed_at"]),
    )


def _repair_task(row: aiosqlite.Row) -> RepairTask:
    return RepairTask(
        repair_id=row["repair_id"],
        run_id=row["run_id"],
        target=RepairTarget(row["target"]),
        attempts=int(row["attempts"]),
        next_attempt_at=datetime.fromisoformat(row["next_attempt_at"]),
        last_error=row["last_error"],
    )


def _parse_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value is not None else None


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("lease timestamps must include a timezone")
    return value.astimezone(UTC)
