from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from knowledge_agents.application.graph.nodes import GraphDependencies
from knowledge_agents.domain.budgets import CallUsage
from knowledge_agents.domain.contracts import (
    AcquisitionPacket,
    AcquisitionRequest,
    Claim,
    Concept,
    CoverageReport,
    CurationDecision,
    DraftNote,
    DraftPackage,
    EvidenceBatch,
    EvidenceItem,
    NoteReview,
    ReviewPackage,
    SourceDescriptor,
)
from knowledge_agents.domain.enums import (
    AcquisitionMethod,
    AgentRole,
    ClaimClassification,
    CurationAction,
    DraftStatus,
    SourceType,
    TerminalRecommendation,
)
from knowledge_agents.domain.hashing import canonical_sha256, hash_draft
from knowledge_agents.ports.llm import StructuredResult
from tests.fakes import (
    FakeArtifactStore,
    FakeKnowledgeSourceProvider,
    FakeRunStore,
    FakeStructuredLLM,
    FakeTelemetry,
    FakeVectorIndex,
)

RUN_ID = "run-0123456789abcdef"
IDEMPOTENCY_KEY = "idempotency-key-graph"
NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class GraphHarness:
    dependencies: GraphDependencies
    request: AcquisitionRequest
    llm: FakeStructuredLLM
    provider: FakeKnowledgeSourceProvider
    run_store: FakeRunStore
    artifacts: FakeArtifactStore
    vector_index: FakeVectorIndex
    telemetry: FakeTelemetry


def make_draft(note_id: str, version: int = 1) -> DraftNote:
    payload = {
        "note_id": note_id,
        "title": f"Title {note_id} v{version}",
        "body_sections": {"Summary": f"Body {note_id} v{version}"},
        "source_claim_ids": ("claim-1",),
        "proposed_action": CurationAction.CREATE,
    }
    return DraftNote(**payload, content_hash=hash_draft(payload))


def make_draft_package(*drafts: DraftNote) -> DraftPackage:
    decisions = tuple(
        CurationDecision(
            note_id=draft.note_id,
            action=CurationAction.CREATE,
            rationale="Create a governed note.",
        )
        for draft in drafts
    )
    package_payload = {
        "run_id": RUN_ID,
        "drafts": [draft.model_dump(mode="json") for draft in drafts],
        "curation_decisions": [item.model_dump(mode="json") for item in decisions],
        "retrieval_refs": [],
    }
    return DraftPackage(
        run_id=RUN_ID,
        drafts=drafts,
        curation_decisions=decisions,
        retrieval_refs=(),
        package_hash=canonical_sha256(package_payload),
        created_at=NOW,
    )


def make_review(
    drafts: tuple[DraftNote, ...],
    *,
    blocked: dict[str, tuple[DraftStatus, str]] | None = None,
) -> ReviewPackage:
    blocked = blocked or {}
    reviews = []
    approved = {}
    for draft in drafts:
        finding = blocked.get(draft.note_id)
        if finding is None:
            reviews.append(
                NoteReview(
                    note_id=draft.note_id,
                    reviewed_hash=draft.content_hash,
                    status=DraftStatus.READY,
                    issues=(),
                    required_changes=(),
                    promotion_eligible=True,
                )
            )
            approved[draft.note_id] = draft.content_hash
        else:
            status, issue = finding
            reviews.append(
                NoteReview(
                    note_id=draft.note_id,
                    reviewed_hash=draft.content_hash,
                    status=status,
                    issues=(issue,),
                    required_changes=(f"Resolve {issue}.",),
                    promotion_eligible=False,
                )
            )
    recommendation = TerminalRecommendation.READY
    if blocked:
        statuses = {status for status, _ in blocked.values()}
        if DraftStatus.REJECTED in statuses:
            recommendation = TerminalRecommendation.REJECTED
        elif DraftStatus.ENRICHMENT_REQUIRED in statuses:
            recommendation = TerminalRecommendation.ENRICHMENT_REQUIRED
        else:
            recommendation = TerminalRecommendation.PARTIALLY_READY
    return ReviewPackage(
        run_id=RUN_ID,
        reviews=tuple(reviews),
        blocked_note_ids=tuple(blocked),
        approved_note_hashes=approved,
        terminal_recommendation=recommendation,
        created_at=NOW,
    )


