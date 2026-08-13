from types import SimpleNamespace

import pytest

from knowledge_agents.adapters.openai_client import (
    AgentModelConfig,
    OpenAIStructuredClient,
    agent_configs_from_settings,
    default_agent_configs,
)
from knowledge_agents.application.agents.prompts import load_prompt
from knowledge_agents.config import Settings
from knowledge_agents.domain.contracts import (
    AcquisitionPacket,
    DraftPackage,
    ReviewPackage,
    SourceDescriptor,
)
from knowledge_agents.domain.enums import AgentRole
from knowledge_agents.domain.errors import DomainError, ErrorCode

RUN_ID = "run-0123456789abcdef"
HASH_A = "a" * 64
HASH_B = "b" * 64
CREATED_AT = "2026-07-21T00:00:00Z"


def source_payload() -> dict[str, object]:
    return {
        "source_id": "source-1",
        "source_type": "web_article",
        "acquisition_method": "static_html",
        "canonical_ref": "https://example.com/article",
        "title": "Example article",
        "publisher": "Example Publisher",
        "retrieved_at": CREATED_AT,
        "content_hash": HASH_A,
        "created_at": CREATED_AT,
    }


def acquisition_packet_fixture() -> AcquisitionPacket:
    return AcquisitionPacket.model_validate(
        {
            "run_id": RUN_ID,
            "source": source_payload(),
            "claims": [],
            "concepts": [],
            "evidence_map": {},
            "coverage_report": {},
            "created_at": CREATED_AT,
        }
    )


def test_agent_1_output_fixture_validates_against_production_contract() -> None:
    packet = AcquisitionPacket.model_validate(
        {
            "run_id": RUN_ID,
            "source": source_payload(),
            "claims": [
                {
                    "claim_id": "claim-1",
                    "text": "Memory is distinct from transient state.",
                    "classification": "durable",
                    "evidence_ids": ["evidence-1"],
                    "supported": True,
                }
            ],
            "concepts": [
                {
                    "concept_id": "concept-1",
                    "name": "Agent memory",
                    "summary": "Durable information available across interactions.",
                    "classification": "durable",
                    "evidence_ids": ["evidence-1"],
                }
            ],
            "evidence_map": {"claim-1": ["evidence-1"]},
            "coverage_report": {
                "covered_topics": ["memory"],
                "missing_topics": [],
                "completeness": 1,
            },
            "warnings": [],
            "created_at": CREATED_AT,
        }
    )

    assert packet.claims[0].supported
    assert packet.schema_version == "1"


def test_agent_2_output_fixture_supports_multiple_atomic_drafts() -> None:
    package = DraftPackage.model_validate(
        {
            "run_id": RUN_ID,
            "drafts": [
                {
                    "note_id": "agent-memory",
                    "title": "Agent memory",
                    "body_sections": {"Summary": "Memory persists beyond transient state."},
                    "source_claim_ids": ["claim-1"],
                    "proposed_action": "create",
                    "content_hash": HASH_A,
                },
                {
                    "note_id": "memory-consolidation",
                    "title": "Memory consolidation",
                    "body_sections": {"Summary": "Consolidation organizes retained information."},
                    "source_claim_ids": ["claim-2"],
                    "proposed_action": "create",
                    "content_hash": HASH_B,
                },
            ],
            "curation_decisions": [
                {
                    "note_id": "agent-memory",
                    "action": "create",
                    "rationale": "No promoted note covers the concept.",
                },
                {
                    "note_id": "memory-consolidation",
                    "action": "create",
                    "rationale": "The concept is independently reusable.",
                },
            ],
            "retrieval_refs": [],
            "package_hash": HASH_A,
            "created_at": CREATED_AT,
        }
    )

    assert len(package.drafts) == 2


