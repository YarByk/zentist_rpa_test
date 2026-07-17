# ruff: noqa: E402, I001
from __future__ import annotations

import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
# Minimal bootstrap script for running the main CLI from the repo checkout.
sys.path.insert(0, str(SRC))
os.environ.setdefault("DB_PATH", str(ROOT / "artifacts" / "debug_all_dry_run.sqlite"))

from portal_automation.__main__ import main


if __name__ == "__main__":
    # Hard-code the safe dry-run command so this script is a quick smoke-check entrypoint.
    raise SystemExit(main(["all", "--dry-run"]))
