from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from knowledge_agents.domain.contracts import ArtifactRef
from knowledge_agents.domain.errors import DomainError, ErrorCode
from knowledge_agents.domain.hashing import canonical_json, canonical_sha256
from knowledge_agents.ports.artifacts import ArtifactStore

SAFE_SEGMENT = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$")
SAFE_ARTIFACT_TYPE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class FilesystemArtifactStore(ArtifactStore):
    def __init__(self, root: Path) -> None:
        self.root = root

    async def write_json(
        self,
        *,
        run_id: str,
        artifact_type: str,
        payload: Any,
        schema_version: str,
    ) -> ArtifactRef:
        _validate_segment(run_id, SAFE_SEGMENT)
        _validate_segment(artifact_type, SAFE_ARTIFACT_TYPE)
        relative_path = PurePosixPath(run_id) / f"{artifact_type}.json"
        serialized = canonical_json(payload).encode("utf-8")
        content_hash = canonical_sha256(payload)
        artifact = ArtifactRef(
            artifact_id=f"{run_id}:{artifact_type}",
            artifact_type=artifact_type,
            relative_path=relative_path.as_posix(),
            content_hash=content_hash,
            schema_version=schema_version,
        )
        await asyncio.to_thread(self._write_atomic, artifact, serialized)
        return artifact

    async def read_json(self, artifact: ArtifactRef) -> Any:
        payload = await asyncio.to_thread(self._read_bytes, artifact)
        return json.loads(payload)

    async def exists(self, artifact: ArtifactRef) -> bool:
        try:
            target = self._safe_target(artifact.relative_path)
        except DomainError:
            return False
        return target.is_file() and not target.is_symlink()

    def _write_atomic(self, artifact: ArtifactRef, serialized: bytes) -> None:
        target = self._safe_target(artifact.relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target = self._safe_target(artifact.relative_path)
        if target.exists():
            if target.is_symlink():
                raise DomainError(ErrorCode.PATH_TRAVERSAL_BLOCKED, "artifact_store.write")
            existing = target.read_bytes()
            if canonical_sha256(json.loads(existing)) != artifact.content_hash:
                raise DomainError(ErrorCode.IDEMPOTENCY_CONFLICT, "artifact_store.write")
            return

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=f".{target.name}.",
                suffix=".tmp",
                dir=target.parent,
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, target)
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def _read_bytes(self, artifact: ArtifactRef) -> bytes:
        target = self._safe_target(artifact.relative_path)
        if not target.is_file() or target.is_symlink():
            raise FileNotFoundError(artifact.artifact_id)
        payload = target.read_bytes()
        if canonical_sha256(json.loads(payload)) != artifact.content_hash:
            raise DomainError(ErrorCode.CONTRACT_VALIDATION_FAILED, "artifact_store.read")
        return payload

    def _safe_target(self, relative_path: str) -> Path:
        normalized = relative_path.replace("\\", "/")
        relative = PurePosixPath(normalized)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or not relative.parts
            or ":" in relative.parts[0]
        ):
            raise DomainError(ErrorCode.PATH_TRAVERSAL_BLOCKED, "artifact_store.path")

        self.root.mkdir(parents=True, exist_ok=True)
        root = self.root.resolve()
        current = root
        for part in relative.parts[:-1]:
            current = current / part
            if current.exists() and current.is_symlink():
                raise DomainError(ErrorCode.PATH_TRAVERSAL_BLOCKED, "artifact_store.path")
        target = root.joinpath(*relative.parts)
        resolved = target.resolve(strict=False)
        if not resolved.is_relative_to(root):
            raise DomainError(ErrorCode.PATH_TRAVERSAL_BLOCKED, "artifact_store.path")
        return target


def _validate_segment(value: str, pattern: re.Pattern[str]) -> None:
    if pattern.fullmatch(value) is None:
        raise DomainError(ErrorCode.PATH_TRAVERSAL_BLOCKED, "artifact_store.path")
