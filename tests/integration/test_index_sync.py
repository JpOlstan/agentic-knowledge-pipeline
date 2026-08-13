from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from qdrant_client import models
from tests.fakes import FakeRunStore, FakeVectorIndex

from knowledge_agents.adapters.chunker import ChunkerConfig, MarkdownChunker
from knowledge_agents.adapters.embeddings import EmbeddingConfig, OpenAIEmbeddings
from knowledge_agents.adapters.qdrant_index import PAYLOAD_INDEX_FIELDS, QdrantVectorIndex
from knowledge_agents.adapters.sqlite_run_store import SqliteRunStore
from knowledge_agents.application.services.index_service import (
    IndexScan,
    IndexService,
    IndexSource,
    build_index_fingerprint,
)
from knowledge_agents.ports.vector_index import (
    DRAFT_COLLECTION,
    INDEX_COLLECTIONS,
    NOTE_COLLECTION,
    IndexDocument,
)

RUN_ID = "run-0123456789abcdef"


def _source(path: str, content: str, *, collection: str = DRAFT_COLLECTION) -> IndexSource:
    note_id = Path(path).stem
    return IndexSource(
        path=path,
        document_id=note_id,
        note_id=note_id,
        collection=collection,
        content=content,
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        run_id=RUN_ID,
        source_type="vault_draft" if collection == DRAFT_COLLECTION else "vault_note",
        status="ready",
    )


def _service(vector: FakeVectorIndex, store: FakeRunStore) -> IndexService:
    return IndexService(
        vector_index=vector,
        run_store=store,
        embedding_model="fake-embedding-v1",
        embedding_dimensions=4,
        chunker=MarkdownChunker(ChunkerConfig(target_tokens=8, max_tokens=12, overlap_tokens=2)),
    )


def test_incremental_sync_noop_and_generation_swap() -> None:
    async def scenario() -> None:
        vector = FakeVectorIndex()
        store = FakeRunStore()
        service = _service(vector, store)
        original = _source("01-inbox/agent-runs/run/drafts/note-a.md", "# A\n\noriginal body")

        first = await service.sync(IndexScan((original,), complete=True), run_id=RUN_ID)
        first_record = store.index_records[original.path]
        first_ids = first_record.point_ids
        second = await service.sync(IndexScan((original,), complete=True), run_id=RUN_ID)

        assert first.indexed_paths == (original.path,)
        assert second.unchanged_paths == (original.path,)
        assert sum(call.operation == "upsert" for call in vector.calls) == 1

        updated = _source(original.path, "# A\n\nupdated body with another fact")
        third = await service.sync(IndexScan((updated,), complete=True), run_id=RUN_ID)
        current = store.index_records[original.path]

        assert third.indexed_paths == (original.path,)
        assert current.point_ids != first_ids
        assert all(point_id not in vector.documents for point_id in first_ids)
        assert await vector.validate(collection=DRAFT_COLLECTION, point_ids=current.point_ids)

    asyncio.run(scenario())


def test_failed_update_preserves_previous_generation_and_creates_repair() -> None:
    async def scenario() -> None:
        vector = FakeVectorIndex()
        store = FakeRunStore()
        service = _service(vector, store)
        original = _source("01-inbox/agent-runs/run/drafts/note-b.md", "# B\n\nstable")
        await service.sync(IndexScan((original,), complete=True), run_id=RUN_ID)
        previous = store.index_records[original.path]

        vector.failures["upsert"] = RuntimeError("qdrant unavailable")
        updated = _source(original.path, "# B\n\nchanged")
        result = await service.sync(IndexScan((updated,), complete=True), run_id=RUN_ID)

        assert result.failed_paths == (original.path,)
        assert result.repair_required is True
        assert store.index_records[original.path] == previous
        assert all(point_id in vector.documents for point_id in previous.point_ids)
        assert len(store.repairs) == 1
        repair = next(iter(store.repairs.values()))
        assert repair.last_error == "index_repair_required"
        assert "qdrant unavailable" not in repair.model_dump_json()

    asyncio.run(scenario())


