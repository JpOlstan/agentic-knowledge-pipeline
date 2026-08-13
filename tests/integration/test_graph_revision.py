import asyncio
import json
from pathlib import Path

from tests.graph_scenarios import (
    IDEMPOTENCY_KEY,
    RUN_ID,
    acquisition_packet,
    make_draft,
    make_draft_package,
    make_harness,
    make_review,
)

from knowledge_agents.application.graph.builder import open_graph
from knowledge_agents.application.graph.state import decode_artifact_ref
from knowledge_agents.application.services.run_service import RunService
from knowledge_agents.domain.contracts import DraftPackage
from knowledge_agents.domain.enums import DraftStatus, RunOutcome


def test_one_revision_sends_only_blocked_draft_and_freezes_approved_hash(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        approved = make_draft("note-a")
        blocked = make_draft("note-b")
        revised = make_draft("note-b", version=2)
        initial = make_draft_package(approved, blocked)
        candidate = make_draft_package(revised)
        harness = make_harness(
            [
                acquisition_packet(),
                initial,
                make_review(
                    (approved, blocked),
                    blocked={"note-b": (DraftStatus.PARTIALLY_READY, "missing link")},
                ),
                candidate,
                make_review((revised,)),
            ]
        )

        async with open_graph(tmp_path / "checkpoints.db", harness.dependencies) as graph:
            state = await RunService(
                graph=graph,
                run_store=harness.run_store,
                artifacts=harness.artifacts,
            ).execute(
                harness.request,
                run_id=RUN_ID,
                idempotency_key=IDEMPOTENCY_KEY,
            )

        user_content = harness.llm.calls[3].arguments["prompt"][1]["content"]
        revision_prompt = json.loads(
            user_content.removeprefix("<UNTRUSTED_DATA>\n").removesuffix("\n</UNTRUSTED_DATA>")
        )
        assert [item["note_id"] for item in revision_prompt["blocked_drafts"]] == ["note-b"]
        assert "note-a" not in str(revision_prompt["blocked_drafts"])
        package_ref = decode_artifact_ref(state["draft_package_ref"])
        final_package = DraftPackage.model_validate(await harness.artifacts.read_json(package_ref))
        final_hashes = {draft.note_id: draft.content_hash for draft in final_package.drafts}
        assert final_hashes["note-a"] == approved.content_hash
        assert final_hashes["note-b"] == revised.content_hash
        assert state["revision_count"] == 1
        assert state["outcome"] == RunOutcome.COMPLETED.value
        assert len(harness.llm.calls) == 5
        assert state["llm_records"][3]["prompt_name"] == "agent_2_revision"

    asyncio.run(scenario())


def test_repeated_finding_stops_without_a_second_revision(tmp_path: Path) -> None:
    async def scenario() -> None:
        original = make_draft("note-a")
        revised = make_draft("note-a", version=2)
        issue = "missing link"
        harness = make_harness(
            [
                acquisition_packet(),
                make_draft_package(original),
                make_review(
                    (original,),
                    blocked={"note-a": (DraftStatus.PARTIALLY_READY, issue)},
                ),
                make_draft_package(revised),
                make_review(
                    (revised,),
                    blocked={"note-a": (DraftStatus.PARTIALLY_READY, issue)},
                ),
            ]
        )

        async with open_graph(tmp_path / "checkpoints.db", harness.dependencies) as graph:
            state = await RunService(
                graph=graph,
                run_store=harness.run_store,
                artifacts=harness.artifacts,
            ).execute(
                harness.request,
                run_id=RUN_ID,
                idempotency_key=IDEMPOTENCY_KEY,
            )

        assert state["revision_count"] == 1
        assert state["outcome"] == RunOutcome.ENRICHMENT_REQUIRED.value
        assert len(harness.llm.calls) == 5

    asyncio.run(scenario())


def test_two_revision_cycles_can_complete_within_the_call_budget(tmp_path: Path) -> None:
    async def scenario() -> None:
        original = make_draft("note-a")
        revision_one = make_draft("note-a", version=2)
        revision_two = make_draft("note-a", version=3)
        harness = make_harness(
            [
                acquisition_packet(),
                make_draft_package(original),
                make_review(
                    (original,),
                    blocked={"note-a": (DraftStatus.PARTIALLY_READY, "missing link")},
                ),
                make_draft_package(revision_one),
                make_review(
                    (revision_one,),
                    blocked={"note-a": (DraftStatus.PARTIALLY_READY, "unclear wording")},
                ),
                make_draft_package(revision_two),
                make_review((revision_two,)),
            ]
        )

        async with open_graph(tmp_path / "checkpoints.db", harness.dependencies) as graph:
            state = await RunService(
                graph=graph,
                run_store=harness.run_store,
                artifacts=harness.artifacts,
            ).execute(
                harness.request,
                run_id=RUN_ID,
                idempotency_key=IDEMPOTENCY_KEY,
            )

        assert state["revision_count"] == 2
        assert state["outcome"] == RunOutcome.COMPLETED.value
        assert len(harness.llm.calls) == 7

    asyncio.run(scenario())


def test_insufficient_evidence_never_reinvokes_acquisition(tmp_path: Path) -> None:
    async def scenario() -> None:
        draft = make_draft("note-a")
        harness = make_harness(
            [
                acquisition_packet(),
                make_draft_package(draft),
                make_review(
                    (draft,),
                    blocked={
                        "note-a": (
                            DraftStatus.ENRICHMENT_REQUIRED,
                            "missing evidence",
                        )
                    },
                ),
            ]
        )

        async with open_graph(tmp_path / "checkpoints.db", harness.dependencies) as graph:
            state = await RunService(
                graph=graph,
                run_store=harness.run_store,
                artifacts=harness.artifacts,
            ).execute(
                harness.request,
                run_id=RUN_ID,
                idempotency_key=IDEMPOTENCY_KEY,
            )

        assert state["revision_count"] == 0
        assert state["outcome"] == RunOutcome.ENRICHMENT_REQUIRED.value
        assert len(harness.llm.calls) == 3
        assert [call.operation for call in harness.provider.calls] == ["inspect", "acquire"]

    asyncio.run(scenario())
