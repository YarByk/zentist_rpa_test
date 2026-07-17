import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest

from portal_automation.core.artifact_store import ArtifactStore
from portal_automation.core.models import (
    ItemResult,
    ItemStatus,
    ReasonCode,
    RunContext,
    RunResult,
    RunStatus,
)
from portal_automation.core.retries import PortalError
from portal_automation.core.runner import BasePortalRunnerZX
from portal_automation.portals.saucedemo import runner as runner_module
from portal_automation.portals.saucedemo.input_schema import CheckoutProfile, SauceDemoAccount
from portal_automation.portals.saucedemo.pages import SauceDemoPages
from portal_automation.portals.saucedemo.runner import SauceDemoRunner
from portal_automation.portals.saucedemo.workflow import LoginResult, LoginStatus, OrderSummary

ROOT = Path(__file__).resolve().parents[2]


@dataclass
class ConfigStub:
    # Minimal config surface required by the SauceDemo runner and page object tests.
    saucedemo_input_path: str
    saucedemo_password: str | None = "pw"
    saucedemo_base_url: str = "https://www.saucedemo.com"
    report_email_to: str | None = "reviewer@example.com"


@dataclass
class ContextStub:
    # Small context substitute used when the full RunContext is unnecessary.
    config: object
    reporter: object


class FakePersistence:
    # In-memory result store that lets tests inspect every write made by the runner.
    def __init__(self) -> None:
        """Initialize this test helper instance.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.created_runs = []
        self.finished_runs = []
        self.real_run_methods = []
        self.upserted_results: list[ItemResult] = []
        self._results_by_key: dict[tuple[str, str], ItemResult] = {}

    def create_run(self, run_id: str, portal_name: str, business_date: date) -> None:
        """Create run.

        Args:
            run_id: Value supplied by the test or fixture for `run_id`.
            portal_name: Value supplied by the test or fixture for `portal_name`.
            business_date: Value supplied by the test or fixture for `business_date`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.created_runs.append((run_id, portal_name, business_date))

    def finish_run(self, run_id: str, status: RunStatus, summary: dict[str, int]) -> None:
        """Finish run.

        Args:
            run_id: Value supplied by the test or fixture for `run_id`.
            status: Value supplied by the test or fixture for `status`.
            summary: Value supplied by the test or fixture for `summary`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.finished_runs.append((run_id, status, summary))

    def get_committed_items(self, portal_name: str, business_date: date) -> set[str]:
        """Get committed items.

        Args:
            portal_name: Value supplied by the test or fixture for `portal_name`.
            business_date: Value supplied by the test or fixture for `business_date`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.real_run_methods.append("get_committed_items")
        return set()

    def mark_item_in_progress(
        self,
        run_id: str,
        portal_name: str,
        business_date: date,
        item_key: str,
        operation: str,
    ) -> None:
        """Mark item in progress.

        Args:
            run_id: Value supplied by the test or fixture for `run_id`.
            portal_name: Value supplied by the test or fixture for `portal_name`.
            business_date: Value supplied by the test or fixture for `business_date`.
            item_key: Value supplied by the test or fixture for `item_key`.
            operation: Value supplied by the test or fixture for `operation`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.real_run_methods.append("mark_item_in_progress")

    def upsert_item_result(self, *args: object) -> None:
        """Upsert item result.

        Args:
            *args: Value supplied by the test or fixture for `args`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.real_run_methods.append("upsert_item_result")
        result = args[0]
        assert isinstance(result, ItemResult)
        self.upserted_results.append(result)
        self._results_by_key[(result.item_key, result.operation)] = result

    def list_results_by_business_date(self, portal_name: str, business_date: date) -> list[object]:
        """List results by business date.

        Args:
            portal_name: Value supplied by the test or fixture for `portal_name`.
            business_date: Value supplied by the test or fixture for `business_date`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.real_run_methods.append("list_results_by_business_date")
        return list(self._results_by_key.values())


class ReporterStub:
    # Captures the finalized result instead of writing a real report file.
    def __init__(self) -> None:
        """Initialize this test helper instance.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.written_results: list[RunResult] = []

    def write_report(self, result: RunResult) -> None:
        """Write report.

        Args:
            result: Value supplied by the test or fixture for `result`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.written_results.append(result)

    def render(self, result: RunResult) -> str:
        """Render.

        Args:
            result: Value supplied by the test or fixture for `result`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        return f"rendered-report:{result.run_id}:{result.status.value}"


class EmailStub:
    # Captures outgoing email parameters so finalize() can be asserted precisely.
    def __init__(self) -> None:
        """Initialize this test helper instance.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.calls: list[dict[str, object]] = []

    def send_report(self, **kwargs: object) -> None:
        """Send report.

        Args:
            **kwargs: Value supplied by the test or fixture for `kwargs`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.calls.append(kwargs)


