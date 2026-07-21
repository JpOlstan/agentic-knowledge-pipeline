import pytest

from knowledge_agents.domain.budgets import (
    BudgetExceeded,
    BudgetReservation,
    CallUsage,
    ContextBudget,
    ContextBudgetManager,
    UsageLedger,
)
from knowledge_agents.domain.enums import AgentRole, BudgetDimension


def reservation(**overrides: object) -> BudgetReservation:
    values: dict[str, object] = {
        "agent": AgentRole.ACQUISITION,
        "estimated_input_tokens": 1_000,
        "reserved_output_tokens": 500,
        "estimated_cost_usd": 0.25,
        "estimated_duration_seconds": 10,
    }
    values.update(overrides)
    return BudgetReservation.model_validate(values)


def usage(index: int = 1, **overrides: object) -> CallUsage:
    values: dict[str, object] = {
        "call_id": f"call-{index}",
        "agent": AgentRole.ACQUISITION,
        "input_tokens": 1_000,
        "output_tokens": 500,
        "cost_usd": 0.25,
        "duration_seconds": 10,
    }
    values.update(overrides)
    return CallUsage.model_validate(values)


def test_budget_before_and_after_actual_usage() -> None:
    manager = ContextBudgetManager()

    before = manager.ensure_can_call(reservation())
    after = manager.record_usage(usage())

    assert before.within_budget
    assert after.within_budget
    assert after.remaining_calls == 6
    assert manager.ledger.input_tokens == 1_000
    assert manager.ledger.output_tokens == 500
    assert manager.ledger.cost_usd == 0.25
    assert manager.ledger.duration_seconds == 10


@pytest.mark.parametrize(
    ("budget", "ledger", "requested", "dimension"),
    [
        (
            ContextBudget(max_input_tokens_per_call=100),
            UsageLedger(),
            reservation(estimated_input_tokens=101),
            BudgetDimension.INPUT_PER_CALL,
        ),
        (
            ContextBudget(output_tokens_agent_1=100),
            UsageLedger(),
            reservation(reserved_output_tokens=101),
            BudgetDimension.OUTPUT_PER_CALL,
        ),
        (
            ContextBudget(max_main_calls=1),
            UsageLedger(entries=(usage(),)),
            reservation(),
            BudgetDimension.CALL_COUNT,
        ),
        (
            ContextBudget(max_input_tokens_per_run=1_000),
            UsageLedger(entries=(usage(input_tokens=900),)),
            reservation(estimated_input_tokens=101),
            BudgetDimension.INPUT_TOTAL,
        ),
        (
            ContextBudget(max_output_tokens_per_run=1_000),
            UsageLedger(entries=(usage(output_tokens=900),)),
            reservation(reserved_output_tokens=101),
            BudgetDimension.OUTPUT_TOTAL,
        ),
        (
            ContextBudget(max_cost_usd=1),
            UsageLedger(entries=(usage(cost_usd=0.9),)),
            reservation(estimated_cost_usd=0.11),
            BudgetDimension.COST_TOTAL,
        ),
        (
            ContextBudget(max_duration_seconds=10),
            UsageLedger(entries=(usage(duration_seconds=9),)),
            reservation(estimated_duration_seconds=2),
            BudgetDimension.DURATION_TOTAL,
        ),
    ],
)
def test_budget_blocks_each_limit(
    budget: ContextBudget,
    ledger: UsageLedger,
    requested: BudgetReservation,
    dimension: BudgetDimension,
) -> None:
    manager = ContextBudgetManager(budget=budget, ledger=ledger)

    with pytest.raises(BudgetExceeded) as exc_info:
        manager.ensure_can_call(requested)

    assert exc_info.value.dimension is dimension
    assert "budget_exceeded" in str(exc_info.value)


def test_actual_usage_is_recorded_even_when_it_exhausts_budget() -> None:
    manager = ContextBudgetManager(ContextBudget(max_cost_usd=1))

    status = manager.record_usage(usage(cost_usd=1.01))

    assert not status.within_budget
    assert status.exceeded == (BudgetDimension.COST_TOTAL,)
    assert manager.ledger.cost_usd == 1.01
