from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from knowledge_agents.adapters.vault_scanner import VaultInventory, VaultScanner
from knowledge_agents.domain.contracts import DraftNote, DraftPackage, ReviewPackage, RunManifest
from knowledge_agents.domain.enums import CurationAction, DraftStatus
from knowledge_agents.domain.errors import DomainError, ErrorCode
from knowledge_agents.domain.hashing import canonical_json, hash_draft

STAGING_ROOT = PurePosixPath("01-inbox/agent-runs")
SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
PRESERVED_STATUSES = {
    DraftStatus.READY,
    DraftStatus.PARTIALLY_READY,
    DraftStatus.ENRICHMENT_REQUIRED,
}


@dataclass(frozen=True, slots=True)
class VaultWriteResult:
    run_path: str
    draft_paths: tuple[str, ...]
    manifest_path: str
    review_summary_path: str
    skipped_note_ids: tuple[str, ...]


class DraftRenderer:
    def render(
        self,
        *,
        run_id: str,
        draft: DraftNote,
        status: DraftStatus,
        promotion_eligible: bool,
    ) -> str:
        if hash_draft(draft) != draft.content_hash:
            raise DomainError(ErrorCode.CONTRACT_VALIDATION_FAILED, "vault_renderer.hash")
        frontmatter = (
            "---\n"
            'schema_version: "1"\n'
            f"note_id: {json.dumps(draft.note_id, ensure_ascii=False)}\n"
            f"run_id: {json.dumps(run_id, ensure_ascii=False)}\n"
            f"status: {json.dumps(status.value)}\n"
            f"content_hash: {json.dumps(draft.content_hash)}\n"
            f"proposed_action: {json.dumps(draft.proposed_action.value)}\n"
            f"promotion_eligible: {'true' if promotion_eligible else 'false'}\n"
            "source_claim_ids: "
            f"{json.dumps(list(draft.source_claim_ids), ensure_ascii=False)}\n"
            "---\n"
        )
        sections = "\n\n".join(
            f"## {_single_line(heading)}\n\n{body.rstrip()}"
            for heading, body in draft.body_sections.items()
        )
        return f"{frontmatter}\n# {_single_line(draft.title)}\n\n{sections}\n"