class FakeTarget:
    # Simplified locator/element object used by the lightweight fake page branch.
    def __init__(self, page: "FakePage", kind: str, name: str) -> None:
        """Initialize this test helper instance.

        Args:
            page: Value supplied by the test or fixture for `page`.
            kind: Value supplied by the test or fixture for `kind`.
            name: Value supplied by the test or fixture for `name`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.page = page
        self.kind = kind
        self.name = name

    def fill(self, value: str) -> None:
        """Fill.

        Args:
            value: Value supplied by the test or fixture for `value`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.page.calls.append((self.kind, self.name, "fill", value))

    def click(self) -> None:
        """Click.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.page.calls.append((self.kind, self.name, "click"))

    def first(self) -> "FakeTarget":
        """First.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.page.calls.append((self.kind, self.name, "first"))
        return self

    def text_content(self) -> str:
        """Text content.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.page.calls.append((self.kind, self.name, "text_content"))
        return self.page.text_values.get(self.name, "")


class FakePage:
    # Very small fake used for call-recording tests that do not need DOM semantics.
    def __init__(self) -> None:
        """Initialize this test helper instance.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.calls: list[tuple] = []
        self.text_values: dict[str, str] = {}
        self.login_locked_out = False
        self.login_succeeded = True
        self.cart_count = 3
        self.order_summary = OrderSummary(item_count=3, confirmation_text="Checkout: Overview")
        self.confirmation = OrderSummary(
            item_count=3,
            confirmation_text="Thank you for your order!",
        )
        self.order_details = {"order_id": "ord-001", "total": "$14.99"}

    def goto(self, url: str) -> None:
        """Goto.

        Args:
            url: Value supplied by the test or fixture for `url`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.calls.append(("goto", url))

    def locator(self, selector: str) -> FakeTarget:
        """Locator.

        Args:
            selector: Value supplied by the test or fixture for `selector`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.calls.append(("locator", selector))
        return FakeTarget(self, "locator", selector)


class DomElement:
    # Represents one DOM node in the richer fake DOM used by page-object tests.
    def __init__(self, *, text: str = "", attrs: dict[str, str] | None = None) -> None:
        """Initialize this test helper instance.

        Args:
            text: Value supplied by the test or fixture for `text`.
            attrs: Value supplied by the test or fixture for `attrs`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.text = text
        self.attrs = attrs or {}
        self.value = ""


class DomLocator:
    # Emulates the subset of locator behavior needed by the page object methods.
    def __init__(self, page: "DomPage", selector: str, index: int | None = None) -> None:
        """Initialize this test helper instance.

        Args:
            page: Value supplied by the test or fixture for `page`.
            selector: Value supplied by the test or fixture for `selector`.
            index: Value supplied by the test or fixture for `index`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.page = page
        self.selector = selector
        self.index = index

    def count(self) -> int:
        """Count.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        return len(self.page.elements.get(self.selector, []))

    def nth(self, index: int) -> "DomLocator":
        """Nth.

        Args:
            index: Value supplied by the test or fixture for `index`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        return DomLocator(self.page, self.selector, index=index)

    def first(self) -> "DomLocator":
        """First.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        return self.nth(0)

    def fill(self, value: str) -> None:
        """Fill.

        Args:
            value: Value supplied by the test or fixture for `value`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.page.fills.append((self.selector, self.index, value))
        element = self._element()
        element.value = value

    def click(self) -> None:
        """Click.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.page.clicks.append((self.selector, self.index))
        handler = self.page.click_handlers.get((self.selector, self.index))
        if handler is None:
            handler = self.page.click_handlers.get((self.selector, None))
        if handler is not None:
            handler()

    def text_content(self) -> str:
        """Text content.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        return self._element().text

    def all_text_contents(self) -> list[str]:
        """All text contents.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        return [element.text for element in self.page.elements.get(self.selector, [])]

    def _element(self) -> DomElement:
        """Element.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        elements = self.page.elements.get(self.selector, [])
        if not elements:
            raise AssertionError(f"no element for selector {self.selector}")
        if self.index is None:
            return elements[0]
        return elements[self.index]


class DomPage:
    # Fake DOM-driven page used to test selector logic and state transitions.
    def __init__(self, *, url: str = "https://www.saucedemo.com/") -> None:
        """Initialize this test helper instance.

        Args:
            url: Value supplied by the test or fixture for `url`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.url = url
        self.elements: dict[str, list[DomElement]] = {
            SauceDemoPages.USERNAME_INPUT: [DomElement()],
            SauceDemoPages.PASSWORD_INPUT: [DomElement()],
            SauceDemoPages.LOGIN_BUTTON: [DomElement(text="Login")],
        }
        self.click_handlers: dict[tuple[str, int | None], object] = {}
        self.fills: list[tuple[str, int | None, str]] = []
        self.clicks: list[tuple[str, int | None]] = []
        self.goto_calls: list[str] = []
        self.waited_urls: list[str] = []

    def goto(self, url: str) -> None:
        """Goto.

        Args:
            url: Value supplied by the test or fixture for `url`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.url = url
        self.goto_calls.append(url)

    def locator(self, selector: str) -> DomLocator:
        """Locator.

        Args:
            selector: Value supplied by the test or fixture for `selector`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        return DomLocator(self, selector)

    def wait_for_url(self, pattern: str) -> None:
        """Wait for url.

        Args:
            pattern: Value supplied by the test or fixture for `pattern`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.waited_urls.append(pattern)


