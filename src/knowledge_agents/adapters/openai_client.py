from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Literal

from openai import AsyncOpenAI
from pydantic import ValidationError

from knowledge_agents.config import Settings
from knowledge_agents.domain.budgets import CallUsage
from knowledge_agents.domain.enums import AgentRole
from knowledge_agents.domain.errors import DomainError, ErrorCode
from knowledge_agents.ports.llm import OutputT, StructuredLLMPort, StructuredResult

ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh"]


@dataclass(frozen=True, slots=True)
class AgentModelConfig:
    model: str
    reasoning_effort: ReasoningEffort
    max_output_tokens: int
    input_cost_per_million: float = 0.0
    output_cost_per_million: float = 0.0

    def __post_init__(self) -> None:
        if not self.model.strip():
            raise ValueError("model must not be empty")
        if self.max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive")
        if self.input_cost_per_million < 0 or self.output_cost_per_million < 0:
            raise ValueError("model pricing must not be negative")


def default_agent_configs(
    *,
    agent_1_model: str = "gpt-5.6-terra",
    agent_2_model: str = "gpt-5.6-terra",
    agent_3_model: str = "gpt-5.6-terra",
    agent_1_reasoning: ReasoningEffort = "low",
    agent_2_reasoning: ReasoningEffort = "medium",
    agent_3_reasoning: ReasoningEffort = "medium",
) -> dict[AgentRole, AgentModelConfig]:
    return {
        AgentRole.ACQUISITION: AgentModelConfig(agent_1_model, agent_1_reasoning, 8_000),
        AgentRole.CURATION: AgentModelConfig(agent_2_model, agent_2_reasoning, 12_000),
        AgentRole.VALIDATION: AgentModelConfig(agent_3_model, agent_3_reasoning, 10_000),
    }


def agent_configs_from_settings(settings: Settings) -> dict[AgentRole, AgentModelConfig]:
    budget = settings.context_budget()
    return {
        AgentRole.ACQUISITION: AgentModelConfig(
            settings.openai_model_agent_1,
            settings.openai_reasoning_agent_1,
            budget.output_tokens_agent_1,
        ),
        AgentRole.CURATION: AgentModelConfig(
            settings.openai_model_agent_2,
            settings.openai_reasoning_agent_2,
            budget.output_tokens_agent_2,
        ),
        AgentRole.VALIDATION: AgentModelConfig(
            settings.openai_model_agent_3,
            settings.openai_reasoning_agent_3,
            budget.output_tokens_agent_3,
        ),
    }


