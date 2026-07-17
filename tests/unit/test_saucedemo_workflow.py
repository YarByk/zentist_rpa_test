from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from portal_automation.core.models import ItemStatus, ReasonCode
from portal_automation.core.retries import PortalError
from portal_automation.portals.saucedemo.input_schema import CheckoutProfile, SauceDemoAccount
from portal_automation.portals.saucedemo.workflow import (
    LoginResult,
    LoginStatus,
    OrderSummary,
    process_account,
)

ROOT = Path(__file__).resolve().parents[2]


class FakePages:
    # -------------------------------------------------------------------------
    # Stateful fake implementation of the SauceDemo page protocol.
    # Tests can control cart counts, summaries, confirmations, captured details,
    # and queued method failures while still asserting the exact call order.
    # -------------------------------------------------------------------------
    def __init__(
        self,
        login_result: LoginResult | None = None,
        cart_count: int | None = None,
        cart_counts: list[int] | None = None,
        order_summary: OrderSummary | None = None,
        confirmation: OrderSummary | None = None,
        captured_details: dict[str, Any] | None = None,
        raise_on: str | None = None,
        failures: dict[str, list[Exception]] | None = None,
    ) -> None:
        """Initialize this test helper instance.
        
        Args:
            login_result: Value supplied by the test or fixture for `login_result`.
            cart_count: Value supplied by the test or fixture for `cart_count`.
            cart_counts: Value supplied by the test or fixture for `cart_counts`.
            order_summary: Value supplied by the test or fixture for `order_summary`.
            confirmation: Value supplied by the test or fixture for `confirmation`.
            captured_details: Value supplied by the test or fixture for `captured_details`.
            raise_on: Value supplied by the test or fixture for `raise_on`.
            failures: Value supplied by the test or fixture for `failures`.
        
        Returns:
            None. The test communicates success through assertions.
        
        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.login_result = login_result or LoginResult.success()
        self.cart_count = 0 if cart_count is None else cart_count
        self.cart_counts = list(cart_counts) if cart_counts is not None else None
        self.order_summary = order_summary
        self.confirmation = confirmation
        self.captured_details = captured_details or {
            "order_id": "order-123",
            "total": "$49.99",
        }
        self.raise_on = raise_on
        self.failures = {key: list(value) for key, value in (failures or {}).items()}
        self.calls: list[tuple[str, Any]] = []
        self.login_password: str | None = None

    def login(self, username: str, password: str) -> LoginResult:
        """Login.
        
        Args:
            username: Value supplied by the test or fixture for `username`.
            password: Value supplied by the test or fixture for `password`.
        
        Returns:
            None. The test communicates success through assertions.
        
        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.calls.append(("login", username))
        self.login_password = password
        self._raise_if_configured("login")
        return self.login_result

    def add_inventory_items(self, count: int) -> None:
        """Add inventory items.
        
        Args:
            count: Value supplied by the test or fixture for `count`.
        
        Returns:
            None. The test communicates success through assertions.
        
        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.calls.append(("add_inventory_items", count))
        self._raise_if_configured("add_inventory_items")
        self.cart_count += count

    def read_cart_count(self) -> int:
        """Read cart count.
        
        Returns:
            None. The test communicates success through assertions.
        
        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.calls.append(("read_cart_count", None))
        self._raise_if_configured("read_cart_count")
        if self.cart_counts:
            self.cart_count = self.cart_counts.pop(0)
        return self.cart_count

    def open_cart(self) -> None:
        """Open cart.
        
        Returns:
            None. The test communicates success through assertions.
        
        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.calls.append(("open_cart", None))
        self._raise_if_configured("open_cart")

    def checkout(self, profile: CheckoutProfile) -> None:
        """Checkout.
        
        Args:
            profile: Value supplied by the test or fixture for `profile`.
        
        Returns:
            None. The test communicates success through assertions.
        
        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.calls.append(("checkout", profile))
        self._raise_if_configured("checkout")

    def read_order_summary(self) -> OrderSummary:
        """Read order summary.
        
        Returns:
            None. The test communicates success through assertions.
        
        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.calls.append(("read_order_summary", None))
        self._raise_if_configured("read_order_summary")
        return self.order_summary or OrderSummary(
            item_count=account().items_to_add,
            confirmation_text="Ready to finish",
        )

    def finish_order(self) -> None:
        """Finish order.
        
        Returns:
            None. The test communicates success through assertions.
        
        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.calls.append(("finish_order", None))
        self._raise_if_configured("finish_order")

    def read_confirmation(self) -> OrderSummary:
        """Read confirmation.
        
        Returns:
            None. The test communicates success through assertions.
        
        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.calls.append(("read_confirmation", None))
        self._raise_if_configured("read_confirmation")
        return self.confirmation or OrderSummary(
            item_count=account().items_to_add,
            confirmation_text="Thank you for your order!",
            order_id="order-123",
            total="$49.99",
        )

    def capture_order_details(self) -> dict[str, Any]:
        """Capture order details.
        
        Returns:
            None. The test communicates success through assertions.
        
        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.calls.append(("capture_order_details", None))
        self._raise_if_configured("capture_order_details")
        return self.captured_details

    def _raise_if_configured(self, method_name: str) -> None:
        """Raise if configured.
        
        Args:
            method_name: Value supplied by the test or fixture for `method_name`.
        
        Returns:
            None. The test communicates success through assertions.
        
        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        queued = self.failures.get(method_name)
        if queued:
            error = queued.pop(0)
            raise error
        if self.raise_on == method_name:
            raise PortalError(ReasonCode.PORTAL_TIMEOUT, f"{method_name} timed out")


def account(items_to_add: int = 3) -> SauceDemoAccount:
    # Canonical account fixture used by the workflow tests.
    """Account.
    
    Args:
        items_to_add: Value supplied by the test or fixture for `items_to_add`.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    return SauceDemoAccount(
        account_key="standard_user",
        username="standard_user",
        items_to_add=items_to_add,
        checkout_profile=CheckoutProfile(
            first_name="Standard",
            last_name="User",
            postal_code="10001",
        ),
    )