def account() -> SauceDemoAccount:
    # Canonical account fixture reused across many runner and page-object tests.
    """Account.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    return SauceDemoAccount(
        account_key="standard_user",
        username="standard_user",
        items_to_add=3,
        checkout_profile=CheckoutProfile(
            first_name="Standard",
            last_name="User",
            postal_code="10001",
        ),
    )


def write_saucedemo_input(tmp_path, records: list[dict[str, object]] | None = None) -> str:
    # Write a temporary JSON fixture that mirrors the real repository input format.
    """Write saucedemo input.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
        records: Value supplied by the test or fixture for `records`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    path = tmp_path / "accounts.json"
    default_records = [
        {
            "account_key": "standard_user",
            "username": "standard_user",
            "items_to_add": 3,
            "checkout_profile": {
                "first_name": "Standard",
                "last_name": "User",
                "postal_code": "10001",
            },
        }
    ]
    path.write_text(
        json.dumps(records if records is not None else default_records),
        encoding="utf-8",
    )
    return str(path)


def make_run_context(tmp_path, *, reporter=None) -> RunContext:
    # Build a realistic run context with fake collaborators and a temp artifact root.
    """Make run context.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
        reporter: Value supplied by the test or fixture for `reporter`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    return RunContext(
        run_id="run-sd-1",
        business_date=date(2026, 6, 29),
        dry_run=True,
        stale_item_timeout_seconds=300,
        config=ConfigStub(saucedemo_input_path=write_saucedemo_input(tmp_path)),
        persistence=FakePersistence(),
        reporter=reporter if reporter is not None else object(),
        logger=object(),
        metrics=object(),
        artifacts=ArtifactStore(str(tmp_path / "artifacts")),
        email=object(),
    )


def make_process_context(tmp_path, *, reporter=None) -> ContextStub:
    # Build a smaller context for methods that only need config/reporter access.
    """Make process context.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
        reporter: Value supplied by the test or fixture for `reporter`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    return ContextStub(
        config=ConfigStub(saucedemo_input_path=write_saucedemo_input(tmp_path)),
        reporter=reporter if reporter is not None else object(),
    )


def test_runner_contract_constants_are_correct() -> None:
    """Verify that runner contract constants are correct.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    assert SauceDemoRunner.portal_name == "saucedemo"
    assert SauceDemoRunner.operation_name == "checkout"


def test_runner_inherits_base_and_does_not_override_run() -> None:
    """Verify that runner inherits base and does not override run.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    assert issubclass(SauceDemoRunner, BasePortalRunnerZX)
    assert "run" not in SauceDemoRunner.__dict__
    assert SauceDemoRunner.run is BasePortalRunnerZX.run


def test_runner_item_key_uses_account_key() -> None:
    """Verify that runner item key uses account key.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    assert SauceDemoRunner().item_key(account()) == "standard_user"


def test_dry_run_does_not_call_page_factory_or_process_item(tmp_path) -> None:
    """Verify that dry run does not call page factory or process item.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    factory_calls = []

    def pages_factory(context: RunContext) -> object:
        """Pages factory.

        Args:
            context: Value supplied by the test or fixture for `context`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        factory_calls.append(context)
        raise AssertionError("page factory must not be called in dry-run")

    runner = SauceDemoRunner(pages_factory=pages_factory)
    context = make_run_context(tmp_path)

    result = runner.run(context)

    assert result.status is RunStatus.SUCCESS
    assert factory_calls == []
    assert context.persistence.real_run_methods == []


def test_process_item_uses_injected_page_factory_and_workflow(tmp_path, monkeypatch) -> None:
    """Verify that process item uses injected page factory and workflow.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
        monkeypatch: Value supplied by the test or fixture for `monkeypatch`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    pages = object()
    calls = []

    def pages_factory(context: ContextStub) -> object:
        """Pages factory.

        Args:
            context: Value supplied by the test or fixture for `context`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        calls.append(("factory", context))
        return pages

    def fake_process_account(record, page_objects, context, *, persist_before_finish=None):
        """Fake process account.

        Args:
            record: Value supplied by the test or fixture for `record`.
            page_objects: Value supplied by the test or fixture for `page_objects`.
            context: Value supplied by the test or fixture for `context`.
            persist_before_finish: Value supplied by the test or fixture for
                `persist_before_finish`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        calls.append(("workflow", record, page_objects, context, persist_before_finish))
        return ItemResult(
            item_key=record.account_key,
            operation="checkout",
            status=ItemStatus.SUCCESS,
            reason_code=None,
            error_detail=None,
            artifact_path=None,
            details={},
        )

    monkeypatch.setattr(runner_module, "process_account", fake_process_account)
    context = make_process_context(tmp_path)

    result = SauceDemoRunner(pages_factory=pages_factory).process_item(context, account())

    assert result.status is ItemStatus.SUCCESS
    assert len(calls) == 2
    assert calls[0] == ("factory", context)
    workflow_call = calls[1]
    assert workflow_call[:4] == ("workflow", account(), pages, context)
    assert callable(workflow_call[4])


