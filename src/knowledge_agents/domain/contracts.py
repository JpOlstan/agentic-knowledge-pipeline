from __future__ import annotations

from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Annotated, Any, ClassVar

from pydantic import (
    AnyHttpUrl,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeFloat,
    NonNegativeInt,
    StringConstraints,
    field_validator,
    model_validator,
)

from knowledge_agents.domain.budgets import ContextBudget
from knowledge_agents.domain.enums import (
    AcquisitionMethod,
    ClaimClassification,
    CurationAction,
    DraftStatus,
    IndexStatus,
    RepairTarget,
    RunOutcome,
    SourceType,
    TerminalRecommendation,
)

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Identifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9._:-]+$"
    ),
]
RunId = Annotated[str, StringConstraints(min_length=20, max_length=80)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema_version: ClassVar[str] = "1"
    created_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))


class AcquisitionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    url: AnyHttpUrl
    run_id: RunId | None = None
    idempotency_key: Annotated[str, StringConstraints(min_length=16, max_length=128)] | None = None


class ArtifactRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_id: Identifier
    artifact_type: NonEmptyStr
    relative_path: NonEmptyStr
    content_hash: Sha256
    schema_version: NonEmptyStr

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        normalized = value.replace("\\", "/")
        path = PurePosixPath(normalized)
        if path.is_absolute() or ".." in path.parts or (path.parts and ":" in path.parts[0]):
            raise ValueError("artifact path must be relative and contained")
        return path.as_posix()


class SourceDescriptor(ContractModel):
    source_id: Identifier
    source_type: SourceType
    acquisition_method: AcquisitionMethod
    canonical_ref: NonEmptyStr
    title: NonEmptyStr
    publisher: NonEmptyStr
    retrieved_at: AwareDatetime
    content_hash: Sha256


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: Identifier
    text: NonEmptyStr
    locator: NonEmptyStr
    content_hash: Sha256


class CoverageReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    covered_topics: tuple[NonEmptyStr, ...] = ()
    missing_topics: tuple[NonEmptyStr, ...] = ()
    completeness: Annotated[float, Field(ge=0, le=1)] = 0


class EvidenceBatch(ContractModel):
    source: SourceDescriptor
    evidence_items: tuple[EvidenceItem, ...]
    coverage: CoverageReport
    truncation: bool
    artifact_refs: tuple[ArtifactRef, ...] = ()

    @model_validator(mode="after")
    def evidence_ids_are_unique(self) -> EvidenceBatch:
        identifiers = [item.evidence_id for item in self.evidence_items]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("evidence IDs must be unique")
        return self


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_id: Identifier
    text: NonEmptyStr
    classification: ClaimClassification
    evidence_ids: tuple[Identifier, ...]
    supported: bool


