from __future__ import annotations

import base64
import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from knowledge_agents.entrypoints.lambda_handler import (
    MAX_REQUEST_BODY_BYTES,
    LambdaTrigger,
)

RUN_ID = "run-0123456789abcdef"
IDEMPOTENCY_KEY = "idempotency-key-1"
NOW = datetime(2026, 7, 18, tzinfo=UTC)
TERRAFORM_ROOT = Path(__file__).parents[2] / "infra" / "terraform"
PACKAGE_SCRIPT = Path(__file__).parents[2] / "scripts" / "package_lambda.ps1"


class FakeSqsSender:
    def __init__(self, *, failure: BaseException | None = None) -> None:
        self.failure = failure
        self.calls: list[dict[str, Any]] = []

    def send_message(self, **kwargs: Any) -> dict[str, str]:
        self.calls.append(kwargs)
        if self.failure is not None:
            raise self.failure
        return {"MessageId": "message-1"}


def event(payload: object, *, method: str = "POST") -> dict[str, object]:
    return {
        "requestContext": {"http": {"method": method}},
        "body": json.dumps(payload),
        "isBase64Encoded": False,
    }


def trigger(queue: FakeSqsSender, *, logger: logging.Logger | None = None) -> LambdaTrigger:
    return LambdaTrigger(
        queue=queue,
        queue_url="https://sqs.example.invalid/queue",
        now=lambda: NOW,
        new_run_id=lambda: RUN_ID,
        logger=logger,
    )


def response_body(response: dict[str, object]) -> dict[str, object]:
    return json.loads(str(response["body"]))


def queued_body(queue: FakeSqsSender) -> dict[str, object]:
    return json.loads(queue.calls[0]["MessageBody"])


def test_minimal_request_generates_ids_and_publishes_small_versioned_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    queue = FakeSqsSender()
    logger = logging.getLogger("test.lambda.accepted")

    with caplog.at_level(logging.INFO, logger=logger.name):
        response = trigger(queue, logger=logger).handle(
            event({"url": "https://example.com/source"})
        )

    assert response["statusCode"] == 202
    assert response_body(response) == {"run_id": RUN_ID, "status": "accepted"}
    message = queued_body(queue)
    assert message == {
        "schema_version": "1",
        "run_id": RUN_ID,
        "idempotency_key": message["idempotency_key"],
        "url": "https://example.com/source",
        "requested_at": "2026-07-18T00:00:00Z",
    }
    assert len(str(message["idempotency_key"])) == 64
    assert queue.calls[0]["QueueUrl"] == "https://sqs.example.invalid/queue"
    assert "example.com/source" not in caplog.text
    assert '"hostname":"example.com"' in caplog.text


def test_supplied_ids_are_preserved_and_optional_metadata_is_not_forwarded() -> None:
    queue = FakeSqsSender()
    payload = {
        "url": "https://example.com/source",
        "run_id": RUN_ID,
        "idempotency_key": IDEMPOTENCY_KEY,
        "metadata": {"source": "manual", "priority": 1},
        "ignored_future_field": True,
    }

    response = trigger(queue).handle(event(payload))

    assert response["statusCode"] == 202
    message = queued_body(queue)
    assert message["run_id"] == RUN_ID
    assert message["idempotency_key"] == IDEMPOTENCY_KEY
    assert "metadata" not in message
    assert "ignored_future_field" not in message


def test_idempotency_key_without_run_id_generates_a_stable_run_id() -> None:
    first = FakeSqsSender()
    second = FakeSqsSender()
    payload = {"url": "https://example.com/source", "idempotency_key": IDEMPOTENCY_KEY}

    first_response = trigger(first).handle(event(payload))
    second_response = trigger(second).handle(event(payload))

    assert response_body(first_response)["run_id"] == response_body(second_response)["run_id"]
    assert queued_body(first)["run_id"] == queued_body(second)["run_id"]
    assert str(queued_body(first)["run_id"]).startswith("run-")


@pytest.mark.parametrize(
    ("payload", "status"),
    [
        ({}, "invalid_request"),
        ({"url": "not-a-url"}, "invalid_request"),
        ({"url": ["https://example.com"]}, "invalid_request"),
        ({"url": "https://example.com", "metadata": "private"}, "invalid_request"),
        (
            {"url": "https://example.com", "sources": ["https://other.example.com"]},
            "multiple_sources_not_supported",
        ),
    ],
)
def test_invalid_or_multi_source_request_is_rejected_before_sqs(
    payload: object,
    status: str,
) -> None:
    queue = FakeSqsSender()

    response = trigger(queue).handle(event(payload))

    assert response["statusCode"] == 400
    assert response_body(response) == {"status": status}
    assert queue.calls == []


