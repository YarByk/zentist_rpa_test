from dataclasses import fields
from datetime import date

from portal_automation.core.models import (
    ItemResult,
    ItemStatus,
    ReasonCode,
    RunContext,
    RunResult,
    RunStatus,
)


def test_reason_code_values_match_contract() -> None:
    # ReasonCode values are stable serialized identifiers used in persistence and reports.
    """Verify that reason code values match contract.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    expected = {
        "LOGIN_FAILED": "LOGIN_FAILED",
        "LOCKED_OUT": "LOCKED_OUT",
        "CREDENTIAL_EXPIRED": "CREDENTIAL_EXPIRED",
        "PORTAL_TIMEOUT": "PORTAL_TIMEOUT",
        "PORTAL_UNAVAILABLE": "PORTAL_UNAVAILABLE",
        "SESSION_DROPPED": "SESSION_DROPPED",
        "INPUT_VALIDATION_FAILED": "INPUT_VALIDATION_FAILED",
        "EMPLOYEE_NOT_FOUND": "EMPLOYEE_NOT_FOUND",
        "EMPLOYEE_MATCH_AMBIGUOUS": "EMPLOYEE_MATCH_AMBIGUOUS",
        "SEARCH_FAILED": "SEARCH_FAILED",
        "ITEM_NOT_FOUND": "ITEM_NOT_FOUND",
        "VALIDATION_FAILED": "VALIDATION_FAILED",
        "UPLOAD_FAILED": "UPLOAD_FAILED",
        "DOCUMENT_GENERATION_FAILED": "DOCUMENT_GENERATION_FAILED",
        "CHECKOUT_FAILED": "CHECKOUT_FAILED",
        "LAYOUT_CHANGED": "LAYOUT_CHANGED",
        "UNEXPECTED_ERROR": "UNEXPECTED_ERROR",
    }

    assert {reason.name: reason.value for reason in ReasonCode} == expected
    assert ReasonCode.ITEM_NOT_FOUND.value == "ITEM_NOT_FOUND"


def test_item_status_values_match_contract() -> None:
    """Verify that item status values match contract.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    expected = {
        "SUCCESS": "success",
        "FAILED": "failed",
        "SKIPPED": "skipped",
        "IN_PROGRESS": "in_progress",
    }

    assert {status.name: status.value for status in ItemStatus} == expected


def test_run_status_values_match_contract() -> None:
    """Verify that run status values match contract.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    expected = {
        "RUNNING": "running",
        "SUCCESS": "success",
        "PARTIAL_SUCCESS": "partial_success",
        "FAILED": "failed",
        "STALE": "stale",
    }

    assert {status.name: status.value for status in RunStatus} == expected


def test_item_result_can_be_created_with_required_fields() -> None:
    """Verify that item result can be created with required fields.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    result = ItemResult(
        item_key="employee-100",
        operation="sync_employee_state",
        status=ItemStatus.FAILED,
        reason_code=ReasonCode.EMPLOYEE_NOT_FOUND,
        error_detail="employee was not found",
        artifact_path="artifacts/run/item.txt",
        attempts=2,
        details={"employee_id": "100"},
    )

    assert result.item_key == "employee-100"
    assert result.operation == "sync_employee_state"
    assert result.status is ItemStatus.FAILED
    assert result.reason_code is ReasonCode.EMPLOYEE_NOT_FOUND
    assert result.error_detail == "employee was not found"
    assert result.artifact_path == "artifacts/run/item.txt"
    assert result.attempts == 2
    assert result.details == {"employee_id": "100"}


def test_item_result_uses_conservative_defaults() -> None:
    """Verify that item result uses conservative defaults.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    result = ItemResult(
        item_key="account-1",
        operation="checkout",
        status=ItemStatus.SUCCESS,
        reason_code=None,
        error_detail=None,
        artifact_path=None,
    )

    assert result.attempts == 1
    assert result.details == {}


def test_run_result_can_be_created_with_item_results() -> None:
    """Verify that run result can be created with item results.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    item_result = ItemResult(
        item_key="account-1",
        operation="checkout",
        status=ItemStatus.SUCCESS,
        reason_code=None,
        error_detail=None,
        artifact_path=None,
    )
    run_result = RunResult(
        run_id="run-1",
        portal_name="saucedemo",
        business_date=date(2026, 6, 28),
        status=RunStatus.SUCCESS,
        results=[item_result],
    )

    assert run_result.run_id == "run-1"
    assert run_result.portal_name == "saucedemo"
    assert run_result.business_date == date(2026, 6, 28)
    assert run_result.status is RunStatus.SUCCESS
    assert run_result.results == [item_result]


