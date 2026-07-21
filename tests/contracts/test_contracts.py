from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from knowledge_agents.config import Settings
from knowledge_agents.domain.contracts import (
    AcquisitionRequest,
    ArtifactRef,
    SourceDescriptor,
    contract_version_matrix,
)
from knowledge_agents.domain.enums import AcquisitionMethod, SourceType
from knowledge_agents.domain.errors import DomainError, ErrorCode


def source_payload() -> dict[str, object]:
    return {
        "source_id": "source-1",
        "source_type": "web_article",
        "acquisition_method": "static_html",
        "canonical_ref": "https://example.com/article",
        "title": "Example article",
        "publisher": "Example Publisher",
        "retrieved_at": "2026-07-21T00:00:00Z",
        "content_hash": "a" * 64,
        "created_at": "2026-07-21T00:00:00Z",
    }


def test_external_request_requires_only_valid_http_url_and_ignores_extras() -> None:
    request = AcquisitionRequest.model_validate(
        {"url": "https://example.com/source", "future_metadata": {"accepted": True}}
    )

    assert str(request.url) == "https://example.com/source"
    assert request.run_id is None
    assert not hasattr(request, "future_metadata")


@pytest.mark.parametrize("url", ["not-a-url", "ftp://example.com/source"])
def test_external_request_rejects_invalid_or_unsupported_urls(url: str) -> None:
    with pytest.raises(ValidationError):
        AcquisitionRequest(url=url)


def test_internal_contracts_forbid_extra_fields_and_are_frozen() -> None:
    with pytest.raises(ValidationError):
        SourceDescriptor.model_validate({**source_payload(), "unexpected": True})

    source = SourceDescriptor.model_validate(source_payload())
    with pytest.raises(ValidationError):
        source.title = "Changed"


def test_contract_enums_and_aware_datetimes_are_typed() -> None:
    source = SourceDescriptor.model_validate(source_payload())

    assert source.source_type is SourceType.WEB_ARTICLE
    assert source.acquisition_method is AcquisitionMethod.STATIC_HTML
    assert source.retrieved_at == datetime(2026, 7, 21, tzinfo=UTC)


@pytest.mark.parametrize("path", ["../escape.json", "/absolute/file.json", "C:\\secret\\file.json"])
def test_artifact_refs_reject_paths_outside_the_relative_root(path: str) -> None:
    with pytest.raises(ValidationError):
        ArtifactRef(
            artifact_id="artifact-1",
            artifact_type="evidence",
            relative_path=path,
            content_hash="a" * 64,
            schema_version="1",
        )


def test_contract_version_matrix_covers_external_and_versioned_contracts() -> None:
    versions = contract_version_matrix()

    assert versions["AcquisitionRequest"] == "external"
    assert versions["SourceDescriptor"] == "1"
    assert versions["ContextBudget"] == "1"
    assert versions["RunManifest"] == "1"
    assert versions["RepairTask"] == "1"


def test_settings_use_approved_prefix_and_hide_secret_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KA_OPENAI_API_KEY", "secret-test-value")
    monkeypatch.setenv("OPENAI_MODEL_AGENT_1", "ignored-model")

    settings = Settings(_env_file=None)

    assert settings.openai_model_agent_1 == "gpt-5.6-terra"
    assert settings.openai_api_key is not None
    assert "secret-test-value" not in repr(settings)


def test_safe_error_representation_excludes_cause_secrets_and_absolute_paths() -> None:
    cause = RuntimeError("sk-private-value at C:\\Users\\private\\credentials.txt")
    error = DomainError(ErrorCode.ACCESS_DENIED, "provider.preflight", cause=cause)

    rendered = f"{error!r} {error} {error.safe_dict()}"

    assert "sk-private-value" not in rendered
    assert "C:\\Users\\private" not in rendered
    assert error.safe_dict()["retryable"] is False