def test_process_item_pre_finish_callback_persists_order_details(tmp_path, monkeypatch) -> None:
    """Verify that process item pre finish callback persists order details.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
        monkeypatch: Value supplied by the test or fixture for `monkeypatch`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    pages = object()
    context = make_run_context(tmp_path)
    context.dry_run = False

    def fake_process_account(record, page_objects, run_context, *, persist_before_finish=None):
        """Fake process account.

        Args:
            record: Value supplied by the test or fixture for `record`.
            page_objects: Value supplied by the test or fixture for `page_objects`.
            run_context: Value supplied by the test or fixture for `run_context`.
            persist_before_finish: Value supplied by the test or fixture for
                `persist_before_finish`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        assert persist_before_finish is not None
        persist_before_finish(
            ItemResult(
                item_key=record.account_key,
                operation="checkout",
                status=ItemStatus.IN_PROGRESS,
                reason_code=None,
                error_detail=None,
                artifact_path=None,
                details={
                    "order_id": "ord-001",
                    "total": "$14.99",
                    "order_details_captured_before_finish": True,
                },
            )
        )
        return ItemResult(
            item_key=record.account_key,
            operation="checkout",
            status=ItemStatus.SUCCESS,
            reason_code=None,
            error_detail=None,
            artifact_path=None,
            details={"confirmation_text": "Thank you for your order!"},
        )

    monkeypatch.setattr(runner_module, "process_account", fake_process_account)

    result = SauceDemoRunner(pages_factory=lambda run_context: pages).process_item(
        context,
        account(),
    )

    assert result.status is ItemStatus.SUCCESS
    assert context.persistence.real_run_methods == ["upsert_item_result"]
    pre_finish_result = context.persistence.upserted_results[0]
    assert pre_finish_result.status is ItemStatus.IN_PROGRESS
    assert pre_finish_result.details["order_details_captured_before_finish"] is True
    assert pre_finish_result.details["order_id"] == "ord-001"


def test_failed_result_after_pre_finish_persistence_keeps_order_details(
    tmp_path,
    monkeypatch,
) -> None:
    """Verify that failed result after pre finish persistence keeps order details.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
        monkeypatch: Value supplied by the test or fixture for `monkeypatch`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    context = make_run_context(tmp_path)
    context.dry_run = False

    def fake_process_account(record, page_objects, run_context, *, persist_before_finish=None):
        """Fake process account.

        Args:
            record: Value supplied by the test or fixture for `record`.
            page_objects: Value supplied by the test or fixture for `page_objects`.
            run_context: Value supplied by the test or fixture for `run_context`.
            persist_before_finish: Value supplied by the test or fixture for
                `persist_before_finish`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        assert persist_before_finish is not None
        persist_before_finish(
            ItemResult(
                item_key=record.account_key,
                operation="checkout",
                status=ItemStatus.IN_PROGRESS,
                reason_code=None,
                error_detail=None,
                artifact_path=None,
                details={
                    "order_id": "ord-before-finish",
                    "total": "$14.99",
                    "order_details_captured_before_finish": True,
                },
            )
        )
        raise PortalError(ReasonCode.CHECKOUT_FAILED, "finish failed after persistence")

    monkeypatch.setattr(runner_module, "process_account", fake_process_account)

    result = SauceDemoRunner(pages_factory=lambda run_context: object()).run(context)

    failed = result.results[0]
    assert failed.status is ItemStatus.FAILED
    assert failed.reason_code is ReasonCode.CHECKOUT_FAILED
    assert failed.details["order_id"] == "ord-before-finish"
    assert failed.details["total"] == "$14.99"
    assert failed.details["order_details_captured_before_finish"] is True
    assert failed.details["failed_after_pre_finish_persist"] is True
    assert context.persistence.upserted_results[-1].details["order_id"] == "ord-before-finish"


