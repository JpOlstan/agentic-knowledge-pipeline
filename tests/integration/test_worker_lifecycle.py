from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from tests.fakes import FakeQueue, FakeRunStore

from knowledge_agents.adapters.sqs_queue import SqsQueue
from knowledge_agents.domain.contracts import AcquisitionRequest
from knowledge_agents.domain.enums import RunStatus
from knowledge_agents.domain.errors import DomainError, ErrorCode
from knowledge_agents.domain.hashing import canonical_sha256
from knowledge_agents.entrypoints.worker import (
    MessageDisposition,
    Worker,
    WorkerConfig,
    parse_queue_envelope,
)
from knowledge_agents.ports.queue import QueueMessage


def message_body() -> str:
    return json.dumps(
        {
            "schema_version": "1",
            "run_id": "run-0123456789abcdef",
            "idempotency_key": "idempotency-key-1",
            "url": "https://example.com/source",
            "requested_at": "2026-07-18T00:00:00Z",
        }
    )


class SyncSqsClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def receive_message(self, **kwargs: Any) -> dict[str, object]:
        self.calls.append(("receive_message", kwargs))
        return {
            "Messages": [
                {
                    "MessageId": "message-1",
                    "ReceiptHandle": "receipt-1",
                    "Body": message_body(),
                    "Attributes": {"ApproximateReceiveCount": "2"},
                }
            ]
        }

    def change_message_visibility(self, **kwargs: Any) -> dict[str, object]:
        self.calls.append(("change_message_visibility", kwargs))
        return {}

    def delete_message(self, **kwargs: Any) -> dict[str, object]:
        self.calls.append(("delete_message", kwargs))
        return {}


class CompletingExecutor:
    def __init__(self, store: FakeRunStore) -> None:
        self.store = store
        self.calls: list[str] = []

    async def execute(
        self,
        request: AcquisitionRequest,
        *,
        run_id: str,
        idempotency_key: str,
    ) -> dict[str, str]:
        self.calls.append(run_id)
        await self.store.update_stage(
            run_id=run_id,
            stage="completed",
            status=RunStatus.COMPLETED,
        )
        return {"run_id": run_id}


def test_sqs_adapter_uses_designed_poll_visibility_and_ack_parameters() -> None:
    async def scenario() -> None:
        client = SyncSqsClient()
        queue = SqsQueue(client, queue_url="https://sqs.example.invalid/queue")

        messages = await queue.receive()
        await queue.extend_visibility(messages[0], seconds=180)
        await queue.acknowledge(messages[0])
        await queue.release(messages[0])

        assert messages[0].receive_count == 2
        assert client.calls == [
            (
                "receive_message",
                {
                    "QueueUrl": "https://sqs.example.invalid/queue",
                    "MaxNumberOfMessages": 1,
                    "WaitTimeSeconds": 20,
                    "VisibilityTimeout": 180,
                    "AttributeNames": ["ApproximateReceiveCount"],
                },
            ),
            (
                "change_message_visibility",
                {
                    "QueueUrl": "https://sqs.example.invalid/queue",
                    "ReceiptHandle": "receipt-1",
                    "VisibilityTimeout": 180,
                },
            ),
            (
                "delete_message",
                {
                    "QueueUrl": "https://sqs.example.invalid/queue",
                    "ReceiptHandle": "receipt-1",
                },
            ),
            (
                "change_message_visibility",
                {
                    "QueueUrl": "https://sqs.example.invalid/queue",
                    "ReceiptHandle": "receipt-1",
                    "VisibilityTimeout": 0,
                },
            ),
        ]

    asyncio.run(scenario())