def make_context(password: str | None = "test_pw") -> SimpleNamespace:
    # Workflow only needs password and retry count from config for these unit tests.
    """Make context.
    
    Args:
        password: Value supplied by the test or fixture for `password`.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    return SimpleNamespace(config=SimpleNamespace(saucedemo_password=password, max_retries=2))


def assert_portal_error(reason: ReasonCode, func) -> PortalError:
    # Helper for tests that assert business reason mapping.
    """Assert portal error.
    
    Args:
        reason: Value supplied by the test or fixture for `reason`.
        func: Value supplied by the test or fixture for `func`.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    with pytest.raises(PortalError) as error:
        func()
    assert error.value.reason is reason
    return error.value


def test_login_result_constructors_produce_expected_statuses_and_details() -> None:
    """Verify that login result constructors produce expected statuses and details.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    assert LoginResult.success() == LoginResult(LoginStatus.SUCCESS)
    assert LoginResult.locked_out("locked").status is LoginStatus.LOCKED_OUT
    assert LoginResult.locked_out("locked").detail == "locked"
    assert LoginResult.failed("bad").status is LoginStatus.FAILED
    assert LoginResult.failed("bad").detail == "bad"


def test_successful_account_workflow_calls_page_methods_in_required_order() -> None:
    # This is the happy-path contract: login, fill cart, checkout, persist, finish, confirm.
    """Verify that successful account workflow calls page methods in required order.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    pages = FakePages()

    def persist_before_finish(result) -> None:
        """Persist before finish.
        
        Args:
            result: Value supplied by the test or fixture for `result`.
        
        Returns:
            None. The test communicates success through assertions.
        
        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        pages.calls.append(("persist_before_finish", result.status.value))

    process_account(
        account(),
        pages,
        make_context(),
        persist_before_finish=persist_before_finish,
    )

    assert pages.calls == [
        ("login", "standard_user"),
        ("read_cart_count", None),
        ("add_inventory_items", 3),
        ("read_cart_count", None),
        ("open_cart", None),
        ("checkout", account().checkout_profile),
        ("read_order_summary", None),
        ("capture_order_details", None),
        ("persist_before_finish", "in_progress"),
        ("finish_order", None),
        ("read_confirmation", None),
    ]


def test_persist_before_finish_receives_sanitized_order_details_before_finish() -> None:
    # Order details are saved before the final click, but credential-like keys must be filtered out.
    """Verify that persist before finish receives sanitized order details before finish.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    pages = FakePages(
        captured_details={
            "order_id": "captured-order",
            "total": "$55.00",
            "password": "test_pw",
            "api_secret": "hidden",
        }
    )
    persisted = []

    def persist_before_finish(result) -> None:
        """Persist before finish.
        
        Args:
            result: Value supplied by the test or fixture for `result`.
        
        Returns:
            None. The test communicates success through assertions.
        
        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        persisted.append(result)
        pages.calls.append(("persist_before_finish", result.details.copy()))

    result = process_account(
        account(),
        pages,
        make_context(),
        persist_before_finish=persist_before_finish,
    )

    assert result.status is ItemStatus.SUCCESS
    assert len(persisted) == 1
    pre_finish = persisted[0]
    assert pre_finish.status is ItemStatus.IN_PROGRESS
    assert pre_finish.details["order_details_captured_before_finish"] is True
    assert pre_finish.details["overview_item_count"] == 3
    assert pre_finish.details["order_id"] == "captured-order"
    assert pre_finish.details["total"] == "$55.00"
    assert "password" not in pre_finish.details
    assert "api_secret" not in pre_finish.details
    assert pages.calls.index(("capture_order_details", None)) < pages.calls.index(
        ("persist_before_finish", pre_finish.details)
    )
    assert pages.calls.index(("persist_before_finish", pre_finish.details)) < pages.calls.index(
        ("finish_order", None)
    )


def test_finish_order_is_not_clicked_when_pre_finish_persistence_fails() -> None:
    # If the pre-finish save fails, the workflow must not click the irreversible final button.
    """Verify that finish order is not clicked when pre finish persistence fails.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    pages = FakePages()

    def persist_before_finish(result) -> None:
        """Persist before finish.
        
        Args:
            result: Value supplied by the test or fixture for `result`.
        
        Returns:
            None. The test communicates success through assertions.
        
        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        pages.calls.append(("persist_before_finish", result.status.value))
        raise RuntimeError("database unavailable")

    with pytest.raises(RuntimeError, match="database unavailable"):
        process_account(
            account(),
            pages,
            make_context(),
            persist_before_finish=persist_before_finish,
        )

    assert ("persist_before_finish", "in_progress") in pages.calls
    assert ("finish_order", None) not in pages.calls
    assert ("read_confirmation", None) not in pages.calls


def test_successful_workflow_adds_account_items_to_add() -> None:
    """Verify that successful workflow adds account items to add.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    test_account = account(items_to_add=2)
    pages = FakePages(
        cart_count=0,
        order_summary=OrderSummary(item_count=2, confirmation_text="Ready"),
        confirmation=OrderSummary(item_count=2, confirmation_text="Complete"),
    )

    result = process_account(test_account, pages, make_context())

    assert ("add_inventory_items", 2) in pages.calls
    assert result.details["items_requested"] == 2


