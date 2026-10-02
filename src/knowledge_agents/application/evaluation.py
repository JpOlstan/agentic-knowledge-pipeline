from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import Annotated, ClassVar, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    StringConstraints,
    model_validator,
)

from knowledge_agents.domain.budgets import ContextBudget
from knowledge_agents.domain.contracts import (
    AcquisitionPacket,
    DraftPackage,
    ReviewPackage,
    RunManifest,
    Sha256,
    UsageSummary,
)
from knowledge_agents.domain.enums import CurationAction, DraftStatus, RunOutcome, SourceType
from knowledge_agents.domain.errors import DomainError, ErrorCode
from knowledge_agents.domain.hashing import canonical_sha256

SafeLabel = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    ),
]
CommitSha = Annotated[
    str,
    StringConstraints(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$"),
]
PositiveFiniteFloat = Annotated[float, Field(gt=0, allow_inf_nan=False)]
UnitInterval = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]

REQUIRED_EXT_ITEMS = tuple(f"EXT-{index:03d}" for index in range(1, 9))
REQUIRED_ROUTES = (SourceType.NOTEBOOKLM, SourceType.WEB_ARTICLE)
REQUIRED_VERSION_KEYS = frozenset(
    {
        "application",
        "contracts",
        "graph",
        "prompt.agent_1",
        "prompt.agent_2",
        "prompt.agent_2_revision",
        "prompt.agent_3",
    }
)
REQUIRED_RUN_VERSION_KEYS = REQUIRED_VERSION_KEYS - {"prompt.agent_2_revision"}
REQUIRED_MODEL_KEYS = frozenset({"agent_1", "agent_2", "agent_3"})
CREDENTIAL_LABEL = re.compile(
    r"(?i)^(?:"
    r"(?:AKIA|ASIA)[A-Z0-9]{16}|"
    r"sk-(?:(?:proj|lf)-)?[A-Za-z0-9_-]{20,}|"
    r"gh[pousr]_[A-Za-z0-9]{36,}|"
    r"github_pat_[A-Za-z0-9_]{40,}"
    r")$"
)


class EvaluationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema_version: ClassVar[str] = "1"
    case_id: SafeLabel
    git_commit: CommitSha
    source_case_fingerprint: Sha256
    versions: dict[SafeLabel, SafeLabel]
    models: dict[SafeLabel, SafeLabel]
    index_snapshot: Sha256
    budget: ContextBudget
    cache_mode: Literal["disabled", "reported"]
    created_at: AwareDatetime

    @model_validator(mode="after")
    def required_pins_are_present(self) -> EvaluationPlan:
        if not REQUIRED_VERSION_KEYS.issubset(self.versions):
            raise ValueError("evaluation plan must pin contracts, graph, application, and prompts")
        if not REQUIRED_MODEL_KEYS.issubset(self.models):
            raise ValueError("evaluation plan must pin all three agent models")
        _reject_credential_labels(
            (self.case_id, *self.versions.keys(), *self.versions.values(), *self.models.values())
        )
        return self

    @property
    def plan_hash(self) -> str:
        return canonical_sha256(self)


