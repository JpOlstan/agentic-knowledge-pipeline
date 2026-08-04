from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class QueueMessage:
    message_id: str
    receipt_handle: str
    body: str
    receive_count: int


@runtime_checkable
class QueuePort(Protocol):
    async def receive(self, *, max_messages: int = 1) -> tuple[QueueMessage, ...]: ...

    async def extend_visibility(self, message: QueueMessage, *, seconds: int) -> None: ...

    async def acknowledge(self, message: QueueMessage) -> None: ...

    async def release(self, message: QueueMessage) -> None: ...
