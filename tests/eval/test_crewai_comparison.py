from __future__ import annotations

import importlib.util
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pytest
from pydantic import ValidationError

from knowledge_agents.application.evaluation import (
    REQUIRED_EXT_ITEMS,
    ComparisonReport,
    EvaluationAuthorization,
    EvaluationPlan,
    ExternalReadiness,
    build_comparison_report,
    build_route_evaluation,
    evaluate_preflight,
    render_public_report,
    require_evaluation_ready,
)
from knowledge_agents.domain.budgets import ContextBudget
from knowledge_agents.domain.contracts import (
    AcquisitionPacket,
    Claim,
    Concept,
    CoverageReport,
    CurationDecision,
    DraftNote,
    DraftPackage,
    NoteReview,
    ReviewPackage,
    RunManifest,
    SourceDescriptor,
    UsageSummary,
)
from knowledge_agents.domain.enums import (
    AcquisitionMethod,
    ClaimClassification,
    CurationAction,
    DraftStatus,
    RunOutcome,
    SourceType,
    TerminalRecommendation,
)
from knowledge_agents.domain.errors import DomainError, ErrorCode

NOW = datetime(2026, 9, 2, tzinfo=UTC)
ROOT = Path(__file__).parents[2]
RENDER_SCRIPT = ROOT / "scripts" / "render_eval_report.py"
BASELINE = ROOT / "docs" / "evals" / "crewai-cognitive-memory-baseline.md"
VERSIONS = {
    "application": "0.1.0",
    "contracts": "1",
    "graph": "1",
    "prompt.agent_1": "v1",
    "prompt.agent_2": "v1",
    "prompt.agent_2_revision": "v1",
    "prompt.agent_3": "v1",
}
MODELS = {
    "agent_1": "gpt-5.6-terra",
    "agent_2": "gpt-5.6-terra",
    "agent_3": "gpt-5.6-terra",
}


def evaluation_plan() -> EvaluationPlan:
    return EvaluationPlan(
        case_id="crewai-cognitive-memory",
        git_commit="a" * 40,
        source_case_fingerprint="b" * 64,
        versions=VERSIONS,
        models=MODELS,
        index_snapshot="c" * 64,
        budget=ContextBudget(),
        cache_mode="disabled",
        created_at=NOW,
    )


def authorization(plan: EvaluationPlan, *, approved_cost: float = 20) -> EvaluationAuthorization:
    return EvaluationAuthorization(
        plan_hash=plan.plan_hash,
        authorization_ref="approval-2026-09-02",
        approved=True,
        approved_at=NOW,
        max_total_cost_usd=approved_cost,
    )


def ready_external_state() -> ExternalReadiness:
    return ExternalReadiness(
        completed_items=frozenset(REQUIRED_EXT_ITEMS),
        private_manifest_storage_ready=True,
    )


