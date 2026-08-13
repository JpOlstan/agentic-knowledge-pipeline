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
from knowledge_agents.domain.contracts import RunManifest
from knowledge_agents.domain.enums import RunOutcome, RunStatus


def test_happy_path_uses_three_calls_and_keeps_large_content_out_of_state(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        drafts = (make_draft("note-a"), make_draft("note-b"))
        package = make_draft_package(*drafts)
        harness = make_harness([acquisition_packet(), package, make_review(drafts)])
        checkpoint_path = tmp_path / "state" / "checkpoints.db"

        async with open_graph(checkpoint_path, harness.dependencies) as graph:
            service = RunService(
                graph=graph,
                run_store=harness.run_store,
                artifacts=harness.artifacts,
            )
            state = await service.execute(
                harness.request,
                run_id=RUN_ID,
                idempotency_key=IDEMPOTENCY_KEY,
            )
            snapshot = await graph.aget_state({"configurable": {"thread_id": RUN_ID}})

        assert state["outcome"] == RunOutcome.COMPLETED.value
        assert state["revision_count"] == 0
        assert harness.run_store.records[RUN_ID].status is RunStatus.COMPLETED
        assert [call.operation for call in harness.llm.calls] == ["parse"] * 3
        assert [call.operation for call in harness.provider.calls] == ["inspect", "acquire"]
        assert harness.telemetry.flushed
        assert "PRIVATE_EVIDENCE_BODY" not in json.dumps(snapshot.values)
        assert "Body note-a" not in json.dumps(snapshot.values)

        manifest_ref = decode_artifact_ref(state["manifest_ref"])
        manifest = RunManifest.model_validate(await harness.artifacts.read_json(manifest_ref))
        assert manifest.usage.call_count == 3
        assert manifest.models == {
            "agent_1": "fake-model",
            "agent_2": "fake-model",
            "agent_3": "fake-model",
        }
        assert manifest.versions["prompt.agent_1"] == "v1"
        assert manifest.versions["prompt.agent_2"] == "v1"
        assert manifest.versions["prompt.agent_3"] == "v1"
        assert [record["response_id"] for record in state["llm_records"]] == [
            "fake-response-1",
            "fake-response-2",
            "fake-response-3",
        ]
        assert manifest.outcome is RunOutcome.COMPLETED
        assert checkpoint_path.exists()

    asyncio.run(scenario())


def test_secondary_failures_complete_with_safe_repair_warnings(tmp_path: Path) -> None:
    async def scenario() -> None:
        drafts = (make_draft("note-a"),)
        harness = make_harness(
            [
                acquisition_packet(),
                make_draft_package(*drafts),
                make_review(drafts),
            ],
            vector_failures={"upsert": RuntimeError("secret index detail")},
            telemetry_failures={"record": RuntimeError("secret telemetry detail")},
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

        assert state["outcome"] == RunOutcome.COMPLETED_WITH_WARNINGS.value
        assert state["warnings"] == [
            "index_repair_required",
            "telemetry_repair_required",
        ]
        assert "secret" not in json.dumps(state)
        assert len(harness.llm.calls) == 3

    asyncio.run(scenario())