class Concept(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    concept_id: Identifier
    name: NonEmptyStr
    summary: NonEmptyStr
    classification: ClaimClassification
    evidence_ids: tuple[Identifier, ...]


class AcquisitionPacket(ContractModel):
    run_id: RunId
    source: SourceDescriptor
    claims: tuple[Claim, ...]
    concepts: tuple[Concept, ...]
    evidence_map: dict[Identifier, tuple[Identifier, ...]]
    coverage_report: CoverageReport
    warnings: tuple[NonEmptyStr, ...] = ()

    @model_validator(mode="after")
    def evidence_map_covers_claims(self) -> AcquisitionPacket:
        claim_ids = {claim.claim_id for claim in self.claims}
        unknown = set(self.evidence_map) - claim_ids
        if unknown:
            raise ValueError("evidence map contains unknown claim IDs")
        return self


class DraftNote(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    note_id: Identifier
    title: NonEmptyStr
    body_sections: dict[NonEmptyStr, NonEmptyStr] = Field(min_length=1)
    source_claim_ids: tuple[Identifier, ...]
    proposed_action: CurationAction
    content_hash: Sha256


class CurationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    note_id: Identifier
    action: CurationAction
    rationale: NonEmptyStr
    target_note_id: Identifier | None = None

    @model_validator(mode="after")
    def merge_requires_target(self) -> CurationDecision:
        if self.action is CurationAction.MERGE and self.target_note_id is None:
            raise ValueError("merge decisions require a target note")
        return self


class RetrievalRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    collection: NonEmptyStr
    point_id: Identifier
    score: float
    content_hash: Sha256


class DraftPackage(ContractModel):
    run_id: RunId
    drafts: tuple[DraftNote, ...]
    curation_decisions: tuple[CurationDecision, ...]
    retrieval_refs: tuple[RetrievalRef, ...]
    package_hash: Sha256

    @model_validator(mode="after")
    def draft_ids_are_unique(self) -> DraftPackage:
        identifiers = [draft.note_id for draft in self.drafts]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("draft note IDs must be unique")
        return self


class NoteReview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    note_id: Identifier
    reviewed_hash: Sha256
    status: DraftStatus
    issues: tuple[NonEmptyStr, ...]
    required_changes: tuple[NonEmptyStr, ...]
    promotion_eligible: bool


class ReviewPackage(ContractModel):
    run_id: RunId
    reviews: tuple[NoteReview, ...]
    blocked_note_ids: tuple[Identifier, ...]
    approved_note_hashes: dict[Identifier, Sha256]
    terminal_recommendation: TerminalRecommendation

    @model_validator(mode="after")
    def review_references_are_consistent(self) -> ReviewPackage:
        reviews = {review.note_id: review for review in self.reviews}
        if not set(self.blocked_note_ids).issubset(reviews):
            raise ValueError("blocked note IDs must reference reviews")
        for note_id, approved_hash in self.approved_note_hashes.items():
            review = reviews.get(note_id)
            if review is None or review.reviewed_hash != approved_hash:
                raise ValueError("approved note hashes must reference the reviewed hash")
            if not review.promotion_eligible:
                raise ValueError("approved note hashes must be promotion eligible")
        return self


class UsageSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    call_count: NonNegativeInt
    input_tokens: NonNegativeInt
    output_tokens: NonNegativeInt
    cost_usd: NonNegativeFloat
    duration_seconds: NonNegativeFloat


class TransitionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    from_stage: NonEmptyStr
    to_stage: NonEmptyStr
    occurred_at: AwareDatetime


class RunManifest(ContractModel):
    run_id: RunId
    versions: dict[NonEmptyStr, NonEmptyStr]
    models: dict[NonEmptyStr, NonEmptyStr]
    artifacts: tuple[ArtifactRef, ...]
    transitions: tuple[TransitionRecord, ...]
    usage: UsageSummary
    warnings: tuple[NonEmptyStr, ...] = ()
    outcome: RunOutcome


class ContextRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_ref: ArtifactRef
    content_hash: Sha256


class RevisionRequest(ContractModel):
    run_id: RunId
    blocked_note_ids: tuple[Identifier, ...]
    issues: dict[Identifier, tuple[NonEmptyStr, ...]]
    draft_hashes: dict[Identifier, Sha256]
    remaining_budget: dict[NonEmptyStr, int | float]


class IndexRecord(ContractModel):
    path: NonEmptyStr
    note_id: Identifier
    content_hash: Sha256
    index_fingerprint: Sha256
    collection: NonEmptyStr
    point_ids: tuple[Identifier, ...]
    status: IndexStatus
    indexed_at: AwareDatetime

    @field_validator("path")
    @classmethod
    def validate_index_path(cls, value: str) -> str:
        normalized = value.replace("\\", "/")
        path = PurePosixPath(normalized)
        if path.is_absolute() or ".." in path.parts or (path.parts and ":" in path.parts[0]):
            raise ValueError("index path must be relative and contained")
        return path.as_posix()


class RepairTask(ContractModel):
    repair_id: Identifier
    run_id: RunId
    target: RepairTarget
    attempts: NonNegativeInt
    next_attempt_at: AwareDatetime
    last_error: NonEmptyStr | None = None


CONTRACT_TYPES: tuple[type[BaseModel], ...] = (
    AcquisitionRequest,
    SourceDescriptor,
    EvidenceBatch,
    AcquisitionPacket,
    DraftPackage,
    ReviewPackage,
    RunManifest,
    ContextBudget,
    RevisionRequest,
    IndexRecord,
    RepairTask,
)


def contract_version_matrix() -> dict[str, str]:
    return {
        contract.__name__: getattr(contract, "schema_version", "external")
        for contract in CONTRACT_TYPES
    }


def json_schema_catalog() -> dict[str, dict[str, Any]]:
    return {contract.__name__: contract.model_json_schema() for contract in CONTRACT_TYPES}