def route_result(
    plan: EvaluationPlan,
    route: SourceType,
    *,
    run_suffix: str,
    human_edits_required: int | None = None,
):
    run_id = f"run-{run_suffix}-0123456789abcdef"
    method = (
        AcquisitionMethod.NOTEBOOKLM_MCP
        if route is SourceType.NOTEBOOKLM
        else AcquisitionMethod.STATIC_HTML
    )
    source = SourceDescriptor(
        source_id=f"source-{run_suffix}",
        source_type=route,
        acquisition_method=method,
        canonical_ref="PRIVATE_SOURCE_REFERENCE",
        title="PRIVATE SOURCE TITLE",
        publisher="PRIVATE PUBLISHER",
        retrieved_at=NOW,
        content_hash="d" * 64,
        created_at=NOW,
    )
    acquisition = AcquisitionPacket(
        run_id=run_id,
        source=source,
        claims=(
            Claim(
                claim_id="claim-supported",
                text="PRIVATE SUPPORTED CLAIM",
                classification=ClaimClassification.DURABLE,
                evidence_ids=("evidence-1",),
                supported=True,
            ),
            Claim(
                claim_id="claim-unsupported",
                text="PRIVATE UNSUPPORTED CLAIM",
                classification=ClaimClassification.UNSUPPORTED,
                evidence_ids=(),
                supported=False,
            ),
        ),
        concepts=(
            Concept(
                concept_id="concept-1",
                name="PRIVATE CONCEPT",
                summary="PRIVATE CONCEPT SUMMARY",
                classification=ClaimClassification.DURABLE,
                evidence_ids=("evidence-1",),
            ),
        ),
        evidence_map={
            "claim-supported": ("evidence-1",),
            "claim-unsupported": (),
        },
        coverage_report=CoverageReport(
            covered_topics=("PRIVATE TOPIC",),
            completeness=0.5,
        ),
        created_at=NOW,
    )
    drafts = DraftPackage(
        run_id=run_id,
        drafts=(
            DraftNote(
                note_id="note-ready",
                title="PRIVATE DRAFT TITLE",
                body_sections={"Summary": "PRIVATE DRAFT BODY"},
                source_claim_ids=("claim-supported",),
                proposed_action=CurationAction.CREATE,
                content_hash="e" * 64,
            ),
            DraftNote(
                note_id="note-enrichment",
                title="PRIVATE SECOND DRAFT",
                body_sections={"Summary": "PRIVATE SECOND BODY"},
                source_claim_ids=("claim-unsupported",),
                proposed_action=CurationAction.MERGE,
                content_hash="f" * 64,
            ),
        ),
        curation_decisions=(
            CurationDecision(
                note_id="note-ready",
                action=CurationAction.CREATE,
                rationale="PRIVATE RATIONALE",
            ),
            CurationDecision(
                note_id="note-enrichment",
                action=CurationAction.MERGE,
                rationale="PRIVATE DUPLICATE RATIONALE",
                target_note_id="existing-note",
            ),
        ),
        retrieval_refs=(),
        package_hash="1" * 64,
        created_at=NOW,
    )
    reviews = ReviewPackage(
        run_id=run_id,
        reviews=(
            NoteReview(
                note_id="note-ready",
                reviewed_hash="e" * 64,
                status=DraftStatus.READY,
                issues=(),
                required_changes=(),
                promotion_eligible=True,
            ),
            NoteReview(
                note_id="note-enrichment",
                reviewed_hash="f" * 64,
                status=DraftStatus.ENRICHMENT_REQUIRED,
                issues=("PRIVATE ISSUE",),
                required_changes=("PRIVATE CHANGE",),
                promotion_eligible=False,
            ),
        ),
        blocked_note_ids=("note-enrichment",),
        approved_note_hashes={"note-ready": "e" * 64},
        terminal_recommendation=TerminalRecommendation.ENRICHMENT_REQUIRED,
        created_at=NOW,
    )
    manifest = RunManifest(
        run_id=run_id,
        versions={
            key: value for key, value in plan.versions.items() if key != "prompt.agent_2_revision"
        },
        models=plan.models,
        artifacts=(),
        transitions=(),
        usage=UsageSummary(
            call_count=3,
            input_tokens=900,
            output_tokens=300,
            cost_usd=0.03,
            duration_seconds=1.25,
        ),
        warnings=("PRIVATE WARNING",),
        outcome=RunOutcome.ENRICHMENT_REQUIRED,
        created_at=NOW,
    )
    return build_route_evaluation(
        route=route,
        plan=plan,
        acquisition=acquisition,
        drafts=drafts,
        reviews=reviews,
        manifest=manifest,
        retries=1,
        failure_codes=("provider_unavailable",),
        human_edits_required=human_edits_required,
        cache_used=False,
    )


def test_preflight_blocks_without_authorization_external_items_or_private_storage() -> None:
    plan = evaluation_plan()

    preflight = evaluate_preflight(
        plan,
        authorization=None,
        readiness=ExternalReadiness(),
    )

    assert not preflight.ready
    assert "explicit_authorization_missing" in preflight.blockers
    assert "external_item_pending:EXT-001" in preflight.blockers
    assert "external_item_pending:EXT-008" in preflight.blockers
    assert "private_manifest_storage_missing" in preflight.blockers
    with pytest.raises(DomainError) as captured:
        require_evaluation_ready(preflight)
    assert captured.value.code is ErrorCode.ACCESS_DENIED


def test_preflight_requires_matching_plan_and_two_route_budget() -> None:
    plan = evaluation_plan()
    wrong_plan = authorization(plan, approved_cost=1).model_copy(update={"plan_hash": "9" * 64})

    preflight = evaluate_preflight(
        plan,
        authorization=wrong_plan,
        readiness=ready_external_state(),
    )

    assert preflight.required_total_cost_usd == 20
    assert preflight.blockers == (
        "authorization_plan_mismatch",
        "authorized_budget_too_low",
    )


def test_preflight_accepts_explicit_matching_authorization() -> None:
    plan = evaluation_plan()

    preflight = evaluate_preflight(
        plan,
        authorization=authorization(plan),
        readiness=ready_external_state(),
    )

    assert preflight.ready
    assert preflight.blockers == ()
    assert require_evaluation_ready(preflight) is None


def test_plan_rejects_credential_shaped_public_labels() -> None:
    payload = evaluation_plan().model_dump(mode="json")
    payload["models"]["agent_1"] = "sk-" + "A" * 24

    with pytest.raises(ValidationError):
        EvaluationPlan.model_validate(payload)