def test_incomplete_scan_never_confirms_deletions() -> None:
    async def scenario() -> None:
        vector = FakeVectorIndex()
        store = FakeRunStore()
        service = _service(vector, store)
        first = _source("notes/first.md", "# First\n\nbody", collection=NOTE_COLLECTION)
        second = _source("notes/second.md", "# Second\n\nbody", collection=NOTE_COLLECTION)
        await service.sync(IndexScan((first, second), complete=True))

        partial = await service.sync(IndexScan((first,), complete=False))
        assert partial.deleted_paths == ()
        assert second.path in store.index_records

        complete = await service.sync(IndexScan((first,), complete=True))
        assert complete.deleted_paths == (second.path,)
        assert second.path not in store.index_records

    asyncio.run(scenario())


def test_qdrant_failure_never_changes_persisted_markdown(tmp_path: Path) -> None:
    async def scenario() -> None:
        draft = tmp_path / "draft.md"
        draft.write_text("# Draft\n\nvaluable body", encoding="utf-8")
        before = draft.read_bytes()
        vector = FakeVectorIndex(failures={"ensure_collections": RuntimeError("offline")})
        store = FakeRunStore()
        service = _service(vector, store)

        result = await service.sync(
            IndexScan((_source("draft.md", draft.read_text(encoding="utf-8")),), complete=True),
            run_id=RUN_ID,
        )

        assert result.repair_required is True
        assert draft.read_bytes() == before
        assert tuple(tmp_path.iterdir()) == (draft,)
        assert len(store.repairs) == 1

    asyncio.run(scenario())


def test_rebuild_requires_complete_scan_and_recreates_derived_collections() -> None:
    async def scenario() -> None:
        vector = FakeVectorIndex()
        store = FakeRunStore()
        service = _service(vector, store)
        source = _source("notes/rebuild.md", "# Rebuild\n\nbody", collection=NOTE_COLLECTION)

        with pytest.raises(ValueError, match="complete scan"):
            await service.rebuild(IndexScan((source,), complete=False))
        result = await service.rebuild(IndexScan((source,), complete=True))

        assert result.indexed_paths == (source.path,)
        assert vector.rebuild_count == 1
        assert source.path in store.index_records

    asyncio.run(scenario())


def test_fingerprint_changes_for_each_schema_input() -> None:
    base = {
        "embedding_model": "embedding-a",
        "embedding_dimensions": 4,
        "chunker_config": ChunkerConfig(8, 12, 2, "v1"),
        "schema_version": "v1",
    }
    fingerprint = build_index_fingerprint(**base)

    assert build_index_fingerprint(**{**base, "embedding_model": "embedding-b"}) != fingerprint
    assert build_index_fingerprint(**{**base, "embedding_dimensions": 8}) != fingerprint
    assert (
        build_index_fingerprint(**{**base, "chunker_config": ChunkerConfig(9, 12, 2, "v1")})
        != fingerprint
    )
    assert build_index_fingerprint(**{**base, "schema_version": "v2"}) != fingerprint


def test_embedding_adapter_deduplicates_exact_text_before_provider_call() -> None:
    class FakeEmbeddingEndpoint:
        def __init__(self) -> None:
            self.inputs: list[list[str]] = []

        async def create(self, **request: object) -> SimpleNamespace:
            texts = list(request["input"])
            self.inputs.append(texts)
            return SimpleNamespace(
                data=[
                    SimpleNamespace(index=index, embedding=[float(index), 1.0])
                    for index in range(len(texts))
                ]
            )

    async def scenario() -> None:
        endpoint = FakeEmbeddingEndpoint()
        adapter = OpenAIEmbeddings(
            SimpleNamespace(embeddings=endpoint),
            EmbeddingConfig(model="fake", dimensions=2),
        )

        vectors = await adapter.embed(("same", "different", "same"))

        assert endpoint.inputs == [["same", "different"]]
        assert vectors[0] == vectors[2]
        assert vectors[0] != vectors[1]

    asyncio.run(scenario())


