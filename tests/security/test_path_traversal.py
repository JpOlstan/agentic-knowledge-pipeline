import asyncio
import os
from pathlib import Path

import pytest

from knowledge_agents.adapters.filesystem_artifacts import FilesystemArtifactStore
from knowledge_agents.domain.contracts import ArtifactRef
from knowledge_agents.domain.errors import DomainError, ErrorCode


def test_write_rejects_unsafe_run_and_artifact_segments(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = FilesystemArtifactStore(tmp_path / "artifacts")
        for run_id, artifact_type in (
            ("../escape", "request"),
            ("C:\\escape", "request"),
            ("run-0123456789abcdef", "../request"),
        ):
            with pytest.raises(DomainError) as exc_info:
                await store.write_json(
                    run_id=run_id,
                    artifact_type=artifact_type,
                    payload={"safe": True},
                    schema_version="1",
                )
            assert exc_info.value.code is ErrorCode.PATH_TRAVERSAL_BLOCKED

    asyncio.run(scenario())


def test_read_revalidates_untrusted_artifact_paths(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = FilesystemArtifactStore(tmp_path / "artifacts")
        unsafe = ArtifactRef.model_construct(
            artifact_id="unsafe",
            artifact_type="request",
            relative_path="../../outside.json",
            content_hash="a" * 64,
            schema_version="1",
        )

        with pytest.raises(DomainError) as exc_info:
            await store.read_json(unsafe)
        assert exc_info.value.code is ErrorCode.PATH_TRAVERSAL_BLOCKED
        assert not await store.exists(unsafe)

    asyncio.run(scenario())


def test_symlink_escape_is_blocked_deterministically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        root = tmp_path / "artifacts"
        root.mkdir()
        link = root / "run-0123456789abcdef"
        link.mkdir()
        original_is_symlink = Path.is_symlink

        def simulated_is_symlink(path: Path) -> bool:
            if path == link:
                return True
            return original_is_symlink(path)

        monkeypatch.setattr(Path, "is_symlink", simulated_is_symlink)

        store = FilesystemArtifactStore(root)
        with pytest.raises(DomainError) as exc_info:
            await store.write_json(
                run_id="run-0123456789abcdef",
                artifact_type="request",
                payload={"safe": True},
                schema_version="1",
            )
        assert exc_info.value.code is ErrorCode.PATH_TRAVERSAL_BLOCKED
        assert list(link.iterdir()) == []

    asyncio.run(scenario())


def test_failed_atomic_replace_leaves_no_partial_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        store = FilesystemArtifactStore(tmp_path / "artifacts")

        def fail_replace(source: Path, target: Path) -> None:
            raise OSError("planned replace failure")

        monkeypatch.setattr(os, "replace", fail_replace)
        with pytest.raises(OSError, match="planned replace failure"):
            await store.write_json(
                run_id="run-0123456789abcdef",
                artifact_type="request",
                payload={"safe": True},
                schema_version="1",
            )

        run_path = tmp_path / "artifacts" / "run-0123456789abcdef"
        assert list(run_path.iterdir()) == []

    asyncio.run(scenario())


def test_existing_artifact_with_different_content_is_rejected(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = FilesystemArtifactStore(tmp_path / "artifacts")
        await store.write_json(
            run_id="run-0123456789abcdef",
            artifact_type="request",
            payload={"value": 1},
            schema_version="1",
        )

        with pytest.raises(DomainError) as exc_info:
            await store.write_json(
                run_id="run-0123456789abcdef",
                artifact_type="request",
                payload={"value": 2},
                schema_version="1",
            )
        assert exc_info.value.code is ErrorCode.IDEMPOTENCY_CONFLICT

    asyncio.run(scenario())