def test_run_continues_after_one_saucedemo_account_failure(tmp_path, monkeypatch) -> None:
    """Verify that run continues after one saucedemo account failure.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
        monkeypatch: Value supplied by the test or fixture for `monkeypatch`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    records = [
        {
            "account_key": "standard_user",
            "username": "standard_user",
            "items_to_add": 3,
            "checkout_profile": {
                "first_name": "Standard",
                "last_name": "User",
                "postal_code": "10001",
            },
        },
        {
            "account_key": "locked_out_user",
            "username": "locked_out_user",
            "items_to_add": 3,
            "checkout_profile": {
                "first_name": "Locked",
                "last_name": "User",
                "postal_code": "10001",
            },
        },
    ]
    context = make_run_context(tmp_path)
    context.dry_run = False
    context.config.saucedemo_input_path = write_saucedemo_input(tmp_path, records)
    processed: list[str] = []

    def fake_process_account(record, page_objects, run_context, *, persist_before_finish=None):
        """Fake process account.

        Args:
            record: Value supplied by the test or fixture for `record`.
            page_objects: Value supplied by the test or fixture for `page_objects`.
            run_context: Value supplied by the test or fixture for `run_context`.
            persist_before_finish: Value supplied by the test or fixture for
                `persist_before_finish`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        processed.append(record.account_key)
        if record.account_key == "locked_out_user":
            raise PortalError(ReasonCode.LOCKED_OUT, "user locked")
        return ItemResult(
            item_key=record.account_key,
            operation="checkout",
            status=ItemStatus.SUCCESS,
            reason_code=None,
            error_detail=None,
            artifact_path=None,
            details={"confirmation_text": "Thank you for your order!"},
        )

    monkeypatch.setattr(runner_module, "process_account", fake_process_account)

    result = SauceDemoRunner(pages_factory=lambda run_context: object()).run(context)

    assert processed == ["standard_user", "locked_out_user"]
    assert result.status is RunStatus.SUCCESS
    results_by_key = {item.item_key: item for item in result.results}
    assert results_by_key["standard_user"].status is ItemStatus.SUCCESS
    assert results_by_key["locked_out_user"].status is ItemStatus.SKIPPED
    assert results_by_key["locked_out_user"].reason_code is ReasonCode.LOCKED_OUT
    assert results_by_key["locked_out_user"].details["expected_demo_failure"] is True
    assert "operator" in results_by_key["locked_out_user"].details["operator_notice"]


@pytest.mark.parametrize(
    ("item_key", "reason"),
    [
        ("locked_out_user", ReasonCode.LOCKED_OUT),
        ("problem_user", ReasonCode.VALIDATION_FAILED),
        ("error_user", ReasonCode.VALIDATION_FAILED),
    ],
)
def test_known_saucedemo_demo_failures_are_skipped_for_operator_visibility(
    item_key: str,
    reason: ReasonCode,
) -> None:
    """Verify that known broken Sauce Demo users become skipped operator notices.

    Args:
        item_key: Known Sauce Demo demo account key.
        reason: Expected portal-domain failure for that account.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    result = SauceDemoRunner()._portal_error_result(item_key, PortalError(reason, "portal failed"))

    assert result.status is ItemStatus.SKIPPED
    assert result.reason_code is reason
    assert result.details["expected_demo_failure"] is True
    assert "operator" in result.details["operator_notice"]


def test_unexpected_saucedemo_demo_user_reason_stays_failed() -> None:
    """Verify that only known account-and-reason pairs are converted to skipped.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    result = SauceDemoRunner()._portal_error_result(
        "error_user",
        PortalError(ReasonCode.CHECKOUT_FAILED, "unexpected checkout failure"),
    )

    assert result.status is ItemStatus.FAILED
    assert "operator_notice" not in result.details


def test_process_item_without_page_factory_raises_portal_unavailable(tmp_path) -> None:
    """Verify that process item without page factory raises portal unavailable.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    with pytest.raises(PortalError) as error:
        SauceDemoRunner().process_item(make_process_context(tmp_path), account())

    assert error.value.reason is ReasonCode.PORTAL_UNAVAILABLE
    assert "page factory" in error.value.detail


@pytest.mark.parametrize("password", [None, "", "   "])
def test_preflight_raises_credential_expired_when_password_missing_or_blank(
    tmp_path,
    password,
) -> None:
    """Verify that preflight raises credential expired when password missing or blank.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
        password: Value supplied by the test or fixture for `password`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    context = make_process_context(tmp_path)
    context.config.saucedemo_password = password

    with pytest.raises(PortalError) as error:
        SauceDemoRunner().preflight_check(context)

    assert error.value.reason is ReasonCode.CREDENTIAL_EXPIRED


def test_preflight_passes_with_required_non_browser_config(tmp_path) -> None:
    """Verify that preflight passes with required non browser config.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    SauceDemoRunner().preflight_check(make_process_context(tmp_path))


def test_preflight_does_not_call_page_factory(tmp_path) -> None:
    """Verify that preflight does not call page factory.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    factory_calls = []
    runner = SauceDemoRunner(pages_factory=lambda context: factory_calls.append(context))

    runner.preflight_check(make_process_context(tmp_path))

    assert factory_calls == []


def test_load_items_still_reads_validated_input_records(tmp_path) -> None:
    """Verify that load items still reads validated input records.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    context = make_process_context(tmp_path)

    items = SauceDemoRunner().load_items(context)

    assert items == [account()]


def test_finalize_writes_report_when_reporter_supports_write_report(tmp_path) -> None:
    """Verify that finalize writes report when reporter supports write report.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    reporter = ReporterStub()
    context = make_process_context(tmp_path, reporter=reporter)
    context.email = object()
    result = RunResult(
        run_id="run-sd-1",
        portal_name="saucedemo",
        business_date=date(2026, 6, 29),
        status=RunStatus.SUCCESS,
        results=[],
    )

    SauceDemoRunner().finalize(context, result)

    assert reporter.written_results == [result]


