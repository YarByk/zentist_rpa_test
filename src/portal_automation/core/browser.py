from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any

from portal_automation.core.models import ReasonCode
from portal_automation.core.retries import PortalError

_PLAYWRIGHT_INSTALL_HINT = "python -m playwright install chromium"
_SECRET_PLACEHOLDER = "redacted"


def _portal_unavailable(detail: str, *, cause: Exception | None = None) -> PortalError:
    message = f"{detail} Install Chromium with: {_PLAYWRIGHT_INSTALL_HINT}"
    if cause is not None and str(cause):
        message = f"{detail}: {cause}. Install Chromium with: {_PLAYWRIGHT_INSTALL_HINT}"
    return PortalError(ReasonCode.PORTAL_UNAVAILABLE, message)


def _load_sync_playwright() -> Any:
    try:
        module = import_module("playwright.sync_api")
    except ModuleNotFoundError as exc:
        raise _portal_unavailable("Playwright runtime is unavailable.", cause=exc) from exc
    return module.sync_playwright


@dataclass
class BrowserSession:
    browser: Any
    context: Any
    page: Any
    diagnostics: Any | None = None


class BrowserManager:
    def __init__(self, config: Any, *, timeout_seconds: int | None = None) -> None:
        if timeout_seconds is not None and timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than 0")
        self._config = config
        self._timeout_seconds = timeout_seconds
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._tracing_started = False

    def __enter__(self) -> BrowserSession:
        return self.open()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def open(self) -> BrowserSession:
        if self._page is not None:
            return BrowserSession(
                browser=self._browser,
                context=self._context,
                page=self._page,
                diagnostics=self,
            )

        try:
            playwright_factory = _load_sync_playwright()
            self._playwright = playwright_factory().start()
            self._browser = self._playwright.chromium.launch(headless=self._config.headless)
            self._context = self._browser.new_context()
            self._start_tracing_if_enabled()
            self._page = self._context.new_page()
            self._page.set_default_timeout(self._resolved_timeout_seconds() * 1000)
        except PortalError:
            self.close()
            raise
        except Exception as exc:
            self.close()
            raise _portal_unavailable("Unable to launch Chromium browser.", cause=exc) from exc

        return BrowserSession(
            browser=self._browser,
            context=self._context,
            page=self._page,
            diagnostics=self,
        )

    def _resolved_timeout_seconds(self) -> int:
        if self._timeout_seconds is not None:
            return self._timeout_seconds
        return self._config.default_timeout_seconds

    def capture_failure_artifacts(
        self,
        *,
        run_id: str,
        portal_name: str,
        item_key: str,
        artifacts: Any,
    ) -> dict[str, str]:
        captured: dict[str, str] = {}
        safe_item_key = self._safe_item_key(item_key)

        if getattr(self._config, "playwright_screenshot_on_failure", False):
            screenshot_path = artifacts.failure_screenshot_path(run_id, portal_name, safe_item_key)
            if self._capture_screenshot(screenshot_path):
                captured["screenshot_path"] = str(screenshot_path)

        if getattr(self._config, "playwright_trace_on_failure", False):
            trace_path = artifacts.failure_trace_path(run_id, portal_name, safe_item_key)
            if self._capture_trace(trace_path):
                captured["trace_path"] = str(trace_path)

        return captured

    def close(self) -> None:
        self._stop_tracing_without_artifact()

        if self._context is not None:
            try:
                self._context.close()
            finally:
                self._context = None
                self._page = None

        if self._browser is not None:
            try:
                self._browser.close()
            finally:
                self._browser = None

        if self._playwright is not None:
            try:
                self._playwright.stop()
            finally:
                self._playwright = None

    def _start_tracing_if_enabled(self) -> None:
        if not getattr(self._config, "playwright_trace_on_failure", False):
            return
        tracing = self._tracing()
        if tracing is None or not hasattr(tracing, "start"):
            return
        try:
            tracing.start(screenshots=True, snapshots=True, sources=True)
        except Exception:
            self._tracing_started = False
            return
        self._tracing_started = True

    def _capture_screenshot(self, path: Path) -> bool:
        if self._page is None or not hasattr(self._page, "screenshot"):
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        self._page.screenshot(path=str(path), full_page=True)
        return True

    def _capture_trace(self, path: Path) -> bool:
        if not self._tracing_started:
            return False
        tracing = self._tracing()
        if tracing is None or not hasattr(tracing, "stop"):
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        tracing.stop(path=str(path))
        self._tracing_started = False
        self._start_tracing_if_enabled()
        return True

    def _stop_tracing_without_artifact(self) -> None:
        if not self._tracing_started:
            return
        tracing = self._tracing()
        if tracing is None or not hasattr(tracing, "stop"):
            self._tracing_started = False
            return
        try:
            tracing.stop()
        except Exception:
            self._tracing_started = False
        else:
            self._tracing_started = False

    def _tracing(self) -> Any | None:
        if self._context is None:
            return None
        return getattr(self._context, "tracing", None)

    def _safe_item_key(self, item_key: str) -> str:
        safe = str(item_key)
        for secret in self._secret_values():
            if secret:
                safe = safe.replace(secret, _SECRET_PLACEHOLDER)
        return safe

    def _secret_values(self) -> tuple[str, ...]:
        values = []
        for name in (
            "orangehrm_password",
            "saucedemo_password",
            "smtp_password",
        ):
            value = getattr(self._config, name, None)
            if value:
                values.append(str(value))
        return tuple(values)
