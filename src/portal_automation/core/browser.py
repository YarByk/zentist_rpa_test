from dataclasses import dataclass
from html import escape
from importlib import import_module
from pathlib import Path
from time import sleep
from typing import Any

from portal_automation.core.models import ReasonCode
from portal_automation.core.retries import PortalError

_PLAYWRIGHT_INSTALL_HINT = "python -m playwright install chromium"
_SECRET_PLACEHOLDER = "redacted"


def _portal_unavailable(detail: str, *, cause: Exception | None = None) -> PortalError:
    """Build a portal-unavailable error with the Chromium install hint.

    Args:
        detail: Human-readable failure summary.
        cause: Optional underlying exception to include in the detail.

    Returns:
        ``PortalError`` with reason ``PORTAL_UNAVAILABLE``.
    """
    # Centralize the install hint so every Playwright startup failure gives the same remediation.
    message = f"{detail} Install Chromium with: {_PLAYWRIGHT_INSTALL_HINT}"
    if cause is not None and str(cause):
        message = f"{detail}: {cause}. Install Chromium with: {_PLAYWRIGHT_INSTALL_HINT}"
    return PortalError(ReasonCode.PORTAL_UNAVAILABLE, message)


def _load_sync_playwright() -> Any:
    """Import and return Playwright's synchronous context factory.

    Returns:
        ``sync_playwright`` factory from ``playwright.sync_api``.

    Raises:
        PortalError: If Playwright is not installed in the runtime environment.
    """
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
        """Create a manager for one Chromium-backed automation session.

        Args:
            config: Runtime config with headless and diagnostic settings.
            timeout_seconds: Optional per-portal timeout override.

        Raises:
            ValueError: If ``timeout_seconds`` is provided and not positive.
        """
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
        """Open the browser session when entering a context manager.

        Returns:
            Open ``BrowserSession``.

        Raises:
            PortalError: If Playwright or Chromium cannot start.
        """
        return self.open()

    def __exit__(self, exc_type, exc, tb) -> None:
        """Close browser resources when leaving a context manager.

        Args:
            exc_type: Exception type from the context block, if any.
            exc: Exception instance from the context block, if any.
            tb: Traceback from the context block, if any.
        """
        self.close()

    def open(self) -> BrowserSession:
        """Start Playwright, launch Chromium, and create one page.

        Returns:
            Open browser session. Repeated calls return the existing session.

        Raises:
            PortalError: If Playwright import or Chromium startup fails.
        """
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
            self._open_context()
            self._start_tracing_if_enabled()
            self._page = self._resolve_initial_page()
            self._page.set_default_timeout(self._resolved_timeout_seconds() * 1000)
            self.show_debug_page(
                "Opening portal",
                "Chromium is ready. The automation is about to navigate to the portal.",
            )
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

    def _open_context(self) -> None:
        """Open either an isolated browser context or a persistent profile context.

        Raises:
            Exception: If Chromium cannot launch or create the requested context.
        """
        profile_dir = getattr(self._config, "playwright_persistent_profile_dir", None)
        if profile_dir:
            # Persistent contexts keep history, cookies, and storage in a dedicated profile folder.
            self._context = self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=self._config.headless,
            )
            # A persistent context owns its browser process; context.close() is the correct
            # cleanup path and avoids a double-close against the underlying browser.
            self._browser = None
            return
        # Default mode stays isolated and disposable for clean automated runs.
        self._browser = self._playwright.chromium.launch(headless=self._config.headless)
        self._context = self._browser.new_context()

    def _resolve_initial_page(self) -> Any:
        """Return an existing persistent page or create a new context page.

        Returns:
            Playwright page object.
        """
        pages = getattr(self._context, "pages", None)
        if pages:
            return pages[0]
        return self._context.new_page()

    def show_debug_page(self, title: str, detail: str) -> None:
        """Render a visible diagnostic page in headed mode.

        Args:
            title: Short page title.
            detail: Human-readable detail text.
        """
        if getattr(self._config, "headless", True):
            return
        if self._page is None:
            return
        html = self._debug_html(title, detail)
        if self._set_page_content(self._page, html):
            return
        fallback_page = self._new_diagnostic_page()
        if fallback_page is not None and self._set_page_content(fallback_page, html):
            self._page = fallback_page

    def pause_for_visible_error(self, title: str, detail: str) -> None:
        """Show a headed-browser error page and keep the browser open briefly.

        Args:
            title: Short diagnostic title.
            detail: Human-readable error detail.
        """
        pause_seconds = int(getattr(self._config, "visible_browser_pause_on_error_seconds", 0))
        self._pause_with_debug_page(title, detail, pause_seconds)

    def pause_for_visible_result(self, title: str, detail: str) -> None:
        """Show a headed-browser result page and keep the browser open briefly.

        Args:
            title: Short diagnostic title.
            detail: Human-readable result detail.
        """
        pause_seconds = int(
            getattr(
                self._config,
                "visible_browser_pause_on_result_seconds",
                getattr(self._config, "visible_browser_pause_on_error_seconds", 0),
            )
        )
        self._pause_with_debug_page(title, detail, pause_seconds)

    def _pause_with_debug_page(self, title: str, detail: str, pause_seconds: int) -> None:
        """Show a debug page and sleep when headed diagnostics are enabled.

        Args:
            title: Short diagnostic title.
            detail: Human-readable page detail.
            pause_seconds: Number of seconds to keep the browser open.
        """
        if getattr(self._config, "headless", True) or pause_seconds <= 0:
            return
        self.show_debug_page(title, detail)
        sleep(pause_seconds)

    def _set_page_content(self, page: Any, html: str) -> bool:
        """Best-effort render diagnostic HTML into a page.

        Args:
            page: Playwright-like page object.
            html: HTML document to render.

        Returns:
            ``True`` when content was set successfully.
        """
        if not hasattr(page, "set_content"):
            return False
        try:
            page.set_content(html, wait_until="domcontentloaded")
            return True
        except TypeError:
            try:
                page.set_content(html)
                return True
            except Exception:
                return False
        except Exception:
            return False

    def _new_diagnostic_page(self) -> Any | None:
        """Create a replacement page for diagnostics when the current page is unusable.

        Returns:
            New page object, or ``None`` when a page cannot be created.
        """
        if self._context is None or not hasattr(self._context, "new_page"):
            return None
        try:
            return self._context.new_page()
        except Exception:
            return None

    def _resolved_timeout_seconds(self) -> int:
        """Return the effective default timeout in seconds.

        Returns:
            Per-portal override when present, otherwise config default timeout.
        """
        if self._timeout_seconds is not None:
            return self._timeout_seconds
        return self._config.default_timeout_seconds

    def _debug_html(self, title: str, detail: str) -> str:
        """Build a small self-contained browser diagnostic page.

        Args:
            title: Short page title.
            detail: Diagnostic detail.

        Returns:
            HTML document string.
        """
        safe_title = escape(str(title))
        safe_detail = escape(str(detail))
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{safe_title}</title>
  <style>
    body {{
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      background: linear-gradient(135deg, #eef7f2, #d8edf5);
      color: #183247;
      font-family: Georgia, "Times New Roman", serif;
    }}
    main {{
      width: min(780px, calc(100vw - 48px));
      padding: 36px;
      border-radius: 24px;
      background: rgba(255, 255, 255, 0.88);
      box-shadow: 0 24px 80px rgba(24, 50, 71, 0.20);
    }}
    h1 {{ margin: 0 0 16px; font-size: 34px; }}
    pre {{
      white-space: pre-wrap;
      font: 15px/1.5 Consolas, "Courier New", monospace;
      padding: 18px;
      border-radius: 14px;
      background: #f3f7f8;
      overflow-wrap: anywhere;
    }}
  </style>
</head>
<body>
  <main>
    <h1>{safe_title}</h1>
    <pre>{safe_detail}</pre>
  </main>
</body>
</html>"""

    def capture_failure_artifacts(
        self,
        *,
        run_id: str,
        portal_name: str,
        item_key: str,
        artifacts: Any,
    ) -> dict[str, str]:
        """Capture configured diagnostic artifacts for a failed item.

        Args:
            run_id: Run identifier used for artifact placement.
            portal_name: Portal key.
            item_key: Business item key associated with the failure.
            artifacts: Artifact store with diagnostic path helpers.

        Returns:
            Dictionary containing captured artifact paths.

        Raises:
            Exception: If screenshot or trace capture fails.
        """
        captured: dict[str, str] = {}
        # Sanitize the item key before using it in filenames so secrets never leak to disk.
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
        """Close tracing, context, browser, and Playwright runtime.

        Resource-close errors from individual components are allowed to propagate only when
        the component method raises outside the guarded tracing stop path.
        """
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
        """Start Playwright tracing when configured.

        Tracing startup failures are swallowed so diagnostics never prevent the main run.
        """
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
        """Capture a full-page screenshot.

        Args:
            path: Destination PNG path.

        Returns:
            ``True`` when a screenshot was captured, otherwise ``False``.

        Raises:
            Exception: If the Playwright screenshot call fails.
        """
        if self._page is None or not hasattr(self._page, "screenshot"):
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        self._page.screenshot(path=str(path), full_page=True)
        return True

    def _capture_trace(self, path: Path) -> bool:
        """Stop current tracing into a trace artifact and restart tracing.

        Args:
            path: Destination trace ZIP path.

        Returns:
            ``True`` when a trace was captured, otherwise ``False``.

        Raises:
            Exception: If the Playwright trace stop call fails.
        """
        if not self._tracing_started:
            return False
        tracing = self._tracing()
        if tracing is None or not hasattr(tracing, "stop"):
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        tracing.stop(path=str(path))
        self._tracing_started = False
        # Restart tracing so a later item failure can still produce its own trace artifact.
        self._start_tracing_if_enabled()
        return True

    def _stop_tracing_without_artifact(self) -> None:
        """Stop active tracing without saving an artifact.

        Trace stop failures are swallowed because this path is used during cleanup.
        """
        if not self._tracing_started:
            return
        tracing = self._tracing()
        if tracing is None or not hasattr(tracing, "stop"):
            self._tracing_started = False
            return
        self._tracing_started = False
        try:
            tracing.stop()
        except Exception:
            return

    def _tracing(self) -> Any | None:
        """Return the current context tracing object.

        Returns:
            Playwright tracing object, or ``None`` when no context exists.
        """
        if self._context is None:
            return None
        return getattr(self._context, "tracing", None)

    def _safe_item_key(self, item_key: str) -> str:
        """Redact configured secret values from an item key.

        Args:
            item_key: Raw business item key.

        Returns:
            Item key safe to use in diagnostic filenames.
        """
        safe = str(item_key)
        for secret in self._secret_values():
            if secret:
                safe = safe.replace(secret, _SECRET_PLACEHOLDER)
        return safe

    def _secret_values(self) -> tuple[str, ...]:
        """Return configured secret values that should be redacted from filenames.

        Returns:
            Tuple of non-empty secret values from runtime config.
        """
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
