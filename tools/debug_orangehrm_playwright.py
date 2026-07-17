# ruff: noqa: E402, I001
from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
# Minimal bootstrap script for live OrangeHRM debugging from Visual Studio.
sys.path.insert(0, str(SRC))

from portal_automation.__main__ import main


if __name__ == "__main__":
    # No --dry-run: this starts Playwright and executes the live OrangeHRM workflow.
    raise SystemExit(main(["orangehrm"]))
