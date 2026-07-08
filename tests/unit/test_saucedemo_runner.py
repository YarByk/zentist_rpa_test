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
    saucedemo_input_path: str
    saucedemo_password: str | None = "pw"
    saucedemo_base_url: str = "https://www.saucedemo.com"
    report_email_to: str | None = "reviewer@example.com"


@dataclass
class ContextStub:
    config: object
    reporter: object


class FakePersistence:
    def __init__(self) -> None:
        self.created_runs = []
        self.finished_runs = []
        self.real_run_methods = []

    def create_run(self, run_id: str, portal_name: str, business_date: date) -> None:
        self.created_runs.append((run_id, portal_name, business_date))

    def finish_run(self, run_id: str, status: RunStatus, summary: dict[str, int]) -> None:
        self.finished_runs.append((run_id, status, summary))

    def get_committed_items(self, portal_name: str, business_date: date) -> set[str]:
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
        self.real_run_methods.append("mark_item_in_progress")

    def upsert_item_result(self, *args: object) -> None:
        self.real_run_methods.append("upsert_item_result")

    def list_results_by_business_date(self, portal_name: str, business_date: date) -> list[object]:
        self.real_run_methods.append("list_results_by_business_date")
        return []


class ReporterStub:
    def __init__(self) -> None:
        self.written_results: list[RunResult] = []

    def write_report(self, result: RunResult) -> None:
        self.written_results.append(result)

    def render(self, result: RunResult) -> str:
        return f"rendered-report:{result.run_id}:{result.status.value}"


class EmailStub:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def send_report(self, **kwargs: object) -> None:
        self.calls.append(kwargs)


class FakeTarget:
    def __init__(self, page: "FakePage", kind: str, name: str) -> None:
        self.page = page
        self.kind = kind
        self.name = name

    def fill(self, value: str) -> None:
        self.page.calls.append((self.kind, self.name, "fill", value))

    def click(self) -> None:
        self.page.calls.append((self.kind, self.name, "click"))

    def first(self) -> "FakeTarget":
        self.page.calls.append((self.kind, self.name, "first"))
        return self

    def text_content(self) -> str:
        self.page.calls.append((self.kind, self.name, "text_content"))
        return self.page.text_values.get(self.name, "")


class FakePage:
    def __init__(self) -> None:
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
        self.calls.append(("goto", url))

    def locator(self, selector: str) -> FakeTarget:
        self.calls.append(("locator", selector))
        return FakeTarget(self, "locator", selector)


class DomElement:
    def __init__(self, *, text: str = "", attrs: dict[str, str] | None = None) -> None:
        self.text = text
        self.attrs = attrs or {}
        self.value = ""


class DomLocator:
    def __init__(self, page: "DomPage", selector: str, index: int | None = None) -> None:
        self.page = page
        self.selector = selector
        self.index = index

    def count(self) -> int:
        return len(self.page.elements.get(self.selector, []))

    def nth(self, index: int) -> "DomLocator":
        return DomLocator(self.page, self.selector, index=index)

    def first(self) -> "DomLocator":
        return self.nth(0)

    def fill(self, value: str) -> None:
        self.page.fills.append((self.selector, self.index, value))
        element = self._element()
        element.value = value

    def click(self) -> None:
        self.page.clicks.append((self.selector, self.index))
        handler = self.page.click_handlers.get((self.selector, self.index))
        if handler is None:
            handler = self.page.click_handlers.get((self.selector, None))
        if handler is not None:
            handler()

    def text_content(self) -> str:
        return self._element().text

    def all_text_contents(self) -> list[str]:
        return [element.text for element in self.page.elements.get(self.selector, [])]

    def _element(self) -> DomElement:
        elements = self.page.elements.get(self.selector, [])
        if not elements:
            raise AssertionError(f"no element for selector {self.selector}")
        if self.index is None:
            return elements[0]
        return elements[self.index]


class DomPage:
    def __init__(self, *, url: str = "https://www.saucedemo.com/") -> None:
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
        self.url = url
        self.goto_calls.append(url)

    def locator(self, selector: str) -> DomLocator:
        return DomLocator(self, selector)

    def wait_for_url(self, pattern: str) -> None:
        self.waited_urls.append(pattern)


def account() -> SauceDemoAccount:
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


