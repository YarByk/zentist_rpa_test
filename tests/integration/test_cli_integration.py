import json
import os
import sqlite3
import subprocess
import sys


def run_cli(args, tmp_path):
    # Run the installed module in a subprocess with isolated DB/artifact paths.
    """Run cli.

    Args:
        args: Value supplied by the test or fixture for `args`.
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
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
    """Verify that module help exits zero.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    result = run_cli(["--help"], tmp_path)

    assert result.returncode == 0
    assert "usage:" in result.stdout


def test_orangehrm_help_exits_zero(tmp_path) -> None:
    """Verify that orangehrm help exits zero.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    result = run_cli(["orangehrm", "--help"], tmp_path)

    assert result.returncode == 0
    assert "usage:" in result.stdout


def test_saucedemo_help_exits_zero(tmp_path) -> None:
    """Verify that saucedemo help exits zero.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    result = run_cli(["saucedemo", "--help"], tmp_path)

    assert result.returncode == 0
    assert "usage:" in result.stdout


def test_all_help_exits_zero(tmp_path) -> None:
    """Verify that all help exits zero.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    result = run_cli(["all", "--help"], tmp_path)

    assert result.returncode == 0
    assert "usage:" in result.stdout


def test_recover_help_exits_zero(tmp_path) -> None:
    """Verify that recover help exits zero.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    result = run_cli(["recover", "--help"], tmp_path)

    assert result.returncode == 0
    assert "usage:" in result.stdout


def test_all_dry_run_exits_zero_with_temporary_artifacts(tmp_path) -> None:
    """Verify that all dry run exits zero with temporary artifacts.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    result = run_cli(["all", "--dry-run"], tmp_path)

    assert result.returncode == 0
    assert (tmp_path / "portal.sqlite").is_file()
    assert (tmp_path / "artifacts" / "runs").is_dir()


def test_all_dry_run_creates_reviewer_artifact_shape(tmp_path) -> None:
    # Dry-run should leave enough evidence for reviewers without doing item-level portal work.
    """Verify that all dry run creates reviewer artifact shape.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    result = run_cli(["all", "--dry-run"], tmp_path)

    assert result.returncode == 0
    assert result.stdout.count("run_summary portal=") == 2
    assert "email_backend=dry_run" in result.stdout
    for forbidden in ("secret_sauce", "admin123"):
        assert forbidden not in result.stdout

    connection = sqlite3.connect(tmp_path / "portal.sqlite")
    connection.row_factory = sqlite3.Row
    try:
        runs = connection.execute(
            "SELECT run_id, portal_name, status FROM runs ORDER BY portal_name"
        ).fetchall()
        item_count = connection.execute("SELECT COUNT(*) AS count FROM item_results").fetchone()[
            "count"
        ]
    finally:
        connection.close()

    assert [(row["portal_name"], row["status"]) for row in runs] == [
        ("orangehrm", "success"),
        ("saucedemo", "success"),
    ]
    # Dry-run validates input and creates run-level evidence but intentionally skips item work.
    assert item_count == 0

    for row in runs:
        run_dir = tmp_path / "artifacts" / "runs" / row["run_id"]
        report = (run_dir / "report.txt").read_text(encoding="utf-8")
        email = (run_dir / "email_report.txt").read_text(encoding="utf-8")
        events = [
            json.loads(line)
            for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))

        assert f"Run ID: {row['run_id']}" in report
        assert "Run status: success" in report
        assert "Reason code" not in report
        portal_label = {"orangehrm": "OrangeHRM", "saucedemo": "SauceDemo"}[row["portal_name"]]
        assert email.startswith(f"To: \nSubject: {portal_label} run report:")
        assert {event["event"] for event in events} >= {
            "run_started",
            "report_generated",
            "email_send_attempt",
            "email_sent",
            "run_finished",
        }
        assert metrics["items_total"] == 0
        assert metrics["items_success"] == 0
        assert metrics["items_failed"] == 0
        combined = "\n".join([report, email, json.dumps(events), json.dumps(metrics)])
        for forbidden in ("secret_sauce", "admin123"):
            assert forbidden not in combined


def test_all_dry_run_does_not_require_network_or_external_objects(tmp_path) -> None:
    # The safe smoke path should avoid external dependencies and live automation setup.
    """Verify that all dry run does not require network or external objects.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    result = run_cli(["all", "--dry-run"], tmp_path)
    combined_output = f"{result.stdout}\n{result.stderr}".lower()

    assert result.returncode == 0
    assert "playwright" not in combined_output
    assert "network" not in combined_output


def test_all_dry_run_does_not_create_browser_or_page_objects(tmp_path) -> None:
    """Verify that all dry run does not create browser or page objects.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    result = run_cli(["all", "--dry-run"], tmp_path)
    combined_output = f"{result.stdout}\n{result.stderr}".lower()

    assert result.returncode == 0
    for forbidden in ("playwright", "browser", "chromium", "firefox", "webkit", "page factory"):
        assert forbidden not in combined_output


def test_unknown_portal_gives_clear_cli_error(tmp_path) -> None:
    """Verify that unknown portal gives clear cli error.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    result = run_cli(["not_a_portal"], tmp_path)

    assert result.returncode != 0
    assert "not_a_portal" in result.stderr
    assert "orangehrm" in result.stderr
    assert "saucedemo" in result.stderr
    assert "all" in result.stderr
