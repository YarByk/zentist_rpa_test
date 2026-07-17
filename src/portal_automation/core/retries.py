from collections.abc import Callable
from typing import Any, TypeVar

from portal_automation.core.models import ReasonCode

T = TypeVar("T")

RETRYABLE_REASON_CODES = frozenset(
    {
        ReasonCode.PORTAL_TIMEOUT,
        ReasonCode.PORTAL_UNAVAILABLE,
        ReasonCode.SESSION_DROPPED,
    }
)

NON_RETRYABLE_REASON_CODES = frozenset(
    {
        ReasonCode.LOCKED_OUT,
        ReasonCode.INPUT_VALIDATION_FAILED,
        ReasonCode.EMPLOYEE_MATCH_AMBIGUOUS,
        ReasonCode.CREDENTIAL_EXPIRED,
    }
)


class PortalError(Exception):
    reason: ReasonCode
    detail: str
    attempts: int

    def __init__(self, reason: ReasonCode, detail: str, attempts: int = 1) -> None:
        """Create a portal-domain exception.

        Args:
            reason: Structured reason code for the failure.
            detail: Human-readable failure detail.
            attempts: Number of attempts represented by this error.

        Raises:
            TypeError: If ``reason`` is not a ``ReasonCode``.
        """
        if not isinstance(reason, ReasonCode):
            raise TypeError("reason must be a ReasonCode")
        self.reason = reason
        self.detail = detail
        self.attempts = attempts
        super().__init__(f"{reason.value}: {detail}")


class RetryPolicy:
    def __init__(self, max_retries: int) -> None:
        """Create a retry policy.

        Args:
            max_retries: Number of retries after the initial attempt.

        Raises:
            ValueError: If ``max_retries`` is negative.
        """
        if max_retries < 0:
            raise ValueError("max_retries must be greater than or equal to 0")
        self.max_retries = max_retries

    def execute(self, operation: Callable[[], T], logger: Any | None = None) -> tuple[T, int]:
        """Run an operation with retry handling for retryable ``PortalError`` values.

        Args:
            operation: Zero-argument callable to execute.
            logger: Optional object with ``info(event, **kwargs)`` for retry telemetry.

        Returns:
            Tuple of the operation result and the number of attempts used.

        Raises:
            PortalError: If a non-retryable error occurs or retries are exhausted.
            Exception: Any non-``PortalError`` raised by ``operation`` is propagated unchanged.
        """
        max_attempts = self.max_retries + 1
        for attempt in range(1, max_attempts + 1):
            try:
                return operation(), attempt
            except PortalError as error:
                error.attempts = attempt
                if error.reason not in RETRYABLE_REASON_CODES or attempt >= max_attempts:
                    raise
                # Log the next attempt number so telemetry reflects the retry that will happen next.
                self._log_retry(logger, attempt + 1, error.reason)

        raise RuntimeError("retry policy ended without result")

    def _log_retry(self, logger: Any | None, next_attempt_number: int, reason: ReasonCode) -> None:
        """Emit a best-effort retry event.

        Args:
            logger: Optional object with an ``info`` method.
            next_attempt_number: Attempt number that will run next.
            reason: Reason code that triggered the retry.
        """
        if logger is None or not hasattr(logger, "info"):
            return
        logger.info(
            "retry_attempt",
            attempt=next_attempt_number,
            reason_code=reason.value,
        )


def is_retryable_error(error: PortalError) -> bool:
    """Return whether a ``PortalError`` reason is retryable.

    Args:
        error: Portal error to classify.

    Returns:
        ``True`` when the reason belongs to ``RETRYABLE_REASON_CODES``.
    """
    return error.reason in RETRYABLE_REASON_CODES


def execute_with_context_retry(
    context: Any,
    operation: Callable[[], T],
) -> tuple[T, int]:
    """Execute an operation using retry settings from a runtime context.

    Args:
        context: Object with optional ``config.max_retries`` and ``logger`` attributes.
        operation: Zero-argument callable to execute.

    Returns:
        Tuple of the operation result and the number of attempts used.

    Raises:
        PortalError: If retry handling ultimately fails with a portal-domain error.
        Exception: Any non-``PortalError`` raised by ``operation`` is propagated unchanged.
    """
    config = getattr(context, "config", None)
    max_retries = getattr(config, "max_retries", 0)
    logger = getattr(context, "logger", None)
    return RetryPolicy(max_retries=max_retries).execute(operation, logger=logger)
