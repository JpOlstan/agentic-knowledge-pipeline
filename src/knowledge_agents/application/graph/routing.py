from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from knowledge_agents.domain.contracts import ReviewPackage
from knowledge_agents.domain.enums import DraftStatus, RunOutcome, TerminalRecommendation
from knowledge_agents.domain.hashing import canonical_sha256


class GraphRoute(StrEnum):
    REVISE = "revise"
    PERSIST = "persist"


@dataclass(frozen=True, slots=True)
class RouteDecision:
    route: GraphRoute
    outcome: RunOutcome | None
    issue_fingerprint: str | None
    revision_count: int


class ReviewPolicy:
    def __init__(self, *, max_revision_cycles: int = 2) -> None:
        if max_revision_cycles < 0:
            raise ValueError("max_revision_cycles must be non-negative")
        self.max_revision_cycles = max_revision_cycles

    def evaluate(
        self,
        *,
        review: ReviewPackage,
        revision_count: int,
        previous_issue_fingerprint: str | None,
    ) -> RouteDecision:
        if self._is_rejected(review):
            return self._terminal(RunOutcome.REJECTED, revision_count)
        if self._requires_missing_evidence(review):
            return self._terminal(RunOutcome.ENRICHMENT_REQUIRED, revision_count)
        if not review.blocked_note_ids:
            return self._terminal(RunOutcome.COMPLETED, revision_count)

        fingerprint = issue_fingerprint(review)
        if revision_count >= self.max_revision_cycles:
            return self._terminal(
                RunOutcome.ENRICHMENT_REQUIRED,
                revision_count,
                fingerprint,
            )
        if fingerprint == previous_issue_fingerprint:
            return self._terminal(
                RunOutcome.ENRICHMENT_REQUIRED,
                revision_count,
                fingerprint,
            )
        return RouteDecision(
            route=GraphRoute.REVISE,
            outcome=None,
            issue_fingerprint=fingerprint,
            revision_count=revision_count + 1,
        )

    @staticmethod
    def _terminal(
        outcome: RunOutcome,
        revision_count: int,
        fingerprint: str | None = None,
    ) -> RouteDecision:
        return RouteDecision(
            route=GraphRoute.PERSIST,
            outcome=outcome,
            issue_fingerprint=fingerprint,
            revision_count=revision_count,
        )

    @staticmethod
    def _is_rejected(review: ReviewPackage) -> bool:
        return review.terminal_recommendation is TerminalRecommendation.REJECTED or any(
            item.status is DraftStatus.REJECTED for item in review.reviews
        )

    @staticmethod
    def _requires_missing_evidence(review: ReviewPackage) -> bool:
        return review.terminal_recommendation is TerminalRecommendation.ENRICHMENT_REQUIRED or any(
            item.status is DraftStatus.ENRICHMENT_REQUIRED for item in review.reviews
        )


def issue_fingerprint(review: ReviewPackage) -> str:
    blocked = set(review.blocked_note_ids)
    issues = {
        item.note_id: {
            "issues": sorted(item.issues),
            "required_changes": sorted(item.required_changes),
        }
        for item in review.reviews
        if item.note_id in blocked
    }
    return canonical_sha256(
        {
            "blocked_note_ids": sorted(blocked),
            "issues": issues,
        }
    )
