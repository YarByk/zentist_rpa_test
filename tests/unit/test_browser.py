from dataclasses import dataclass
from pathlib import Path

import pytest

from portal_automation.core.artifact_store import ArtifactStore
from portal_automation.core.browser import BrowserManager
from portal_automation.core.models import ReasonCode
from portal_automation.core.retries import PortalError


@dataclass
class ConfigStub:
    # Minimal config object covering only the fields BrowserManager reads.
    headless: bool = True
    default_timeout_seconds: int = 30
    playwright_trace_on_failure: bool = False
    playwright_screenshot_on_failure: bool = False
    visible_browser_pause_on_error_seconds: int = 0
    visible_browser_pause_on_result_seconds: int = 0
    playwright_persistent_profile_dir: str | None = None
    orangehrm_password: str | None = None
    saucedemo_password: str | None = None
    smtp_password: str | None = None


class FakePage:
    # Fake page object that records timeout and screenshot calls.
    def __init__(
        self,
        *,
        screenshot_error: Exception | None = None,
        set_content_error: Exception | None = None,
    ) -> None:
        """Initialize this test helper instance.

        Args:
            screenshot_error: Value supplied by the test or fixture for `screenshot_error`.
            set_content_error: Value supplied by the test or fixture for `set_content_error`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.default_timeout = None
        self.screenshot_error = screenshot_error
        self.set_content_error = set_content_error
        self.screenshot_calls: list[dict[str, object]] = []
        self.content_calls: list[dict[str, object]] = []

    def set_default_timeout(self, value: int) -> None:
        """Set default timeout.

        Args:
            value: Value supplied by the test or fixture for `value`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.default_timeout = value

    def set_content(self, html: str, *, wait_until: str | None = None) -> None:
        """Set page content.

        Args:
            html: Value supplied by the test or fixture for `html`.
            wait_until: Value supplied by the test or fixture for `wait_until`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.content_calls.append({"html": html, "wait_until": wait_until})
        if self.set_content_error is not None:
            raise self.set_content_error

    def screenshot(self, *, path: str, full_page: bool) -> None:
        """Screenshot.

        Args:
            path: Value supplied by the test or fixture for `path`.
            full_page: Value supplied by the test or fixture for `full_page`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.screenshot_calls.append({"path": path, "full_page": full_page})
        if self.screenshot_error is not None:
            raise self.screenshot_error
        with open(path, "wb") as handle:
            handle.write(b"png")


class FakeTracing:
    # Tracing stub used to validate start/stop behavior and generated trace files.
    def __init__(self, *, stop_error: Exception | None = None) -> None:
        """Initialize this test helper instance.

        Args:
            stop_error: Value supplied by the test or fixture for `stop_error`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.stop_error = stop_error
        self.start_calls: list[dict[str, bool]] = []
        self.stop_calls: list[str | None] = []

    def start(self, *, screenshots: bool, snapshots: bool, sources: bool) -> None:
        """Start.

        Args:
            screenshots: Value supplied by the test or fixture for `screenshots`.
            snapshots: Value supplied by the test or fixture for `snapshots`.
            sources: Value supplied by the test or fixture for `sources`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.start_calls.append(
            {
                "screenshots": screenshots,
                "snapshots": snapshots,
                "sources": sources,
            }
        )

    def stop(self, *, path: str | None = None) -> None:
        """Stop.

        Args:
            path: Value supplied by the test or fixture for `path`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.stop_calls.append(path)
        if self.stop_error is not None:
            raise self.stop_error
        if path is not None:
            with open(path, "wb") as handle:
                handle.write(b"trace")


class FakeContext:
    # Fake browser context that hands back one page instance and exposes tracing.
    def __init__(
        self,
        page: FakePage,
        tracing: FakeTracing | None = None,
        new_page: FakePage | None = None,
    ) -> None:
        """Initialize this test helper instance.

        Args:
            page: Value supplied by the test or fixture for `page`.
            tracing: Value supplied by the test or fixture for `tracing`.
            new_page: Value supplied by the test or fixture for `new_page`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.page = page
        self._new_page = new_page
        self.tracing = tracing
        self.closed = False
        self.new_page_calls = 0
        self.pages: list[FakePage] = []

    def new_page(self) -> FakePage:
        """New page.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.new_page_calls += 1
        if self._new_page is not None:
            return self._new_page
        return self.page

    def close(self) -> None:
        """Close.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.closed = True