def test_finalize_calls_email_send_report_with_written_report(tmp_path) -> None:
    """Verify that finalize calls email send report with written report.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    reporter = ReporterStub()
    email = EmailStub()
    context = make_process_context(tmp_path, reporter=reporter)
    context.email = email
    result = RunResult(
        run_id="run-sd-1",
        portal_name="saucedemo",
        business_date=date(2026, 6, 29),
        status=RunStatus.SUCCESS,
        results=[],
    )

    SauceDemoRunner().finalize(context, result)

    assert reporter.written_results == [result]
    assert email.calls == [
        {
            "run_id": "run-sd-1",
            "to": "reviewer@example.com",
            "subject": "SauceDemo run report: run-sd-1",
            "body": "rendered-report:run-sd-1:success",
            "report_path": None,
        }
    ]


def test_finalize_returns_without_error_when_reporter_has_no_write_report(tmp_path) -> None:
    """Verify that finalize returns without error when reporter has no write report.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    result = RunResult(
        run_id="run-sd-1",
        portal_name="saucedemo",
        business_date=date(2026, 6, 29),
        status=RunStatus.SUCCESS,
        results=[],
    )

    SauceDemoRunner().finalize(make_process_context(tmp_path), result)


def test_saucedemo_pages_login_uses_arguments_config_values_and_page_calls() -> None:
    """Verify that saucedemo pages login uses arguments config values and page calls.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    page = FakePage()
    config = ConfigStub(
        saucedemo_input_path="accounts.json",
        saucedemo_base_url="https://sauce.example",
    )

    result = SauceDemoPages(page, config).login("standard_user", "pw")

    assert result == LoginResult.success()
    assert ("goto", "https://sauce.example") in page.calls
    assert ("locator", SauceDemoPages.USERNAME_INPUT, "fill", "standard_user") in page.calls
    assert ("locator", SauceDemoPages.PASSWORD_INPUT, "fill", "pw") in page.calls
    assert ("locator", SauceDemoPages.LOGIN_BUTTON, "click") in page.calls


def test_saucedemo_pages_login_returns_locked_out_result() -> None:
    """Verify that saucedemo pages login returns locked out result.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    page = FakePage()
    page.login_locked_out = True

    result = SauceDemoPages(page, ConfigStub("accounts.json")).login("locked_out_user", "pw")

    assert result.status is LoginStatus.LOCKED_OUT
    assert "locked out" in result.detail


def test_saucedemo_pages_login_returns_failed_result() -> None:
    """Verify that saucedemo pages login returns failed result.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    page = FakePage()
    page.login_succeeded = False

    result = SauceDemoPages(page, ConfigStub("accounts.json")).login("standard_user", "pw")

    assert result.status is LoginStatus.FAILED
    assert "login failed" in result.detail


def test_saucedemo_pages_login_reads_locked_out_dom_error() -> None:
    """Verify that saucedemo pages login reads locked out dom error.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    page = DomPage()
    page.click_handlers[(SauceDemoPages.LOGIN_BUTTON, None)] = lambda: page.elements.update(
        {
            SauceDemoPages.ERROR_MESSAGE: [DomElement(text=SauceDemoPages.LOCKED_OUT_TEXT)],
        }
    )

    result = SauceDemoPages(page, ConfigStub("accounts.json")).login("locked_out_user", "pw")

    assert result.status is LoginStatus.LOCKED_OUT
    assert result.detail == SauceDemoPages.LOCKED_OUT_TEXT


def test_saucedemo_pages_login_reads_non_locked_dom_error() -> None:
    """Verify that saucedemo pages login reads non locked dom error.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    page = DomPage()
    error_text = "Epic sadface: Username and password do not match."
    page.click_handlers[(SauceDemoPages.LOGIN_BUTTON, None)] = lambda: page.elements.update(
        {
            SauceDemoPages.ERROR_MESSAGE: [DomElement(text=error_text)],
        }
    )

    result = SauceDemoPages(page, ConfigStub("accounts.json")).login("standard_user", "pw")

    assert result.status is LoginStatus.FAILED
    assert result.detail == error_text


def test_saucedemo_pages_login_succeeds_when_inventory_page_is_visible() -> None:
    """Verify that saucedemo pages login succeeds when inventory page is visible.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    page = DomPage()

    def on_login() -> None:
        """On login.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        page.url = "https://www.saucedemo.com/inventory.html"
        page.elements[SauceDemoPages.INVENTORY_ITEM] = [DomElement(text="item")]

    page.click_handlers[(SauceDemoPages.LOGIN_BUTTON, None)] = on_login

    result = SauceDemoPages(page, ConfigStub("accounts.json")).login("standard_user", "pw")

    assert result.status is LoginStatus.SUCCESS


def test_add_inventory_items_records_exactly_requested_clicks() -> None:
    """Verify that add inventory items records exactly requested clicks.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    page = FakePage()

    SauceDemoPages(page, ConfigStub("accounts.json")).add_inventory_items(2)

    # Fake branch records one locator call and one click per item, no .first() indirection
    assert page.calls.count(("locator", SauceDemoPages.ADD_TO_CART_BUTTON, "click")) == 2