def write_saucedemo_input(tmp_path) -> str:
    path = tmp_path / "accounts.json"
    path.write_text(
        json.dumps(
            [
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
        ),
        encoding="utf-8",
    )
    return str(path)


def make_run_context(tmp_path, *, reporter=None) -> RunContext:
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
    return ContextStub(
        config=ConfigStub(saucedemo_input_path=write_saucedemo_input(tmp_path)),
        reporter=reporter if reporter is not None else object(),
    )


def test_runner_contract_constants_are_correct() -> None:
    assert SauceDemoRunner.portal_name == "saucedemo"
    assert SauceDemoRunner.operation_name == "checkout"
    assert SauceDemoRunner.max_sessions_per_account == 1


def test_runner_inherits_base_and_does_not_override_run() -> None:
    assert issubclass(SauceDemoRunner, BasePortalRunnerZX)
    assert "run" not in SauceDemoRunner.__dict__
    assert SauceDemoRunner.run is BasePortalRunnerZX.run


def test_runner_item_key_uses_account_key() -> None:
    assert SauceDemoRunner().item_key(account()) == "standard_user"


def test_dry_run_does_not_call_page_factory_or_process_item(tmp_path) -> None:
    factory_calls = []

    def pages_factory(context: RunContext) -> object:
        factory_calls.append(context)
        raise AssertionError("page factory must not be called in dry-run")

    runner = SauceDemoRunner(pages_factory=pages_factory)
    context = make_run_context(tmp_path)

    result = runner.run(context)

    assert result.status is RunStatus.SUCCESS
    assert factory_calls == []
    assert context.persistence.real_run_methods == []


def test_process_item_uses_injected_page_factory_and_workflow(tmp_path, monkeypatch) -> None:
    pages = object()
    calls = []

    def pages_factory(context: ContextStub) -> object:
        calls.append(("factory", context))
        return pages

    def fake_process_account(record, page_objects, context):
        calls.append(("workflow", record, page_objects, context))
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
    assert calls == [
        ("factory", context),
        ("workflow", account(), pages, context),
    ]


def test_process_item_without_page_factory_raises_portal_unavailable(tmp_path) -> None:
    with pytest.raises(PortalError) as error:
        SauceDemoRunner().process_item(make_process_context(tmp_path), account())

    assert error.value.reason is ReasonCode.PORTAL_UNAVAILABLE
    assert "page factory" in error.value.detail


@pytest.mark.parametrize("password", [None, "", "   "])
def test_preflight_raises_credential_expired_when_password_missing_or_blank(
    tmp_path,
    password,
) -> None:
    context = make_process_context(tmp_path)
    context.config.saucedemo_password = password

    with pytest.raises(PortalError) as error:
        SauceDemoRunner().preflight_check(context)

    assert error.value.reason is ReasonCode.CREDENTIAL_EXPIRED


def test_preflight_passes_with_required_non_browser_config(tmp_path) -> None:
    SauceDemoRunner().preflight_check(make_process_context(tmp_path))


def test_preflight_does_not_call_page_factory(tmp_path) -> None:
    factory_calls = []
    runner = SauceDemoRunner(pages_factory=lambda context: factory_calls.append(context))

    runner.preflight_check(make_process_context(tmp_path))

    assert factory_calls == []


def test_load_items_still_reads_validated_input_records(tmp_path) -> None:
    context = make_process_context(tmp_path)

    items = SauceDemoRunner().load_items(context)

    assert items == [account()]


def test_finalize_writes_report_when_reporter_supports_write_report(tmp_path) -> None:
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
    result = RunResult(
        run_id="run-sd-1",
        portal_name="saucedemo",
        business_date=date(2026, 6, 29),
        status=RunStatus.SUCCESS,
        results=[],
    )

    SauceDemoRunner().finalize(make_process_context(tmp_path), result)


def test_saucedemo_pages_login_uses_arguments_config_values_and_page_calls() -> None:
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
    page = FakePage()
    page.login_locked_out = True

    result = SauceDemoPages(page, ConfigStub("accounts.json")).login("locked_out_user", "pw")

    assert result.status is LoginStatus.LOCKED_OUT
    assert "locked out" in result.detail


def test_saucedemo_pages_login_returns_failed_result() -> None:
    page = FakePage()
    page.login_succeeded = False

    result = SauceDemoPages(page, ConfigStub("accounts.json")).login("standard_user", "pw")

    assert result.status is LoginStatus.FAILED
    assert "login failed" in result.detail


def test_saucedemo_pages_login_reads_locked_out_dom_error() -> None:
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
    page = DomPage()

    def on_login() -> None:
        page.url = "https://www.saucedemo.com/inventory.html"
        page.elements[SauceDemoPages.INVENTORY_ITEM] = [DomElement(text="item")]

    page.click_handlers[(SauceDemoPages.LOGIN_BUTTON, None)] = on_login

    result = SauceDemoPages(page, ConfigStub("accounts.json")).login("standard_user", "pw")

    assert result.status is LoginStatus.SUCCESS


def test_add_inventory_items_records_exactly_requested_clicks() -> None:
    page = FakePage()

    SauceDemoPages(page, ConfigStub("accounts.json")).add_inventory_items(2)

    # Fake branch records one locator call and one click per item, no .first() indirection
    assert page.calls.count(("locator", SauceDemoPages.ADD_TO_CART_BUTTON, "click")) == 2


def test_add_inventory_items_raises_when_no_buttons_available() -> None:
    """Real branch: raises ITEM_NOT_FOUND immediately when count() returns 0."""

    class CountZeroTarget:
        def count(self) -> int:
            return 0

        def nth(self, index: int) -> "CountZeroTarget":
            return self

        def click(self) -> None:
            raise AssertionError("click should not be called when count is 0")

    class CountZeroPage:
        def locator(self, selector: str) -> CountZeroTarget:
            return CountZeroTarget()

    with pytest.raises(PortalError) as exc:
        SauceDemoPages(CountZeroPage(), ConfigStub("accounts.json")).add_inventory_items(1)

    assert exc.value.reason is ReasonCode.ITEM_NOT_FOUND


def test_read_cart_count_returns_fake_attribute_when_present() -> None:
    page = FakePage()
    page.cart_count = 4

    assert SauceDemoPages(page, ConfigStub("accounts.json")).read_cart_count() == 4


def test_read_cart_count_reads_numeric_badge_text() -> None:
    page = FakePage()
    delattr(page, "cart_count")
    page.text_values[SauceDemoPages.CART_BADGE] = "5"

    assert SauceDemoPages(page, ConfigStub("accounts.json")).read_cart_count() == 5


def test_read_cart_count_returns_zero_for_blank_badge_text() -> None:
    page = FakePage()
    delattr(page, "cart_count")

    assert SauceDemoPages(page, ConfigStub("accounts.json")).read_cart_count() == 0


def test_read_cart_count_returns_zero_when_badge_is_absent_in_dom() -> None:
    page = DomPage(url="https://www.saucedemo.com/inventory.html")

    assert SauceDemoPages(page, ConfigStub("accounts.json")).read_cart_count() == 0


def test_read_cart_count_reads_integer_badge_from_dom() -> None:
    page = DomPage(url="https://www.saucedemo.com/inventory.html")
    page.elements[SauceDemoPages.CART_BADGE] = [DomElement(text="3")]

    assert SauceDemoPages(page, ConfigStub("accounts.json")).read_cart_count() == 3


def test_page_methods_operate_against_fake_page_and_record_expected_calls() -> None:
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
    page = DomPage(url="https://www.saucedemo.com/inventory.html")

    def on_open_cart() -> None:
        page.url = "https://www.saucedemo.com/cart.html"
        page.elements[SauceDemoPages.CHECKOUT_BUTTON] = [DomElement(text="Checkout")]

    page.click_handlers[(SauceDemoPages.CART_LINK, None)] = on_open_cart

    SauceDemoPages(page, ConfigStub("accounts.json")).open_cart()

    assert page.url.endswith("/cart.html")


def test_read_order_summary_reads_dom_summary_totals_and_item_count() -> None:
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
    assert SauceDemoPages.POSTAL_CODE_INPUT == "#postal-code"


def test_capture_order_details_excludes_secret_like_fields() -> None:
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
    source = (ROOT / "src/portal_automation/portals/saucedemo/pages.py").read_text(
        encoding="utf-8"
    )

    assert "persistence" not in source
    assert "sqlite" not in source


def test_page_objects_and_runner_do_not_contain_demo_credentials() -> None:
    paths = [
        ROOT / "src/portal_automation/portals/saucedemo/pages.py",
        ROOT / "src/portal_automation/portals/saucedemo/runner.py",
    ]

    for path in paths:
        source = path.read_text(encoding="utf-8")
        assert "secret_sauce" not in source
        assert "admin123" not in source


def test_runner_and_page_source_do_not_import_playwright_directly() -> None:
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
    forbidden_paths = [
        "src/portal_automation/core/logging.py",
    ]

    assert [path for path in forbidden_paths if (ROOT / path).exists()] == []