def test_successful_workflow_validates_cart_count() -> None:
    """Verify that successful workflow validates cart count.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    error = assert_portal_error(
        ReasonCode.VALIDATION_FAILED,
        lambda: process_account(account(), FakePages(cart_count=4), make_context()),
    )

    assert "Cart count mismatch" in error.detail


def test_successful_workflow_validates_order_summary_item_count() -> None:
    """Verify that successful workflow validates order summary item count.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    pages = FakePages(order_summary=OrderSummary(item_count=2, confirmation_text="Ready"))

    error = assert_portal_error(
        ReasonCode.VALIDATION_FAILED,
        lambda: process_account(account(), pages, make_context()),
    )

    assert "Order summary item count mismatch" in error.detail


def test_successful_workflow_validates_confirmation() -> None:
    """Verify that successful workflow validates confirmation.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    pages = FakePages(confirmation=OrderSummary(item_count=3, confirmation_text=" "))

    error = assert_portal_error(
        ReasonCode.CHECKOUT_FAILED,
        lambda: process_account(account(), pages, make_context()),
    )

    assert "confirmation was blank" in error.detail


def test_successful_workflow_returns_success_item_result_with_non_secret_details() -> None:
    """Verify that successful workflow returns success item result with non secret details.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    pages = FakePages(
        captured_details={
            "order_id": "captured-order",
            "total": "$55.00",
            "password": "test_pw",
            "api_secret": "hidden",
            "access_token": "hidden",
            "credential_id": "hidden",
        }
    )

    result = process_account(account(), pages, make_context())

    assert result.item_key == "standard_user"
    assert result.operation == "checkout"
    assert result.status is ItemStatus.SUCCESS
    assert result.reason_code is None
    assert result.error_detail is None
    assert result.artifact_path is None
    assert result.attempts == 1
    assert result.details["username"] == "standard_user"
    assert result.details["items_requested"] == 3
    assert result.details["cart_count"] == 3
    assert result.details["confirmation_text"] == "Thank you for your order!"
    assert result.details["order_id"] == "captured-order"
    assert result.details["total"] == "$55.00"
    assert "password" not in result.details
    assert "api_secret" not in result.details
    assert "access_token" not in result.details
    assert "credential_id" not in result.details
    assert "test_pw" not in repr(result.details)


