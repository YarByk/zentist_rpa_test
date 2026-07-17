from pathlib import Path

import pytest

from portal_automation.core.models import ReasonCode
from portal_automation.core.retries import (
    NON_RETRYABLE_REASON_CODES,
    RETRYABLE_REASON_CODES,
    PortalError,
    RetryPolicy,
)

ROOT = Path(__file__).resolve().parents[2]


class FakeLogger:
    # Records retry telemetry so tests can verify exactly which retry events were emitted.
    def __init__(self) -> None:
        """Initialize this test helper instance.
        
        Returns:
            None. The test communicates success through assertions.
        
        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.calls: list[tuple[str, dict[str, object]]] = []

    def info(self, event: str, **kwargs: object) -> None:
        """Info.
        
        Args:
            event: Value supplied by the test or fixture for `event`.
            **kwargs: Value supplied by the test or fixture for `kwargs`.
        
        Returns:
            None. The test communicates success through assertions.
        
        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.calls.append((event, kwargs))


def test_portal_error_stores_reason_detail_and_default_attempts() -> None:
    """Verify that portal error stores reason detail and default attempts.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    error = PortalError(ReasonCode.PORTAL_TIMEOUT, "portal timed out")

    assert error.reason is ReasonCode.PORTAL_TIMEOUT
    assert error.detail == "portal timed out"
    assert error.attempts == 1


def test_portal_error_message_contains_reason_value_and_detail() -> None:
    """Verify that portal error message contains reason value and detail.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    error = PortalError(ReasonCode.LOCKED_OUT, "account is locked")

    assert str(error) == "LOCKED_OUT: account is locked"


def test_portal_error_rejects_raw_string_reason_codes() -> None:
    """Verify that portal error rejects raw string reason codes.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    with pytest.raises(TypeError, match="ReasonCode"):
        PortalError("PORTAL_TIMEOUT", "raw reason")  # type: ignore[arg-type]


def test_retry_policy_rejects_negative_max_retries() -> None:
    """Verify that retry policy rejects negative max retries.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    with pytest.raises(ValueError, match="max_retries"):
        RetryPolicy(max_retries=-1)


def test_retryable_portal_error_is_retried_and_eventually_succeeds() -> None:
    # A retryable error should be retried until the operation succeeds or attempts are exhausted.
    """Verify that retryable portal error is retried and eventually succeeds.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    attempts = 0

    def operation() -> str:
        """Operation.
        
        Returns:
            None. The test communicates success through assertions.
        
        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise PortalError(ReasonCode.PORTAL_TIMEOUT, "temporary timeout")
        return "ok"

    result, actual_attempts = RetryPolicy(max_retries=2).execute(operation)

    assert result == "ok"
    assert actual_attempts == 3
    assert attempts == 3


def test_retryable_portal_error_logs_each_retry_attempt() -> None:
    # The logger records the next attempt number, which is what operators need in run events.
    """Verify that retryable portal error logs each retry attempt.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    attempts = 0
    logger = FakeLogger()

    def operation() -> str:
        """Operation.
        
        Returns:
            None. The test communicates success through assertions.
        
        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise PortalError(ReasonCode.PORTAL_UNAVAILABLE, "temporary outage")
        return "ok"

    assert RetryPolicy(max_retries=2).execute(operation, logger=logger) == ("ok", 3)
    assert logger.calls == [
        (
            "retry_attempt",
            {"attempt": 2, "reason_code": ReasonCode.PORTAL_UNAVAILABLE.value},
        ),
        (
            "retry_attempt",
            {"attempt": 3, "reason_code": ReasonCode.PORTAL_UNAVAILABLE.value},
        ),
    ]


def test_exhausted_retryable_portal_error_reraises_final_error_with_attempts() -> None:
    # When all retries fail, the final raised PortalError should carry the final attempt count.
    """Verify that exhausted retryable portal error reraises final error with attempts.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    errors: list[PortalError] = []

    def operation() -> str:
        """Operation.
        
        Returns:
            None. The test communicates success through assertions.
        
        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        error = PortalError(ReasonCode.SESSION_DROPPED, "session dropped")
        errors.append(error)
        raise error

    with pytest.raises(PortalError) as exc_info:
        RetryPolicy(max_retries=2).execute(operation)

    assert exc_info.value is errors[-1]
    assert exc_info.value.reason is ReasonCode.SESSION_DROPPED
    assert exc_info.value.attempts == 3


