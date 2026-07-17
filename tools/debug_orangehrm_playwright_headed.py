# ruff: noqa: E402, I001
from __future__ import annotations

import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
# Minimal bootstrap script for visible-browser OrangeHRM debugging.
sys.path.insert(0, str(SRC))

from portal_automation.__main__ import main


def _run_headed_debug() -> int:
    """Run the headed OrangeHRM debug profile without treating known run failures as crashes.

    Returns:
        ``0`` when a handled run report should not be treated as a script crash,
        even if the portal run itself produced a failed report. The underlying report,
        events, screenshots, and diagnostics still carry the real failure status for
        the operator to inspect.
    """
    exit_code = main(["orangehrm", "--headless", "false"])
    if exit_code == 1:
        print(
            "OrangeHRM headed debug finished with a failed run report. "
            "This operator-diagnosed portal failure is not treated as a script crash."
        )
        print(
            "If the details above show LOGIN_FAILED, invalid credentials, "
            "or CSRF token validation, "
            "verify ORANGEHRM_PASSWORD in tools\\set_live_env.local.ps1 and try again."
        )
        return 0
    return exit_code


if __name__ == "__main__":
    if not os.environ.get("ORANGEHRM_PASSWORD"):
        print("ORANGEHRM_PASSWORD is not visible inside this Python process.")
        print("Set it in tools\\set_live_env.local.ps1, then run the headed helper again.")
        print("Example: . .\\tools\\set_live_env.local.ps1; python <this-script>")
        raise SystemExit(1)
    os.environ.setdefault("VISIBLE_BROWSER_PAUSE_ON_ERROR_SECONDS", "20")
    os.environ.setdefault("VISIBLE_BROWSER_PAUSE_ON_RESULT_SECONDS", "20")
    os.environ.setdefault("ORANGEHRM_TIMEOUT_SECONDS", "8")
    os.environ.setdefault(
        "PLAYWRIGHT_PERSISTENT_PROFILE_DIR",
        str(ROOT / "artifacts" / "browser_profiles" / "orangehrm"),
    )
    # Headed mode keeps the Chromium window visible while Playwright runs.
    raise SystemExit(_run_headed_debug())
