# ruff: noqa: E402, I001
from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from portal_automation.__main__ import main


if __name__ == "__main__":
    raise SystemExit(main(["all", "--dry-run"]))
