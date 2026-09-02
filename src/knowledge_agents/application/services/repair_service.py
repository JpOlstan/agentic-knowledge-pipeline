from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from knowledge_agents.domain.contracts import RepairTask
from knowledge_agents.domain.enums import RepairTarget
from knowledge_agents.domain.errors import ErrorCode
from knowledge_agents.ports.run_store import RunStore

RepairHandler = Callable[[RepairTask], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class RepairRunResult:
    run_id: str
    attempted: tuple[str, ...] = ()
    completed: tuple[str, ...] = ()
    rescheduled: tuple[str, ...] = ()
    exhausted: tuple[str, ...] = ()
    not_due: tuple[str, ...] = ()


class RepairService:
    def __init__(
        self,
        *,
        run_store: RunStore,
        handlers: Mapping[RepairTarget, RepairHandler],
        clock: Callable[[], datetime] | None = None,
        max_attempts: int = 3,
        base_delay_seconds: int = 30,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if base_delay_seconds < 1:
            raise ValueError("base_delay_seconds must be positive")
        self.run_store = run_store
        self.handlers = dict(handlers)
        self.clock = clock or (lambda: datetime.now(UTC))
        self.max_attempts = max_attempts
        self.base_delay_seconds = base_delay_seconds

    async def list(self, *, run_id: str | None = None) -> tuple[RepairTask, ...]:
        repairs = await self.run_store.list_repairs()
        return tuple(task for task in repairs if run_id is None or task.run_id == run_id)

    async def run(self, run_id: str) -> RepairRunResult:
        now = self.clock()
        attempted: list[str] = []
        completed: list[str] = []
        rescheduled: list[str] = []
        exhausted: list[str] = []
        not_due: list[str] = []

        for task in await self.list(run_id=run_id):
            if task.next_attempt_at > now:
                not_due.append(task.repair_id)
                continue
            attempted.append(task.repair_id)
            handler = self.handlers.get(task.target)
            try:
                if handler is None:
                    raise LookupError("repair handler unavailable")
                await handler(task)
            except Exception:
                attempts = task.attempts + 1
                error_code = _repair_error_code(task.target)
                if attempts >= self.max_attempts:
                    await self.run_store.fail_repair(
                        repair_id=task.repair_id,
                        attempts=attempts,
                        last_error=error_code,
                    )
                    exhausted.append(task.repair_id)
                    continue
                await self.run_store.enqueue_repair(
                    task.model_copy(
                        update={
                            "attempts": attempts,
                            "next_attempt_at": now + self._retry_delay(task.repair_id, attempts),
                            "last_error": error_code,
                        }
                    )
                )
                rescheduled.append(task.repair_id)
            else:
                await self.run_store.complete_repair(task.repair_id)
                completed.append(task.repair_id)

        return RepairRunResult(
            run_id=run_id,
            attempted=tuple(attempted),
            completed=tuple(completed),
            rescheduled=tuple(rescheduled),
            exhausted=tuple(exhausted),
            not_due=tuple(not_due),
        )

    def _retry_delay(self, repair_id: str, attempts: int) -> timedelta:
        base = self.base_delay_seconds * 2 ** (attempts - 1)
        digest = hashlib.sha256(f"{repair_id}:{attempts}".encode()).digest()
        jitter_ratio = int.from_bytes(digest[:2]) / 65_535 * 0.25
        return timedelta(seconds=base * (1 + jitter_ratio))


def _repair_error_code(target: RepairTarget) -> str:
    if target is RepairTarget.QDRANT:
        return ErrorCode.INDEX_REPAIR_REQUIRED.value
    return ErrorCode.TELEMETRY_REPAIR_REQUIRED.value
