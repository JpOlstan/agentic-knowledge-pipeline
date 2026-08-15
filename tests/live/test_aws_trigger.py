from __future__ import annotations

import json
import os
import time
from uuid import uuid4

import boto3
import httpx
import pytest
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest


@pytest.mark.live
def test_signed_aws_trigger_reaches_dev_queue_and_cleans_up_message() -> None:
    if os.getenv("KA_RUN_LIVE_AWS") != "1":
        pytest.skip("set KA_RUN_LIVE_AWS=1 for the explicitly authorized AWS smoke test")
    function_url = os.getenv("KA_LAMBDA_FUNCTION_URL")
    queue_url = os.getenv("KA_SQS_QUEUE_URL")
    if not function_url or not queue_url:
        pytest.skip("AWS live smoke configuration is incomplete")

    region = os.getenv("KA_AWS_REGION", "us-east-1")
    profile = os.getenv("KA_AWS_PROFILE") or None
    session = boto3.Session(profile_name=profile, region_name=region)
    credentials = session.get_credentials()
    if credentials is None:
        pytest.skip("temporary AWS credentials are required for the authorized live smoke test")

    run_id = f"run-live-{uuid4().hex}"
    idempotency_key = f"live-{uuid4().hex}"
    payload = json.dumps(
        {
            "url": "https://example.com/knowledge-agents-live-smoke",
            "run_id": run_id,
            "idempotency_key": idempotency_key,
        },
        separators=(",", ":"),
    )
    request = AWSRequest(
        method="POST",
        url=function_url,
        data=payload,
        headers={"content-type": "application/json"},
    )
    SigV4Auth(credentials.get_frozen_credentials(), "lambda", region).add_auth(request)
    response = httpx.post(function_url, content=payload, headers=dict(request.headers), timeout=30)

    assert response.status_code == 202
    assert response.json()["run_id"] == run_id

    sqs = session.client("sqs")
    deadline = time.monotonic() + 30
    matched = False
    while time.monotonic() < deadline and not matched:
        received = sqs.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=10,
            WaitTimeSeconds=5,
            VisibilityTimeout=30,
        )
        for message in received.get("Messages", []):
            body = json.loads(message["Body"])
            if body.get("run_id") == run_id:
                sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=message["ReceiptHandle"])
                matched = True
            else:
                sqs.change_message_visibility(
                    QueueUrl=queue_url,
                    ReceiptHandle=message["ReceiptHandle"],
                    VisibilityTimeout=0,
                )
    assert matched
