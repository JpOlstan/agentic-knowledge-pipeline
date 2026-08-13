from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from tests.graph_scenarios import (
    IDEMPOTENCY_KEY,
    RUN_ID,
    make_draft,
    make_draft_package,
    make_harness,
    make_review,
)

from knowledge_agents.adapters.web_article_provider import (
    FailureHTMLStore,
    ValidatedTarget,
    WebArticleConfig,
    WebArticleProvider,
    WebResponse,
)
from knowledge_agents.application.graph.builder import open_graph
from knowledge_agents.application.services.run_service import RunService
from knowledge_agents.domain.budgets import ContextBudget
from knowledge_agents.domain.contracts import (
    AcquisitionPacket,
    AcquisitionRequest,
    Claim,
    Concept,
)
from knowledge_agents.domain.enums import (
    AcquisitionMethod,
    ClaimClassification,
    RunOutcome,
    SourceType,
)
from knowledge_agents.domain.errors import DomainError, ErrorCode
from knowledge_agents.ports.providers import KnowledgeSourceProvider

FIXTURE = Path(__file__).parents[1] / "fixtures" / "web" / "crewai-public-sanitized.html"
NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
PUBLIC_IPV4 = "93.184.216.34"


class SequenceFetcher:
    def __init__(self, responses: list[WebResponse]) -> None:
        self.responses = list(responses)
        self.targets: list[ValidatedTarget] = []

    async def __call__(
        self,
        target: ValidatedTarget,
        config: WebArticleConfig,
    ) -> WebResponse:
        self.targets.append(target)
        assert config.timeout_seconds == 30
        return self.responses.pop(0)


async def public_resolver(host: str, port: int) -> tuple[str, ...]:
    assert host in {"example.com", "www.example.com"}
    assert port == 443
    return (PUBLIC_IPV4,)


def html_response(body: bytes | None = None) -> WebResponse:
    payload = body if body is not None else FIXTURE.read_bytes()
    return WebResponse(200, {"content-type": "text/html; charset=utf-8"}, payload)


def provider(
    tmp_path: Path,
    responses: list[WebResponse],
    *,
    max_body_bytes: int = 5 * 1024 * 1024,
) -> tuple[WebArticleProvider, SequenceFetcher]:
    fetcher = SequenceFetcher(responses)
    instance = WebArticleProvider(
        WebArticleConfig(
            max_body_bytes=max_body_bytes,
            failure_root=tmp_path / "web-failures",
        ),
        resolver=public_resolver,
        fetcher=fetcher,
        clock=lambda: NOW,
    )
    return instance, fetcher


def test_sanitized_fixture_produces_deterministic_evidence_batch(tmp_path: Path) -> None:
    async def scenario() -> None:
        first, first_fetcher = provider(tmp_path / "first", [html_response()])
        second, _ = provider(tmp_path / "second", [html_response()])
        request = AcquisitionRequest(url="https://example.com/articles/memory")

        first_source = await first.inspect(request)
        first_batch = await first.acquire(first_source, ContextBudget())
        second_source = await second.inspect(request)
        second_batch = await second.acquire(second_source, ContextBudget())

        assert isinstance(first, KnowledgeSourceProvider)
        assert first_source == second_source
        assert first_batch == second_batch
        assert first_source.source_type is SourceType.WEB_ARTICLE
        assert first_source.acquisition_method is AcquisitionMethod.STATIC_HTML
        assert first_source.title == "Building cognitive memory for AI agents"
        assert first_source.publisher == "CrewAI Engineering"
        assert first_source.canonical_ref == "https://example.com/articles/memory"
        assert len(first_batch.evidence_items) >= 3
        assert "durable knowledge" in " ".join(item.text for item in first_batch.evidence_items)
        assert first_batch.artifact_refs == ()
        assert first_fetcher.targets[0].addresses == (PUBLIC_IPV4,)
        assert list((tmp_path / "first" / "web-failures").glob("*.html")) == []

    asyncio.run(scenario())


