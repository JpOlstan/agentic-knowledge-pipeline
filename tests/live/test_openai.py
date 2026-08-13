from __future__ import annotations

import asyncio
import os
from typing import Literal

import pytest

from knowledge_agents.adapters.openai_client import (
    AgentModelConfig,
    OpenAIStructuredClient,
    default_agent_configs,
)
from knowledge_agents.domain.contracts import ContractModel
from knowledge_agents.domain.enums import AgentRole


class LiveSmokeOutput(ContractModel):
    value: Literal["ok"]


@pytest.mark.live
def test_openai_structured_output_smoke_is_explicit_and_sanitized() -> None:
    if os.getenv("KA_RUN_LIVE_OPENAI") != "1":
        pytest.skip("set KA_RUN_LIVE_OPENAI=1 for the explicitly authorized smoke test")
    api_key = os.getenv("KA_OPENAI_API_KEY")
    if not api_key:
        pytest.skip("KA_OPENAI_API_KEY is required for the authorized live smoke test")

    async def scenario() -> None:
        model = os.getenv("KA_OPENAI_MODEL_AGENT_1", "gpt-5.6-terra")
        configs = default_agent_configs(agent_1_model=model)
        configs[AgentRole.ACQUISITION] = AgentModelConfig(model, "low", 128)
        client = OpenAIStructuredClient.from_api_key(api_key=api_key, configs=configs)
        try:
            result = await client.parse(
                agent=AgentRole.ACQUISITION,
                prompt_version="live-smoke-v1",
                prompt=(
                    {
                        "role": "developer",
                        "content": (
                            "Return the requested structured object. No tools are available."
                        ),
                    },
                    {
                        "role": "user",
                        "content": '<UNTRUSTED_DATA>{"value":"ok"}</UNTRUSTED_DATA>',
                    },
                ),
                output_type=LiveSmokeOutput,
            )
            assert result.output.value == "ok"
            assert result.usage.input_tokens > 0
        finally:
            await client.close()

    asyncio.run(scenario())
