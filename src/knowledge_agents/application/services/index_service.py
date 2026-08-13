from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from knowledge_agents.domain.contracts import IndexRecord, RepairTask
from knowledge_agents.domain.enums import IndexStatus, RepairTarget
from knowledge_agents.domain.errors import ErrorCode
from knowledge_agents.domain.hashing import canonical_sha256
from knowledge_agents.ports.run_store import RunStore
from knowledge_agents.ports.vector_index import INDEX_COLLECTIONS, IndexDocument, VectorIndex


@dataclass(frozen=True, slots=True)
class IndexSource:
    path: str
    document_id: str
    note_id: str
    collection: str
    content: str
    content_hash: str
    run_id: str = ""
    source_type: str = "vault"
    status: str = "unknown"
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class IndexScan:
    sources: tuple[IndexSource, ...]
    complete: bool


@dataclass(frozen=True, slots=True)
class IndexSyncResult:
    indexed_paths: tuple[str, ...] = ()
    unchanged_paths: tuple[str, ...] = ()
    deleted_paths: tuple[str, ...] = ()
    failed_paths: tuple[str, ...] = ()
    repair_required: bool = False


@dataclass(frozen=True, slots=True)
class IndexStatusReport:
    records: int
    pending_repairs: int
    collection_counts: dict[str, int]
    index_fingerprint: str


class ChunkerConfigPort(Protocol):
    target_tokens: int
    max_tokens: int
    overlap_tokens: int
    version: str


class ChunkPort(Protocol):
    ordinal: int
    content: str
    content_hash: str
    heading_path: tuple[str, ...]
    source_locator: str


class ChunkerPort(Protocol):
    config: ChunkerConfigPort

    def chunk(
        self,
        *,
        document_id: str,
        content: str,
        source_locator: str,
    ) -> tuple[ChunkPort, ...]: ...


