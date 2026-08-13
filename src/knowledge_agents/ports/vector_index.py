from dataclasses import dataclass
from typing import Protocol, runtime_checkable

EVIDENCE_COLLECTION = "knowledge_evidence_v1"
DRAFT_COLLECTION = "knowledge_drafts_v1"
NOTE_COLLECTION = "knowledge_notes_v1"
INDEX_COLLECTIONS = (EVIDENCE_COLLECTION, DRAFT_COLLECTION, NOTE_COLLECTION)


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
    async def ensure_collections(self) -> None: ...

    async def upsert(self, documents: tuple[IndexDocument, ...]) -> tuple[str, ...]: ...

    async def query(self, query: VectorQuery) -> tuple[VectorHit, ...]: ...

    async def delete(self, *, collection: str, point_ids: tuple[str, ...]) -> None: ...

    async def validate(self, *, collection: str, point_ids: tuple[str, ...]) -> bool: ...

    async def recreate_collections(self) -> None: ...

    async def collection_counts(self) -> dict[str, int]: ...