def test_agent_3_output_fixture_links_decisions_to_exact_hashes() -> None:
    package = ReviewPackage.model_validate(
        {
            "run_id": RUN_ID,
            "reviews": [
                {
                    "note_id": "agent-memory",
                    "reviewed_hash": HASH_A,
                    "status": "ready",
                    "issues": [],
                    "required_changes": [],
                    "promotion_eligible": True,
                },
                {
                    "note_id": "memory-consolidation",
                    "reviewed_hash": HASH_B,
                    "status": "enrichment_required",
                    "issues": ["Evidence is incomplete."],
                    "required_changes": ["Add primary support."],
                    "promotion_eligible": False,
                },
            ],
            "blocked_note_ids": ["memory-consolidation"],
            "approved_note_hashes": {"agent-memory": HASH_A},
            "terminal_recommendation": "partially_ready",
            "created_at": CREATED_AT,
        }
    )

    assert package.approved_note_hashes["agent-memory"] == HASH_A
    assert package.blocked_note_ids == ("memory-consolidation",)


def test_all_versioned_prompts_define_schema_and_untrusted_data_boundary() -> None:
    prompts = (
        load_prompt(AgentRole.ACQUISITION),
        load_prompt(AgentRole.CURATION),
        load_prompt(AgentRole.CURATION, revision=True),
        load_prompt(AgentRole.VALIDATION),
    )

    assert {prompt.name for prompt in prompts} == {
        "agent_1",
        "agent_2",
        "agent_2_revision",
        "agent_3",
    }
    assert all(prompt.version == "v1" for prompt in prompts)
    assert all("UNTRUSTED_DATA" in prompt.instructions for prompt in prompts)
    assert all("schema" in prompt.instructions.lower() for prompt in prompts)
    assert all("tool" in prompt.instructions.lower() for prompt in prompts)


def test_settings_configure_model_reasoning_and_output_per_agent() -> None:
    settings = Settings(
        openai_model_agent_1="model-a",
        openai_model_agent_2="model-b",
        openai_model_agent_3="model-c",
        openai_reasoning_agent_1="minimal",
        openai_reasoning_agent_2="low",
        openai_reasoning_agent_3="high",
    )

    configs = agent_configs_from_settings(settings)

    assert configs[AgentRole.ACQUISITION] == AgentModelConfig("model-a", "minimal", 8_000)
    assert configs[AgentRole.CURATION] == AgentModelConfig("model-b", "low", 12_000)
    assert configs[AgentRole.VALIDATION] == AgentModelConfig("model-c", "high", 10_000)


class FakeResponses:
    def __init__(self, responses: list[SimpleNamespace]) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, object]] = []

    async def parse(self, **request: object) -> SimpleNamespace:
        self.requests.append(request)
        return self.responses.pop(0)


