from dataclasses import dataclass

import pytest

from portal_automation.core.browser import BrowserManager
from portal_automation.core.models import ReasonCode
from portal_automation.core.retries import PortalError


@dataclass
class ConfigStub:
    headless: bool = True
    default_timeout_seconds: int = 30


class FakePage:
    def __init__(self) -> None:
        self.default_timeout = None

    def set_default_timeout(self, value: int) -> None:
        self.default_timeout = value


class FakeContext:
    def __init__(self, page: FakePage) -> None:
        self.page = page
        self.closed = False
        self.new_page_calls = 0

    def new_page(self) -> FakePage:
        self.new_page_calls += 1
        return self.page

    def close(self) -> None:
        self.closed = True


class FakeBrowser:
    def __init__(self, context: FakeContext) -> None:
        self.context = context
        self.closed = False
        self.new_context_calls = 0

    def new_context(self) -> FakeContext:
        self.new_context_calls += 1
        return self.context

    def close(self) -> None:
        self.closed = True


class FakeChromium:
    def __init__(self, browser: FakeBrowser, *, launch_error: Exception | None = None) -> None:
        self.browser = browser
        self.launch_error = launch_error
        self.launch_calls = []

    def launch(self, *, headless: bool) -> FakeBrowser:
        self.launch_calls.append(headless)
        if self.launch_error is not None:
            raise self.launch_error
        return self.browser


class FakePlaywright:
    def __init__(self, chromium: FakeChromium) -> None:
        self.chromium = chromium
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


class FakeSyncPlaywrightFactory:
    def __init__(self, playwright: FakePlaywright) -> None:
        self.playwright = playwright
        self.started = False

    def __call__(self) -> "FakeSyncPlaywrightFactory":
        return self

    def start(self) -> FakePlaywright:
        self.started = True
        return self.playwright


def test_browser_manager_opens_page_and_sets_timeout(monkeypatch) -> None:
    page = FakePage()
    context = FakeContext(page)
    browser = FakeBrowser(context)
    chromium = FakeChromium(browser)
    playwright = FakePlaywright(chromium)
    factory = FakeSyncPlaywrightFactory(playwright)

    monkeypatch.setattr("portal_automation.core.browser._load_sync_playwright", lambda: factory)

    manager = BrowserManager(ConfigStub(headless=False, default_timeout_seconds=15))
    with manager as session:
        assert session.page is page
        assert session.context is context
        assert session.browser is browser
        assert factory.started is True
        assert chromium.launch_calls == [False]
        assert context.new_page_calls == 1
        assert browser.new_context_calls == 1
        assert page.default_timeout == 15000

    assert context.closed is True
    assert browser.closed is True
    assert playwright.stopped is True


def test_browser_manager_closes_resources_on_exception(monkeypatch) -> None:
    page = FakePage()
    context = FakeContext(page)
    browser = FakeBrowser(context)
    chromium = FakeChromium(browser)
    playwright = FakePlaywright(chromium)
    factory = FakeSyncPlaywrightFactory(playwright)

    monkeypatch.setattr("portal_automation.core.browser._load_sync_playwright", lambda: factory)

    manager = BrowserManager(ConfigStub())

    with pytest.raises(RuntimeError, match="boom"):
        with manager:
            raise RuntimeError("boom")

    assert context.closed is True
    assert browser.closed is True
    assert playwright.stopped is True


def test_browser_manager_wraps_missing_chromium_with_portal_error(monkeypatch) -> None:
    page = FakePage()
    context = FakeContext(page)
    browser = FakeBrowser(context)
    chromium = FakeChromium(browser, launch_error=RuntimeError("Executable doesn't exist"))
    playwright = FakePlaywright(chromium)
    factory = FakeSyncPlaywrightFactory(playwright)

    monkeypatch.setattr("portal_automation.core.browser._load_sync_playwright", lambda: factory)

    manager = BrowserManager(ConfigStub())

    with pytest.raises(PortalError) as exc_info:
        manager.open()

    assert exc_info.value.reason.value == "PORTAL_UNAVAILABLE"
    assert "python -m playwright install chromium" in exc_info.value.detail
    assert "Unable to launch Chromium browser." in exc_info.value.detail
    assert browser.closed is False
    assert context.closed is False
    assert playwright.stopped is True


def test_browser_manager_wraps_missing_playwright_runtime(monkeypatch) -> None:
    def fail_loader():
        raise PortalError(
            reason=ReasonCode.PORTAL_UNAVAILABLE,
            detail=(
                "Playwright runtime is unavailable. "
                "Install Chromium with: python -m playwright install chromium"
            ),
        )

    monkeypatch.setattr("portal_automation.core.browser._load_sync_playwright", fail_loader)

    manager = BrowserManager(ConfigStub())

    with pytest.raises(PortalError) as exc_info:
        manager.open()

    assert exc_info.value.reason.value == "PORTAL_UNAVAILABLE"
    assert "python -m playwright install chromium" in exc_info.value.detail
