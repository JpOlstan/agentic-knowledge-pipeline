from enum import StrEnum
from typing import Any


class ErrorCategory(StrEnum):
    TRANSIENT = "transient"
    CONTRACT = "contract"
    PERMANENT = "permanent"
    SECONDARY = "secondary"


class ErrorCode(StrEnum):
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    QUEUE_UNAVAILABLE = "queue_unavailable"
    LLM_UNAVAILABLE = "llm_unavailable"
    CONTRACT_VALIDATION_FAILED = "contract_validation_failed"
    STRUCTURED_OUTPUT_INVALID = "structured_output_invalid"
    INVALID_REQUEST = "invalid_request"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    ACCESS_DENIED = "access_denied"
    SSRF_BLOCKED = "ssrf_blocked"
    PATH_TRAVERSAL_BLOCKED = "path_traversal_blocked"
    BUDGET_EXCEEDED = "budget_exceeded"
    INDEX_REPAIR_REQUIRED = "index_repair_required"
    TELEMETRY_REPAIR_REQUIRED = "telemetry_repair_required"

    @property
    def category(self) -> ErrorCategory:
        return _ERROR_CATEGORIES[self]

    @property
    def retryable(self) -> bool:
        return self.category is ErrorCategory.TRANSIENT


_ERROR_CATEGORIES: dict[ErrorCode, ErrorCategory] = {
    ErrorCode.PROVIDER_UNAVAILABLE: ErrorCategory.TRANSIENT,
    ErrorCode.QUEUE_UNAVAILABLE: ErrorCategory.TRANSIENT,
    ErrorCode.LLM_UNAVAILABLE: ErrorCategory.TRANSIENT,
    ErrorCode.CONTRACT_VALIDATION_FAILED: ErrorCategory.CONTRACT,
    ErrorCode.STRUCTURED_OUTPUT_INVALID: ErrorCategory.CONTRACT,
    ErrorCode.INVALID_REQUEST: ErrorCategory.PERMANENT,
    ErrorCode.IDEMPOTENCY_CONFLICT: ErrorCategory.PERMANENT,
    ErrorCode.ACCESS_DENIED: ErrorCategory.PERMANENT,
    ErrorCode.SSRF_BLOCKED: ErrorCategory.PERMANENT,
    ErrorCode.PATH_TRAVERSAL_BLOCKED: ErrorCategory.PERMANENT,
    ErrorCode.BUDGET_EXCEEDED: ErrorCategory.PERMANENT,
    ErrorCode.INDEX_REPAIR_REQUIRED: ErrorCategory.SECONDARY,
    ErrorCode.TELEMETRY_REPAIR_REQUIRED: ErrorCategory.SECONDARY,
}


class DomainError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        operation: str,
        *,
        cause: BaseException | None = None,
    ) -> None:
        self.code = code
        self.operation = operation
        self.cause = cause
        super().__init__(code.value, operation)

    def __str__(self) -> str:
        return f"{self.code.value} during {self.operation}"

    def safe_dict(self) -> dict[str, Any]:
        return {
            "category": self.code.category.value,
            "code": self.code.value,
            "operation": self.operation,
            "retryable": self.code.retryable,
        }