class FakeBrowser:
    # Fake browser wrapper used to verify context creation and cleanup ordering.
    def __init__(self, context: FakeContext) -> None:
        """Initialize this test helper instance.

        Args:
            context: Value supplied by the test or fixture for `context`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.context = context
        self.closed = False
        self.new_context_calls = 0

    def new_context(self) -> FakeContext:
        """New context.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.new_context_calls += 1
        return self.context

    def close(self) -> None:
        """Close.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.closed = True


class FakeChromium:
    # Launch stub that can either return a fake browser or simulate a startup failure.
    def __init__(self, browser: FakeBrowser, *, launch_error: Exception | None = None) -> None:
        """Initialize this test helper instance.

        Args:
            browser: Value supplied by the test or fixture for `browser`.
            launch_error: Value supplied by the test or fixture for `launch_error`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.browser = browser
        self.launch_error = launch_error
        self.launch_calls = []
        self.launch_persistent_context_calls: list[dict[str, object]] = []

    def launch(self, *, headless: bool) -> FakeBrowser:
        """Launch.

        Args:
            headless: Value supplied by the test or fixture for `headless`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.launch_calls.append(headless)
        if self.launch_error is not None:
            raise self.launch_error
        return self.browser

    def launch_persistent_context(self, *, user_data_dir: str, headless: bool) -> FakeContext:
        """Launch persistent context.

        Args:
            user_data_dir: Value supplied by the test or fixture for `user_data_dir`.
            headless: Value supplied by the test or fixture for `headless`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            RuntimeError: If this fake was configured with a launch error.
        """
        self.launch_persistent_context_calls.append(
            {"user_data_dir": user_data_dir, "headless": headless}
        )
        if self.launch_error is not None:
            raise self.launch_error
        return self.browser.context


class FakePlaywright:
    # Minimal Playwright runtime stub with a Chromium handle and stop flag.
    def __init__(self, chromium: FakeChromium) -> None:
        """Initialize this test helper instance.

        Args:
            chromium: Value supplied by the test or fixture for `chromium`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.chromium = chromium
        self.stopped = False

    def stop(self) -> None:
        """Stop.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.stopped = True


class FakeSyncPlaywrightFactory:
    # Emulates sync_playwright() followed by .start().
    def __init__(self, playwright: FakePlaywright) -> None:
        """Initialize this test helper instance.

        Args:
            playwright: Value supplied by the test or fixture for `playwright`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.playwright = playwright
        self.started = False

    def __call__(self) -> "FakeSyncPlaywrightFactory":
        """Call.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        return self

    def start(self) -> FakePlaywright:
        """Start.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.started = True
        return self.playwright


def test_browser_manager_opens_page_and_sets_timeout(monkeypatch) -> None:
    # Opening the manager should launch Chromium, create a context, and set the page timeout.
    """Verify that browser manager opens page and sets timeout.

    Args:
        monkeypatch: Value supplied by the test or fixture for `monkeypatch`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
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


def test_browser_manager_shows_start_page_in_headed_mode(monkeypatch) -> None:
    """Verify that headed browser opens with a visible diagnostic start page.

    Args:
        monkeypatch: Value supplied by the test or fixture for `monkeypatch`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    page = FakePage()
    context = FakeContext(page)
    browser = FakeBrowser(context)
    chromium = FakeChromium(browser)
    playwright = FakePlaywright(chromium)
    factory = FakeSyncPlaywrightFactory(playwright)
    monkeypatch.setattr("portal_automation.core.browser._load_sync_playwright", lambda: factory)

    manager = BrowserManager(ConfigStub(headless=False))
    session = manager.open()

    assert session.page is page
    assert page.content_calls
    assert "Opening portal" in str(page.content_calls[-1]["html"])
    manager.close()


