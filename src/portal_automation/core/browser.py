from dataclasses import dataclass
from importlib import import_module
from typing import Any

from portal_automation.core.models import ReasonCode
from portal_automation.core.retries import PortalError

_PLAYWRIGHT_INSTALL_HINT = "python -m playwright install chromium"


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


class BrowserManager:
    def __init__(self, config: Any) -> None:
        self._config = config
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

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
            )

        try:
            playwright_factory = _load_sync_playwright()
            self._playwright = playwright_factory().start()
            self._browser = self._playwright.chromium.launch(headless=self._config.headless)
            self._context = self._browser.new_context()
            self._page = self._context.new_page()
            self._page.set_default_timeout(self._config.default_timeout_seconds * 1000)
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
        )

    def close(self) -> None:
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
