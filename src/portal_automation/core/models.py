from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any


class ReasonCode(str, Enum):  # noqa: UP042
    # -------------------------------------------------------------------------
    # Canonical machine-readable reasons used across workflows, reports, and
    # recovery logic. These values are stable identifiers, not UI copy.
    # -------------------------------------------------------------------------
    LOGIN_FAILED = "LOGIN_FAILED"
    LOCKED_OUT = "LOCKED_OUT"
    CREDENTIAL_EXPIRED = "CREDENTIAL_EXPIRED"
    PORTAL_TIMEOUT = "PORTAL_TIMEOUT"
    PORTAL_UNAVAILABLE = "PORTAL_UNAVAILABLE"
    SESSION_DROPPED = "SESSION_DROPPED"
    INPUT_VALIDATION_FAILED = "INPUT_VALIDATION_FAILED"
    EMPLOYEE_NOT_FOUND = "EMPLOYEE_NOT_FOUND"
    EMPLOYEE_MATCH_AMBIGUOUS = "EMPLOYEE_MATCH_AMBIGUOUS"
    SEARCH_FAILED = "SEARCH_FAILED"
    ITEM_NOT_FOUND = "ITEM_NOT_FOUND"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    UPLOAD_FAILED = "UPLOAD_FAILED"
    DOCUMENT_GENERATION_FAILED = "DOCUMENT_GENERATION_FAILED"
    CHECKOUT_FAILED = "CHECKOUT_FAILED"
    LAYOUT_CHANGED = "LAYOUT_CHANGED"
    UNEXPECTED_ERROR = "UNEXPECTED_ERROR"


class ItemStatus(str, Enum):  # noqa: UP042
    # Per-item execution state recorded in reports and stored results.
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    IN_PROGRESS = "in_progress"


class RunStatus(str, Enum):  # noqa: UP042
    # Top-level run state used for summaries, CLI exit decisions, and recovery.
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"
    STALE = "stale"


@dataclass
class RunContext:
    # -------------------------------------------------------------------------
    # Shared runtime bundle passed through the orchestration and workflow layers.
    # The context keeps all cross-cutting services together so hooks can stay
    # focused on business logic instead of constructor plumbing.
    # -------------------------------------------------------------------------
    run_id: str
    business_date: date
    dry_run: bool
    stale_item_timeout_seconds: int
    config: Any = field(repr=False)
    persistence: Any = field(repr=False)
    reporter: Any = field(repr=False)
    logger: Any = field(repr=False)
    metrics: Any = field(repr=False)
    artifacts: Any = field(repr=False)
    email: Any = field(repr=False)


@dataclass
class ItemResult:
    # One finalized or in-progress business item outcome.
    item_key: str
    operation: str
    status: ItemStatus
    reason_code: ReasonCode | None
    error_detail: str | None = field(repr=False)
    artifact_path: str | None
    attempts: int = 1
    details: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass
class RunResult:
    # Final summary object returned by a portal run.
    run_id: str
    portal_name: str
    business_date: date
    status: RunStatus
    results: list[ItemResult]