class OpenAIStructuredClient(StructuredLLMPort):
    def __init__(
        self,
        client: Any,
        configs: dict[AgentRole, AgentModelConfig],
        *,
        clock: Callable[[], float] = perf_counter,
    ) -> None:
        missing = set(AgentRole) - set(configs)
        if missing:
            raise ValueError("model configuration is missing an agent")
        self._client = client
        self._configs = dict(configs)
        self._clock = clock

    @classmethod
    def from_api_key(
        cls,
        *,
        api_key: str,
        configs: dict[AgentRole, AgentModelConfig],
    ) -> OpenAIStructuredClient:
        client = AsyncOpenAI(api_key=api_key, timeout=120, max_retries=2)
        return cls(client, configs)

    async def parse(
        self,
        *,
        agent: AgentRole,
        prompt_version: str,
        prompt: tuple[dict[str, Any], ...],
        output_type: type[OutputT],
    ) -> StructuredResult[OutputT]:
        config = self._configs[agent]
        instructions, user_input = _normalize_prompt(prompt)
        started = self._clock()
        responses: list[Any] = []

        repaired = False
        try:
            first = await self._parse_once(
                config=config,
                agent=agent,
                prompt_version=prompt_version,
                instructions=instructions,
                user_input=user_input,
                output_type=output_type,
            )
        except ValidationError:
            first = None
            repaired = True
        if first is not None:
            responses.append(first)
            if _has_refusal(first):
                raise DomainError(ErrorCode.STRUCTURED_OUTPUT_INVALID, "openai.refusal")

        output = getattr(first, "output_parsed", None)
        if output is None or not isinstance(output, output_type):
            repaired = True
            try:
                repair = await self._parse_once(
                    config=config,
                    agent=agent,
                    prompt_version=prompt_version,
                    instructions=f"{instructions}\n\n{_CONTRACT_REPAIR_INSTRUCTION}",
                    user_input=user_input,
                    output_type=output_type,
                )
            except ValidationError as error:
                raise DomainError(
                    ErrorCode.STRUCTURED_OUTPUT_INVALID,
                    "openai.structured_output",
                    cause=error,
                ) from error
            responses.append(repair)
            if _has_refusal(repair):
                raise DomainError(ErrorCode.STRUCTURED_OUTPUT_INVALID, "openai.refusal")
            output = getattr(repair, "output_parsed", None)

        if output is None or not isinstance(output, output_type):
            raise DomainError(ErrorCode.STRUCTURED_OUTPUT_INVALID, "openai.structured_output")

        final = responses[-1]
        usage = _aggregate_usage(
            responses,
            agent=agent,
            config=config,
            call_id=str(final.id),
            duration_seconds=max(self._clock() - started, 0.0),
        )
        return StructuredResult(
            output=output,
            usage=usage,
            response_id=str(final.id),
            model=str(final.model),
            prompt_version=prompt_version,
            contract_repaired=repaired,
        )

    async def close(self) -> None:
        close = getattr(self._client, "close", None)
        if close is not None:
            await close()

    async def _parse_once(
        self,
        *,
        config: AgentModelConfig,
        agent: AgentRole,
        prompt_version: str,
        instructions: str,
        user_input: list[dict[str, Any]],
        output_type: type[OutputT],
    ) -> Any:
        return await self._client.responses.parse(
            model=config.model,
            reasoning={"effort": config.reasoning_effort},
            max_output_tokens=config.max_output_tokens,
            instructions=instructions,
            input=user_input,
            text_format=output_type,
            metadata={"agent": agent.value, "prompt_version": prompt_version},
            store=False,
        )


def _normalize_prompt(prompt: tuple[dict[str, Any], ...]) -> tuple[str, list[dict[str, Any]]]:
    developer = [message for message in prompt if message.get("role") == "developer"]
    users = [message for message in prompt if message.get("role") == "user"]
    if len(developer) != 1 or not users or len(developer) + len(users) != len(prompt):
        raise DomainError(ErrorCode.INVALID_REQUEST, "openai.prompt_boundary")
    instructions = developer[0].get("content")
    if not isinstance(instructions, str) or not instructions.strip():
        raise DomainError(ErrorCode.INVALID_REQUEST, "openai.prompt_boundary")
    normalized: list[dict[str, Any]] = []
    for message in users:
        content = message.get("content")
        if not isinstance(content, str):
            raise DomainError(ErrorCode.INVALID_REQUEST, "openai.prompt_boundary")
        normalized.append(
            {
                "role": "user",
                "content": [{"type": "input_text", "text": content}],
            }
        )
    return instructions, normalized


def _has_refusal(response: Any) -> bool:
    for output in getattr(response, "output", ()):
        for content in getattr(output, "content", ()):
            if getattr(content, "type", None) == "refusal":
                return True
    return False


def _aggregate_usage(
    responses: list[Any],
    *,
    agent: AgentRole,
    config: AgentModelConfig,
    call_id: str,
    duration_seconds: float,
) -> CallUsage:
    input_tokens = sum(int(response.usage.input_tokens) for response in responses)
    output_tokens = sum(int(response.usage.output_tokens) for response in responses)
    cost = (
        input_tokens * config.input_cost_per_million
        + output_tokens * config.output_cost_per_million
    ) / 1_000_000
    return CallUsage(
        call_id=call_id,
        agent=agent,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost,
        duration_seconds=duration_seconds,
    )


_CONTRACT_REPAIR_INSTRUCTION = (
    "CONTRACT REPAIR: the prior response did not validate. Return only one object matching the "
    "provided Structured Output schema. Preserve the original data and do not add fields."
)