def test_worker_revalidates_untrusted_body_and_releases_invalid_message() -> None:
    class UnexpectedExecutor:
        async def execute(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("invalid input must not start a run")

    async def scenario() -> None:
        invalid = message_body()[:-1] + ', "unexpected": true}'
        queue = FakeQueue([QueueMessage("message-1", "receipt-1", invalid, 1)])
        worker = Worker(
            queue=queue,
            run_store=FakeRunStore(),
            run_executor=UnexpectedExecutor(),
            config=WorkerConfig(worker_id="worker-1"),
        )

        assert await worker.run_once() == (MessageDisposition.INVALID,)
        assert queue.released == ["message-1"]
        assert queue.acknowledged == []

        duplicate_key = message_body().replace(
            '"schema_version": "1"',
            '"schema_version": "1", "schema_version": "1"',
        )
        with pytest.raises(DomainError) as captured:
            parse_queue_envelope(duplicate_key)
        assert captured.value.code is ErrorCode.INVALID_REQUEST

    asyncio.run(scenario())


def test_heartbeat_renews_sqlite_lease_before_extending_sqs_visibility() -> None:
    class GatedExecutor(CompletingExecutor):
        def __init__(self, store: FakeRunStore, finish: asyncio.Event) -> None:
            super().__init__(store)
            self.finish = finish

        async def execute(
            self,
            request: AcquisitionRequest,
            *,
            run_id: str,
            idempotency_key: str,
        ) -> dict[str, str]:
            self.calls.append(run_id)
            await self.finish.wait()
            await self.store.update_stage(
                run_id=run_id,
                stage="completed",
                status=RunStatus.COMPLETED,
            )
            return {"run_id": run_id}

    async def scenario() -> None:
        tick = asyncio.Event()
        finish = asyncio.Event()
        timeline: list[str] = []

        class TrackingStore(FakeRunStore):
            async def renew_lease(self, **kwargs: Any) -> bool:
                timeline.append("renew_lease")
                return await super().renew_lease(**kwargs)

        class TrackingQueue(FakeQueue):
            async def extend_visibility(
                self,
                message: QueueMessage,
                *,
                seconds: int,
            ) -> None:
                timeline.append("extend_visibility")
                await super().extend_visibility(message, seconds=seconds)

        async def wait(_: float) -> None:
            await tick.wait()
            tick.clear()

        queue = TrackingQueue([QueueMessage("message-1", "receipt-1", message_body(), 1)])
        store = TrackingStore()
        worker = Worker(
            queue=queue,
            run_store=store,
            run_executor=GatedExecutor(store, finish),
            config=WorkerConfig(
                worker_id="worker-1",
                heartbeat_seconds=60,
                lease_ttl_seconds=180,
            ),
            wait=wait,
        )
        processing = asyncio.create_task(worker.run_once())
        await asyncio.sleep(0)
        tick.set()
        for _ in range(20):
            if any(call.operation == "extend_visibility" for call in queue.calls):
                break
            await asyncio.sleep(0)
        finish.set()

        assert await processing == (MessageDisposition.ACKNOWLEDGED,)
        assert timeline[:2] == ["renew_lease", "extend_visibility"]
        assert any(
            call.operation == "extend_visibility" and call.arguments["seconds"] == 180
            for call in queue.calls
        )

    asyncio.run(scenario())


def test_lost_heartbeat_allows_redelivery_and_resume_without_early_ack() -> None:
    class CancelledExecutor:
        def __init__(self) -> None:
            self.cancelled = asyncio.Event()

        async def execute(self, *args: object, **kwargs: object) -> object:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled.set()
                raise

    async def scenario() -> None:
        async def immediate_wait(_: float) -> None:
            return None

        first_queue = FakeQueue([QueueMessage("message-1", "receipt-1", message_body(), 1)])
        store = FakeRunStore(failures={"renew_lease": RuntimeError("lease lost")})
        interrupted = CancelledExecutor()
        first_worker = Worker(
            queue=first_queue,
            run_store=store,
            run_executor=interrupted,
            config=WorkerConfig(worker_id="worker-1"),
            wait=immediate_wait,
        )

        assert await first_worker.run_once() == (MessageDisposition.HEARTBEAT_LOST,)
        assert interrupted.cancelled.is_set()
        assert first_queue.acknowledged == []
        assert first_queue.released == []

        store.failures.clear()
        second_queue = FakeQueue([QueueMessage("message-1", "receipt-2", message_body(), 2)])
        resumed = CompletingExecutor(store)
        second_worker = Worker(
            queue=second_queue,
            run_store=store,
            run_executor=resumed,
            config=WorkerConfig(worker_id="worker-2"),
        )

        assert await second_worker.run_once() == (MessageDisposition.ACKNOWLEDGED,)
        assert resumed.calls == ["run-0123456789abcdef"]
        assert second_queue.acknowledged == ["message-1"]

    asyncio.run(scenario())


def test_non_terminal_result_is_released_without_ack() -> None:
    class NonTerminalExecutor:
        async def execute(self, *args: object, **kwargs: object) -> object:
            return {"stage": "agent_1"}

    async def scenario() -> None:
        queue = FakeQueue([QueueMessage("message-1", "receipt-1", message_body(), 1)])
        worker = Worker(
            queue=queue,
            run_store=FakeRunStore(),
            run_executor=NonTerminalExecutor(),
            config=WorkerConfig(worker_id="worker-1"),
        )

        assert await worker.run_once() == (MessageDisposition.RELEASED,)
        assert queue.released == ["message-1"]
        assert queue.acknowledged == []

    asyncio.run(scenario())


def test_busy_lease_releases_delivery_without_starting_executor() -> None:
    class UnexpectedExecutor:
        async def execute(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("busy lease must prevent concurrent execution")

    async def scenario() -> None:
        envelope = parse_queue_envelope(message_body())
        request = envelope.acquisition_request()
        store = FakeRunStore()
        await store.create_or_get_run(
            run_id=envelope.run_id,
            idempotency_key=envelope.idempotency_key,
            request_hash=canonical_sha256(request),
        )
        assert await store.acquire_lease(
            run_id=envelope.run_id,
            owner="worker-already-running",
            ttl_seconds=180,
        )
        queue = FakeQueue([QueueMessage("message-1", "receipt-1", message_body(), 2)])
        worker = Worker(
            queue=queue,
            run_store=store,
            run_executor=UnexpectedExecutor(),
            config=WorkerConfig(worker_id="worker-2"),
        )

        assert await worker.run_once() == (MessageDisposition.LEASE_BUSY,)
        assert queue.released == ["message-1"]
        assert queue.acknowledged == []

    asyncio.run(scenario())


def test_shutdown_after_poll_releases_message_without_starting_a_run() -> None:
    class StopAfterReceiveQueue(FakeQueue):
        def __init__(self, stop: asyncio.Event) -> None:
            super().__init__([QueueMessage("message-1", "receipt-1", message_body(), 1)])
            self.stop = stop

        async def receive(self, *, max_messages: int = 1) -> tuple[QueueMessage, ...]:
            messages = await super().receive(max_messages=max_messages)
            self.stop.set()
            return messages

    class UnexpectedExecutor:
        async def execute(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("shutdown must not start a run")

    async def scenario() -> None:
        stop = asyncio.Event()
        queue = StopAfterReceiveQueue(stop)
        worker = Worker(
            queue=queue,
            run_store=FakeRunStore(),
            run_executor=UnexpectedExecutor(),
            config=WorkerConfig(worker_id="worker-1"),
        )

        await worker.run(stop)

        assert queue.released == ["message-1"]
        assert queue.acknowledged == []

    asyncio.run(scenario())