def test_browser_manager_uses_persistent_profile_when_configured(monkeypatch) -> None:
    """Verify that persistent profile mode launches a persistent browser context.

    Args:
        monkeypatch: Value supplied by the test or fixture for `monkeypatch`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    page = FakePage()
    context = FakeContext(page)
    browser = FakeBrowser(context)
    chromium = FakeChromium(browser)
    playwright = FakePlaywright(chromium)
    factory = FakeSyncPlaywrightFactory(playwright)
    monkeypatch.setattr("portal_automation.core.browser._load_sync_playwright", lambda: factory)

    manager = BrowserManager(
        ConfigStub(
            headless=False,
            playwright_persistent_profile_dir="artifacts/browser_profiles/orangehrm",
        )
    )
    session = manager.open()

    assert session.context is context
    assert chromium.launch_calls == []
    assert browser.new_context_calls == 0
    assert chromium.launch_persistent_context_calls == [
        {
            "user_data_dir": "artifacts/browser_profiles/orangehrm",
            "headless": False,
        }
    ]
    manager.close()
    assert context.closed is True
    assert browser.closed is False


def test_browser_manager_reuses_existing_persistent_profile_page(monkeypatch) -> None:
    """Verify that persistent profile mode does not create an extra about:blank tab.

    Args:
        monkeypatch: Value supplied by the test or fixture for `monkeypatch`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    page = FakePage()
    context = FakeContext(FakePage())
    context.pages = [page]
    browser = FakeBrowser(context)
    chromium = FakeChromium(browser)
    playwright = FakePlaywright(chromium)
    factory = FakeSyncPlaywrightFactory(playwright)
    monkeypatch.setattr("portal_automation.core.browser._load_sync_playwright", lambda: factory)

    manager = BrowserManager(
        ConfigStub(playwright_persistent_profile_dir="artifacts/browser_profiles/orangehrm")
    )
    session = manager.open()

    assert session.page is page
    assert context.new_page_calls == 0
    manager.close()


