from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class IndexDocument:
    document_id: str
    collection: str
    content: str
    content_hash: str
    metadata: dict[str, str]


@dataclass(frozen=True, slots=True)
class VectorQuery:
    collection: str
    text: str
    limit: int
    filters: dict[str, str]


@dataclass(frozen=True, slots=True)
class VectorHit:
    point_id: str
    score: float
    content: str
    metadata: dict[str, str]


@runtime_checkable
class VectorIndex(Protocol):
    async def upsert(self, documents: tuple[IndexDocument, ...]) -> tuple[str, ...]: ...

    async def query(self, query: VectorQuery) -> tuple[VectorHit, ...]: ...

    async def delete(self, *, collection: str, point_ids: tuple[str, ...]) -> None: ...