@pytest.mark.parametrize("password", [None, "   "])
def test_missing_or_blank_password_maps_to_credential_expired(password) -> None:
    """Verify that missing or blank password maps to credential expired.
    
    Args:
        password: Value supplied by the test or fixture for `password`.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    assert_portal_error(
        ReasonCode.CREDENTIAL_EXPIRED,
        lambda: process_account(account(), FakePages(), make_context(password)),
    )


def test_locked_out_login_maps_to_locked_out() -> None:
    """Verify that locked out login maps to locked out.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    pages = FakePages(login_result=LoginResult.locked_out("user locked"))

    error = assert_portal_error(
        ReasonCode.LOCKED_OUT,
        lambda: process_account(account(), pages, make_context()),
    )

    assert error.detail == "user locked"
    assert pages.calls == [("login", "standard_user")]


def test_failed_login_maps_to_login_failed() -> None:
    """Verify that failed login maps to login failed.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    pages = FakePages(login_result=LoginResult.failed("bad credentials"))

    error = assert_portal_error(
        ReasonCode.LOGIN_FAILED,
        lambda: process_account(account(), pages, make_context()),
    )

    assert error.detail == "bad credentials"
    assert pages.calls == [("login", "standard_user")]


def test_cart_mismatch_maps_to_validation_failed() -> None:
    """Verify that cart mismatch maps to validation failed.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    assert_portal_error(
        ReasonCode.VALIDATION_FAILED,
        lambda: process_account(account(), FakePages(cart_count=4), make_context()),
    )


def test_order_summary_mismatch_maps_to_validation_failed() -> None:
    """Verify that order summary mismatch maps to validation failed.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    pages = FakePages(order_summary=OrderSummary(item_count=1, confirmation_text="Ready"))

    assert_portal_error(
        ReasonCode.VALIDATION_FAILED,
        lambda: process_account(account(), pages, make_context()),
    )


def test_blank_confirmation_text_maps_to_checkout_failed() -> None:
    """Verify that blank confirmation text maps to checkout failed.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    pages = FakePages(confirmation=OrderSummary(item_count=3, confirmation_text=""))

    assert_portal_error(
        ReasonCode.CHECKOUT_FAILED,
        lambda: process_account(account(), pages, make_context()),
    )


def test_confirmation_count_mismatch_maps_to_checkout_failed() -> None:
    """Verify that confirmation count mismatch maps to checkout failed.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    pages = FakePages(confirmation=OrderSummary(item_count=2, confirmation_text="Complete"))

    assert_portal_error(
        ReasonCode.CHECKOUT_FAILED,
        lambda: process_account(account(), pages, make_context()),
    )


def test_portal_error_raised_by_page_method_propagates_unchanged() -> None:
    """Verify that portal error raised by page method propagates unchanged.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    pages = FakePages(raise_on="add_inventory_items")

    error = assert_portal_error(
        ReasonCode.PORTAL_TIMEOUT,
        lambda: process_account(account(), pages, make_context()),
    )

    assert error.detail == "add_inventory_items timed out"


def test_retryable_login_failure_is_retried_and_eventually_succeeds() -> None:
    """Verify that retryable login failure is retried and eventually succeeds.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    pages = FakePages(
        failures={"login": [PortalError(ReasonCode.PORTAL_TIMEOUT, "temporary login timeout")]}
    )

    result = process_account(account(), pages, make_context())

    assert result.status is ItemStatus.SUCCESS
    assert result.attempts == 2
    assert [call for call in pages.calls if call[0] == "login"] == [
        ("login", "standard_user"),
        ("login", "standard_user"),
    ]


def test_exhausted_retryable_read_step_raises_final_portal_error_with_attempts() -> None:
    """Verify that exhausted retryable read step raises final portal error with attempts.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    pages = FakePages(
        failures={
            "open_cart": [
                PortalError(ReasonCode.PORTAL_TIMEOUT, "cart timeout 1"),
                PortalError(ReasonCode.PORTAL_TIMEOUT, "cart timeout 2"),
                PortalError(ReasonCode.PORTAL_TIMEOUT, "cart timeout 3"),
            ]
        }
    )
    context = make_context()
    context.config.max_retries = 2

    error = assert_portal_error(
        ReasonCode.PORTAL_TIMEOUT,
        lambda: process_account(account(), pages, context),
    )

    assert error.attempts == 3


