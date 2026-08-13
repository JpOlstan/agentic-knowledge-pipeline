import asyncio
import os
from pathlib import Path

import pytest

from knowledge_agents.adapters.filesystem_artifacts import FilesystemArtifactStore
from knowledge_agents.adapters.vault_scanner import VaultScanner
from knowledge_agents.adapters.vault_writer import VaultWriter
from knowledge_agents.domain.contracts import (
    ArtifactRef,
    CurationDecision,
    DraftNote,
    DraftPackage,
    NoteReview,
    ReviewPackage,
    RunManifest,
    UsageSummary,
)
from knowledge_agents.domain.enums import (
    CurationAction,
    DraftStatus,
    RunOutcome,
    TerminalRecommendation,
)
from knowledge_agents.domain.errors import DomainError, ErrorCode
from knowledge_agents.domain.hashing import hash_draft


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


def test_vault_scanner_rejects_unsafe_allowlist_paths(tmp_path: Path) -> None:
    for unsafe in ("../private", "C:\\private", "/private"):
        with pytest.raises(DomainError) as exc_info:
            VaultScanner(tmp_path / "vault", allowed_paths=(unsafe,))
        assert exc_info.value.code is ErrorCode.PATH_TRAVERSAL_BLOCKED


def test_vault_scanner_reads_only_allowlisted_markdown(tmp_path: Path) -> None:
    async def scenario() -> None:
        vault = tmp_path / "vault"
        allowed = vault / "knowledge"
        private = vault / "private"
        allowed.mkdir(parents=True)
        private.mkdir()
        allowed.joinpath("safe.md").write_text(
            "---\nnote_id: safe-note\nstatus: ready\n---\n# Safe\n",
            encoding="utf-8",
        )
        private.joinpath("secret.md").write_text(
            "---\nnote_id: secret-note\n---\n# Secret\nPRIVATE_BODY\n",
            encoding="utf-8",
        )

        inventory = await VaultScanner(
            vault,
            allowed_paths=("knowledge",),
        ).scan()

        assert len(inventory.entries) == 1
        assert inventory.entries[0].note_id == "safe-note"
        assert inventory.entries[0].relative_path == "knowledge/safe.md"
        assert not hasattr(inventory.entries[0], "content")

    asyncio.run(scenario())


def test_vault_scanner_blocks_symlinked_inventory_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        vault = tmp_path / "vault"
        allowed = vault / "knowledge"
        allowed.mkdir(parents=True)
        original_is_symlink = Path.is_symlink

        def simulated_is_symlink(path: Path) -> bool:
            if path == allowed:
                return True
            return original_is_symlink(path)

        monkeypatch.setattr(Path, "is_symlink", simulated_is_symlink)
        with pytest.raises(DomainError) as exc_info:
            await VaultScanner(vault, allowed_paths=("knowledge",)).scan()
        assert exc_info.value.code is ErrorCode.PATH_TRAVERSAL_BLOCKED

    asyncio.run(scenario())


def test_vault_writer_rejects_note_id_that_is_not_a_safe_filename(tmp_path: Path) -> None:
    async def scenario() -> None:
        payload = {
            "note_id": "note:unsafe",
            "title": "Unsafe",
            "body_sections": {"Summary": "Body"},
            "source_claim_ids": ("claim-1",),
            "proposed_action": CurationAction.CREATE,
        }
        draft = DraftNote(**payload, content_hash=hash_draft(payload))
        package = DraftPackage(
            run_id="run-0123456789abcdef",
            drafts=(draft,),
            curation_decisions=(
                CurationDecision(
                    note_id=draft.note_id,
                    action=CurationAction.CREATE,
                    rationale="Fixture.",
                ),
            ),
            retrieval_refs=(),
            package_hash="a" * 64,
        )
        review = ReviewPackage(
            run_id=package.run_id,
            reviews=(
                NoteReview(
                    note_id=draft.note_id,
                    reviewed_hash=draft.content_hash,
                    status=DraftStatus.READY,
                    issues=(),
                    required_changes=(),
                    promotion_eligible=True,
                ),
            ),
            blocked_note_ids=(),
            approved_note_hashes={draft.note_id: draft.content_hash},
            terminal_recommendation=TerminalRecommendation.READY,
        )
        manifest = RunManifest(
            run_id=package.run_id,
            versions={"vault": "1"},
            models={},
            artifacts=(),
            transitions=(),
            usage=UsageSummary(
                call_count=0,
                input_tokens=0,
                output_tokens=0,
                cost_usd=0,
                duration_seconds=0,
            ),
            outcome=RunOutcome.COMPLETED,
        )

        with pytest.raises(DomainError) as exc_info:
            await VaultWriter(
                tmp_path / "vault",
                allowed_inventory_paths=("knowledge",),
            ).persist(
                draft_package=package,
                review_package=review,
                manifest=manifest,
            )
        assert exc_info.value.code is ErrorCode.PATH_TRAVERSAL_BLOCKED
        assert not (tmp_path / "vault" / "01-inbox").exists()

    asyncio.run(scenario())


def test_vault_writer_blocks_symlinked_staging_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        vault = tmp_path / "vault"
        staging = vault / "01-inbox"
        staging.mkdir(parents=True)
        original_is_symlink = Path.is_symlink

        def simulated_is_symlink(path: Path) -> bool:
            if path == staging:
                return True
            return original_is_symlink(path)

        monkeypatch.setattr(Path, "is_symlink", simulated_is_symlink)
        writer = VaultWriter(vault, allowed_inventory_paths=("knowledge",))

        with pytest.raises(DomainError) as exc_info:
            await writer.scanner.scan()
        assert exc_info.value.code is ErrorCode.PATH_TRAVERSAL_BLOCKED

    asyncio.run(scenario())
