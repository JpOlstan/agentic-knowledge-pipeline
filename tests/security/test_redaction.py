import asyncio
from datetime import UTC, datetime
from typing import Any

from knowledge_agents.adapters.langfuse_telemetry import (
    LangfuseTelemetry,
    deterministic_trace_id,
)
from knowledge_agents.observability.redaction import RedactionPolicy
from knowledge_agents.ports.telemetry import TelemetryEvent

NOW = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
RUN_ID = "run-redaction-0123456789"


class FakeObservation:
    def __init__(self, calls: list[tuple[str, dict[str, Any]]]) -> None:
        self.calls = calls

    def update(self, **kwargs: Any) -> None:
        self.calls.append(("update", kwargs))

    def end(self) -> None:
        self.calls.append(("end", {}))


class FakeLangfuseClient:
    def __init__(self, *, fail_flush: bool = False) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail_flush = fail_flush

    def start_observation(
        self,
        *,
        name: str,
        as_type: str,
        trace_context: dict[str, str],
    ) -> FakeObservation:
        self.calls.append(
            (
                "start_observation",
                {"name": name, "as_type": as_type, "trace_context": trace_context},
            )
        )
        return FakeObservation(self.calls)

    def flush(self) -> None:
        self.calls.append(("flush", {}))
        if self.fail_flush:
            raise RuntimeError("Authorization: Bearer sk-private-value")


def test_redaction_drops_raw_fields_and_masks_sensitive_allowlisted_values() -> None:
    event = TelemetryEvent(
        run_id=RUN_ID,
        name=" Agent 1 private ",
        occurred_at=NOW,
        attributes={
            "body": "PRIVATE SOURCE BODY",
            "url": "https://private.example/notebook/123",
            "path": r"C:\Users\private\vault\note.md",
            "authorization": "Bearer sk-private-value",
            "provider_type": "https://private.example/notebook/123",
            "model": r"C:\Users\private\model",
            "status": "api_key=sk-private-value",
            "input_tokens": 42,
        },
    )

    sanitized = RedactionPolicy().sanitize_event(event)

    assert sanitized.name == "agent-1-private"
    assert sanitized.attributes == {
        "input_tokens": 42,
        "model": "[REDACTED_PATH]",
        "provider_type": "[REDACTED_URL]",
        "status": "[REDACTED_SECRET]",
    }

    sensitive_name = event.__class__(
        run_id=RUN_ID,
        name="https://private.example/notebook/123",
        occurred_at=NOW,
        attributes={"model": "/mnt/private/project/model.bin"},
    )
    sanitized_sensitive = RedactionPolicy().sanitize_event(sensitive_name)
    assert sanitized_sensitive.name == "telemetry.event"
    assert sanitized_sensitive.attributes == {"model": "[REDACTED_PATH]"}


def test_adapter_emits_only_sanitized_metadata_and_deterministic_trace_types() -> None:
    async def scenario() -> None:
        client = FakeLangfuseClient()
        telemetry = LangfuseTelemetry(client)
        for observation_type in ("span", "generation", "retriever"):
            await telemetry.record(
                TelemetryEvent(
                    run_id=RUN_ID,
                    name=f"private {observation_type}",
                    occurred_at=NOW,
                    observation_type=observation_type,
                    attributes={
                        "body": "PRIVATE SOURCE BODY",
                        "url": "https://private.example/notebook/123",
                        "path": r"C:\Users\private\vault\note.md",
                        "status": "ok",
                    },
                )
            )

        await telemetry.flush()

        starts = [
            payload for operation, payload in client.calls if operation == "start_observation"
        ]
        updates = [payload for operation, payload in client.calls if operation == "update"]
        assert [payload["as_type"] for payload in starts] == [
            "span",
            "generation",
            "retriever",
        ]
        assert {payload["trace_context"]["trace_id"] for payload in starts} == {
            deterministic_trace_id(RUN_ID)
        }
        assert len(deterministic_trace_id(RUN_ID)) == 32
        assert updates == [{"metadata": {"status": "ok"}}] * 3
        assert "PRIVATE SOURCE BODY" not in repr(client.calls)
        assert "private.example" not in repr(client.calls)
        assert "private\\vault" not in repr(client.calls)

    asyncio.run(scenario())


def test_failed_flush_keeps_sanitized_batch_for_secondary_repair() -> None:
    async def scenario() -> None:
        client = FakeLangfuseClient(fail_flush=True)
        telemetry = LangfuseTelemetry(client)
        await telemetry.record(
            TelemetryEvent(
                run_id=RUN_ID,
                name="run terminal",
                occurred_at=NOW,
                attributes={"status": "Bearer sk-private-value", "body": "PRIVATE BODY"},
            )
        )

        try:
            await telemetry.flush()
        except RuntimeError:
            pass
        else:
            raise AssertionError("simulated flush failure was not propagated")

        assert telemetry.pending_count == 1
        updates = [payload for operation, payload in client.calls if operation == "update"]
        assert updates == [{"metadata": {"status": "[REDACTED_SECRET]"}}]
        assert "PRIVATE BODY" not in repr(client.calls)

    asyncio.run(scenario())