def test_add_inventory_items_raises_when_no_buttons_available() -> None:
    """Real branch: raises ITEM_NOT_FOUND immediately when count() returns 0."""

    class CountZeroTarget:
        def count(self) -> int:
            """Count.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
            return 0

        def nth(self, index: int) -> "CountZeroTarget":
            """Nth.

            Args:
                index: Value supplied by the test or fixture for `index`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
            return self

        def click(self) -> None:
            """Click.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
            raise AssertionError("click should not be called when count is 0")

    class CountZeroPage:
        def locator(self, selector: str) -> CountZeroTarget:
            """Locator.

            Args:
                selector: Value supplied by the test or fixture for `selector`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
            return CountZeroTarget()

    with pytest.raises(PortalError) as exc:
        SauceDemoPages(CountZeroPage(), ConfigStub("accounts.json")).add_inventory_items(1)

    assert exc.value.reason is ReasonCode.ITEM_NOT_FOUND


def test_read_cart_count_returns_fake_attribute_when_present() -> None:
    """Verify that read cart count returns fake attribute when present.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    page = FakePage()
    page.cart_count = 4

    assert SauceDemoPages(page, ConfigStub("accounts.json")).read_cart_count() == 4


def test_read_cart_count_reads_numeric_badge_text() -> None:
    """Verify that read cart count reads numeric badge text.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    page = FakePage()
    delattr(page, "cart_count")
    page.text_values[SauceDemoPages.CART_BADGE] = "5"

    assert SauceDemoPages(page, ConfigStub("accounts.json")).read_cart_count() == 5


def test_read_cart_count_returns_zero_for_blank_badge_text() -> None:
    """Verify that read cart count returns zero for blank badge text.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    page = FakePage()
    delattr(page, "cart_count")

    assert SauceDemoPages(page, ConfigStub("accounts.json")).read_cart_count() == 0


def test_read_cart_count_returns_zero_when_badge_is_absent_in_dom() -> None:
    """Verify that read cart count returns zero when badge is absent in dom.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    page = DomPage(url="https://www.saucedemo.com/inventory.html")

    assert SauceDemoPages(page, ConfigStub("accounts.json")).read_cart_count() == 0


def test_read_cart_count_reads_integer_badge_from_dom() -> None:
    """Verify that read cart count reads integer badge from dom.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    page = DomPage(url="https://www.saucedemo.com/inventory.html")
    page.elements[SauceDemoPages.CART_BADGE] = [DomElement(text="3")]

    assert SauceDemoPages(page, ConfigStub("accounts.json")).read_cart_count() == 3


def test_page_methods_operate_against_fake_page_and_record_expected_calls() -> None:
    """Verify that page methods operate against fake page and record expected calls.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    page = FakePage()
    pages = SauceDemoPages(page, ConfigStub("accounts.json"))

    pages.open_cart()
    pages.checkout(account().checkout_profile)
    assert pages.read_order_summary() == page.order_summary
    pages.finish_order()
    assert pages.read_confirmation() == page.confirmation
    assert pages.capture_order_details() == page.order_details

    assert ("locator", SauceDemoPages.CART_LINK, "click") in page.calls
    assert ("locator", SauceDemoPages.CHECKOUT_BUTTON, "click") in page.calls
    assert ("locator", SauceDemoPages.FIRST_NAME_INPUT, "fill", "Standard") in page.calls
    assert ("locator", SauceDemoPages.LAST_NAME_INPUT, "fill", "User") in page.calls
    assert ("locator", SauceDemoPages.POSTAL_CODE_INPUT, "fill", "10001") in page.calls
    assert ("locator", SauceDemoPages.CONTINUE_BUTTON, "click") in page.calls
    assert ("locator", SauceDemoPages.FINISH_BUTTON, "click") in page.calls


def test_open_cart_real_dom_empty_cart_does_not_crash() -> None:
    """Verify that open cart real dom empty cart does not crash.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    page = DomPage(url="https://www.saucedemo.com/inventory.html")

    def on_open_cart() -> None:
        """On open cart.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        page.url = "https://www.saucedemo.com/cart.html"
        page.elements[SauceDemoPages.CHECKOUT_BUTTON] = [DomElement(text="Checkout")]

    page.click_handlers[(SauceDemoPages.CART_LINK, None)] = on_open_cart

    SauceDemoPages(page, ConfigStub("accounts.json")).open_cart()

    assert page.url.endswith("/cart.html")


