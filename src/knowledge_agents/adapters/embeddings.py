from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class EmbeddingConfig:
    model: str = "text-embedding-3-small"
    dimensions: int = 1_536
    batch_size: int = 128

    def __post_init__(self) -> None:
        if self.dimensions <= 0:
            raise ValueError("dimensions must be positive")
        if self.batch_size <= 0:
            raise ValueError("batch_size must be positive")


@runtime_checkable
class EmbeddingProvider(Protocol):
    @property
    def config(self) -> EmbeddingConfig: ...

    async def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]: ...


class OpenAIEmbeddings:
    """Thin adapter over an injected OpenAI-compatible async client."""

    def __init__(self, client: Any, config: EmbeddingConfig | None = None) -> None:
        self._client = client
        self._config = config or EmbeddingConfig()

    @property
    def config(self) -> EmbeddingConfig:
        return self._config

    async def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        if not texts:
            return ()

        unique: dict[str, str] = {}
        keys: list[str] = []
        for text in texts:
            key = hashlib.sha256(text.encode("utf-8")).hexdigest()
            keys.append(key)
            unique.setdefault(key, text)

        vectors: dict[str, tuple[float, ...]] = {}
        unique_items = tuple(unique.items())
        for offset in range(0, len(unique_items), self._config.batch_size):
            batch = unique_items[offset : offset + self._config.batch_size]
            response = await self._client.embeddings.create(
                model=self._config.model,
                input=[text for _, text in batch],
                dimensions=self._config.dimensions,
                encoding_format="float",
            )
            ordered = sorted(response.data, key=lambda item: item.index)
            if len(ordered) != len(batch):
                raise ValueError("embedding response size mismatch")
            for (key, _), item in zip(batch, ordered, strict=True):
                vector = tuple(float(value) for value in item.embedding)
                if len(vector) != self._config.dimensions:
                    raise ValueError("embedding dimension mismatch")
                vectors[key] = vector
        return tuple(vectors[key] for key in keys)