def test_redirect_is_revalidated_and_final_url_becomes_canonical(tmp_path: Path) -> None:
    async def scenario() -> None:
        instance, fetcher = provider(
            tmp_path,
            [
                WebResponse(302, {"location": "https://www.example.com/final"}, b""),
                html_response(),
            ],
        )

        source = await instance.inspect(AcquisitionRequest(url="https://example.com/start"))

        assert source.canonical_ref == "https://www.example.com/final"
        assert [target.host for target in fetcher.targets] == ["example.com", "www.example.com"]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("response", "expected_operation"),
    [
        (WebResponse(200, {"content-type": "application/json"}, b"{}"), "web.content_type"),
        (html_response(b"x" * 33), "web.body_limit"),
    ],
)
def test_content_type_and_body_limit_fail_closed(
    tmp_path: Path,
    response: WebResponse,
    expected_operation: str,
) -> None:
    async def scenario() -> None:
        instance, _ = provider(tmp_path, [response], max_body_bytes=32)
        with pytest.raises(DomainError) as captured:
            await instance.inspect(AcquisitionRequest(url="https://example.com/article"))
        assert captured.value.code is ErrorCode.INVALID_REQUEST
        assert captured.value.operation == expected_operation

    asyncio.run(scenario())


def test_context_budget_rejects_cached_source_before_evidence(tmp_path: Path) -> None:
    async def scenario() -> None:
        instance, _ = provider(tmp_path, [html_response()])
        source = await instance.inspect(AcquisitionRequest(url="https://example.com/article"))

        with pytest.raises(DomainError) as captured:
            await instance.acquire(source, ContextBudget(max_source_bytes=64))

        assert captured.value.code is ErrorCode.BUDGET_EXCEEDED
        assert captured.value.operation == "web.acquire.source_bytes"

    asyncio.run(scenario())


def test_failed_extraction_is_retained_locally_and_expires_within_24_hours(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        invalid_html = b"<html><head><title>Empty</title></head><body></body></html>"
        instance, _ = provider(tmp_path, [html_response(invalid_html)])

        with pytest.raises(DomainError) as captured:
            await instance.inspect(AcquisitionRequest(url="https://example.com/empty"))

        assert captured.value.code is ErrorCode.CONTRACT_VALIDATION_FAILED
        retained = list((tmp_path / "web-failures").glob("failure-*.html"))
        assert len(retained) == 1
        assert "example.com" not in retained[0].name

        store = FailureHTMLStore(tmp_path / "web-failures", timedelta(hours=24))
        await store.cleanup(NOW + timedelta(hours=24, seconds=1))
        assert list((tmp_path / "web-failures").glob("failure-*.html")) == []

    asyncio.run(scenario())


def test_provider_feeds_the_same_langgraph_used_by_fakes(tmp_path: Path) -> None:
    async def scenario() -> None:
        instance, _ = provider(tmp_path / "provider", [html_response(), html_response()])
        request = AcquisitionRequest(url="https://example.com/articles/memory")
        source = await instance.inspect(request)
        evidence = await instance.acquire(source, ContextBudget())
        evidence_id = evidence.evidence_items[0].evidence_id
        packet = AcquisitionPacket(
            run_id=RUN_ID,
            source=source,
            claims=(
                Claim(
                    claim_id="claim-1",
                    text="A durable claim.",
                    classification=ClaimClassification.DURABLE,
                    evidence_ids=(evidence_id,),
                    supported=True,
                ),
            ),
            concepts=(
                Concept(
                    concept_id="concept-1",
                    name="Governed knowledge",
                    summary="A governed concept.",
                    classification=ClaimClassification.DURABLE,
                    evidence_ids=(evidence_id,),
                ),
            ),
            evidence_map={"claim-1": (evidence_id,)},
            coverage_report=evidence.coverage,
            created_at=NOW,
        )
        drafts = (make_draft("note-a"),)
        harness = make_harness([packet, make_draft_package(*drafts), make_review(drafts)])
        dependencies = replace(harness.dependencies, provider=instance)

        async with open_graph(tmp_path / "checkpoints.db", dependencies) as graph:
            state = await RunService(
                graph=graph,
                run_store=harness.run_store,
                artifacts=harness.artifacts,
            ).execute(
                request,
                run_id=RUN_ID,
                idempotency_key=IDEMPOTENCY_KEY,
            )

        assert state["outcome"] == RunOutcome.COMPLETED.value
        assert [call.operation for call in harness.llm.calls] == ["parse"] * 3

    asyncio.run(scenario())
