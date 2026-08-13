from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from typing import Any, Protocol

from knowledge_agents.domain.errors import DomainError, ErrorCode
from knowledge_agents.ports.queue import QueueMessage, QueuePort

LONG_POLL_SECONDS = 20
INITIAL_VISIBILITY_SECONDS = 180
MAX_SQS_BATCH_SIZE = 10
MAX_VISIBILITY_SECONDS = 43_200


class SqsClient(Protocol):
    def receive_message(self, **kwargs: Any) -> Mapping[str, object]: ...

    def change_message_visibility(self, **kwargs: Any) -> object: ...

    def delete_message(self, **kwargs: Any) -> object: ...


class SqsQueue(QueuePort):
    """Async QueuePort over the synchronous boto3 SQS client."""

    def __init__(self, client: SqsClient, *, queue_url: str) -> None:
        if not queue_url.strip():
            raise ValueError("queue_url must not be empty")
        self._client = client
        self._queue_url = queue_url

    @classmethod
    def from_aws(
        cls,
        *,
        queue_url: str,
        region_name: str,
        profile_name: str | None = None,
    ) -> SqsQueue:
        try:
            import boto3

            session = boto3.Session(profile_name=profile_name, region_name=region_name)
            client = session.client("sqs")
        except Exception as exc:
            raise DomainError(ErrorCode.QUEUE_UNAVAILABLE, "sqs.configure", cause=exc) from exc
        return cls(client, queue_url=queue_url)

    async def receive(self, *, max_messages: int = 1) -> tuple[QueueMessage, ...]:
        if not 1 <= max_messages <= MAX_SQS_BATCH_SIZE:
            raise ValueError("max_messages must be between 1 and 10")
        response = await self._call(
            "sqs.receive",
            self._client.receive_message,
            QueueUrl=self._queue_url,
            MaxNumberOfMessages=max_messages,
            WaitTimeSeconds=LONG_POLL_SECONDS,
            VisibilityTimeout=INITIAL_VISIBILITY_SECONDS,
            AttributeNames=["ApproximateReceiveCount"],
        )
        if not isinstance(response, Mapping):
            raise DomainError(ErrorCode.QUEUE_UNAVAILABLE, "sqs.receive")
        raw_messages = response.get("Messages", [])
        if not isinstance(raw_messages, list):
            raise DomainError(ErrorCode.QUEUE_UNAVAILABLE, "sqs.receive")
        return tuple(self._parse_message(item) for item in raw_messages)

    async def extend_visibility(self, message: QueueMessage, *, seconds: int) -> None:
        if not 1 <= seconds <= MAX_VISIBILITY_SECONDS:
            raise ValueError("visibility seconds must be between 1 and 43200")
        await self._call(
            "sqs.extend_visibility",
            self._client.change_message_visibility,
            QueueUrl=self._queue_url,
            ReceiptHandle=message.receipt_handle,
            VisibilityTimeout=seconds,
        )

    async def acknowledge(self, message: QueueMessage) -> None:
        await self._call(
            "sqs.acknowledge",
            self._client.delete_message,
            QueueUrl=self._queue_url,
            ReceiptHandle=message.receipt_handle,
        )

    async def release(self, message: QueueMessage) -> None:
        await self._call(
            "sqs.release",
            self._client.change_message_visibility,
            QueueUrl=self._queue_url,
            ReceiptHandle=message.receipt_handle,
            VisibilityTimeout=0,
        )

    async def _call(
        self,
        operation: str,
        method: Callable[..., object],
        **kwargs: object,
    ) -> object:
        try:
            return await asyncio.to_thread(method, **kwargs)
        except DomainError:
            raise
        except Exception as exc:
            raise DomainError(ErrorCode.QUEUE_UNAVAILABLE, operation, cause=exc) from exc

    @staticmethod
    def _parse_message(value: object) -> QueueMessage:
        if not isinstance(value, Mapping):
            raise DomainError(ErrorCode.QUEUE_UNAVAILABLE, "sqs.receive")
        message_id = value.get("MessageId")
        receipt_handle = value.get("ReceiptHandle")
        body = value.get("Body")
        attributes = value.get("Attributes")
        if not all(isinstance(item, str) and item for item in (message_id, receipt_handle, body)):
            raise DomainError(ErrorCode.QUEUE_UNAVAILABLE, "sqs.receive")
        if not isinstance(attributes, Mapping):
            raise DomainError(ErrorCode.QUEUE_UNAVAILABLE, "sqs.receive")
        receive_count_value = attributes.get("ApproximateReceiveCount")
        try:
            receive_count = int(receive_count_value)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise DomainError(ErrorCode.QUEUE_UNAVAILABLE, "sqs.receive", cause=exc) from exc
        if receive_count < 1:
            raise DomainError(ErrorCode.QUEUE_UNAVAILABLE, "sqs.receive")
        return QueueMessage(
            message_id=message_id,
            receipt_handle=receipt_handle,
            body=body,
            receive_count=receive_count,
        )
