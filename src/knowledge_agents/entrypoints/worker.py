from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Annotated, Any, Literal, Protocol
from uuid import uuid4

from pydantic import AnyHttpUrl, AwareDatetime, BaseModel, ConfigDict, StringConstraints
from pydantic import ValidationError as PydanticValidationError

from knowledge_agents.domain.contracts import AcquisitionRequest, RunId
from knowledge_agents.domain.enums import RunStatus
from knowledge_agents.domain.errors import DomainError, ErrorCode
from knowledge_agents.domain.hashing import canonical_sha256
from knowledge_agents.ports.queue import QueueMessage, QueuePort
from knowledge_agents.ports.run_store import RunStore

HEARTBEAT_SECONDS = 60
LEASE_TTL_SECONDS = 180
MAX_MESSAGE_BODY_BYTES = 16 * 1024

TERMINAL_STATUSES = {
    RunStatus.COMPLETED,
    RunStatus.COMPLETED_WITH_WARNINGS,
    RunStatus.ENRICHMENT_REQUIRED,
    RunStatus.REJECTED,
    RunStatus.FAILED,
}

IdempotencyKey = Annotated[str, StringConstraints(min_length=16, max_length=128)]
Wait = Callable[[float], Awaitable[None]]


class QueueEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1"]
    run_id: RunId
    idempotency_key: IdempotencyKey
    url: AnyHttpUrl
    requested_at: AwareDatetime

    def acquisition_request(self) -> AcquisitionRequest:
        return AcquisitionRequest(
            url=self.url,
            run_id=self.run_id,
            idempotency_key=self.idempotency_key,
        )


class RunExecutor(Protocol):
    async def execute(
        self,
        request: AcquisitionRequest,
        *,
        run_id: str,
        idempotency_key: str,
    ) -> object: ...


class MessageDisposition(StrEnum):
    ACKNOWLEDGED = "acknowledged"
    RELEASED = "released"
    LEASE_BUSY = "lease_busy"
    HEARTBEAT_LOST = "heartbeat_lost"
    INVALID = "invalid"
    TIMEOUT_PENDING = "timeout_pending"


@dataclass(frozen=True, slots=True)
class WorkerConfig:
    worker_id: str = field(default_factory=lambda: f"worker-{uuid4().hex}")
    heartbeat_seconds: float = HEARTBEAT_SECONDS
    lease_ttl_seconds: int = LEASE_TTL_SECONDS
    max_messages: int = 1
    message_body_limit: int = MAX_MESSAGE_BODY_BYTES

    def __post_init__(self) -> None:
        if not self.worker_id.strip():
            raise ValueError("worker_id must not be empty")
        if self.heartbeat_seconds <= 0:
            raise ValueError("heartbeat_seconds must be positive")
        if self.lease_ttl_seconds <= self.heartbeat_seconds:
            raise ValueError("lease_ttl_seconds must exceed heartbeat_seconds")
        if not 1 <= self.max_messages <= 10:
            raise ValueError("max_messages must be between 1 and 10")
        if self.message_body_limit <= 0:
            raise ValueError("message_body_limit must be positive")


class _HeartbeatLost(Exception):
    pass