def test_read_order_summary_reads_dom_summary_totals_and_item_count() -> None:
    """Verify that read order summary reads dom summary totals and item count.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    page = DomPage(url="https://www.saucedemo.com/checkout-step-two.html")
    page.elements[SauceDemoPages.CART_ITEM_ROW] = [DomElement(), DomElement(), DomElement()]
    page.elements[SauceDemoPages.SUBTOTAL_LABEL] = [DomElement(text="Item total: $55.97")]
    page.elements[SauceDemoPages.TAX_LABEL] = [DomElement(text="Tax: $4.48")]
    page.elements[SauceDemoPages.TOTAL_LABEL] = [DomElement(text="Total: $60.45")]

    summary = SauceDemoPages(page, ConfigStub("accounts.json")).read_order_summary()

    assert summary.item_count == 3
    assert summary.total == "Total: $60.45"
    assert "Item total: $55.97" in summary.confirmation_text
    assert "Tax: $4.48" in summary.confirmation_text
    assert "Total: $60.45" in summary.confirmation_text


def test_read_confirmation_reads_dom_header_and_text() -> None:
    """Verify that read confirmation reads dom header and text.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    page = DomPage(url="https://www.saucedemo.com/checkout-complete.html")
    page.elements[SauceDemoPages.CONFIRMATION_HEADER] = [
        DomElement(text="Thank you for your order!")
    ]
    page.elements[SauceDemoPages.CONFIRMATION_TEXT] = [
        DomElement(
            text=(
                "Your order has been dispatched, and will arrive just as fast "
                "as the pony can get there!"
            )
        )
    ]
    pages = SauceDemoPages(page, ConfigStub("accounts.json"))
    pages._last_order_summary = OrderSummary(
        item_count=3,
        confirmation_text="overview",
        total="Total: $60.45",
    )

    confirmation = pages.read_confirmation()

    assert confirmation.item_count == 3
    assert "Thank you for your order!" in confirmation.confirmation_text
    assert "pony can get there" in confirmation.confirmation_text
    assert confirmation.total == "Total: $60.45"


def test_capture_order_details_real_dom_does_not_leak_secret_like_keys() -> None:
    """Verify that capture order details real dom does not leak secret like keys.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    page = DomPage(url="https://www.saucedemo.com/checkout-step-two.html")
    page.elements[SauceDemoPages.CART_ITEM_NAME] = [
        DomElement(text="Sauce Labs Backpack"),
        DomElement(text="Sauce Labs Bike Light"),
    ]
    page.elements[SauceDemoPages.CART_ITEM_QUANTITY] = [
        DomElement(text="1"),
        DomElement(text="1"),
    ]
    page.elements[SauceDemoPages.SUBTOTAL_LABEL] = [DomElement(text="Item total: $39.98")]
    page.elements[SauceDemoPages.TAX_LABEL] = [DomElement(text="Tax: $3.20")]
    page.elements[SauceDemoPages.TOTAL_LABEL] = [DomElement(text="Total: $43.18")]

    details = SauceDemoPages(page, ConfigStub("accounts.json")).capture_order_details()

    assert details == {
        "item_names": ["Sauce Labs Backpack", "Sauce Labs Bike Light"],
        "item_quantities": ["1", "1"],
        "subtotal": "Item total: $39.98",
        "tax": "Tax: $3.20",
        "total": "Total: $43.18",
    }


def test_checkout_uses_current_sauce_demo_postal_code_selector() -> None:
    """Verify that checkout uses current sauce demo postal code selector.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    assert SauceDemoPages.POSTAL_CODE_INPUT == "#postal-code"


def test_capture_order_details_excludes_secret_like_fields() -> None:
    """Verify that capture order details excludes secret like fields.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    page = FakePage()
    page.order_details = {
        "order_id": "ord-001",
        "total": "$14.99",
        "password_hint": "hidden",
        "api_secret": "hidden",
        "access_token": "hidden",
        "credential_id": "hidden",
    }

    details = SauceDemoPages(page, ConfigStub("accounts.json")).capture_order_details()

    assert details == {"order_id": "ord-001", "total": "$14.99"}


def test_page_objects_do_not_import_persistence_or_sqlite_modules() -> None:
    """Verify that page objects do not import persistence or sqlite modules.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    source = (ROOT / "src/portal_automation/portals/saucedemo/pages.py").read_text(encoding="utf-8")

    assert "persistence" not in source
    assert "sqlite" not in source


def test_page_objects_and_runner_do_not_contain_demo_credentials() -> None:
    """Verify that page objects and runner do not contain demo credentials.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    paths = [
        ROOT / "src/portal_automation/portals/saucedemo/pages.py",
        ROOT / "src/portal_automation/portals/saucedemo/runner.py",
    ]

    for path in paths:
        source = path.read_text(encoding="utf-8")
        assert "secret_sauce" not in source
        assert "admin123" not in source


def test_runner_and_page_source_do_not_import_playwright_directly() -> None:
    """Verify that runner and page source do not import playwright directly.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    paths = [
        ROOT / "src/portal_automation/portals/saucedemo/pages.py",
        ROOT / "src/portal_automation/portals/saucedemo/runner.py",
    ]

    for path in paths:
        source = path.read_text(encoding="utf-8").lower()
        for forbidden in (
            "import playwright",
            "from playwright",
            "sync_playwright",
            "async_playwright",
            "chromium.launch",
            "firefox.launch",
            "webkit.launch",
        ):
            assert forbidden not in source


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