def test_non_retryable_portal_error_is_not_retried() -> None:
    # Non-retryable business outcomes should fail immediately without repeating the operation.
    """Verify that non retryable portal error is not retried.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    attempts = 0

    def operation() -> str:
        """Operation.
        
        Returns:
            None. The test communicates success through assertions.
        
        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        nonlocal attempts
        attempts += 1
        raise PortalError(ReasonCode.LOCKED_OUT, "locked")

    with pytest.raises(PortalError) as exc_info:
        RetryPolicy(max_retries=5).execute(operation)

    assert attempts == 1
    assert exc_info.value.reason is ReasonCode.LOCKED_OUT
    assert exc_info.value.attempts == 1


def test_unknown_portal_error_reason_is_not_retried() -> None:
    """Verify that unknown portal error reason is not retried.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    attempts = 0

    def operation() -> str:
        """Operation.
        
        Returns:
            None. The test communicates success through assertions.
        
        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        nonlocal attempts
        attempts += 1
        raise PortalError(ReasonCode.UNEXPECTED_ERROR, "not classified")

    with pytest.raises(PortalError) as exc_info:
        RetryPolicy(max_retries=5).execute(operation)

    assert attempts == 1
    assert exc_info.value.reason is ReasonCode.UNEXPECTED_ERROR
    assert exc_info.value.attempts == 1


def test_unexpected_non_portal_error_is_not_caught_or_converted() -> None:
    """Verify that unexpected non portal error is not caught or converted.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    def operation() -> str:
        """Operation.
        
        Returns:
            None. The test communicates success through assertions.
        
        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        raise RuntimeError("unexpected")

    with pytest.raises(RuntimeError, match="unexpected"):
        RetryPolicy(max_retries=2).execute(operation)


def test_max_retries_zero_means_exactly_one_attempt() -> None:
    """Verify that max retries zero means exactly one attempt.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    attempts = 0

    def operation() -> str:
        """Operation.
        
        Returns:
            None. The test communicates success through assertions.
        
        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        nonlocal attempts
        attempts += 1
        raise PortalError(ReasonCode.PORTAL_TIMEOUT, "temporary timeout")

    with pytest.raises(PortalError) as exc_info:
        RetryPolicy(max_retries=0).execute(operation)

    assert attempts == 1
    assert exc_info.value.attempts == 1


def test_success_on_first_attempt_emits_no_retry_log() -> None:
    """Verify that success on first attempt emits no retry log.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    logger = FakeLogger()

    assert RetryPolicy(max_retries=2).execute(lambda: "ok", logger=logger) == ("ok", 1)
    assert logger.calls == []


def test_non_retryable_error_emits_no_retry_log() -> None:
    """Verify that non retryable error emits no retry log.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    logger = FakeLogger()

    def operation() -> str:
        """Operation.
        
        Returns:
            None. The test communicates success through assertions.
        
        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        raise PortalError(ReasonCode.CREDENTIAL_EXPIRED, "expired")

    with pytest.raises(PortalError):
        RetryPolicy(max_retries=2).execute(operation, logger=logger)

    assert logger.calls == []


def test_none_logger_does_not_fail_retryable_flow() -> None:
    """Verify that none logger does not fail retryable flow.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    attempts = 0

    def operation() -> str:
        """Operation.
        
        Returns:
            None. The test communicates success through assertions.
        
        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PortalError(ReasonCode.PORTAL_TIMEOUT, "temporary timeout")
        return "ok"

    assert RetryPolicy(max_retries=1).execute(operation, logger=None) == ("ok", 2)


def test_retryable_reason_codes_match_contract() -> None:
    """Verify that retryable reason codes match contract.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    assert RETRYABLE_REASON_CODES == {
        ReasonCode.PORTAL_TIMEOUT,
        ReasonCode.PORTAL_UNAVAILABLE,
        ReasonCode.SESSION_DROPPED,
    }


def test_non_retryable_reason_codes_match_contract() -> None:
    """Verify that non retryable reason codes match contract.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    assert NON_RETRYABLE_REASON_CODES == {
        ReasonCode.LOCKED_OUT,
        ReasonCode.INPUT_VALIDATION_FAILED,
        ReasonCode.EMPLOYEE_MATCH_AMBIGUOUS,
        ReasonCode.CREDENTIAL_EXPIRED,
    }


def test_forbidden_modules_were_not_created() -> None:
    """Verify that forbidden modules were not created.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    forbidden_paths = [
        "src/portal_automation/core/logging.py",
    ]

    assert [path for path in forbidden_paths if (ROOT / path).exists()] == []