def _response(
    response_id: str,
    *,
    output: object | None,
    input_tokens: int,
    output_tokens: int,
    refusal: bool = False,
) -> SimpleNamespace:
    content = (SimpleNamespace(type="refusal"),) if refusal else ()
    return SimpleNamespace(
        id=response_id,
        model="resolved-model-snapshot",
        output_parsed=output,
        output=(SimpleNamespace(content=content),),
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def _adapter(
    responses: list[SimpleNamespace],
    *,
    clock: object | None = None,
) -> tuple[OpenAIStructuredClient, FakeResponses]:
    endpoint = FakeResponses(responses)
    configs = default_agent_configs(agent_1_model="configured-model")
    configs[AgentRole.ACQUISITION] = AgentModelConfig(
        "configured-model",
        "low",
        8_000,
        input_cost_per_million=1.0,
        output_cost_per_million=2.0,
    )
    ticks = iter((10.0, 10.5))
    return (
        OpenAIStructuredClient(
            SimpleNamespace(responses=endpoint),
            configs,
            clock=clock or (lambda: next(ticks)),
        ),
        endpoint,
    )


def test_openai_adapter_maps_structured_output_and_sdk_usage() -> None:
    async def scenario() -> None:
        packet = acquisition_packet_fixture()
        adapter, endpoint = _adapter(
            [_response("resp-1", output=packet, input_tokens=100, output_tokens=20)]
        )
        prompt = load_prompt(AgentRole.ACQUISITION)

        result = await adapter.parse(
            agent=AgentRole.ACQUISITION,
            prompt_version=prompt.version,
            prompt=prompt.messages({"run_id": RUN_ID, "evidence": "sanitized fixture"}),
            output_type=AcquisitionPacket,
        )

        assert result.output is packet
        assert result.response_id == "resp-1"
        assert result.model == "resolved-model-snapshot"
        assert result.prompt_version == "v1"
        assert result.contract_repaired is False
        assert result.usage.input_tokens == 100
        assert result.usage.output_tokens == 20
        assert result.usage.cost_usd == pytest.approx(0.00014)
        assert result.usage.duration_seconds == 0.5
        request = endpoint.requests[0]
        assert request["model"] == "configured-model"
        assert request["reasoning"] == {"effort": "low"}
        assert request["max_output_tokens"] == 8_000
        assert request["text_format"] is AcquisitionPacket
        assert request["store"] is False
        assert "tools" not in request

    import asyncio

    asyncio.run(scenario())


def test_openai_adapter_allows_exactly_one_separate_contract_repair() -> None:
    async def scenario() -> None:
        packet = acquisition_packet_fixture()
        adapter, endpoint = _adapter(
            [
                _response(
                    "resp-invalid",
                    output=SourceDescriptor.model_validate(source_payload()),
                    input_tokens=30,
                    output_tokens=10,
                ),
                _response("resp-repaired", output=packet, input_tokens=40, output_tokens=12),
            ]
        )
        prompt = load_prompt(AgentRole.ACQUISITION)

        result = await adapter.parse(
            agent=AgentRole.ACQUISITION,
            prompt_version="v1",
            prompt=prompt.messages({"run_id": RUN_ID}),
            output_type=AcquisitionPacket,
        )

        assert len(endpoint.requests) == 2
        assert "CONTRACT REPAIR" not in str(endpoint.requests[0]["instructions"])
        assert "CONTRACT REPAIR" in str(endpoint.requests[1]["instructions"])
        assert result.contract_repaired is True
        assert result.response_id == "resp-repaired"
        assert result.usage.input_tokens == 70
        assert result.usage.output_tokens == 22

    import asyncio

    asyncio.run(scenario())


def test_openai_adapter_does_not_repair_refusal_or_repeat_invalid_output() -> None:
    async def refusal_scenario() -> None:
        adapter, endpoint = _adapter(
            [_response("resp-refusal", output=None, input_tokens=5, output_tokens=2, refusal=True)]
        )
        prompt = load_prompt(AgentRole.ACQUISITION)
        with pytest.raises(DomainError) as captured:
            await adapter.parse(
                agent=AgentRole.ACQUISITION,
                prompt_version="v1",
                prompt=prompt.messages({"run_id": RUN_ID}),
                output_type=AcquisitionPacket,
            )
        assert captured.value.code is ErrorCode.STRUCTURED_OUTPUT_INVALID
        assert len(endpoint.requests) == 1

    async def invalid_scenario() -> None:
        adapter, endpoint = _adapter(
            [
                _response("resp-invalid-1", output=None, input_tokens=5, output_tokens=2),
                _response("resp-invalid-2", output=None, input_tokens=5, output_tokens=2),
            ]
        )
        prompt = load_prompt(AgentRole.ACQUISITION)
        with pytest.raises(DomainError) as captured:
            await adapter.parse(
                agent=AgentRole.ACQUISITION,
                prompt_version="v1",
                prompt=prompt.messages({"run_id": RUN_ID}),
                output_type=AcquisitionPacket,
            )
        assert captured.value.code is ErrorCode.STRUCTURED_OUTPUT_INVALID
        assert len(endpoint.requests) == 2

    import asyncio

    asyncio.run(refusal_scenario())
    asyncio.run(invalid_scenario())


def test_openai_adapter_leaves_transport_retry_ownership_to_the_sdk() -> None:
    class FailingResponses:
        def __init__(self) -> None:
            self.calls = 0

        async def parse(self, **_: object) -> object:
            self.calls += 1
            raise RuntimeError("transport owned by injected SDK")

    async def scenario() -> None:
        endpoint = FailingResponses()
        adapter = OpenAIStructuredClient(
            SimpleNamespace(responses=endpoint),
            default_agent_configs(),
        )
        prompt = load_prompt(AgentRole.ACQUISITION)
        with pytest.raises(RuntimeError, match="transport owned"):
            await adapter.parse(
                agent=AgentRole.ACQUISITION,
                prompt_version="v1",
                prompt=prompt.messages({"run_id": RUN_ID}),
                output_type=AcquisitionPacket,
            )
        assert endpoint.calls == 1

    import asyncio

    asyncio.run(scenario())