def test_run_context_can_be_created_with_required_runtime_dependencies() -> None:
    """Verify that run context can be created with required runtime dependencies.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    context = RunContext(
        run_id="run-1",
        business_date=date(2026, 6, 28),
        dry_run=True,
        stale_item_timeout_seconds=300,
        config={"sentinel": "config"},
        persistence={"sentinel": "persistence"},
        reporter={"sentinel": "reporter"},
        logger={"sentinel": "logger"},
        metrics={"sentinel": "metrics"},
        artifacts={"sentinel": "artifacts"},
        email={"sentinel": "email"},
    )

    assert context.run_id == "run-1"
    assert context.business_date == date(2026, 6, 28)
    assert context.dry_run is True
    assert context.stale_item_timeout_seconds == 300
    assert context.config == {"sentinel": "config"}
    assert context.persistence == {"sentinel": "persistence"}
    assert context.reporter == {"sentinel": "reporter"}
    assert context.logger == {"sentinel": "logger"}
    assert context.metrics == {"sentinel": "metrics"}
    assert context.artifacts == {"sentinel": "artifacts"}
    assert context.email == {"sentinel": "email"}


def test_dataclass_fields_match_contract() -> None:
    # Field order is part of the lightweight data contract used across tests and repr checks.
    """Verify that dataclass fields match contract.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    assert [field.name for field in fields(RunContext)] == [
        "run_id",
        "business_date",
        "dry_run",
        "stale_item_timeout_seconds",
        "config",
        "persistence",
        "reporter",
        "logger",
        "metrics",
        "artifacts",
        "email",
    ]
    assert [field.name for field in fields(ItemResult)] == [
        "item_key",
        "operation",
        "status",
        "reason_code",
        "error_detail",
        "artifact_path",
        "attempts",
        "details",
    ]
    assert [field.name for field in fields(RunResult)] == [
        "run_id",
        "portal_name",
        "business_date",
        "status",
        "results",
    ]


def test_item_result_repr_excludes_sensitive_operational_fields() -> None:
    # repr() should stay safe for logs and assertion failures when details contain secrets.
    """Verify that item result repr excludes sensitive operational fields.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    result = ItemResult(
        item_key="employee-100",
        operation="sync_employee_state",
        status=ItemStatus.FAILED,
        reason_code=ReasonCode.UNEXPECTED_ERROR,
        error_detail="token-value",
        artifact_path=None,
        details={"password": "token-value"},
    )

    result_repr = repr(result)

    assert "token-value" not in result_repr
    assert "password" not in result_repr


def test_run_context_repr_excludes_runtime_dependency_fields() -> None:
    # Runtime collaborators are hidden because they may carry credentials or large objects.
    """Verify that run context repr excludes runtime dependency fields.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    context = RunContext(
        run_id="run-1",
        business_date=date(2026, 6, 28),
        dry_run=True,
        stale_item_timeout_seconds=300,
        config={"password": "token-value"},
        persistence={"password": "token-value"},
        reporter={"password": "token-value"},
        logger={"password": "token-value"},
        metrics={"password": "token-value"},
        artifacts={"password": "token-value"},
        email={"password": "token-value"},
    )

    context_repr = repr(context)

    assert "token-value" not in context_repr
    assert "password" not in context_repr


def test_forbidden_modules_were_not_created() -> None:
    """Verify that forbidden modules were not created.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    root = __import__("pathlib").Path(__file__).resolve().parents[2]
    forbidden_paths = [
        "src/portal_automation/core/logging.py",
    ]

    assert [path for path in forbidden_paths if (root / path).exists()] == []