class VaultWriter:
    def __init__(
        self,
        vault_root: Path,
        *,
        allowed_inventory_paths: tuple[str, ...],
        renderer: DraftRenderer | None = None,
    ) -> None:
        self.vault_root = vault_root
        inventory_paths = tuple(dict.fromkeys((*allowed_inventory_paths, STAGING_ROOT.as_posix())))
        self.scanner = VaultScanner(vault_root, allowed_paths=inventory_paths)
        self.renderer = renderer or DraftRenderer()

    async def persist(
        self,
        *,
        draft_package: DraftPackage,
        review_package: ReviewPackage,
        manifest: RunManifest,
    ) -> VaultWriteResult:
        return await asyncio.to_thread(
            self._persist,
            draft_package,
            review_package,
            manifest,
        )

    def _persist(
        self,
        draft_package: DraftPackage,
        review_package: ReviewPackage,
        manifest: RunManifest,
    ) -> VaultWriteResult:
        run_id = draft_package.run_id
        if review_package.run_id != run_id or manifest.run_id != run_id:
            raise DomainError(ErrorCode.CONTRACT_VALIDATION_FAILED, "vault_writer.run_id")
        _validate_segment(run_id, "vault_writer.run_id")

        inventory = self.scanner._scan()
        reviews = {review.note_id: review for review in review_package.reviews}
        documents: dict[str, bytes] = {}
        persisted_note_ids: list[str] = []
        skipped_note_ids: list[str] = []
        run_root = STAGING_ROOT / run_id

        for draft in sorted(draft_package.drafts, key=lambda item: item.note_id):
            _validate_segment(draft.note_id, "vault_writer.note_id")
            review = reviews.get(draft.note_id)
            if review is not None and review.reviewed_hash != draft.content_hash:
                raise DomainError(
                    ErrorCode.CONTRACT_VALIDATION_FAILED,
                    "vault_writer.reviewed_hash",
                )
            if (
                review is None
                or review.status not in PRESERVED_STATUSES
                or draft.proposed_action is CurationAction.DISCARD
            ):
                skipped_note_ids.append(draft.note_id)
                continue
            target = run_root / "drafts" / f"{draft.note_id}.md"
            self._ensure_note_id_available(inventory, draft.note_id, target)
            documents[target.as_posix()] = self.renderer.render(
                run_id=run_id,
                draft=draft,
                status=review.status,
                promotion_eligible=review.promotion_eligible,
            ).encode("utf-8")
            persisted_note_ids.append(draft.note_id)

        review_summary_path = (run_root / "review-summary.md").as_posix()
        manifest_path = (run_root / "manifest.json").as_posix()
        documents[review_summary_path] = _review_summary(
            run_id=run_id,
            review=review_package,
            persisted_note_ids=tuple(persisted_note_ids),
            skipped_note_ids=tuple(skipped_note_ids),
        ).encode("utf-8")
        documents[manifest_path] = f"{canonical_json(manifest)}\n".encode()

        targets = {relative_path: self._safe_target(relative_path) for relative_path in documents}
        for relative_path, target in targets.items():
            self._preflight_target(target, documents[relative_path])
        for relative_path in sorted(documents):
            self._write_atomic(relative_path, documents[relative_path])

        return VaultWriteResult(
            run_path=run_root.as_posix(),
            draft_paths=tuple(
                (run_root / "drafts" / f"{note_id}.md").as_posix() for note_id in persisted_note_ids
            ),
            manifest_path=manifest_path,
            review_summary_path=review_summary_path,
            skipped_note_ids=tuple(skipped_note_ids),
        )

    @staticmethod
    def _ensure_note_id_available(
        inventory: VaultInventory,
        note_id: str,
        target: PurePosixPath,
    ) -> None:
        collisions = inventory.entries_for_note(note_id)
        if any(entry.relative_path != target.as_posix() for entry in collisions):
            raise DomainError(ErrorCode.IDEMPOTENCY_CONFLICT, "vault_writer.note_collision")

    def _safe_target(self, relative_path: str) -> Path:
        relative = PurePosixPath(relative_path)
        if not relative.is_relative_to(STAGING_ROOT):
            raise DomainError(ErrorCode.ACCESS_DENIED, "vault_writer.path")
        root = self.vault_root.resolve()
        current = root
        for part in relative.parts:
            current = current / part
            if current.exists() and current.is_symlink():
                raise DomainError(ErrorCode.PATH_TRAVERSAL_BLOCKED, "vault_writer.path")
        resolved = current.resolve(strict=False)
        if not resolved.is_relative_to(root):
            raise DomainError(ErrorCode.PATH_TRAVERSAL_BLOCKED, "vault_writer.path")
        return current

    @staticmethod
    def _preflight_target(target: Path, content: bytes) -> None:
        if not target.exists():
            return
        if target.is_symlink() or not target.is_file():
            raise DomainError(ErrorCode.PATH_TRAVERSAL_BLOCKED, "vault_writer.write")
        if target.read_bytes() != content:
            raise DomainError(ErrorCode.IDEMPOTENCY_CONFLICT, "vault_writer.write")

    def _write_atomic(self, relative_path: str, content: bytes) -> None:
        target = self._safe_target(relative_path)
        if target.exists():
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        target = self._safe_target(relative_path)
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
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, target)
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)


def _validate_segment(value: str, operation: str) -> None:
    if SAFE_SEGMENT.fullmatch(value) is None:
        raise DomainError(ErrorCode.PATH_TRAVERSAL_BLOCKED, operation)


def _single_line(value: str) -> str:
    return " ".join(value.split())


def _review_summary(
    *,
    run_id: str,
    review: ReviewPackage,
    persisted_note_ids: tuple[str, ...],
    skipped_note_ids: tuple[str, ...],
) -> str:
    reviews = {item.note_id: item for item in review.reviews}
    rows = [
        "| Note ID | Status | Promotion eligible |",
        "|---|---|---|",
    ]
    for note_id in persisted_note_ids:
        item = reviews[note_id]
        rows.append(
            f"| `{note_id}` | `{item.status.value}` | "
            f"`{'yes' if item.promotion_eligible else 'no'}` |"
        )
    skipped = ", ".join(f"`{note_id}`" for note_id in skipped_note_ids) or "none"
    rows_text = "\n".join(rows)
    return (
        "# Review summary\n\n"
        f"- Run ID: `{run_id}`\n"
        f"- Recommendation: `{review.terminal_recommendation.value}`\n"
        f"- Persisted drafts: `{len(persisted_note_ids)}`\n"
        f"- Skipped note IDs: {skipped}\n\n"
        "## Persisted drafts\n\n"
        f"{rows_text}\n"
    )