class IndexService:
    def __init__(
        self,
        *,
        vector_index: VectorIndex,
        run_store: RunStore,
        embedding_model: str,
        embedding_dimensions: int,
        chunker: ChunkerPort,
        schema_version: str = "v1",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.vector_index = vector_index
        self.run_store = run_store
        self.chunker = chunker
        self.embedding_model = embedding_model
        self.embedding_dimensions = embedding_dimensions
        self.schema_version = schema_version
        self.clock = clock or (lambda: datetime.now(UTC))
        self.index_fingerprint = build_index_fingerprint(
            embedding_model=embedding_model,
            embedding_dimensions=embedding_dimensions,
            chunker_config=self.chunker.config,
            schema_version=schema_version,
        )

    async def sync(self, scan: IndexScan, *, run_id: str | None = None) -> IndexSyncResult:
        _validate_scan(scan)
        try:
            await self.vector_index.ensure_collections()
        except Exception:
            await self._repair(run_id)
            return IndexSyncResult(
                failed_paths=tuple(sorted(source.path for source in scan.sources)),
                repair_required=True,
            )

        indexed: list[str] = []
        unchanged: list[str] = []
        deleted: list[str] = []
        failed: list[str] = []
        repair_required = False
        seen_paths = {source.path for source in scan.sources}

        for source in sorted(scan.sources, key=lambda item: item.path):
            existing = await self.run_store.get_index_record(source.path)
            if await self._is_unchanged(source, existing):
                unchanged.append(source.path)
                continue
            success, cleanup_repair = await self._replace_generation(source, existing)
            if success:
                indexed.append(source.path)
            else:
                failed.append(source.path)
            if cleanup_repair or not success:
                repair_required = True

        if scan.complete:
            for existing in await self.run_store.list_index_records():
                if existing.path in seen_paths:
                    continue
                try:
                    await self.vector_index.delete(
                        collection=existing.collection,
                        point_ids=existing.point_ids,
                    )
                    await self.run_store.delete_index_record(existing.path)
                    deleted.append(existing.path)
                except Exception:
                    failed.append(existing.path)
                    repair_required = True

        if repair_required:
            await self._repair(run_id)
        return IndexSyncResult(
            indexed_paths=tuple(indexed),
            unchanged_paths=tuple(unchanged),
            deleted_paths=tuple(deleted),
            failed_paths=tuple(sorted(set(failed))),
            repair_required=repair_required,
        )

    async def rebuild(self, scan: IndexScan, *, run_id: str | None = None) -> IndexSyncResult:
        if not scan.complete:
            raise ValueError("rebuild requires a complete scan")
        try:
            await self.vector_index.recreate_collections()
            for record in await self.run_store.list_index_records():
                await self.run_store.delete_index_record(record.path)
        except Exception:
            await self._repair(run_id)
            return IndexSyncResult(
                failed_paths=tuple(sorted(source.path for source in scan.sources)),
                repair_required=True,
            )
        return await self.sync(scan, run_id=run_id)

    async def status(self) -> IndexStatusReport:
        records = await self.run_store.list_index_records()
        repairs = await self.run_store.list_repairs()
        counts = await self.vector_index.collection_counts()
        return IndexStatusReport(
            records=len(records),
            pending_repairs=sum(task.target is RepairTarget.QDRANT for task in repairs),
            collection_counts={
                collection: counts.get(collection, 0) for collection in INDEX_COLLECTIONS
            },
            index_fingerprint=self.index_fingerprint,
        )

    async def _is_unchanged(
        self,
        source: IndexSource,
        existing: IndexRecord | None,
    ) -> bool:
        return bool(
            existing is not None
            and existing.status is IndexStatus.INDEXED
            and existing.content_hash == source.content_hash
            and existing.index_fingerprint == self.index_fingerprint
            and existing.collection == source.collection
            and await self.vector_index.validate(
                collection=existing.collection,
                point_ids=existing.point_ids,
            )
        )

    async def _replace_generation(
        self,
        source: IndexSource,
        existing: IndexRecord | None,
    ) -> tuple[bool, bool]:
        generation = canonical_sha256(
            {
                "path": source.path,
                "content_hash": source.content_hash,
                "index_fingerprint": self.index_fingerprint,
            }
        )
        chunks = self.chunker.chunk(
            document_id=source.document_id,
            content=source.content,
            source_locator=source.path,
        )
        documents = tuple(
            IndexDocument(
                document_id=_point_id(
                    source.collection, source.document_id, generation, chunk.ordinal
                ),
                collection=source.collection,
                content=chunk.content,
                content_hash=chunk.content_hash,
                metadata={
                    **source.metadata,
                    "document_id": source.document_id,
                    "run_id": source.run_id,
                    "source_type": source.source_type,
                    "status": source.status,
                    "path": source.path,
                    "content_hash": source.content_hash,
                    "generation": generation,
                    "heading_path": " / ".join(chunk.heading_path),
                    "source_locator": chunk.source_locator,
                    "chunk_hash": chunk.content_hash,
                },
            )
            for chunk in chunks
        )
        point_ids = tuple(document.document_id for document in documents)
        try:
            returned_ids = await self.vector_index.upsert(documents)
            if returned_ids != point_ids or not await self.vector_index.validate(
                collection=source.collection,
                point_ids=point_ids,
            ):
                raise ValueError("new index generation did not validate")
            await self.run_store.save_index_record(
                IndexRecord(
                    path=source.path,
                    note_id=source.note_id,
                    content_hash=source.content_hash,
                    index_fingerprint=self.index_fingerprint,
                    collection=source.collection,
                    point_ids=point_ids,
                    status=IndexStatus.INDEXED,
                    indexed_at=self.clock(),
                )
            )
        except Exception:
            with suppress(Exception):
                await self.vector_index.delete(
                    collection=source.collection,
                    point_ids=point_ids,
                )
            return False, False

        if existing is not None:
            stale_ids = tuple(
                point_id for point_id in existing.point_ids if point_id not in point_ids
            )
            try:
                await self.vector_index.delete(
                    collection=existing.collection,
                    point_ids=stale_ids,
                )
            except Exception:
                return True, True
        return True, False

    async def _repair(self, run_id: str | None) -> None:
        if run_id is None:
            return
        repair_id = f"repair-{canonical_sha256({'run_id': run_id, 'target': 'qdrant'})[:24]}"
        await self.run_store.enqueue_repair(
            RepairTask(
                repair_id=repair_id,
                run_id=run_id,
                target=RepairTarget.QDRANT,
                attempts=0,
                next_attempt_at=self.clock(),
                last_error=ErrorCode.INDEX_REPAIR_REQUIRED.value,
            )
        )


def build_index_fingerprint(
    *,
    embedding_model: str,
    embedding_dimensions: int,
    chunker_config: ChunkerConfigPort,
    schema_version: str,
) -> str:
    return canonical_sha256(
        {
            "embedding_model": embedding_model,
            "embedding_dimensions": embedding_dimensions,
            "chunker": {
                "version": chunker_config.version,
                "target_tokens": chunker_config.target_tokens,
                "max_tokens": chunker_config.max_tokens,
                "overlap_tokens": chunker_config.overlap_tokens,
            },
            "schema_version": schema_version,
        }
    )


def _point_id(collection: str, document_id: str, generation: str, ordinal: int) -> str:
    return str(uuid5(NAMESPACE_URL, f"{collection}:{document_id}:{generation}:{ordinal}"))


def _validate_scan(scan: IndexScan) -> None:
    paths: set[str] = set()
    for source in scan.sources:
        if source.collection not in INDEX_COLLECTIONS:
            raise ValueError("unknown index collection")
        if source.path in paths:
            raise ValueError("scan contains duplicate paths")
        paths.add(source.path)