class FakeQdrantClient:
    def __init__(self) -> None:
        self.collections: dict[str, models.VectorParams] = {}
        self.schemas: dict[str, dict[str, object]] = {}
        self.points: dict[str, dict[str, models.PointStruct]] = {}
        self.deleted: list[str] = []

    async def collection_exists(self, collection: str) -> bool:
        return collection in self.collections

    async def create_collection(
        self,
        *,
        collection_name: str,
        vectors_config: models.VectorParams,
    ) -> None:
        self.collections[collection_name] = vectors_config
        self.schemas[collection_name] = {}
        self.points[collection_name] = {}

    async def get_collection(self, collection: str) -> SimpleNamespace:
        return SimpleNamespace(
            config=SimpleNamespace(params=SimpleNamespace(vectors=self.collections[collection])),
            payload_schema=self.schemas[collection],
        )

    async def create_payload_index(
        self,
        *,
        collection_name: str,
        field_name: str,
        field_schema: object,
        wait: bool,
    ) -> None:
        assert wait is True
        self.schemas[collection_name][field_name] = field_schema

    async def delete_collection(self, *, collection_name: str) -> None:
        self.deleted.append(collection_name)
        self.collections.pop(collection_name)
        self.schemas.pop(collection_name)
        self.points.pop(collection_name)

    async def upsert(
        self,
        *,
        collection_name: str,
        points: list[models.PointStruct],
        wait: bool,
    ) -> None:
        assert wait is True
        self.points[collection_name].update({str(point.id): point for point in points})


def test_qdrant_fixture_creates_payload_indexes_and_can_rebuild_collections() -> None:
    class FakeEmbeddings:
        config = EmbeddingConfig(model="fake", dimensions=4)

        async def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
            return tuple((1.0, 0.0, 0.0, 0.0) for _ in texts)

    async def scenario() -> None:
        client = FakeQdrantClient()
        index = QdrantVectorIndex(client, FakeEmbeddings())

        await index.ensure_collections()
        assert tuple(client.collections) == INDEX_COLLECTIONS
        assert all(
            set(client.schemas[name]) == set(PAYLOAD_INDEX_FIELDS) for name in INDEX_COLLECTIONS
        )

        document_hash = "a" * 64
        chunk_hash = "b" * 64
        point_id = "ca978112-ca1b-5dca-bac2-31b39a23dc4d"
        await index.upsert(
            (
                IndexDocument(
                    document_id=point_id,
                    collection=DRAFT_COLLECTION,
                    content="chunk content",
                    content_hash=chunk_hash,
                    metadata={"content_hash": document_hash, "chunk_hash": chunk_hash},
                ),
            )
        )
        payload = client.points[DRAFT_COLLECTION][point_id].payload
        assert payload is not None
        assert payload["content_hash"] == document_hash
        assert payload["chunk_hash"] == chunk_hash

        await index.recreate_collections()
        assert tuple(client.deleted) == INDEX_COLLECTIONS
        assert tuple(client.collections) == INDEX_COLLECTIONS

    asyncio.run(scenario())


def test_index_records_and_repairs_are_durable_in_sqlite(tmp_path: Path) -> None:
    async def scenario() -> None:
        database = tmp_path / "runs.db"
        store = SqliteRunStore(database)
        await store.migrate()
        await store.create_or_get_run(
            run_id=RUN_ID,
            idempotency_key="index-sync-idempotency-key",
            request_hash="a" * 64,
        )
        vector = FakeVectorIndex()
        source = _source("notes/durable.md", "# Durable\n\nbody", collection=NOTE_COLLECTION)
        service = IndexService(
            vector_index=vector,
            run_store=store,
            embedding_model="fake-embedding-v1",
            embedding_dimensions=4,
            chunker=MarkdownChunker(),
        )
        await service.sync(IndexScan((source,), complete=True), run_id=RUN_ID)

        reopened = SqliteRunStore(database)
        record = await reopened.get_index_record(source.path)
        assert record is not None
        assert record.point_ids

        unavailable = FakeVectorIndex(
            failures={"ensure_collections": RuntimeError("qdrant unavailable")}
        )
        repair_service = IndexService(
            vector_index=unavailable,
            run_store=reopened,
            embedding_model="fake-embedding-v1",
            embedding_dimensions=4,
            chunker=MarkdownChunker(),
        )
        result = await repair_service.sync(IndexScan((source,), complete=True), run_id=RUN_ID)

        assert result.repair_required is True
        repairs = await SqliteRunStore(database).list_repairs()
        assert len(repairs) == 1
        assert repairs[0].last_error == "index_repair_required"

    asyncio.run(scenario())
