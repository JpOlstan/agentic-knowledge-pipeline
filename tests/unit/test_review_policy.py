from tests.graph_scenarios import make_draft, make_review

from knowledge_agents.application.graph.routing import GraphRoute, ReviewPolicy, issue_fingerprint
from knowledge_agents.domain.enums import DraftStatus, RunOutcome


def test_ready_review_routes_to_persistence() -> None:
    review = make_review((make_draft("note-a"),))

    decision = ReviewPolicy().evaluate(
        review=review,
        revision_count=0,
        previous_issue_fingerprint=None,
    )

    assert decision.route is GraphRoute.PERSIST
    assert decision.outcome is RunOutcome.COMPLETED
    assert decision.revision_count == 0


def test_actionable_finding_routes_only_to_revision() -> None:
    review = make_review(
        (make_draft("note-a"),),
        blocked={"note-a": (DraftStatus.PARTIALLY_READY, "missing link")},
    )

    decision = ReviewPolicy().evaluate(
        review=review,
        revision_count=0,
        previous_issue_fingerprint=None,
    )

    assert decision.route is GraphRoute.REVISE
    assert decision.outcome is None
    assert decision.revision_count == 1


def test_missing_evidence_never_loops_back_to_acquisition() -> None:
    review = make_review(
        (make_draft("note-a"),),
        blocked={"note-a": (DraftStatus.ENRICHMENT_REQUIRED, "missing evidence")},
    )

    decision = ReviewPolicy().evaluate(
        review=review,
        revision_count=0,
        previous_issue_fingerprint=None,
    )

    assert decision.route is GraphRoute.PERSIST
    assert decision.outcome is RunOutcome.ENRICHMENT_REQUIRED
    assert decision.revision_count == 0


def test_repeated_finding_and_cycle_limit_end_in_enrichment() -> None:
    review = make_review(
        (make_draft("note-a"),),
        blocked={"note-a": (DraftStatus.PARTIALLY_READY, "same issue")},
    )
    fingerprint = issue_fingerprint(review)

    repeated = ReviewPolicy().evaluate(
        review=review,
        revision_count=1,
        previous_issue_fingerprint=fingerprint,
    )
    exhausted = ReviewPolicy().evaluate(
        review=review,
        revision_count=2,
        previous_issue_fingerprint=None,
    )

    assert repeated.outcome is RunOutcome.ENRICHMENT_REQUIRED
    assert exhausted.outcome is RunOutcome.ENRICHMENT_REQUIRED
    assert repeated.route is exhausted.route is GraphRoute.PERSIST
