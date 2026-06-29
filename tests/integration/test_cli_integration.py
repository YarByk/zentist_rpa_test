import os
import subprocess
import sys


def run_cli(args, tmp_path):
    env = {
        **os.environ,
        "DB_PATH": str(tmp_path / "portal.sqlite"),
        "ARTIFACTS_DIR": str(tmp_path / "artifacts"),
        "EMAIL_BACKEND": "dry_run",
    }
    return subprocess.run(
        [sys.executable, "-m", "portal_automation", *args],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )


def test_module_help_exits_zero(tmp_path) -> None:
    result = run_cli(["--help"], tmp_path)

    assert result.returncode == 0
    assert "usage:" in result.stdout


def test_orangehrm_help_exits_zero(tmp_path) -> None:
    result = run_cli(["orangehrm", "--help"], tmp_path)

    assert result.returncode == 0
    assert "usage:" in result.stdout


def test_saucedemo_help_exits_zero(tmp_path) -> None:
    result = run_cli(["saucedemo", "--help"], tmp_path)

    assert result.returncode == 0
    assert "usage:" in result.stdout


def test_all_help_exits_zero(tmp_path) -> None:
    result = run_cli(["all", "--help"], tmp_path)

    assert result.returncode == 0
    assert "usage:" in result.stdout


def test_all_dry_run_exits_zero_with_temporary_artifacts(tmp_path) -> None:
    result = run_cli(["all", "--dry-run"], tmp_path)

    assert result.returncode == 0
    assert (tmp_path / "portal.sqlite").is_file()
    assert (tmp_path / "artifacts" / "runs").is_dir()


def test_all_dry_run_does_not_require_network_or_external_objects(tmp_path) -> None:
    result = run_cli(["all", "--dry-run"], tmp_path)
    combined_output = f"{result.stdout}\n{result.stderr}".lower()

    assert result.returncode == 0
    assert "playwright" not in combined_output
    assert "network" not in combined_output


def test_all_dry_run_does_not_create_browser_or_page_objects(tmp_path) -> None:
    result = run_cli(["all", "--dry-run"], tmp_path)
    combined_output = f"{result.stdout}\n{result.stderr}".lower()

    assert result.returncode == 0
    for forbidden in ("playwright", "browser", "chromium", "firefox", "webkit", "page factory"):
        assert forbidden not in combined_output


def test_unknown_portal_gives_clear_cli_error(tmp_path) -> None:
    result = run_cli(["not_a_portal"], tmp_path)

    assert result.returncode != 0
    assert "not_a_portal" in result.stderr
    assert "orangehrm" in result.stderr
    assert "saucedemo" in result.stderr
    assert "all" in result.stderr
