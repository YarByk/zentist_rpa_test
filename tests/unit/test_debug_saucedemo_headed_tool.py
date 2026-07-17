from __future__ import annotations

import os
import runpy
from pathlib import Path

import pytest

from portal_automation import __main__ as cli

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "debug_saucedemo_playwright_headed.py"


def test_saucedemo_headed_tool_requires_visible_password(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify that the VS headed helper stops before live work when the password is missing.

    Args:
        monkeypatch: Pytest fixture used to isolate environment and patched functions.
        capsys: Pytest fixture used to capture operator-facing console text.

    Returns:
        None. Assertions communicate the test outcome.

    Raises:
        AssertionError: If the helper starts live work without a visible password.
    """

    def fail_if_called(_argv: list[str]) -> int:
        raise AssertionError("Sauce Demo main should not run without SAUCEDEMO_PASSWORD.")

    monkeypatch.delenv("SAUCEDEMO_PASSWORD", raising=False)
    monkeypatch.setattr(cli, "main", fail_if_called)

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(str(SCRIPT), run_name="__main__")

    captured = capsys.readouterr()
    assert exc_info.value.code == 1
    assert "SAUCEDEMO_PASSWORD is not visible" in captured.out
    assert "tools\\set_live_env.local.ps1" in captured.out


def test_saucedemo_headed_tool_sets_profile_and_makes_handled_failure_vs_friendly(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify that the VS headed helper applies Sauce Demo debug defaults.

    Args:
        monkeypatch: Pytest fixture used to isolate environment and patched functions.
        capsys: Pytest fixture used to capture operator-facing console text.

    Returns:
        None. Assertions communicate the test outcome.

    Raises:
        AssertionError: If env defaults, arguments, or VS-friendly exit behavior regress.
    """
    calls = []

    def fake_main(argv: list[str]) -> int:
        calls.append(argv)
        return 1

    monkeypatch.setenv("SAUCEDEMO_PASSWORD", "secret_sauce")
    monkeypatch.delenv("VISIBLE_BROWSER_PAUSE_ON_ERROR_SECONDS", raising=False)
    monkeypatch.delenv("VISIBLE_BROWSER_PAUSE_ON_RESULT_SECONDS", raising=False)
    monkeypatch.delenv("PLAYWRIGHT_PERSISTENT_PROFILE_DIR", raising=False)
    monkeypatch.setattr(cli, "main", fake_main)

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(str(SCRIPT), run_name="__main__")

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert calls == [["saucedemo", "--headless", "false"]]
    assert "failed or partial run report" in captured.out
    assert "Visual Studio will not treat" in captured.out
    assert (
        os.environ["PLAYWRIGHT_PERSISTENT_PROFILE_DIR"]
        == str(ROOT / "artifacts" / "browser_profiles" / "saucedemo")
    )
    assert os.environ["VISIBLE_BROWSER_PAUSE_ON_ERROR_SECONDS"] == "20"
    assert os.environ["VISIBLE_BROWSER_PAUSE_ON_RESULT_SECONDS"] == "20"