def test_route_result_contains_only_aggregate_sanitized_metrics() -> None:
    plan = evaluation_plan()

    result = route_result(plan, SourceType.NOTEBOOKLM, run_suffix="notebooklm")
    serialized = result.model_dump_json()

    assert result.metrics.concepts_total == 1
    assert result.metrics.covered_topics == 1
    assert result.metrics.missing_topics == 0
    assert result.metrics.coverage_ratio == 0.5
    assert result.metrics.supported_claims == 1
    assert result.metrics.unsupported_claims == 1
    assert result.metrics.provenance_links == 1
    assert result.metrics.drafts_total == 2
    assert result.metrics.useful_drafts == 2
    assert result.metrics.duplicates_detected == 1
    assert result.metrics.blocked_drafts == 1
    assert len(result.acquisition_hash) == 64
    assert len(result.draft_package_hash) == 64
    assert len(result.review_package_hash) == 64
    assert "PRIVATE" not in serialized
    assert "run-notebooklm" not in serialized


def test_route_result_rejects_cache_or_usage_outside_the_pinned_plan() -> None:
    plan = evaluation_plan()
    valid = route_result(plan, SourceType.NOTEBOOKLM, run_suffix="notebooklm")
    manifest_payload = {
        "run_id": "run-budget-0123456789",
        "versions": plan.versions,
        "models": plan.models,
        "artifacts": (),
        "transitions": (),
        "usage": valid.usage.model_copy(update={"cost_usd": 11}),
        "warnings": (),
        "outcome": RunOutcome.COMPLETED,
        "created_at": NOW,
    }
    source_route = SourceType.WEB_ARTICLE
    with pytest.raises(DomainError) as captured:
        build_route_evaluation(
            route=source_route,
            plan=plan,
            acquisition=_minimal_acquisition(manifest_payload["run_id"], source_route),
            drafts=_minimal_drafts(manifest_payload["run_id"]),
            reviews=_minimal_reviews(manifest_payload["run_id"]),
            manifest=RunManifest.model_validate(manifest_payload),
        )
    assert captured.value.code is ErrorCode.BUDGET_EXCEEDED

    with pytest.raises(DomainError) as captured:
        _minimal_route(plan, cache_used=True)
    assert captured.value.code is ErrorCode.CONTRACT_VALIDATION_FAILED


def test_comparison_is_deterministic_side_by_side_and_has_no_automatic_score() -> None:
    plan = evaluation_plan()
    notebooklm = route_result(plan, SourceType.NOTEBOOKLM, run_suffix="notebooklm")
    web = route_result(
        plan,
        SourceType.WEB_ARTICLE,
        run_suffix="web",
        human_edits_required=2,
    )

    report = build_comparison_report(plan, (web, notebooklm))
    rendered = render_public_report(report)

    assert report.routes == (notebooklm, web)
    assert "automatic_score" not in ComparisonReport.model_fields
    assert rendered == render_public_report(report)
    assert "| Coverage ratio | 0.5 | 0.5 |" in rendered
    assert "| Supported claims | 1 | 1 |" in rendered
    assert "| Human edits required | pending | 2 |" in rendered
    assert "| Acquisition hash |" in rendered
    assert "| Draft package hash |" in rendered
    assert "| Review package hash |" in rendered
    assert "no automatic quality score" in rendered
    assert "PRIVATE" not in rendered
    assert "https://" not in rendered
    assert "run-notebooklm" not in rendered


def test_comparison_rejects_duplicate_route_or_unknown_public_fields() -> None:
    plan = evaluation_plan()
    notebooklm = route_result(plan, SourceType.NOTEBOOKLM, run_suffix="notebooklm")

    with pytest.raises(ValidationError):
        ComparisonReport.model_validate(
            {
                **build_comparison_report(
                    plan,
                    (
                        notebooklm,
                        route_result(plan, SourceType.WEB_ARTICLE, run_suffix="web"),
                    ),
                ).model_dump(mode="json"),
                "source_url": "PRIVATE_SOURCE_REFERENCE",
            }
        )
    with pytest.raises(ValidationError):
        ComparisonReport(
            case_id=plan.case_id,
            plan_hash=plan.plan_hash,
            git_commit=plan.git_commit,
            source_case_fingerprint=plan.source_case_fingerprint,
            versions=plan.versions,
            models=plan.models,
            index_snapshot=plan.index_snapshot,
            budget=plan.budget,
            cache_mode=plan.cache_mode,
            routes=(notebooklm, notebooklm),
            generated_at=NOW,
        )