def test_finish_order_retryable_failure_is_not_retried_blindly_when_confirmation_missing() -> None:
    """Verify that finish order retryable failure is not retried blindly when confirmation missing.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    pages = FakePages(
        confirmation=OrderSummary(item_count=0, confirmation_text=""),
        failures={"finish_order": [PortalError(ReasonCode.PORTAL_TIMEOUT, "finish timed out")]},
    )

    error = assert_portal_error(
        ReasonCode.PORTAL_TIMEOUT,
        lambda: process_account(account(), pages, make_context()),
    )

    assert error.detail == "finish timed out"
    assert [call for call in pages.calls if call[0] == "finish_order"] == [("finish_order", None)]
    assert [call for call in pages.calls if call[0] == "read_confirmation"] == [
        ("read_confirmation", None)
    ]


def test_runtime_workflow_uses_retry_policy_execute() -> None:
    """Verify that runtime workflow uses retry policy execute.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    pages = FakePages()
    execute_calls = []

    from portal_automation.core.retries import RetryPolicy

    original_execute = RetryPolicy.execute

    def tracked_execute(self, operation, logger=None):
        """Tracked execute.
        
        Args:
            operation: Value supplied by the test or fixture for `operation`.
            logger: Value supplied by the test or fixture for `logger`.
        
        Returns:
            None. The test communicates success through assertions.
        
        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        execute_calls.append(self.max_retries)
        return original_execute(self, operation, logger=logger)

    RetryPolicy.execute = tracked_execute
    try:
        result = process_account(account(), pages, make_context())
    finally:
        RetryPolicy.execute = original_execute

    assert result.status is ItemStatus.SUCCESS
    assert execute_calls != []


def test_sample_account_created_from_p16_shape_works_with_workflow() -> None:
    """Verify that sample account created from p16 shape works with workflow.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    sample_account = account()
    pages = FakePages()

    result = process_account(sample_account, pages, make_context())

    assert result.status is ItemStatus.SUCCESS
    assert ("add_inventory_items", 3) in pages.calls


def test_workflow_source_does_not_import_playwright_browser_or_page_modules() -> None:
    """Verify that workflow source does not import playwright browser or page modules.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    source = workflow_source().lower()

    for forbidden in (
        "playwright",
        "import browser",
        "from browser",
        "import page",
        "from page",
    ):
        assert forbidden not in source


def test_workflow_source_does_not_import_persistence_or_sqlite_modules() -> None:
    """Verify that workflow source does not import persistence or sqlite modules.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    source = workflow_source()

    assert "persistence" not in source
    assert "sqlite" not in source


def test_workflow_source_does_not_contain_demo_credentials() -> None:
    """Verify that workflow source does not contain demo credentials.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    source = workflow_source()

    assert "secret_sauce" not in source
    assert "admin123" not in source


def test_tests_mention_demo_credentials_only_as_forbidden_scan_targets() -> None:
    """Verify that tests mention demo credentials only as forbidden scan targets.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    source = Path(__file__).read_text(encoding="utf-8")
    forbidden_literals = ("secret_" + "sauce", "admin" + "123")

    for forbidden in forbidden_literals:
        configured_markers = [
            f'= "{forbidden}"',
            f"= '{forbidden}'",
            f'": "{forbidden}"',
            f"': '{forbidden}'",
        ]
        assert not any(marker in source for marker in configured_markers)


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


def workflow_source() -> str:
    """Workflow source.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    return (ROOT / "src/portal_automation/portals/saucedemo/workflow.py").read_text(
        encoding="utf-8"
    )


@pytest.mark.parametrize(
    "username",
    [
        "problem_user",
        "performance_glitch_user",
        "error_user",
        "visual_user",
    ],
)
def test_non_locked_demo_accounts_are_not_treated_as_login_failures(username: str) -> None:
    """Verify that non locked demo accounts are not treated as login failures.
    
    Args:
        username: Value supplied by the test or fixture for `username`.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    test_account = SauceDemoAccount(
        account_key=username,
        username=username,
        items_to_add=3,
        checkout_profile=CheckoutProfile(
            first_name="Demo",
            last_name="User",
            postal_code="10001",
        ),
    )
    pages = FakePages(login_result=LoginResult.success())

    result = process_account(test_account, pages, make_context())

    assert result.status is ItemStatus.SUCCESS
    assert pages.calls[0] == ("login", username)
    assert ("open_cart", None) in pages.calls
    assert ("checkout", test_account.checkout_profile) in pages.calls
    assert ("finish_order", None) in pages.calls
