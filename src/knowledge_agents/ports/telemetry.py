from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class TelemetryEvent:
    run_id: str
    name: str
    occurred_at: datetime
    attributes: dict[str, str | int | float | bool]


@runtime_checkable
class TelemetryPort(Protocol):
    async def record(self, event: TelemetryEvent) -> None: ...

    async def flush(self) -> None: ...
