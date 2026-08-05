import ast
import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.fakes import (
    FakeArtifactStore,
    FakeKnowledgeSourceProvider,
    FakeQueue,
    FakeRunStore,
    FakeStructuredLLM,
    FakeTelemetry,
    FakeVectorIndex,
)

from knowledge_agents.domain.budgets import CallUsage, ContextBudget
from knowledge_agents.domain.contracts import (
    AcquisitionRequest,
    CoverageReport,
    EvidenceBatch,
    SourceDescriptor,
)
from knowledge_agents.domain.enums import AcquisitionMethod, SourceType
from knowledge_agents.ports.artifacts import ArtifactStore
from knowledge_agents.ports.llm import StructuredLLMPort, StructuredResult
from knowledge_agents.ports.providers import KnowledgeSourceProvider
from knowledge_agents.ports.queue import QueueMessage, QueuePort
from knowledge_agents.ports.run_store import RunStore
from knowledge_agents.ports.telemetry import TelemetryEvent, TelemetryPort
from knowledge_agents.ports.vector_index import IndexDocument, VectorIndex, VectorQuery

ROOT = Path(__file__).parents[2]
DOMAIN_ROOT = ROOT / "src" / "knowledge_agents" / "domain"
PORTS_ROOT = ROOT / "src" / "knowledge_agents" / "ports"
APPLICATION_ROOT = ROOT / "src" / "knowledge_agents" / "application"
FORBIDDEN_DOMAIN_PREFIXES = (
    "knowledge_agents.adapters",
    "knowledge_agents.application",
    "knowledge_agents.ports",
)
FORBIDDEN_EXTERNAL_SDKS = {
    "aiosqlite",
    "boto3",
    "botocore",
    "langfuse",
    "langgraph",
    "mcp",
    "openai",
    "qdrant_client",
}


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_domain_does_not_import_outer_layers_or_external_sdks() -> None:
    violations: list[str] = []
    for path in DOMAIN_ROOT.glob("*.py"):
        for module in imported_modules(path):
            if module.startswith(FORBIDDEN_DOMAIN_PREFIXES) or module.split(".")[0] in (
                FORBIDDEN_EXTERNAL_SDKS
            ):
                violations.append(f"{path.name}: {module}")

    assert violations == []


def test_ports_depend_only_on_domain_and_standard_library() -> None:
    allowed_prefixes = {"knowledge_agents.domain"}
    violations: list[str] = []
    for path in PORTS_ROOT.glob("*.py"):
        for module in imported_modules(path):
            if module.startswith("knowledge_agents") and not any(
                module.startswith(prefix) for prefix in allowed_prefixes
            ):
                violations.append(f"{path.name}: {module}")
            if module.split(".")[0] in FORBIDDEN_EXTERNAL_SDKS:
                violations.append(f"{path.name}: {module}")

    assert violations == []


def test_application_layer_only_imports_langgraph_inside_graph_modules() -> None:
    violations: list[str] = []
    for path in APPLICATION_ROOT.rglob("*.py"):
        relative_parts = path.relative_to(APPLICATION_ROOT).parts
        for module in imported_modules(path):
            if module.startswith("knowledge_agents.adapters"):
                violations.append(f"{path.name}: {module}")
            if module.split(".")[0] in FORBIDDEN_EXTERNAL_SDKS:
                if (
                    module.split(".")[0] in {"aiosqlite", "langgraph"}
                    and relative_parts[0] == "graph"
                ):
                    continue
                violations.append(f"{path.name}: {module}")

    assert violations == []


def test_every_port_has_a_runtime_compatible_fake() -> None:
    source = SourceDescriptor(
        source_id="source-1",
        source_type=SourceType.WEB_ARTICLE,
        acquisition_method=AcquisitionMethod.STATIC_HTML,
        canonical_ref="https://example.com",
        title="Example",
        publisher="Example",
        retrieved_at=datetime.now(UTC),
        content_hash="a" * 64,
    )
    evidence = EvidenceBatch(
        source=source,
        evidence_items=(),
        coverage=CoverageReport(),
        truncation=False,
    )

    assert isinstance(
        FakeKnowledgeSourceProvider(source=source, evidence=evidence), KnowledgeSourceProvider
    )
    assert isinstance(FakeStructuredLLM([]), StructuredLLMPort)
    assert isinstance(FakeRunStore(), RunStore)
    assert isinstance(FakeArtifactStore(), ArtifactStore)
    assert isinstance(FakeQueue(), QueuePort)
    assert isinstance(FakeVectorIndex(), VectorIndex)
    assert isinstance(FakeTelemetry(), TelemetryPort)


def test_fakes_are_deterministic_and_record_calls() -> None:
    async def scenario() -> None:
        artifacts = FakeArtifactStore()
        artifact = await artifacts.write_json(
            run_id="run-0123456789abcdef",
            artifact_type="request",
            payload={"url": "https://example.com"},
            schema_version="1",
        )
        assert await artifacts.read_json(artifact) == {"url": "https://example.com"}

        queue_message = QueueMessage("message-1", "receipt-1", "{}", 1)
        queue = FakeQueue([queue_message])
        assert await queue.receive() == (queue_message,)
        await queue.acknowledge(queue_message)

        vector = FakeVectorIndex()
        document = IndexDocument("doc-1", "notes", "body", "a" * 64, {})
        assert await vector.upsert((document,)) == ("doc-1",)
        assert await vector.query(VectorQuery("notes", "body", 5, {})) == ()

        telemetry = FakeTelemetry()
        event = TelemetryEvent("run-1", "test", datetime.now(UTC), {"count": 1})
        await telemetry.record(event)
        await telemetry.flush()

        assert [call.operation for call in artifacts.calls] == ["write_json", "read_json"]
        assert queue.acknowledged == ["message-1"]
        assert telemetry.events == [event]
        assert telemetry.flushed

    asyncio.run(scenario())


def test_fake_failure_plan_is_explicit_and_recorded() -> None:
    async def scenario() -> None:
        queue = FakeQueue(failures={"receive": RuntimeError("planned failure")})
        with pytest.raises(RuntimeError, match="planned failure"):
            await queue.receive()
        assert queue.calls[0].operation == "receive"

    asyncio.run(scenario())


def test_fake_llm_returns_typed_result() -> None:
    async def scenario() -> None:
        source = SourceDescriptor(
            source_id="source-1",
            source_type=SourceType.WEB_ARTICLE,
            acquisition_method=AcquisitionMethod.STATIC_HTML,
            canonical_ref="https://example.com",
            title="Example",
            publisher="Example",
            retrieved_at=datetime.now(UTC),
            content_hash="a" * 64,
        )
        usage = CallUsage(
            call_id="call-1",
            agent="agent_1",
            input_tokens=10,
            output_tokens=5,
            cost_usd=0,
            duration_seconds=0,
        )
        llm = FakeStructuredLLM([StructuredResult(source, usage, "response-1")])
        result = await llm.parse(prompt=({},), output_type=SourceDescriptor)
        assert result.output is source
        assert result.response_id == "response-1"

        provider = FakeKnowledgeSourceProvider(
            source=source,
            evidence=EvidenceBatch(
                source=source,
                evidence_items=(),
                coverage=CoverageReport(),
                truncation=False,
            ),
        )
        assert await provider.inspect(AcquisitionRequest(url="https://example.com")) is source
        await provider.acquire(source, ContextBudget())
        assert [call.operation for call in provider.calls] == ["inspect", "acquire"]

    asyncio.run(scenario())
