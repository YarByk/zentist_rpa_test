# ruff: noqa: E402, I001
from __future__ import annotations

from time import time

from generate_test_data import main


if __name__ == "__main__":
    # Visual Studio Folder View does not reliably pass arguments to this tool target.
    seed = int(time()) % 100000
    raise SystemExit(
        main(
            [
                "--portal",
                "orangehrm",
                "--count",
                "3",
                "--output",
                "artifacts/generated_orangehrm_employees.json",
                "--seed",
                str(seed),
            ]
        )
    )
