# ruff: noqa: E402, I001
from __future__ import annotations

import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
# Minimal bootstrap script for visible-browser OrangeHRM debugging with generated input data.
sys.path.insert(0, str(SRC))

from portal_automation.__main__ import main


def _run_generated_headed_debug() -> int:
    """Run the headed OrangeHRM generated-data demo without turning report failures into VS errors.

    Returns:
        ``0`` when Visual Studio should stay out of exception mode after a handled run report.
    """
    exit_code = main(
        [
            "orangehrm",
            "--headless",
            "false",
            "--input",
            "artifacts/generated_orangehrm_employees.json",
        ]
    )
    if exit_code == 1:
        print(
            "OrangeHRM generated-data headed debug finished with a failed run report. "
            "Visual Studio will not treat this operator-diagnosed portal result as a script crash."
        )
        return 0
    return exit_code


if __name__ == "__main__":
    if not os.environ.get("ORANGEHRM_PASSWORD"):
        print("ORANGEHRM_PASSWORD is not visible inside this Visual Studio Python process.")
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
        str(ROOT / "artifacts" / "browser_profiles" / "orangehrm"),
    )
    raise SystemExit(_run_generated_headed_debug())
