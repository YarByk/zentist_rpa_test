# ruff: noqa: E402, I001
from __future__ import annotations

import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
# Minimal bootstrap script for visible-browser Sauce Demo debugging.
sys.path.insert(0, str(SRC))

from portal_automation.__main__ import main


def _run_headed_debug() -> int:
    """Run the headed Sauce Demo debug profile without turning known run failures into VS errors.

    Returns:
        ``0`` when Visual Studio should stay out of exception mode, even if the portal run itself
        produced a failed or partial report. Reports, events, screenshots, and diagnostics still
        carry the real status for the operator to inspect.
    """
    exit_code = main(["saucedemo", "--headless", "false"])
    if exit_code == 1:
        print(
            "Sauce Demo headed debug finished with a failed or partial run report. "
            "Visual Studio will not treat this operator-diagnosed portal result as a script crash."
        )
        return 0
    return exit_code


if __name__ == "__main__":
    if not os.environ.get("SAUCEDEMO_PASSWORD"):
        print("SAUCEDEMO_PASSWORD is not visible inside this Visual Studio Python process.")
        print(
            "Set it in tools\\set_live_env.local.ps1, "
            "then start Visual Studio from that same shell."
        )
        print("Example: . .\\tools\\set_live_env.local.ps1; devenv .")
        raise SystemExit(1)
    os.environ.setdefault("VISIBLE_BROWSER_PAUSE_ON_ERROR_SECONDS", "20")
    os.environ.setdefault("VISIBLE_BROWSER_PAUSE_ON_RESULT_SECONDS", "20")
    os.environ.setdefault(
        "PLAYWRIGHT_PERSISTENT_PROFILE_DIR",
        str(ROOT / "artifacts" / "browser_profiles" / "saucedemo"),
    )
    # Headed mode keeps the Chromium window visible while Playwright runs.
    raise SystemExit(_run_headed_debug())
