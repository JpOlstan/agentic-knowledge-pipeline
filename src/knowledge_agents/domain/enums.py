from enum import StrEnum


class AgentRole(StrEnum):
    ACQUISITION = "agent_1"
    CURATION = "agent_2"
    VALIDATION = "agent_3"


class SourceType(StrEnum):
    NOTEBOOKLM = "notebooklm"
    WEB_ARTICLE = "web_article"


class AcquisitionMethod(StrEnum):
    NOTEBOOKLM_MCP = "notebooklm_mcp"
    STATIC_HTML = "static_html"


class ClaimClassification(StrEnum):
    DURABLE = "durable"
    VERSIONED = "versioned"
    UNSUPPORTED = "unsupported"


class CurationAction(StrEnum):
    CREATE = "create"
    MERGE = "merge"
    DEFER = "defer"
    DISCARD = "discard"


class DraftStatus(StrEnum):
    READY = "ready"
    PARTIALLY_READY = "partially_ready"
    ENRICHMENT_REQUIRED = "enrichment_required"
    REJECTED = "rejected"


class TerminalRecommendation(StrEnum):
    READY = "ready"
    PARTIALLY_READY = "partially_ready"
    ENRICHMENT_REQUIRED = "enrichment_required"
    REJECTED = "rejected"


class RunOutcome(StrEnum):
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    ENRICHMENT_REQUIRED = "enrichment_required"
    REJECTED = "rejected"
    FAILED = "failed"


class RunStatus(StrEnum):
    RECEIVED = "received"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    ENRICHMENT_REQUIRED = "enrichment_required"
    REJECTED = "rejected"
    FAILED = "failed"


class IndexStatus(StrEnum):
    PENDING = "pending"
    INDEXED = "indexed"
    FAILED = "failed"


class RepairTarget(StrEnum):
    QDRANT = "qdrant"
    LANGFUSE = "langfuse"


class BudgetDimension(StrEnum):
    INPUT_PER_CALL = "input_per_call"
    OUTPUT_PER_CALL = "output_per_call"
    CALL_COUNT = "call_count"
    INPUT_TOTAL = "input_total"
    OUTPUT_TOTAL = "output_total"
    COST_TOTAL = "cost_total"
    DURATION_TOTAL = "duration_total"