def test_renderer_command_writes_only_the_sanitized_report(tmp_path: Path) -> None:
    plan = evaluation_plan()
    private_dir = tmp_path / "private"
    private_dir.mkdir()
    models = {
        "plan.json": plan,
        "authorization.json": authorization(plan),
        "external-readiness.json": ready_external_state(),
        "notebooklm-route.json": route_result(
            plan,
            SourceType.NOTEBOOKLM,
            run_suffix="notebooklm",
        ),
        "web-article-route.json": route_result(
            plan,
            SourceType.WEB_ARTICLE,
            run_suffix="web",
        ),
    }
    for name, model in models.items():
        private_dir.joinpath(name).write_text(model.model_dump_json(), encoding="utf-8")
    output = tmp_path / "public" / "baseline.md"

    result = load_renderer().main(("--private-dir", str(private_dir), "--output", str(output)))

    assert result == 0
    rendered = output.read_text(encoding="utf-8")
    assert rendered == render_public_report(
        build_comparison_report(
            plan,
            (
                models["notebooklm-route.json"],
                models["web-article-route.json"],
            ),
        )
    )
    assert "PRIVATE" not in rendered


def test_renderer_command_fails_closed_without_private_authorization(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    private_dir = tmp_path / "private"
    private_dir.mkdir()
    private_dir.joinpath("plan.json").write_text(
        evaluation_plan().model_dump_json(),
        encoding="utf-8",
    )
    output = tmp_path / "baseline.md"

    result = load_renderer().main(("--private-dir", str(private_dir), "--output", str(output)))

    assert result == 2
    assert not output.exists()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "evaluation report preflight failed\n"
    assert str(private_dir) not in captured.err


def test_public_baseline_is_an_unexecuted_placeholder_and_private_dir_is_ignored() -> None:
    baseline = BASELINE.read_text(encoding="utf-8")
    gitignore = ROOT.joinpath(".gitignore").read_text(encoding="utf-8")

    assert "awaiting controlled execution and human review" in baseline
    assert "No comparative result is recorded" in baseline
    assert "Placeholder text is not evaluation evidence" in baseline
    assert "https://" not in baseline
    assert ".local/evals/" in gitignore


@pytest.mark.eval
def test_controlled_crewai_comparison_is_explicit_and_uses_private_manifests() -> None:
    if os.getenv("KA_RUN_EVAL_CREWAI") != "1":
        pytest.skip("set KA_RUN_EVAL_CREWAI=1 for the explicitly authorized comparison")
    private_dir = os.getenv("KA_EVAL_PRIVATE_DIR")
    output = os.getenv("KA_EVAL_PUBLIC_REPORT")
    if not private_dir or not output:
        pytest.skip("controlled evaluation paths are incomplete")

    result = load_renderer().main(("--private-dir", private_dir, "--output", output))

    assert result == 0
    rendered = Path(output).read_text(encoding="utf-8")
    assert "Status: pending human review" in rendered
    assert "PRIVATE" not in rendered


def load_renderer() -> ModuleType:
    spec = importlib.util.spec_from_file_location("eval_renderer_under_test", RENDER_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _minimal_route(plan: EvaluationPlan, *, cache_used: bool):
    run_id = "run-minimal-0123456789"
    return build_route_evaluation(
        route=SourceType.WEB_ARTICLE,
        plan=plan,
        acquisition=_minimal_acquisition(run_id, SourceType.WEB_ARTICLE),
        drafts=_minimal_drafts(run_id),
        reviews=_minimal_reviews(run_id),
        manifest=RunManifest(
            run_id=run_id,
            versions=plan.versions,
            models=plan.models,
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
            created_at=NOW,
        ),
        cache_used=cache_used,
    )


def _minimal_acquisition(run_id: str, route: SourceType) -> AcquisitionPacket:
    method = (
        AcquisitionMethod.NOTEBOOKLM_MCP
        if route is SourceType.NOTEBOOKLM
        else AcquisitionMethod.STATIC_HTML
    )
    return AcquisitionPacket(
        run_id=run_id,
        source=SourceDescriptor(
            source_id="source-minimal",
            source_type=route,
            acquisition_method=method,
            canonical_ref="source-minimal",
            title="Minimal",
            publisher="Synthetic",
            retrieved_at=NOW,
            content_hash="2" * 64,
            created_at=NOW,
        ),
        claims=(),
        concepts=(),
        evidence_map={},
        coverage_report=CoverageReport(),
        created_at=NOW,
    )


def _minimal_drafts(run_id: str) -> DraftPackage:
    return DraftPackage(
        run_id=run_id,
        drafts=(),
        curation_decisions=(),
        retrieval_refs=(),
        package_hash="3" * 64,
        created_at=NOW,
    )


def _minimal_reviews(run_id: str) -> ReviewPackage:
    return ReviewPackage(
        run_id=run_id,
        reviews=(),
        blocked_note_ids=(),
        approved_note_hashes={},
        terminal_recommendation=TerminalRecommendation.READY,
        created_at=NOW,
    )
