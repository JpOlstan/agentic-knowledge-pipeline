from __future__ import annotations

import math
import re
from collections.abc import Mapping

from knowledge_agents.ports.telemetry import TelemetryEvent

ALLOWED_METADATA_KEYS = frozenset(
    {
        "agent",
        "collection",
        "contract_repaired",
        "cost_usd",
        "draft_count",
        "error_code",
        "evidence_count",
        "input_tokens",
        "issue_count",
        "latency_ms",
        "model",
        "outcome",
        "output_tokens",
        "point_count",
        "prompt_version",
        "provider_type",
        "revision_count",
        "score",
        "status",
        "target",
        "transition",
        "warning_count",
    }
)

_SECRET_PATTERN = re.compile(
    r"(?i)(?:bearer\s+\S+|(?:sk|pk)-[a-z0-9_-]{8,}|"
    r"(?:api[_-]?key|authorization|cookie|password|secret|session(?:id)?|token)"
    r"\s*[:=]\s*\S+)"
)
_URL_PATTERN = re.compile(r"(?i)https?://\S+")
_WINDOWS_PATH_PATTERN = re.compile(r"(?i)(?:[a-z]:[\\/]|\\\\)[^\s]+")
_POSIX_PATH_PATTERN = re.compile(r"(?<![a-z0-9:])/(?:[^\s/]+/)*[^\s/]+", re.I)
_SAFE_NAME_PATTERN = re.compile(r"[^a-z0-9_.-]+")


class RedactionPolicy:
    def __init__(self, *, max_string_length: int = 128) -> None:
        if max_string_length < 16:
            raise ValueError("max_string_length must be at least 16")
        self.max_string_length = max_string_length

    def sanitize_event(self, event: TelemetryEvent) -> TelemetryEvent:
        return TelemetryEvent(
            run_id=event.run_id,
            name=self.sanitize_name(event.name),
            occurred_at=event.occurred_at,
            attributes=self.sanitize_attributes(event.attributes),
            observation_type=event.observation_type,
        )

    def sanitize_name(self, value: str) -> str:
        if _contains_sensitive_value(value):
            return "telemetry.event"
        normalized = _SAFE_NAME_PATTERN.sub("-", value.strip().lower()).strip("-.")
        return normalized[:80] or "telemetry.event"

    def sanitize_attributes(
        self,
        attributes: Mapping[str, object],
    ) -> dict[str, str | int | float | bool]:
        sanitized: dict[str, str | int | float | bool] = {}
        for key in sorted(attributes):
            if key not in ALLOWED_METADATA_KEYS:
                continue
            value = self._sanitize_value(attributes[key])
            if value is not None:
                sanitized[key] = value
        return sanitized

    def _sanitize_value(self, value: object) -> str | int | float | bool | None:
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return value if math.isfinite(value) else None
        if not isinstance(value, str):
            return None
        if _SECRET_PATTERN.search(value):
            return "[REDACTED_SECRET]"
        if _URL_PATTERN.search(value):
            return "[REDACTED_URL]"
        if _WINDOWS_PATH_PATTERN.search(value) or _POSIX_PATH_PATTERN.search(value):
            return "[REDACTED_PATH]"
        return value[: self.max_string_length]


def _contains_sensitive_value(value: str) -> bool:
    return bool(
        _SECRET_PATTERN.search(value)
        or _URL_PATTERN.search(value)
        or _WINDOWS_PATH_PATTERN.search(value)
        or _POSIX_PATH_PATTERN.search(value)
    )