def test_duplicate_json_keys_and_oversized_body_are_rejected() -> None:
    queue = FakeSqsSender()
    instance = trigger(queue)
    duplicate = {
        "requestContext": {"http": {"method": "POST"}},
        "body": '{"url":"https://example.com","url":"https://other.example.com"}',
        "isBase64Encoded": False,
    }
    oversized = {
        "requestContext": {"http": {"method": "POST"}},
        "body": "x" * (MAX_REQUEST_BODY_BYTES + 1),
        "isBase64Encoded": False,
    }

    assert instance.handle(duplicate)["statusCode"] == 400
    assert instance.handle(oversized)["statusCode"] == 413
    assert queue.calls == []


def test_base64_function_url_body_is_supported() -> None:
    queue = FakeSqsSender()
    body = json.dumps({"url": "https://example.com/source"}).encode()
    encoded_event = {
        "requestContext": {"http": {"method": "POST"}},
        "body": base64.b64encode(body).decode(),
        "isBase64Encoded": True,
    }

    response = trigger(queue).handle(encoded_event)

    assert response["statusCode"] == 202
    assert len(queue.calls) == 1


def test_non_post_method_is_rejected_without_sqs() -> None:
    queue = FakeSqsSender()

    response = trigger(queue).handle(event({"url": "https://example.com"}, method="GET"))

    assert response["statusCode"] == 405
    assert queue.calls == []


def test_queue_failure_is_sanitized_and_returns_recoverable_status(
    caplog: pytest.LogCaptureFixture,
) -> None:
    queue = FakeSqsSender(failure=RuntimeError("https://example.com/private?token=secret"))
    logger = logging.getLogger("test.lambda.failure")

    with caplog.at_level(logging.ERROR, logger=logger.name):
        response = trigger(queue, logger=logger).handle(
            event({"url": "https://example.com/private?token=secret"})
        )

    assert response["statusCode"] == 503
    assert response_body(response) == {"run_id": RUN_ID, "status": "queue_unavailable"}
    assert "example.com/private" not in caplog.text
    assert "token=secret" not in caplog.text


def test_terraform_models_the_designed_queue_redrive_and_monitoring() -> None:
    queues = (TERRAFORM_ROOT / "queues.tf").read_text(encoding="utf-8")
    monitoring = (TERRAFORM_ROOT / "monitoring.tf").read_text(encoding="utf-8")

    assert "receive_wait_time_seconds  = 20" in queues
    assert "visibility_timeout_seconds = 180" in queues
    assert "message_retention_seconds  = 345600" in queues
    assert "message_retention_seconds = 1209600" in queues
    assert "maxReceiveCount     = 5" in queues
    assert 'redrivePermission = "byQueue"' in queues
    assert 'metric_name         = "ApproximateNumberOfMessagesVisible"' in monitoring
    assert 'metric_name         = "ApproximateAgeOfOldestMessage"' in monitoring


def test_terraform_iam_is_least_privilege_and_uses_both_function_url_actions() -> None:
    iam = (TERRAFORM_ROOT / "iam.tf").read_text(encoding="utf-8")
    execution = iam.split('data "aws_iam_policy_document" "lambda_execution"', 1)[1].split(
        'resource "aws_iam_role_policy"', 1
    )[0]
    execution_actions = set(re.findall(r'"((?:logs|sqs):[A-Za-z]+)"', execution))

    assert execution_actions == {
        "logs:CreateLogStream",
        "logs:PutLogEvents",
        "sqs:SendMessage",
    }
    assert 'actions   = ["lambda:InvokeFunctionUrl"]' in iam
    assert 'variable = "lambda:FunctionUrlAuthType"' in iam
    assert 'values   = ["AWS_IAM"]' in iam
    assert 'actions   = ["lambda:InvokeFunction"]' in iam
    assert 'variable = "lambda:InvokedViaFunctionUrl"' in iam
    assert 'resources = ["*"]' not in iam


def test_terraform_uses_authenticated_url_sensitive_outputs_and_local_ignored_state() -> None:
    lambda_configuration = (TERRAFORM_ROOT / "lambda.tf").read_text(encoding="utf-8")
    outputs = (TERRAFORM_ROOT / "outputs.tf").read_text(encoding="utf-8")
    gitignore = (TERRAFORM_ROOT.parents[1] / ".gitignore").read_text(encoding="utf-8")

    assert 'authorization_type = "AWS_IAM"' in lambda_configuration
    assert 'runtime          = "python3.12"' in lambda_configuration
    assert outputs.count("sensitive   = true") == 3
    assert ".terraform/" in gitignore
    assert "*.tfstate" in gitignore


def test_lambda_package_script_pins_from_lock_and_includes_internal_dependencies() -> None:
    script = PACKAGE_SCRIPT.read_text(encoding="utf-8")

    assert "Get-Content -Raw -LiteralPath $lockPath" in script
    assert '"knowledge_agents/domain/contracts.py"' in script
    assert '"knowledge_agents/domain/budgets.py"' in script
    assert '"knowledge_agents/domain/enums.py"' in script
    assert '"knowledge_agents/domain/errors.py"' in script
    assert "$entry.LastWriteTime = $fixedTimestamp" in script
    assert '"x86_64-manylinux2014"' in script
    assert "OutputPath must stay inside the repository dist directory" in script
