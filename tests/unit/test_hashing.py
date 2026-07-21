from datetime import UTC, datetime

import pytest

from knowledge_agents.domain.contracts import DraftNote, SourceDescriptor
from knowledge_agents.domain.enums import AcquisitionMethod, CurationAction, SourceType
from knowledge_agents.domain.hashing import canonical_json, canonical_sha256, hash_draft


def test_hash_is_stable_under_mapping_key_order() -> None:
    left = {"outer": {"b": 2, "a": 1}, "items": [3, 2, 1]}
    right = {"items": [3, 2, 1], "outer": {"a": 1, "b": 2}}

    assert canonical_json(left) == canonical_json(right)
    assert canonical_sha256(left) == canonical_sha256(right)


def test_contract_hash_includes_schema_version() -> None:
    source = SourceDescriptor(
        source_id="source-1",
        source_type=SourceType.WEB_ARTICLE,
        acquisition_method=AcquisitionMethod.STATIC_HTML,
        canonical_ref="https://example.com/article",
        title="Example",
        publisher="Example Publisher",
        retrieved_at=datetime(2026, 7, 21, tzinfo=UTC),
        content_hash="a" * 64,
        created_at=datetime(2026, 7, 21, tzinfo=UTC),
    )

    assert '"schema_version":"1"' in canonical_json(source)


def test_draft_hash_excludes_existing_content_hash() -> None:
    draft = DraftNote(
        note_id="note-1",
        title="Atomic note",
        body_sections={"Summary": "Stable content"},
        source_claim_ids=("claim-1",),
        proposed_action=CurationAction.CREATE,
        content_hash="0" * 64,
    )
    changed_hash_field = draft.model_copy(update={"content_hash": "f" * 64})

    assert hash_draft(draft) == hash_draft(changed_hash_field)


def test_canonical_json_rejects_non_finite_numbers() -> None:
    with pytest.raises(ValueError):
        canonical_json({"invalid": float("nan")})
