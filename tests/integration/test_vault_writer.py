import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from knowledge_agents.adapters.vault_writer import VaultWriter
from knowledge_agents.domain.contracts import (
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
from knowledge_agents.domain.hashing import canonical_sha256, hash_draft

RUN_ID = "run-0123456789abcdef"
NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


def test_persist_renders_expected_tree_and_preserves_only_useful_drafts(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        vault = tmp_path / "vault"
        drafts = (
            _draft("note-ready"),
            _draft("note-partial"),
            _draft("note-enrichment"),
            _draft("note-rejected"),
            _draft("note-discarded", action=CurationAction.DISCARD),
        )
        package = _package(*drafts)
        review = _review(
            drafts,
            statuses={
                "note-ready": DraftStatus.READY,
                "note-partial": DraftStatus.PARTIALLY_READY,
                "note-enrichment": DraftStatus.ENRICHMENT_REQUIRED,
                "note-rejected": DraftStatus.REJECTED,
                "note-discarded": DraftStatus.READY,
            },
        )
        manifest = _manifest(RunOutcome.ENRICHMENT_REQUIRED)
        writer = VaultWriter(vault, allowed_inventory_paths=("knowledge",))

        result = await writer.persist(
            draft_package=package,
            review_package=review,
            manifest=manifest,
        )

        assert result.run_path == f"01-inbox/agent-runs/{RUN_ID}"
        assert result.draft_paths == (
            f"01-inbox/agent-runs/{RUN_ID}/drafts/note-enrichment.md",
            f"01-inbox/agent-runs/{RUN_ID}/drafts/note-partial.md",
            f"01-inbox/agent-runs/{RUN_ID}/drafts/note-ready.md",
        )
        assert result.skipped_note_ids == ("note-discarded", "note-rejected")
        relative_files = tuple(
            path.relative_to(vault).as_posix()
            for path in sorted(vault.rglob("*"))
            if path.is_file()
        )
        assert relative_files == (
            f"01-inbox/agent-runs/{RUN_ID}/drafts/note-enrichment.md",
            f"01-inbox/agent-runs/{RUN_ID}/drafts/note-partial.md",
            f"01-inbox/agent-runs/{RUN_ID}/drafts/note-ready.md",
            f"01-inbox/agent-runs/{RUN_ID}/manifest.json",
            f"01-inbox/agent-runs/{RUN_ID}/review-summary.md",
        )

        ready_content = (vault / result.draft_paths[2]).read_text(encoding="utf-8")
        assert ready_content == (
            "---\n"
            'schema_version: "1"\n'
            'note_id: "note-ready"\n'
            f'run_id: "{RUN_ID}"\n'
            'status: "ready"\n'
            f'content_hash: "{drafts[0].content_hash}"\n'
            'proposed_action: "create"\n'
            "promotion_eligible: true\n"
            'source_claim_ids: ["claim-1"]\n'
            "---\n\n"
            "# Title note-ready\n\n"
            "## Summary\n\n"
            "Body note-ready\n"
        )
        summary = (vault / result.review_summary_path).read_text(encoding="utf-8")
        assert "private issue detail" not in summary
        assert "Body note-ready" not in summary
        assert "`note-enrichment` | `enrichment_required`" in summary
        assert (vault / result.manifest_path).read_text(encoding="utf-8").endswith("\n")
        assert not hasattr(writer, "promote")
        assert not hasattr(writer, "delete")
        assert not hasattr(writer, "commit")

    asyncio.run(scenario())


def test_persist_is_idempotent_and_rejects_changed_content(tmp_path: Path) -> None:
    async def scenario() -> None:
        vault = tmp_path / "vault"
        draft = _draft("note-ready")
        package = _package(draft)
        review = _review((draft,), statuses={"note-ready": DraftStatus.READY})
        manifest = _manifest(RunOutcome.COMPLETED)
        writer = VaultWriter(vault, allowed_inventory_paths=("knowledge",))

        first = await writer.persist(
            draft_package=package,
            review_package=review,
            manifest=manifest,
        )
        paths = tuple(path for path in vault.rglob("*") if path.is_file())
        before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}
        second = await writer.persist(
            draft_package=package,
            review_package=review,
            manifest=manifest,
        )

        assert first == second
        assert before == {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}

        changed = _draft("note-ready", body="Changed body")
        with pytest.raises(DomainError) as exc_info:
            await writer.persist(
                draft_package=_package(changed),
                review_package=_review((changed,), statuses={"note-ready": DraftStatus.READY}),
                manifest=manifest,
            )
        assert exc_info.value.code is ErrorCode.IDEMPOTENCY_CONFLICT

    asyncio.run(scenario())


def test_existing_canonical_note_id_blocks_staging_write(tmp_path: Path) -> None:
    async def scenario() -> None:
        vault = tmp_path / "vault"
        canonical = vault / "knowledge" / "existing.md"
        canonical.parent.mkdir(parents=True)
        canonical.write_text(
            "---\nid: note-ready\n---\n# Canonical note\n",
            encoding="utf-8",
        )
        draft = _draft("note-ready")
        writer = VaultWriter(vault, allowed_inventory_paths=("knowledge",))

        with pytest.raises(DomainError) as exc_info:
            await writer.persist(
                draft_package=_package(draft),
                review_package=_review((draft,), statuses={"note-ready": DraftStatus.READY}),
                manifest=_manifest(RunOutcome.COMPLETED),
            )

        assert exc_info.value.code is ErrorCode.IDEMPOTENCY_CONFLICT
        assert exc_info.value.operation == "vault_writer.note_collision"
        assert not (vault / "01-inbox").exists()

    asyncio.run(scenario())


def test_failed_replace_leaves_no_partial_vault_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        vault = tmp_path / "vault"
        draft = _draft("note-ready")
        writer = VaultWriter(vault, allowed_inventory_paths=("knowledge",))

        def fail_replace(source: Path, target: Path) -> None:
            raise OSError("planned replace failure")

        monkeypatch.setattr(os, "replace", fail_replace)
        with pytest.raises(OSError, match="planned replace failure"):
            await writer.persist(
                draft_package=_package(draft),
                review_package=_review((draft,), statuses={"note-ready": DraftStatus.READY}),
                manifest=_manifest(RunOutcome.COMPLETED),
            )

        assert tuple(path for path in vault.rglob("*") if path.is_file()) == ()
        assert tuple(vault.rglob("*.tmp")) == ()

    asyncio.run(scenario())


def _draft(
    note_id: str,
    *,
    action: CurationAction = CurationAction.CREATE,
    body: str | None = None,
) -> DraftNote:
    payload = {
        "note_id": note_id,
        "title": f"Title {note_id}",
        "body_sections": {"Summary": body or f"Body {note_id}"},
        "source_claim_ids": ("claim-1",),
        "proposed_action": action,
    }
    return DraftNote(**payload, content_hash=hash_draft(payload))


def _package(*drafts: DraftNote) -> DraftPackage:
    decisions = tuple(
        CurationDecision(
            note_id=draft.note_id,
            action=draft.proposed_action,
            rationale="Deterministic fixture decision.",
        )
        for draft in drafts
    )
    payload = {
        "run_id": RUN_ID,
        "drafts": [draft.model_dump(mode="json") for draft in drafts],
        "curation_decisions": [decision.model_dump(mode="json") for decision in decisions],
        "retrieval_refs": [],
    }
    return DraftPackage(
        run_id=RUN_ID,
        drafts=drafts,
        curation_decisions=decisions,
        retrieval_refs=(),
        package_hash=canonical_sha256(payload),
        created_at=NOW,
    )


def _review(
    drafts: tuple[DraftNote, ...],
    *,
    statuses: dict[str, DraftStatus],
) -> ReviewPackage:
    reviews = []
    approved = {}
    blocked = []
    for draft in drafts:
        status = statuses[draft.note_id]
        eligible = status is DraftStatus.READY
        reviews.append(
            NoteReview(
                note_id=draft.note_id,
                reviewed_hash=draft.content_hash,
                status=status,
                issues=() if eligible else ("private issue detail",),
                required_changes=() if eligible else ("private required change",),
                promotion_eligible=eligible,
            )
        )
        if eligible:
            approved[draft.note_id] = draft.content_hash
        else:
            blocked.append(draft.note_id)
    recommendation = (
        TerminalRecommendation.ENRICHMENT_REQUIRED
        if DraftStatus.ENRICHMENT_REQUIRED in statuses.values()
        else TerminalRecommendation.READY
    )
    return ReviewPackage(
        run_id=RUN_ID,
        reviews=tuple(reviews),
        blocked_note_ids=tuple(blocked),
        approved_note_hashes=approved,
        terminal_recommendation=recommendation,
        created_at=NOW,
    )


def _manifest(outcome: RunOutcome) -> RunManifest:
    return RunManifest(
        run_id=RUN_ID,
        versions={"application": "0.1.0", "vault": "1"},
        models={},
        artifacts=(),
        transitions=(),
        usage=UsageSummary(
            call_count=3,
            input_tokens=300,
            output_tokens=150,
            cost_usd=0.03,
            duration_seconds=0.3,
        ),
        warnings=(),
        outcome=outcome,
        created_at=NOW,
    )
