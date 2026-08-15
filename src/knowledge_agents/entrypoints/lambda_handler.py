from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
import os
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any, Protocol
from uuid import uuid4

from pydantic import ValidationError

from knowledge_agents.domain.contracts import AcquisitionRequest

MAX_REQUEST_BODY_BYTES = 16 * 1024
SCHEMA_VERSION = "1"


class SqsSender(Protocol):
    def send_message(self, **kwargs: Any) -> Mapping[str, object]: ...


class TriggerRequestError(ValueError):
    def __init__(self, status_code: int, code: str) -> None:
        self.status_code = status_code
        self.code = code
        super().__init__(code)


class LambdaTrigger:
    def __init__(
        self,
        *,
        queue: SqsSender,
        queue_url: str,
        now: Callable[[], datetime] | None = None,
        new_run_id: Callable[[], str] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        if not queue_url.strip():
            raise ValueError("queue_url must not be empty")
        self._queue = queue
        self._queue_url = queue_url
        self._now = now or (lambda: datetime.now(UTC))
        self._new_run_id = new_run_id or (lambda: f"run-{uuid4().hex}")
        self._logger = logger or logging.getLogger("knowledge_agents.lambda_trigger")

    def handle(self, event: Mapping[str, object]) -> dict[str, object]:
        if _http_method(event) != "POST":
            return _response(405, "method_not_allowed")
        try:
            payload = _request_payload(event)
            request = _validate_request(payload)
        except TriggerRequestError as exc:
            self._logger.warning(
                json.dumps(
                    {"component": "lambda_trigger", "error_code": exc.code, "status": "rejected"},
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            return _response(exc.status_code, exc.code)

        run_id, idempotency_key = _request_identifiers(request, self._new_run_id)
        requested_at = _as_utc(self._now()).isoformat().replace("+00:00", "Z")
        message = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "idempotency_key": idempotency_key,
            "url": str(request.url),
            "requested_at": requested_at,
        }
        try:
            self._queue.send_message(
                QueueUrl=self._queue_url,
                MessageBody=json.dumps(
                    message,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            )
        except Exception:
            self._logger.error(
                json.dumps(
                    {
                        "component": "lambda_trigger",
                        "error_code": "queue_unavailable",
                        "run_id": run_id,
                        "status": "failed",
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            return _response(503, "queue_unavailable", run_id=run_id)

        self._logger.info(
            json.dumps(
                {
                    "component": "lambda_trigger",
                    "hostname": request.url.host or "unknown",
                    "run_id": run_id,
                    "status": "accepted",
                },
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return _response(202, "accepted", run_id=run_id)


def lambda_handler(event: Mapping[str, object], context: object) -> dict[str, object]:
    del context
    try:
        return _default_trigger().handle(event)
    except Exception:
        logging.getLogger("knowledge_agents.lambda_trigger").error(
            '{"component":"lambda_trigger","error_code":"configuration_unavailable",'
            '"status":"failed"}'
        )
        return _response(503, "configuration_unavailable")


@lru_cache(maxsize=1)
def _default_trigger() -> LambdaTrigger:
    queue_url = os.getenv("KA_SQS_QUEUE_URL")
    if not queue_url:
        raise RuntimeError("KA_SQS_QUEUE_URL is required")
    import boto3

    return LambdaTrigger(queue=boto3.client("sqs"), queue_url=queue_url)


def _http_method(event: Mapping[str, object]) -> str:
    request_context = event.get("requestContext")
    if isinstance(request_context, Mapping):
        http = request_context.get("http")
        if isinstance(http, Mapping) and isinstance(http.get("method"), str):
            return str(http["method"]).upper()
    method = event.get("httpMethod")
    return method.upper() if isinstance(method, str) else ""


def _request_payload(event: Mapping[str, object]) -> dict[str, object]:
    body = event.get("body")
    if not isinstance(body, str):
        raise TriggerRequestError(400, "invalid_request")
    try:
        raw = (
            base64.b64decode(body, validate=True)
            if event.get("isBase64Encoded") is True
            else body.encode("utf-8")
        )
    except (UnicodeError, ValueError, binascii.Error) as exc:
        raise TriggerRequestError(400, "invalid_request") from exc
    if len(raw) > MAX_REQUEST_BODY_BYTES:
        raise TriggerRequestError(413, "request_too_large")
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise TriggerRequestError(400, "invalid_request") from exc
    if not isinstance(payload, dict):
        raise TriggerRequestError(400, "invalid_request")
    return payload


def _validate_request(payload: dict[str, object]) -> AcquisitionRequest:
    metadata = payload.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        raise TriggerRequestError(400, "invalid_request")
    if any(payload.get(field) not in (None, [], {}) for field in ("urls", "sources")):
        raise TriggerRequestError(400, "multiple_sources_not_supported")
    try:
        return AcquisitionRequest.model_validate(payload)
    except ValidationError as exc:
        raise TriggerRequestError(400, "invalid_request") from exc


def _request_identifiers(
    request: AcquisitionRequest,
    new_run_id: Callable[[], str],
) -> tuple[str, str]:
    if request.run_id is not None:
        run_id = request.run_id
    elif request.idempotency_key is not None:
        digest = hashlib.sha256(request.idempotency_key.encode("utf-8")).hexdigest()
        run_id = f"run-{digest[:32]}"
    else:
        run_id = new_run_id()
    idempotency_key = request.idempotency_key
    if idempotency_key is None:
        canonical = json.dumps(
            {"run_id": run_id, "url": str(request.url)},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        idempotency_key = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return run_id, idempotency_key


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("trigger timestamps must include a timezone")
    return value.astimezone(UTC)


def _response(status_code: int, status: str, *, run_id: str | None = None) -> dict[str, object]:
    payload = {"status": status}
    if run_id is not None:
        payload["run_id"] = run_id
    return {
        "statusCode": status_code,
        "headers": {"content-type": "application/json; charset=utf-8"},
        "body": json.dumps(payload, separators=(",", ":"), sort_keys=True),
    }
