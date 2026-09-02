from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable

ObservationType = Literal["span", "generation", "retriever"]


@dataclass(frozen=True, slots=True)
class TelemetryEvent:
    run_id: str
    name: str
    occurred_at: datetime
    attributes: dict[str, str | int | float | bool]
    observation_type: ObservationType = "span"


@runtime_checkable
class TelemetryPort(Protocol):
    async def record(self, event: TelemetryEvent) -> None: ...

    async def flush(self) -> None: ...
