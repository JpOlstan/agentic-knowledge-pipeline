from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from typing import Any, Protocol

from knowledge_agents.observability.redaction import RedactionPolicy
from knowledge_agents.ports.telemetry import TelemetryEvent, TelemetryPort


class LangfuseObservationPort(Protocol):
    def update(self, **kwargs: Any) -> Any: ...

    def end(self) -> Any: ...


class LangfuseClientPort(Protocol):
    def start_observation(self, **kwargs: Any) -> LangfuseObservationPort: ...

    def flush(self) -> Any: ...


class LangfuseTelemetry(TelemetryPort):
    def __init__(
        self,
        client: LangfuseClientPort,
        *,
        redaction: RedactionPolicy | None = None,
    ) -> None:
        self._client = client
        self._redaction = redaction or RedactionPolicy()
        self._pending: list[TelemetryEvent] = []
        self._lock = asyncio.Lock()

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    async def record(self, event: TelemetryEvent) -> None:
        sanitized = self._redaction.sanitize_event(event)
        async with self._lock:
            self._pending.append(sanitized)

    async def flush(self) -> None:
        async with self._lock:
            if not self._pending:
                return
            batch = tuple(self._pending)
            await asyncio.to_thread(self._export, batch)
            del self._pending[: len(batch)]

    def _export(self, events: tuple[TelemetryEvent, ...]) -> None:
        for event in events:
            trace_id = deterministic_trace_id(event.run_id)
            observation = self._client.start_observation(
                name=event.name,
                as_type=event.observation_type,
                trace_context={"trace_id": trace_id},
            )
            observation.update(metadata=event.attributes)
            observation.end()
        self._client.flush()


def deterministic_trace_id(run_id: str) -> str:
    return hashlib.sha256(f"knowledge-agents:{run_id}".encode()).hexdigest()[:32]


def create_langfuse_telemetry(
    *,
    public_key: str,
    secret_key: str,
    base_url: str,
    environment: str,
    client_factory: Callable[..., LangfuseClientPort] | None = None,
) -> LangfuseTelemetry:
    if client_factory is None:
        from langfuse import Langfuse

        client_factory = Langfuse
    client = client_factory(
        public_key=public_key,
        secret_key=secret_key,
        base_url=base_url,
        environment=environment,
    )
    return LangfuseTelemetry(client)
