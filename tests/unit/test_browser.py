from dataclasses import dataclass
from pathlib import Path

import pytest

from portal_automation.core.artifact_store import ArtifactStore
from portal_automation.core.browser import BrowserManager
from portal_automation.core.models import ReasonCode
from portal_automation.core.retries import PortalError


@dataclass
class ConfigStub:
    headless: bool = True
    default_timeout_seconds: int = 30
    playwright_trace_on_failure: bool = False
    playwright_screenshot_on_failure: bool = False
    orangehrm_password: str | None = None
    saucedemo_password: str | None = None
    smtp_password: str | None = None


class FakePage:
    def __init__(self, *, screenshot_error: Exception | None = None) -> None:
        self.default_timeout = None
        self.screenshot_error = screenshot_error
        self.screenshot_calls: list[dict[str, object]] = []

    def set_default_timeout(self, value: int) -> None:
        self.default_timeout = value

    def screenshot(self, *, path: str, full_page: bool) -> None:
        self.screenshot_calls.append({"path": path, "full_page": full_page})
        if self.screenshot_error is not None:
            raise self.screenshot_error
        with open(path, "wb") as handle:
            handle.write(b"png")


class FakeTracing:
    def __init__(self, *, stop_error: Exception | None = None) -> None:
        self.stop_error = stop_error
        self.start_calls: list[dict[str, bool]] = []
        self.stop_calls: list[str | None] = []

    def start(self, *, screenshots: bool, snapshots: bool, sources: bool) -> None:
        self.start_calls.append(
            {
                "screenshots": screenshots,
                "snapshots": snapshots,
                "sources": sources,
            }
        )

    def stop(self, *, path: str | None = None) -> None:
        self.stop_calls.append(path)
        if self.stop_error is not None:
            raise self.stop_error
        if path is not None:
            with open(path, "wb") as handle:
                handle.write(b"trace")


class FakeContext:
    def __init__(self, page: FakePage, tracing: FakeTracing | None = None) -> None:
        self.page = page
        self.tracing = tracing
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


def test_browser_manager_accepts_per_portal_timeout_override(monkeypatch) -> None:
    page = FakePage()
    context = FakeContext(page)
    browser = FakeBrowser(context)
    chromium = FakeChromium(browser)
    playwright = FakePlaywright(chromium)
    factory = FakeSyncPlaywrightFactory(playwright)

    monkeypatch.setattr("portal_automation.core.browser._load_sync_playwright", lambda: factory)

    manager = BrowserManager(ConfigStub(default_timeout_seconds=30), timeout_seconds=17)
    with manager:
        assert page.default_timeout == 17000


def test_browser_manager_rejects_non_positive_timeout_override() -> None:
    with pytest.raises(ValueError, match="timeout_seconds must be greater than 0"):
        BrowserManager(ConfigStub(default_timeout_seconds=30), timeout_seconds=0)


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


def test_browser_manager_captures_screenshot_and_trace_on_failure(monkeypatch, tmp_path) -> None:
    page = FakePage()
    tracing = FakeTracing()
    context = FakeContext(page, tracing)
    browser = FakeBrowser(context)
    chromium = FakeChromium(browser)
    playwright = FakePlaywright(chromium)
    factory = FakeSyncPlaywrightFactory(playwright)

    monkeypatch.setattr("portal_automation.core.browser._load_sync_playwright", lambda: factory)

    config = ConfigStub(
        playwright_trace_on_failure=True,
        playwright_screenshot_on_failure=True,
    )
    manager = BrowserManager(config)
    manager.open()

    paths = manager.capture_failure_artifacts(
        run_id="run-1",
        portal_name="orangehrm",
        item_key="employee 1",
        artifacts=ArtifactStore(str(tmp_path / "artifacts")),
    )

    assert sorted(paths) == ["screenshot_path", "trace_path"]
    assert (
        Path(paths["screenshot_path"])
        .as_posix()
        .endswith("artifacts/runs/run-1/screenshots/orangehrm_employee_1_failure.png")
    )
    assert (
        Path(paths["trace_path"])
        .as_posix()
        .endswith("artifacts/runs/run-1/traces/orangehrm_employee_1_trace.zip")
    )
    assert page.screenshot_calls == [
        {"path": paths["screenshot_path"], "full_page": True},
    ]
    assert tracing.start_calls == [
        {"screenshots": True, "snapshots": True, "sources": True},
        {"screenshots": True, "snapshots": True, "sources": True},
    ]
    assert tracing.stop_calls == [paths["trace_path"]]
    assert (tmp_path / "artifacts" / "runs" / "run-1" / "screenshots").is_dir()
    assert (tmp_path / "artifacts" / "runs" / "run-1" / "traces").is_dir()

    manager.close()


def test_browser_manager_does_not_capture_success_artifacts(monkeypatch, tmp_path) -> None:
    page = FakePage()
    tracing = FakeTracing()
    context = FakeContext(page, tracing)
    browser = FakeBrowser(context)
    chromium = FakeChromium(browser)
    playwright = FakePlaywright(chromium)
    factory = FakeSyncPlaywrightFactory(playwright)

    monkeypatch.setattr("portal_automation.core.browser._load_sync_playwright", lambda: factory)

    manager = BrowserManager(
        ConfigStub(
            playwright_trace_on_failure=True,
            playwright_screenshot_on_failure=True,
        )
    )
    manager.open()
    manager.close()

    assert page.screenshot_calls == []
    assert tracing.stop_calls == [None]
    assert not (tmp_path / "artifacts").exists()


def test_browser_manager_redacts_config_secrets_from_diagnostic_names(
    monkeypatch,
    tmp_path,
) -> None:
    page = FakePage()
    context = FakeContext(page)
    browser = FakeBrowser(context)
    chromium = FakeChromium(browser)
    playwright = FakePlaywright(chromium)
    factory = FakeSyncPlaywrightFactory(playwright)

    monkeypatch.setattr("portal_automation.core.browser._load_sync_playwright", lambda: factory)

    manager = BrowserManager(
        ConfigStub(
            playwright_screenshot_on_failure=True,
            saucedemo_password="secret_sauce",
        )
    )
    manager.open()

    paths = manager.capture_failure_artifacts(
        run_id="run-1",
        portal_name="saucedemo",
        item_key="standard_user-secret_sauce",
        artifacts=ArtifactStore(str(tmp_path / "artifacts")),
    )

    assert "secret_sauce" not in paths["screenshot_path"]
    assert "redacted" in paths["screenshot_path"]


def test_browser_manager_propagates_screenshot_capture_failure(monkeypatch, tmp_path) -> None:
    page = FakePage(screenshot_error=RuntimeError("screenshot failed"))
    context = FakeContext(page)
    browser = FakeBrowser(context)
    chromium = FakeChromium(browser)
    playwright = FakePlaywright(chromium)
    factory = FakeSyncPlaywrightFactory(playwright)

    monkeypatch.setattr("portal_automation.core.browser._load_sync_playwright", lambda: factory)

    manager = BrowserManager(ConfigStub(playwright_screenshot_on_failure=True))
    manager.open()

    with pytest.raises(RuntimeError, match="screenshot failed"):
        manager.capture_failure_artifacts(
            run_id="run-1",
            portal_name="orangehrm",
            item_key="employee",
            artifacts=ArtifactStore(str(tmp_path / "artifacts")),
        )
