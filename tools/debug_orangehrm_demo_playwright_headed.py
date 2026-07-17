# ruff: noqa: E402, I001
from __future__ import annotations

import os
from pathlib import Path
import sys
from time import time


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TOOLS = ROOT / "tools"
GENERATED_INPUT = "artifacts/generated_orangehrm_employees.json"

# Minimal bootstrap script for a one-click visible-browser OrangeHRM demo.
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TOOLS))

from generate_test_data import main as generate_main
from portal_automation.__main__ import main as portal_main


def _generate_demo_input() -> int:
    """Generate a fresh three-employee OrangeHRM demo input file.

    Returns:
        Process-style exit code.
    """
    seed = int(time()) % 100000
    return generate_main(
        [
            "--portal",
            "orangehrm",
            "--count",
            "3",
            "--output",
            GENERATED_INPUT,
            "--seed",
            str(seed),
        ]
    )


def _run_demo_headed() -> int:
    """Generate input and run the headed OrangeHRM demo.

    Returns:
        ``0`` when a handled run report should not be treated as a script crash.
    """
    generate_code = _generate_demo_input()
    if generate_code != 0:
        return generate_code
    exit_code = portal_main(
        [
            "orangehrm",
            "--headless",
            "false",
            "--input",
            GENERATED_INPUT,
        ]
    )
    if exit_code == 1:
        print(
            "OrangeHRM demo headed run finished with a failed run report. "
            "This operator-diagnosed portal result is not treated as a script crash."
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
    raise SystemExit(_run_demo_headed())