class EvaluationAuthorization(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    plan_hash: Sha256
    authorization_ref: SafeLabel
    approved: bool
    approved_at: AwareDatetime
    max_total_cost_usd: PositiveFiniteFloat


class ExternalReadiness(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    completed_items: frozenset[SafeLabel] = frozenset()
    private_manifest_storage_ready: bool = False


class EvaluationPreflight(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    plan_hash: Sha256
    ready: bool
    required_total_cost_usd: PositiveFiniteFloat
    blockers: tuple[SafeLabel, ...]


def evaluate_preflight(
    plan: EvaluationPlan,
    *,
    authorization: EvaluationAuthorization | None,
    readiness: ExternalReadiness,
) -> EvaluationPreflight:
    blockers: list[str] = []
    required_total_cost = plan.budget.max_cost_usd * len(REQUIRED_ROUTES)
    if authorization is None:
        blockers.append("explicit_authorization_missing")
    else:
        if not authorization.approved:
            blockers.append("explicit_authorization_missing")
        if authorization.plan_hash != plan.plan_hash:
            blockers.append("authorization_plan_mismatch")
        if authorization.max_total_cost_usd < required_total_cost:
            blockers.append("authorized_budget_too_low")
    for item in REQUIRED_EXT_ITEMS:
        if item not in readiness.completed_items:
            blockers.append(f"external_item_pending:{item}")
    if not readiness.private_manifest_storage_ready:
        blockers.append("private_manifest_storage_missing")
    normalized = tuple(sorted(set(blockers)))
    return EvaluationPreflight(
        plan_hash=plan.plan_hash,
        ready=not normalized,
        required_total_cost_usd=required_total_cost,
        blockers=normalized,
    )


def require_evaluation_ready(preflight: EvaluationPreflight) -> None:
    if not preflight.ready:
        raise DomainError(ErrorCode.ACCESS_DENIED, "evaluation.preflight")


class RouteMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    concepts_total: NonNegativeInt
    covered_topics: NonNegativeInt
    missing_topics: NonNegativeInt
    coverage_ratio: UnitInterval
    supported_claims: NonNegativeInt
    unsupported_claims: NonNegativeInt
    provenance_links: NonNegativeInt
    drafts_total: NonNegativeInt
    useful_drafts: NonNegativeInt
    duplicates_detected: NonNegativeInt
    actions_create: NonNegativeInt
    actions_merge: NonNegativeInt
    actions_defer: NonNegativeInt
    actions_discard: NonNegativeInt
    reviews_ready: NonNegativeInt
    reviews_partially_ready: NonNegativeInt
    reviews_enrichment_required: NonNegativeInt
    reviews_rejected: NonNegativeInt
    blocked_drafts: NonNegativeInt
    human_edits_required: NonNegativeInt | None = None


class RouteEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema_version: ClassVar[str] = "1"
    route: SourceType
    plan_hash: Sha256
    run_ref: Sha256
    source_case_fingerprint: Sha256
    acquisition_hash: Sha256
    draft_package_hash: Sha256
    review_package_hash: Sha256
    private_manifest_hash: Sha256
    metrics: RouteMetrics
    usage: UsageSummary
    retries: NonNegativeInt
    failure_codes: tuple[SafeLabel, ...] = ()
    cache_used: bool
    outcome: RunOutcome
    completed_at: AwareDatetime

    @model_validator(mode="after")
    def route_is_comparable(self) -> RouteEvaluation:
        if self.route not in REQUIRED_ROUTES:
            raise ValueError("unsupported evaluation route")
        if tuple(sorted(set(self.failure_codes))) != self.failure_codes:
            raise ValueError("failure codes must be unique and sorted")
        _reject_credential_labels(self.failure_codes)
        return self


def build_route_evaluation(
    *,
    route: SourceType,
    plan: EvaluationPlan,
    acquisition: AcquisitionPacket,
    drafts: DraftPackage,
    reviews: ReviewPackage,
    manifest: RunManifest,
    retries: int = 0,
    failure_codes: Iterable[str] = (),
    human_edits_required: int | None = None,
    cache_used: bool = False,
) -> RouteEvaluation:
    run_ids = {acquisition.run_id, drafts.run_id, reviews.run_id, manifest.run_id}
    if len(run_ids) != 1:
        raise DomainError(ErrorCode.CONTRACT_VALIDATION_FAILED, "evaluation.route_run_ids")
    draft_ids = {draft.note_id for draft in drafts.drafts}
    review_ids = {review.note_id for review in reviews.reviews}
    if draft_ids != review_ids:
        raise DomainError(ErrorCode.CONTRACT_VALIDATION_FAILED, "evaluation.route_reviews")
    manifest_versions_match = REQUIRED_RUN_VERSION_KEYS.issubset(manifest.versions) and all(
        plan.versions.get(key) == value for key, value in manifest.versions.items()
    )
    if not manifest_versions_match or manifest.models != plan.models:
        raise DomainError(ErrorCode.CONTRACT_VALIDATION_FAILED, "evaluation.route_pins")
    _require_usage_within_budget(manifest.usage, plan.budget)
    if plan.cache_mode == "disabled" and cache_used:
        raise DomainError(ErrorCode.CONTRACT_VALIDATION_FAILED, "evaluation.route_cache")

    actions = [decision.action for decision in drafts.curation_decisions]
    statuses = [review.status for review in reviews.reviews]
    supported_claims = sum(claim.supported for claim in acquisition.claims)
    provenance_links = sum(len(evidence_ids) for evidence_ids in acquisition.evidence_map.values())
    useful_statuses = {
        DraftStatus.READY,
        DraftStatus.PARTIALLY_READY,
        DraftStatus.ENRICHMENT_REQUIRED,
    }
    metrics = RouteMetrics(
        concepts_total=len(acquisition.concepts),
        covered_topics=len(acquisition.coverage_report.covered_topics),
        missing_topics=len(acquisition.coverage_report.missing_topics),
        coverage_ratio=acquisition.coverage_report.completeness,
        supported_claims=supported_claims,
        unsupported_claims=len(acquisition.claims) - supported_claims,
        provenance_links=provenance_links,
        drafts_total=len(drafts.drafts),
        useful_drafts=sum(status in useful_statuses for status in statuses),
        duplicates_detected=actions.count(CurationAction.MERGE),
        actions_create=actions.count(CurationAction.CREATE),
        actions_merge=actions.count(CurationAction.MERGE),
        actions_defer=actions.count(CurationAction.DEFER),
        actions_discard=actions.count(CurationAction.DISCARD),
        reviews_ready=statuses.count(DraftStatus.READY),
        reviews_partially_ready=statuses.count(DraftStatus.PARTIALLY_READY),
        reviews_enrichment_required=statuses.count(DraftStatus.ENRICHMENT_REQUIRED),
        reviews_rejected=statuses.count(DraftStatus.REJECTED),
        blocked_drafts=len(reviews.blocked_note_ids),
        human_edits_required=human_edits_required,
    )
    normalized_failures = tuple(sorted(set(failure_codes)))
    return RouteEvaluation(
        route=route,
        plan_hash=plan.plan_hash,
        run_ref=canonical_sha256({"run_id": manifest.run_id}),
        source_case_fingerprint=plan.source_case_fingerprint,
        acquisition_hash=canonical_sha256(acquisition),
        draft_package_hash=canonical_sha256(drafts),
        review_package_hash=canonical_sha256(reviews),
        private_manifest_hash=canonical_sha256(manifest),
        metrics=metrics,
        usage=manifest.usage,
        retries=retries,
        failure_codes=normalized_failures,
        cache_used=cache_used,
        outcome=manifest.outcome,
        completed_at=manifest.created_at,
    )


class ComparisonReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema_version: ClassVar[str] = "1"
    case_id: SafeLabel
    plan_hash: Sha256
    git_commit: CommitSha
    source_case_fingerprint: Sha256
    versions: dict[SafeLabel, SafeLabel]
    models: dict[SafeLabel, SafeLabel]
    index_snapshot: Sha256
    budget: ContextBudget
    cache_mode: Literal["disabled", "reported"]
    routes: tuple[RouteEvaluation, RouteEvaluation]
    generated_at: AwareDatetime
    human_conclusion_status: Literal["pending_human_review"] = "pending_human_review"

    @model_validator(mode="after")
    def contains_two_comparable_routes(self) -> ComparisonReport:
        if {route.route for route in self.routes} != set(REQUIRED_ROUTES):
            raise ValueError("comparison requires NotebookLM and web article routes")
        if len({route.run_ref for route in self.routes}) != len(REQUIRED_ROUTES):
            raise ValueError("comparison routes must come from separate runs")
        if any(route.plan_hash != self.plan_hash for route in self.routes):
            raise ValueError("comparison routes must use the same evaluation plan")
        if any(
            route.source_case_fingerprint != self.source_case_fingerprint for route in self.routes
        ):
            raise ValueError("comparison routes must use the same source case")
        return self


def build_comparison_report(
    plan: EvaluationPlan,
    routes: Sequence[RouteEvaluation],
) -> ComparisonReport:
    ordered = tuple(sorted(routes, key=lambda item: item.route.value))
    if len(ordered) != len(REQUIRED_ROUTES):
        raise ValueError("comparison requires exactly two routes")
    generated_at = max(route.completed_at for route in ordered)
    return ComparisonReport(
        case_id=plan.case_id,
        plan_hash=plan.plan_hash,
        git_commit=plan.git_commit,
        source_case_fingerprint=plan.source_case_fingerprint,
        versions=plan.versions,
        models=plan.models,
        index_snapshot=plan.index_snapshot,
        budget=plan.budget,
        cache_mode=plan.cache_mode,
        routes=ordered,
        generated_at=generated_at,
    )


def render_public_report(report: ComparisonReport) -> str:
    routes = {route.route: route for route in report.routes}
    notebooklm = routes[SourceType.NOTEBOOKLM]
    web = routes[SourceType.WEB_ARTICLE]
    model_pins = ", ".join(f"{key}={value}" for key, value in sorted(report.models.items()))
    version_pins = ", ".join(f"{key}={value}" for key, value in sorted(report.versions.items()))
    lines = [
        "# CrewAI Cognitive Memory Baseline",
        "",
        "Status: pending human review",
        "",
        "## Sanitized run metadata",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Case | `{report.case_id}` |",
        f"| Plan hash | `{report.plan_hash}` |",
        f"| Git commit | `{report.git_commit}` |",
        f"| Source case fingerprint | `{report.source_case_fingerprint}` |",
        f"| Index snapshot | `{report.index_snapshot}` |",
        f"| Cache mode | `{report.cache_mode}` |",
        f"| Generated at | `{report.generated_at.isoformat()}` |",
        f"| Versions | {version_pins} |",
        f"| Models | {model_pins} |",
        "",
        "## Operational budget per route",
        "",
        "| Calls | Input tokens | Output tokens | Cost USD | Duration seconds |",
        "|---:|---:|---:|---:|---:|",
        (
            f"| {report.budget.max_main_calls} | {report.budget.max_input_tokens_per_run} | "
            f"{report.budget.max_output_tokens_per_run} | "
            f"{report.budget.max_cost_usd:.6f} | "
            f"{report.budget.max_duration_seconds:.3f} |"
        ),
        "",
        "## Route comparison",
        "",
        "| Metric | NotebookLM | Web article |",
        "|---|---:|---:|",
        *_metric_rows(notebooklm, web),
        "",
        "## Provenance and failures",
        "",
        "| Field | NotebookLM | Web article |",
        "|---|---|---|",
        f"| Run reference | `{notebooklm.run_ref}` | `{web.run_ref}` |",
        (f"| Acquisition hash | `{notebooklm.acquisition_hash}` | `{web.acquisition_hash}` |"),
        (
            f"| Draft package hash | `{notebooklm.draft_package_hash}` | "
            f"`{web.draft_package_hash}` |"
        ),
        (
            f"| Review package hash | `{notebooklm.review_package_hash}` | "
            f"`{web.review_package_hash}` |"
        ),
        (
            f"| Private manifest hash | `{notebooklm.private_manifest_hash}` | "
            f"`{web.private_manifest_hash}` |"
        ),
        f"| Outcome | `{notebooklm.outcome.value}` | `{web.outcome.value}` |",
        (
            f"| Cache used | `{str(notebooklm.cache_used).lower()}` | "
            f"`{str(web.cache_used).lower()}` |"
        ),
        f"| Failure codes | {_failure_codes(notebooklm)} | {_failure_codes(web)} |",
        "",
        "## Human conclusion",
        "",
        "Pending human review. This baseline deliberately contains no automatic quality score, "
        "ranking, or pass threshold.",
        "",
        "Private URLs, source content, vault text, credentials, and raw prompts are excluded.",
    ]
    return "\n".join(lines).strip() + "\n"


def _metric_rows(first: RouteEvaluation, second: RouteEvaluation) -> list[str]:
    metrics = (
        ("Concepts identified", "concepts_total"),
        ("Covered topics", "covered_topics"),
        ("Missing topics", "missing_topics"),
        ("Coverage ratio", "coverage_ratio"),
        ("Supported claims", "supported_claims"),
        ("Unsupported claims", "unsupported_claims"),
        ("Provenance links", "provenance_links"),
        ("Drafts total", "drafts_total"),
        ("Useful drafts", "useful_drafts"),
        ("Duplicates detected", "duplicates_detected"),
        ("Create decisions", "actions_create"),
        ("Merge decisions", "actions_merge"),
        ("Defer decisions", "actions_defer"),
        ("Discard decisions", "actions_discard"),
        ("Ready reviews", "reviews_ready"),
        ("Partially ready reviews", "reviews_partially_ready"),
        ("Enrichment required", "reviews_enrichment_required"),
        ("Rejected reviews", "reviews_rejected"),
        ("Blocked drafts", "blocked_drafts"),
        ("Human edits required", "human_edits_required"),
    )
    rows = [
        f"| {label} | {_metric_value(first, field)} | {_metric_value(second, field)} |"
        for label, field in metrics
    ]
    usage = (
        ("LLM calls", "call_count"),
        ("Input tokens", "input_tokens"),
        ("Output tokens", "output_tokens"),
        ("Cost USD", "cost_usd"),
        ("Latency seconds", "duration_seconds"),
    )
    rows.extend(
        f"| {label} | {_usage_value(first, field)} | {_usage_value(second, field)} |"
        for label, field in usage
    )
    rows.append(f"| Retries | {first.retries} | {second.retries} |")
    return rows


def _metric_value(route: RouteEvaluation, field: str) -> str:
    value = getattr(route.metrics, field)
    return "pending" if value is None else str(value)


def _usage_value(route: RouteEvaluation, field: str) -> str:
    value = getattr(route.usage, field)
    if isinstance(value, float):
        return f"{value:.6f}" if field == "cost_usd" else f"{value:.3f}"
    return str(value)


def _failure_codes(route: RouteEvaluation) -> str:
    return ", ".join(f"`{code}`" for code in route.failure_codes) or "none"


def _require_usage_within_budget(usage: UsageSummary, budget: ContextBudget) -> None:
    exceeded = (
        usage.call_count > budget.max_main_calls
        or usage.input_tokens > budget.max_input_tokens_per_run
        or usage.output_tokens > budget.max_output_tokens_per_run
        or usage.cost_usd > budget.max_cost_usd
        or usage.duration_seconds > budget.max_duration_seconds
    )
    if exceeded:
        raise DomainError(ErrorCode.BUDGET_EXCEEDED, "evaluation.route_usage")


def _reject_credential_labels(values: Iterable[str]) -> None:
    if any(CREDENTIAL_LABEL.fullmatch(value) for value in values):
        raise ValueError("public evaluation labels cannot contain credential-shaped values")
