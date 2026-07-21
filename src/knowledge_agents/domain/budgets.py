from __future__ import annotations

from typing import Annotated, ClassVar

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, PositiveInt

from knowledge_agents.domain.enums import AgentRole, BudgetDimension
from knowledge_agents.domain.errors import DomainError, ErrorCode

NonNegativeFiniteFloat = Annotated[float, Field(ge=0, allow_inf_nan=False)]
PositiveFiniteFloat = Annotated[float, Field(gt=0, allow_inf_nan=False)]


class ContextBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: ClassVar[str] = "1"
    max_input_tokens_per_call: PositiveInt = 48_000
    output_tokens_agent_1: PositiveInt = 8_000
    output_tokens_agent_2: PositiveInt = 12_000
    output_tokens_agent_3: PositiveInt = 10_000
    max_main_calls: PositiveInt = 7
    max_input_tokens_per_run: PositiveInt = 250_000
    max_output_tokens_per_run: PositiveInt = 50_000
    max_cost_usd: PositiveFiniteFloat = 10.0
    max_duration_seconds: PositiveFiniteFloat = 45 * 60
    max_source_bytes: PositiveInt = 5 * 1024 * 1024
    safety_margin_ratio: Annotated[float, Field(ge=0, lt=1, allow_inf_nan=False)] = 0.15

    def output_limit(self, agent: AgentRole) -> int:
        return {
            AgentRole.ACQUISITION: self.output_tokens_agent_1,
            AgentRole.CURATION: self.output_tokens_agent_2,
            AgentRole.VALIDATION: self.output_tokens_agent_3,
        }[agent]


class CallUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    call_id: str = Field(min_length=1, max_length=128)
    agent: AgentRole
    input_tokens: NonNegativeInt
    output_tokens: NonNegativeInt
    cost_usd: NonNegativeFiniteFloat
    duration_seconds: NonNegativeFiniteFloat


class UsageLedger(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    entries: tuple[CallUsage, ...] = ()

    @property
    def call_count(self) -> int:
        return len(self.entries)

    @property
    def input_tokens(self) -> int:
        return sum(entry.input_tokens for entry in self.entries)

    @property
    def output_tokens(self) -> int:
        return sum(entry.output_tokens for entry in self.entries)

    @property
    def cost_usd(self) -> float:
        return sum(entry.cost_usd for entry in self.entries)

    @property
    def duration_seconds(self) -> float:
        return sum(entry.duration_seconds for entry in self.entries)

    def append(self, usage: CallUsage) -> UsageLedger:
        return self.model_copy(update={"entries": (*self.entries, usage)})


class BudgetReservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    agent: AgentRole
    estimated_input_tokens: NonNegativeInt
    reserved_output_tokens: NonNegativeInt
    estimated_cost_usd: NonNegativeFiniteFloat = 0
    estimated_duration_seconds: NonNegativeFiniteFloat = 0


class BudgetStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    within_budget: bool
    exceeded: tuple[BudgetDimension, ...]
    remaining_calls: NonNegativeInt
    remaining_input_tokens: NonNegativeInt
    remaining_output_tokens: NonNegativeInt
    remaining_cost_usd: NonNegativeFiniteFloat
    remaining_duration_seconds: NonNegativeFiniteFloat


class BudgetExceeded(DomainError):
    def __init__(self, dimension: BudgetDimension) -> None:
        self.dimension = dimension
        super().__init__(ErrorCode.BUDGET_EXCEEDED, f"budget.{dimension.value}")


class ContextBudgetManager:
    def __init__(
        self,
        budget: ContextBudget | None = None,
        ledger: UsageLedger | None = None,
    ) -> None:
        self.budget = budget or ContextBudget()
        self.ledger = ledger or UsageLedger()

    def status(self) -> BudgetStatus:
        exceeded: list[BudgetDimension] = []
        if self.ledger.call_count > self.budget.max_main_calls:
            exceeded.append(BudgetDimension.CALL_COUNT)
        if self.ledger.input_tokens > self.budget.max_input_tokens_per_run:
            exceeded.append(BudgetDimension.INPUT_TOTAL)
        if self.ledger.output_tokens > self.budget.max_output_tokens_per_run:
            exceeded.append(BudgetDimension.OUTPUT_TOTAL)
        if self.ledger.cost_usd > self.budget.max_cost_usd:
            exceeded.append(BudgetDimension.COST_TOTAL)
        if self.ledger.duration_seconds > self.budget.max_duration_seconds:
            exceeded.append(BudgetDimension.DURATION_TOTAL)
        if any(
            entry.input_tokens > self.budget.max_input_tokens_per_call
            for entry in self.ledger.entries
        ):
            exceeded.append(BudgetDimension.INPUT_PER_CALL)
        if any(
            entry.output_tokens > self.budget.output_limit(entry.agent)
            for entry in self.ledger.entries
        ):
            exceeded.append(BudgetDimension.OUTPUT_PER_CALL)

        return BudgetStatus(
            within_budget=not exceeded,
            exceeded=tuple(exceeded),
            remaining_calls=max(self.budget.max_main_calls - self.ledger.call_count, 0),
            remaining_input_tokens=max(
                self.budget.max_input_tokens_per_run - self.ledger.input_tokens, 0
            ),
            remaining_output_tokens=max(
                self.budget.max_output_tokens_per_run - self.ledger.output_tokens, 0
            ),
            remaining_cost_usd=max(self.budget.max_cost_usd - self.ledger.cost_usd, 0),
            remaining_duration_seconds=max(
                self.budget.max_duration_seconds - self.ledger.duration_seconds, 0
            ),
        )

    def ensure_can_call(self, reservation: BudgetReservation) -> BudgetStatus:
        checks = (
            (
                BudgetDimension.INPUT_PER_CALL,
                reservation.estimated_input_tokens > self.budget.max_input_tokens_per_call,
            ),
            (
                BudgetDimension.OUTPUT_PER_CALL,
                reservation.reserved_output_tokens > self.budget.output_limit(reservation.agent),
            ),
            (
                BudgetDimension.CALL_COUNT,
                self.ledger.call_count + 1 > self.budget.max_main_calls,
            ),
            (
                BudgetDimension.INPUT_TOTAL,
                self.ledger.input_tokens + reservation.estimated_input_tokens
                > self.budget.max_input_tokens_per_run,
            ),
            (
                BudgetDimension.OUTPUT_TOTAL,
                self.ledger.output_tokens + reservation.reserved_output_tokens
                > self.budget.max_output_tokens_per_run,
            ),
            (
                BudgetDimension.COST_TOTAL,
                self.ledger.cost_usd + reservation.estimated_cost_usd > self.budget.max_cost_usd,
            ),
            (
                BudgetDimension.DURATION_TOTAL,
                self.ledger.duration_seconds + reservation.estimated_duration_seconds
                > self.budget.max_duration_seconds,
            ),
        )
        for dimension, is_exceeded in checks:
            if is_exceeded:
                raise BudgetExceeded(dimension)
        return self.status()

    def record_usage(self, usage: CallUsage) -> BudgetStatus:
        self.ledger = self.ledger.append(usage)
        return self.status()
