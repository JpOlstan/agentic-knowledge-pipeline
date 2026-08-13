from __future__ import annotations

from collections import defaultdict
from typing import Any

from qdrant_client import models

from knowledge_agents.adapters.embeddings import EmbeddingProvider
from knowledge_agents.ports.vector_index import (
    INDEX_COLLECTIONS,
    IndexDocument,
    VectorHit,
    VectorIndex,
    VectorQuery,
)

PAYLOAD_INDEX_FIELDS = (
    "document_id",
    "run_id",
    "source_type",
    "status",
    "path",
    "content_hash",
    "generation",
)


class QdrantVectorIndex(VectorIndex):
    def __init__(self, client: Any, embeddings: EmbeddingProvider) -> None:
        self._client = client
        self._embeddings = embeddings

    async def ensure_collections(self) -> None:
        for collection in INDEX_COLLECTIONS:
            if not await self._client.collection_exists(collection):
                await self._client.create_collection(
                    collection_name=collection,
                    vectors_config=models.VectorParams(
                        size=self._embeddings.config.dimensions,
                        distance=models.Distance.COSINE,
                    ),
                )
            await self._validate_collection(collection)
            info = await self._client.get_collection(collection)
            payload_schema = getattr(info, "payload_schema", {}) or {}
            for field in PAYLOAD_INDEX_FIELDS:
                if field not in payload_schema:
                    await self._client.create_payload_index(
                        collection_name=collection,
                        field_name=field,
                        field_schema=models.PayloadSchemaType.KEYWORD,
                        wait=True,
                    )

    async def upsert(self, documents: tuple[IndexDocument, ...]) -> tuple[str, ...]:
        if not documents:
            return ()
        vectors = await self._embeddings.embed(tuple(document.content for document in documents))
        grouped: dict[str, list[models.PointStruct]] = defaultdict(list)
        for document, vector in zip(documents, vectors, strict=True):
            self._require_collection(document.collection)
            payload = dict(document.metadata)
            payload.setdefault("document_id", document.document_id)
            payload.setdefault("content_hash", document.content_hash)
            payload["content"] = document.content
            grouped[document.collection].append(
                models.PointStruct(id=document.document_id, vector=list(vector), payload=payload)
            )
        for collection, points in grouped.items():
            await self._client.upsert(
                collection_name=collection,
                points=points,
                wait=True,
            )
        return tuple(document.document_id for document in documents)

    async def query(self, query: VectorQuery) -> tuple[VectorHit, ...]:
        self._require_collection(query.collection)
        vector = (await self._embeddings.embed((query.text,)))[0]
        conditions = [
            models.FieldCondition(key=key, match=models.MatchValue(value=value))
            for key, value in sorted(query.filters.items())
        ]
        response = await self._client.query_points(
            collection_name=query.collection,
            query=list(vector),
            query_filter=models.Filter(must=conditions) if conditions else None,
            limit=query.limit,
            with_payload=True,
            with_vectors=False,
        )
        return tuple(
            VectorHit(
                point_id=str(point.id),
                score=float(point.score),
                content=str((point.payload or {}).get("content", "")),
                metadata={
                    str(key): str(value)
                    for key, value in (point.payload or {}).items()
                    if key != "content"
                },
            )
            for point in response.points
        )

    async def delete(self, *, collection: str, point_ids: tuple[str, ...]) -> None:
        self._require_collection(collection)
        if not point_ids:
            return
        await self._client.delete(
            collection_name=collection,
            points_selector=models.PointIdsList(points=list(point_ids)),
            wait=True,
        )

    async def validate(self, *, collection: str, point_ids: tuple[str, ...]) -> bool:
        self._require_collection(collection)
        if not point_ids:
            return True
        points = await self._client.retrieve(
            collection_name=collection,
            ids=list(point_ids),
            with_payload=False,
            with_vectors=False,
        )
        return {str(point.id) for point in points} == set(point_ids)

    async def recreate_collections(self) -> None:
        for collection in INDEX_COLLECTIONS:
            if await self._client.collection_exists(collection):
                await self._client.delete_collection(collection_name=collection)
        await self.ensure_collections()

    async def collection_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for collection in INDEX_COLLECTIONS:
            if not await self._client.collection_exists(collection):
                counts[collection] = 0
                continue
            result = await self._client.count(collection_name=collection, exact=True)
            counts[collection] = int(result.count)
        return counts

    async def _validate_collection(self, collection: str) -> None:
        info = await self._client.get_collection(collection)
        vectors = info.config.params.vectors
        if isinstance(vectors, dict):
            raise ValueError("named vectors are not supported by index schema v1")
        if vectors.size != self._embeddings.config.dimensions:
            raise ValueError("Qdrant collection dimension mismatch")
        if vectors.distance != models.Distance.COSINE:
            raise ValueError("Qdrant collection distance mismatch")

    @staticmethod
    def _require_collection(collection: str) -> None:
        if collection not in INDEX_COLLECTIONS:
            raise ValueError("unknown index collection")