def test_browser_manager_visible_error_page_pauses_in_headed_mode(monkeypatch) -> None:
    """Verify that headed error pause renders diagnostic content and sleeps.

    Args:
        monkeypatch: Value supplied by the test or fixture for `monkeypatch`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    sleeps: list[int] = []
    page = FakePage()
    context = FakeContext(page)
    browser = FakeBrowser(context)
    chromium = FakeChromium(browser)
    playwright = FakePlaywright(chromium)
    factory = FakeSyncPlaywrightFactory(playwright)
    monkeypatch.setattr("portal_automation.core.browser._load_sync_playwright", lambda: factory)
    monkeypatch.setattr(
        "portal_automation.core.browser.sleep",
        lambda seconds: sleeps.append(seconds),
    )

    manager = BrowserManager(ConfigStub(headless=False, visible_browser_pause_on_error_seconds=7))
    manager.open()
    manager.pause_for_visible_error("Portal failed", "This page cannot be displayed")

    assert sleeps == [7]
    assert "Portal failed" in str(page.content_calls[-1]["html"])
    assert "This page cannot be displayed" in str(page.content_calls[-1]["html"])
    manager.close()


def test_browser_manager_visible_result_page_pauses_in_headed_mode(monkeypatch) -> None:
    """Verify that headed result pause renders success content and sleeps."""
    sleeps: list[int] = []
    page = FakePage()
    context = FakeContext(page)
    browser = FakeBrowser(context)
    chromium = FakeChromium(browser)
    playwright = FakePlaywright(chromium)
    factory = FakeSyncPlaywrightFactory(playwright)
    monkeypatch.setattr("portal_automation.core.browser._load_sync_playwright", lambda: factory)
    monkeypatch.setattr(
        "portal_automation.core.browser.sleep",
        lambda seconds: sleeps.append(seconds),
    )

    manager = BrowserManager(ConfigStub(headless=False, visible_browser_pause_on_result_seconds=5))
    manager.open()
    manager.pause_for_visible_result("Portal succeeded", "Completed 3 item(s)")

    assert sleeps == [5]
    assert "Portal succeeded" in str(page.content_calls[-1]["html"])
    assert "Completed 3 item(s)" in str(page.content_calls[-1]["html"])
    manager.close()


def test_browser_manager_result_page_falls_back_to_new_page_when_current_page_fails(
    monkeypatch,
) -> None:
    """Verify that final result diagnostics use a new tab if the active page is unusable.

    Args:
        monkeypatch: Pytest patch fixture.

    Returns:
        None. Assertions communicate the test outcome.

    Raises:
        AssertionError: If the fallback diagnostic page is not used.
    """
    sleeps: list[int] = []
    broken_page = FakePage(set_content_error=RuntimeError("page is navigating"))
    fallback_page = FakePage()
    context = FakeContext(broken_page, new_page=fallback_page)
    context.pages = [broken_page]
    browser = FakeBrowser(context)
    chromium = FakeChromium(browser)
    playwright = FakePlaywright(chromium)
    factory = FakeSyncPlaywrightFactory(playwright)
    monkeypatch.setattr("portal_automation.core.browser._load_sync_playwright", lambda: factory)
    monkeypatch.setattr(
        "portal_automation.core.browser.sleep",
        lambda seconds: sleeps.append(seconds),
    )

    manager = BrowserManager(ConfigStub(headless=False, visible_browser_pause_on_result_seconds=4))
    manager.open()
    manager.pause_for_visible_result("Portal finished", "Completed")

    assert sleeps == [4]
    assert context.new_page_calls == 1
    assert "Portal finished" in str(fallback_page.content_calls[-1]["html"])
    manager.close()


def test_browser_manager_accepts_per_portal_timeout_override(monkeypatch) -> None:
    """Verify that browser manager accepts per portal timeout override.

    Args:
        monkeypatch: Value supplied by the test or fixture for `monkeypatch`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
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
    """Verify that browser manager rejects non positive timeout override.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    with pytest.raises(ValueError, match="timeout_seconds must be greater than 0"):
        BrowserManager(ConfigStub(default_timeout_seconds=30), timeout_seconds=0)


def test_browser_manager_closes_resources_on_exception(monkeypatch) -> None:
    """Verify that browser manager closes resources on exception.

    Args:
        monkeypatch: Value supplied by the test or fixture for `monkeypatch`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
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
    """Verify that browser manager wraps missing chromium with portal error.

    Args:
        monkeypatch: Value supplied by the test or fixture for `monkeypatch`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
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
    """Verify that browser manager wraps missing playwright runtime.

    Args:
        monkeypatch: Value supplied by the test or fixture for `monkeypatch`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """

    def fail_loader():
        """Fail loader.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
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
    # When failure capture is enabled, both screenshot and trace artifacts should be created.
    """Verify that browser manager captures screenshot and trace on failure.

    Args:
        monkeypatch: Value supplied by the test or fixture for `monkeypatch`.
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
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
    """Verify that browser manager does not capture success artifacts.

    Args:
        monkeypatch: Value supplied by the test or fixture for `monkeypatch`.
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
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
    # Secret values from config must never leak into generated artifact filenames.
    """Verify that browser manager redacts config secrets from diagnostic names.

    Args:
        monkeypatch: Value supplied by the test or fixture for `monkeypatch`.
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
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
    """Verify that browser manager propagates screenshot capture failure.

    Args:
        monkeypatch: Value supplied by the test or fixture for `monkeypatch`.
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
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
