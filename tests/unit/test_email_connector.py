from pathlib import Path

import pytest

from portal_automation.core.artifact_store import ArtifactStore
from portal_automation.core.email_connector import EmailConnector

ROOT = Path(__file__).resolve().parents[2]


def test_dry_run_backend_writes_email_report_under_run_artifacts(tmp_path) -> None:
    artifacts = ArtifactStore(str(tmp_path / "artifacts"))

    path = EmailConnector("dry_run", artifacts).send_report(
        run_id="run-1",
        to="lead@example.com",
        subject="Daily report",
        body="Report body",
    )

    assert path == tmp_path / "artifacts" / "runs" / "run-1" / "email_report.txt"
    assert path.is_file()


def test_dry_run_email_artifact_includes_headers_blank_line_and_body(tmp_path) -> None:
    artifacts = ArtifactStore(str(tmp_path / "artifacts"))

    path = EmailConnector("dry_run", artifacts).send_report(
        run_id="run-1",
        to="lead@example.com",
        subject="Daily report",
        body="Report body",
    )

    assert path.read_text(encoding="utf-8") == (
        "To: lead@example.com\nSubject: Daily report\n\nReport body"
    )


def test_dry_run_backend_returns_written_path(tmp_path) -> None:
    artifacts = ArtifactStore(str(tmp_path / "artifacts"))

    path = EmailConnector("dry_run", artifacts).send_report(
        run_id="run-1",
        to="lead@example.com",
        subject="Daily report",
        body="Report body",
    )

    assert path == artifacts.email_report_path("run-1")


def test_dry_run_backend_handles_missing_recipient_without_none_text(tmp_path) -> None:
    artifacts = ArtifactStore(str(tmp_path / "artifacts"))

    path = EmailConnector("dry_run", artifacts).send_report(
        run_id="run-1",
        to=None,
        subject="Daily report",
        body="Report body",
    )

    assert path.read_text(encoding="utf-8").startswith("To: \n")
    assert "None" not in path.read_text(encoding="utf-8")


def test_smtp_backend_raises_runtime_error_and_does_not_create_artifact(tmp_path) -> None:
    artifacts = ArtifactStore(str(tmp_path / "artifacts"))

    with pytest.raises(RuntimeError, match="SMTP sending is not implemented"):
        EmailConnector("smtp", artifacts).send_report(
            run_id="run-1",
            to="lead@example.com",
            subject="Daily report",
            body="Report body",
        )

    assert not artifacts.email_report_path("run-1").exists()


def test_unknown_backend_raises_value_error(tmp_path) -> None:
    artifacts = ArtifactStore(str(tmp_path / "artifacts"))

    with pytest.raises(ValueError, match="Supported backends: dry_run, smtp"):
        EmailConnector("console", artifacts)


def test_email_connector_does_not_import_smtplib() -> None:
    source = (ROOT / "src/portal_automation/core/email_connector.py").read_text(
        encoding="utf-8"
    )

    assert "smtplib" not in source


def test_email_connector_source_does_not_contain_demo_credentials() -> None:
    source = (ROOT / "src/portal_automation/core/email_connector.py").read_text(
        encoding="utf-8"
    )

    assert "secret_sauce" not in source
    assert "admin123" not in source


def test_forbidden_modules_were_not_created() -> None:
    forbidden_paths = [
        "src/portal_automation/core/logging.py",
    ]

    assert [path for path in forbidden_paths if (ROOT / path).exists()] == []