def make_harness(
    outputs: list[AcquisitionPacket | DraftPackage | ReviewPackage],
    *,
    vector_failures: dict[str, BaseException] | None = None,
    telemetry_failures: dict[str, BaseException] | None = None,
) -> GraphHarness:
    source = _source()
    evidence = _evidence(source)
    provider = FakeKnowledgeSourceProvider(source=source, evidence=evidence)
    results = [
        StructuredResult(
            output=output,
            usage=_usage(index, _role(output)),
            response_id=f"fake-response-{index}",
        )
        for index, output in enumerate(outputs, start=1)
    ]
    llm = FakeStructuredLLM(results)
    run_store = FakeRunStore()
    artifacts = FakeArtifactStore()
    vector_index = FakeVectorIndex(failures=vector_failures)
    telemetry = FakeTelemetry(failures=telemetry_failures)
    dependencies = GraphDependencies(
        provider=provider,
        llm=llm,
        run_store=run_store,
        artifacts=artifacts,
        vector_index=vector_index,
        telemetry=telemetry,
    )
    return GraphHarness(
        dependencies=dependencies,
        request=AcquisitionRequest(url="https://example.test/knowledge"),
        llm=llm,
        provider=provider,
        run_store=run_store,
        artifacts=artifacts,
        vector_index=vector_index,
        telemetry=telemetry,
    )


def acquisition_packet() -> AcquisitionPacket:
    source = _source()
    return AcquisitionPacket(
        run_id=RUN_ID,
        source=source,
        claims=(
            Claim(
                claim_id="claim-1",
                text="A durable claim.",
                classification=ClaimClassification.DURABLE,
                evidence_ids=("evidence-1",),
                supported=True,
            ),
        ),
        concepts=(
            Concept(
                concept_id="concept-1",
                name="Governed knowledge",
                summary="A governed concept.",
                classification=ClaimClassification.DURABLE,
                evidence_ids=("evidence-1",),
            ),
        ),
        evidence_map={"claim-1": ("evidence-1",)},
        coverage_report=CoverageReport(
            covered_topics=("governance",),
            completeness=1,
        ),
        created_at=NOW,
    )


def _source() -> SourceDescriptor:
    return SourceDescriptor(
        source_id="source-1",
        source_type=SourceType.WEB_ARTICLE,
        acquisition_method=AcquisitionMethod.STATIC_HTML,
        canonical_ref="https://example.test/knowledge",
        title="Governed knowledge",
        publisher="Example",
        retrieved_at=NOW,
        content_hash="a" * 64,
        created_at=NOW,
    )


def _evidence(source: SourceDescriptor) -> EvidenceBatch:
    return EvidenceBatch(
        source=source,
        evidence_items=(
            EvidenceItem(
                evidence_id="evidence-1",
                text="PRIVATE_EVIDENCE_BODY",
                locator="paragraph-1",
                content_hash="b" * 64,
            ),
        ),
        coverage=CoverageReport(
            covered_topics=("governance",),
            completeness=1,
        ),
        truncation=False,
        created_at=NOW,
    )


def _role(output: AcquisitionPacket | DraftPackage | ReviewPackage) -> AgentRole:
    if isinstance(output, AcquisitionPacket):
        return AgentRole.ACQUISITION
    if isinstance(output, DraftPackage):
        return AgentRole.CURATION
    return AgentRole.VALIDATION


def _usage(index: int, role: AgentRole) -> CallUsage:
    return CallUsage(
        call_id=f"call-{index}",
        agent=role,
        input_tokens=100,
        output_tokens=50,
        cost_usd=0.01,
        duration_seconds=0.1,
    )
