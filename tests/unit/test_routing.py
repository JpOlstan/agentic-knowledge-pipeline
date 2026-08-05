from tests.graph_scenarios import make_draft, make_review

from knowledge_agents.application.graph.builder import graph_manifest
from knowledge_agents.application.graph.routing import issue_fingerprint
from knowledge_agents.domain.enums import DraftStatus


def test_graph_manifest_matches_the_validated_design() -> None:
    manifest = graph_manifest()

    assert manifest["nodes"] == (
        "prepare_run",
        "inspect_source",
        "acquire_evidence",
        "agent_1",
        "validate_acquisition",
        "retrieve_vault_context",
        "agent_2",
        "validate_drafts",
        "agent_3",
        "route_review",
        "persist_terminal",
        "sync_index",
        "flush_telemetry",
    )
    assert manifest["conditional_routes"] == {
        "revise": "agent_2",
        "persist": "persist_terminal",
    }
    assert manifest["subgraphs"] == ("agent_1", "agent_2", "agent_3")


def test_issue_fingerprint_is_stable_for_equivalent_findings() -> None:
    draft = make_draft("note-a")
    first = make_review((draft,), blocked={"note-a": (DraftStatus.PARTIALLY_READY, "missing link")})
    second = make_review(
        (draft,), blocked={"note-a": (DraftStatus.PARTIALLY_READY, "missing link")}
    )

    assert issue_fingerprint(first) == issue_fingerprint(second)