class Worker:
    def __init__(
        self,
        *,
        queue: QueuePort,
        run_store: RunStore,
        run_executor: RunExecutor,
        config: WorkerConfig | None = None,
        wait: Wait = asyncio.sleep,
    ) -> None:
        self.queue = queue
        self.run_store = run_store
        self.run_executor = run_executor
        self.config = config or WorkerConfig()
        self._wait = wait

    async def run(self, stop: asyncio.Event) -> None:
        """Poll until stopped; a stop observed after receive releases unstarted work."""
        while not stop.is_set():
            messages = await self.queue.receive(max_messages=self.config.max_messages)
            if stop.is_set():
                for message in messages:
                    await self._release_safely(message)
                return
            for index, message in enumerate(messages):
                if stop.is_set():
                    for pending in messages[index:]:
                        await self._release_safely(pending)
                    return
                await self.process(message)

    async def run_once(self) -> tuple[MessageDisposition, ...]:
        messages = await self.queue.receive(max_messages=self.config.max_messages)
        dispositions = [await self.process(message) for message in messages]
        return tuple(dispositions)

    async def process(self, message: QueueMessage) -> MessageDisposition:
        try:
            envelope = parse_queue_envelope(
                message.body,
                max_bytes=self.config.message_body_limit,
            )
        except DomainError:
            await self._release_safely(message)
            return MessageDisposition.INVALID

        request = envelope.acquisition_request()
        request_hash = canonical_sha256(request)
        try:
            created = await self.run_store.create_or_get_run(
                run_id=envelope.run_id,
                idempotency_key=envelope.idempotency_key,
                request_hash=request_hash,
            )
            if created.record.request_hash != request_hash:
                raise DomainError(ErrorCode.IDEMPOTENCY_CONFLICT, "worker.prepare")
            if created.record.status in TERMINAL_STATUSES:
                return await self._acknowledge_terminal(message)
            acquired = await self.run_store.acquire_lease(
                run_id=created.record.run_id,
                owner=self.config.worker_id,
                ttl_seconds=self.config.lease_ttl_seconds,
            )
        except Exception:
            await self._release_safely(message)
            return MessageDisposition.RELEASED

        if not acquired:
            await self._release_safely(message)
            return MessageDisposition.LEASE_BUSY

        try:
            return await self._execute_with_heartbeat(
                message=message,
                envelope=envelope,
                request=request,
                canonical_run_id=created.record.run_id,
            )
        finally:
            with suppress(Exception):
                await self.run_store.release_lease(
                    run_id=created.record.run_id,
                    owner=self.config.worker_id,
                )

    async def _execute_with_heartbeat(
        self,
        *,
        message: QueueMessage,
        envelope: QueueEnvelope,
        request: AcquisitionRequest,
        canonical_run_id: str,
    ) -> MessageDisposition:
        execution = asyncio.create_task(
            self.run_executor.execute(
                request,
                run_id=canonical_run_id,
                idempotency_key=envelope.idempotency_key,
            )
        )
        heartbeat = asyncio.create_task(self._heartbeat(message, canonical_run_id))
        done, _ = await asyncio.wait(
            {execution, heartbeat},
            return_when=asyncio.FIRST_COMPLETED,
        )

        if heartbeat in done:
            heartbeat_error = heartbeat.exception()
            if heartbeat_error is not None:
                execution.cancel()
                with suppress(asyncio.CancelledError):
                    await execution
                return MessageDisposition.HEARTBEAT_LOST

        try:
            await execution
        except Exception:
            await self._release_safely(message)
            return MessageDisposition.RELEASED
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat

        try:
            durable = await self.run_store.get_run(canonical_run_id)
        except Exception:
            return MessageDisposition.TIMEOUT_PENDING
        if durable is not None and durable.status in TERMINAL_STATUSES:
            return await self._acknowledge_terminal(message)
        await self._release_safely(message)
        return MessageDisposition.RELEASED

    async def _heartbeat(self, message: QueueMessage, run_id: str) -> None:
        while True:
            await self._wait(self.config.heartbeat_seconds)
            try:
                renewed = await self.run_store.renew_lease(
                    run_id=run_id,
                    owner=self.config.worker_id,
                    ttl_seconds=self.config.lease_ttl_seconds,
                )
                if not renewed:
                    raise _HeartbeatLost
                await self.queue.extend_visibility(
                    message,
                    seconds=self.config.lease_ttl_seconds,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                raise _HeartbeatLost from exc

    async def _acknowledge_terminal(self, message: QueueMessage) -> MessageDisposition:
        try:
            await self.queue.acknowledge(message)
        except Exception:
            return MessageDisposition.TIMEOUT_PENDING
        return MessageDisposition.ACKNOWLEDGED

    async def _release_safely(self, message: QueueMessage) -> None:
        with suppress(Exception):
            await self.queue.release(message)


def parse_queue_envelope(body: str, *, max_bytes: int = MAX_MESSAGE_BODY_BYTES) -> QueueEnvelope:
    try:
        if len(body.encode("utf-8")) > max_bytes:
            raise ValueError("queue message exceeds the size limit")
        payload = json.loads(body, object_pairs_hook=_unique_object)
        if not isinstance(payload, dict):
            raise ValueError("queue message must be a JSON object")
        return QueueEnvelope.model_validate(payload)
    except (PydanticValidationError, TypeError, ValueError) as exc:
        raise DomainError(ErrorCode.INVALID_REQUEST, "worker.parse_message", cause=exc) from exc


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result
