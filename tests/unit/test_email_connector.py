from pathlib import Path
from unittest.mock import MagicMock

import pytest

from portal_automation.core.artifact_store import ArtifactStore
from portal_automation.core.email_connector import (
    EmailConfigurationError,
    EmailConnector,
    EmailDeliveryError,
)

ROOT = Path(__file__).resolve().parents[2]


def test_dry_run_backend_writes_email_report_under_run_artifacts(tmp_path) -> None:
    # Dry-run delivery should materialize an email artifact instead of sending anything externally.
    """Verify that dry run backend writes email report under run artifacts.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
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
    """Verify that dry run email artifact includes headers blank line and body.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
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
    """Verify that dry run backend returns written path.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    artifacts = ArtifactStore(str(tmp_path / "artifacts"))

    path = EmailConnector("dry_run", artifacts).send_report(
        run_id="run-1",
        to="lead@example.com",
        subject="Daily report",
        body="Report body",
    )

    assert path == artifacts.email_report_path("run-1")


def test_dry_run_backend_handles_missing_recipient_without_none_text(tmp_path) -> None:
    """Verify that dry run backend handles missing recipient without none text.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    artifacts = ArtifactStore(str(tmp_path / "artifacts"))

    path = EmailConnector("dry_run", artifacts).send_report(
        run_id="run-1",
        to=None,
        subject="Daily report",
        body="Report body",
    )

    assert path.read_text(encoding="utf-8").startswith("To: \n")
    assert "None" not in path.read_text(encoding="utf-8")


def test_dry_run_backend_includes_report_path_when_provided(tmp_path) -> None:
    """Verify that dry run backend includes report path when provided.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    artifacts = ArtifactStore(str(tmp_path / "artifacts"))
    report_path = artifacts.write_text(artifacts.report_path("run-1"), "report body")

    path = EmailConnector("dry_run", artifacts).send_report(
        run_id="run-1",
        to="lead@example.com",
        subject="Daily report",
        body="Report body",
        report_path=report_path,
    )

    assert f"Report-Path: {report_path}" in path.read_text(encoding="utf-8")


def test_smtp_backend_sends_message_with_expected_server_auth_and_attachment(
    tmp_path,
    monkeypatch,
) -> None:
    # SMTP mode should construct one message and drive the expected auth/send sequence.
    """Verify that smtp backend sends message with expected server auth and attachment.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
        monkeypatch: Value supplied by the test or fixture for `monkeypatch`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    artifacts = ArtifactStore(str(tmp_path / "artifacts"))
    report_path = artifacts.write_text(artifacts.report_path("run-1"), "report body")
    smtp_instance = MagicMock()
    smtp_factory = MagicMock()
    smtp_factory.return_value.__enter__.return_value = smtp_instance
    monkeypatch.setattr("portal_automation.core.email_connector.smtplib.SMTP", smtp_factory)

    result = EmailConnector(
        "smtp",
        artifacts,
        default_to="ops@example.com",
        smtp_host="smtp.example.com",
        smtp_port=2525,
        smtp_username="smtp-user",
        smtp_password="smtp-secret",
        smtp_from="from@example.com",
        smtp_use_tls=True,
    ).send_report(
        run_id="run-1",
        to=None,
        subject="Daily report",
        body="Report body",
        report_path=report_path,
    )

    assert result is None
    smtp_factory.assert_called_once_with("smtp.example.com", 2525)
    smtp_instance.starttls.assert_called_once_with()
    smtp_instance.login.assert_called_once_with("smtp-user", "smtp-secret")
    smtp_instance.send_message.assert_called_once()
    message = smtp_instance.send_message.call_args.args[0]
    assert message["To"] == "ops@example.com"
    assert message["From"] == "from@example.com"
    assert message["Subject"] == "Daily report"
    assert any(part.get_filename() == "report.txt" for part in message.iter_attachments())


def test_smtp_backend_can_skip_tls_and_login_when_not_configured(tmp_path, monkeypatch) -> None:
    """Verify that smtp backend can skip tls and login when not configured.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
        monkeypatch: Value supplied by the test or fixture for `monkeypatch`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    artifacts = ArtifactStore(str(tmp_path / "artifacts"))
    smtp_instance = MagicMock()
    smtp_factory = MagicMock()
    smtp_factory.return_value.__enter__.return_value = smtp_instance
    monkeypatch.setattr("portal_automation.core.email_connector.smtplib.SMTP", smtp_factory)

    EmailConnector(
        "smtp",
        artifacts,
        default_to="ops@example.com",
        smtp_host="smtp.example.com",
        smtp_port=25,
        smtp_from="from@example.com",
        smtp_use_tls=False,
    ).send_report(
        run_id="run-1",
        to=None,
        subject="Daily report",
        body="Report body",
    )

    smtp_instance.starttls.assert_not_called()
    smtp_instance.login.assert_not_called()
    smtp_instance.send_message.assert_called_once()


def test_smtp_backend_raises_clear_configuration_error_when_required_values_missing(
    tmp_path,
) -> None:
    """Verify that smtp backend raises clear configuration error when required values missing.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    artifacts = ArtifactStore(str(tmp_path / "artifacts"))

    with pytest.raises(EmailConfigurationError, match="SMTP backend is selected"):
        EmailConnector("smtp", artifacts)


def test_smtp_backend_requires_password_when_username_is_provided(tmp_path) -> None:
    """Verify that smtp backend requires password when username is provided.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    artifacts = ArtifactStore(str(tmp_path / "artifacts"))

    with pytest.raises(EmailConfigurationError, match="SMTP_PASSWORD"):
        EmailConnector(
            "smtp",
            artifacts,
            default_to="ops@example.com",
            smtp_host="smtp.example.com",
            smtp_username="smtp-user",
            smtp_from="from@example.com",
        )


def test_smtp_backend_wraps_delivery_failures_without_exposing_password(
    tmp_path,
    monkeypatch,
) -> None:
    # Delivery failures should stay readable while never leaking SMTP credentials.
    """Verify that smtp backend wraps delivery failures without exposing password.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
        monkeypatch: Value supplied by the test or fixture for `monkeypatch`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    artifacts = ArtifactStore(str(tmp_path / "artifacts"))
    smtp_instance = MagicMock()
    smtp_instance.send_message.side_effect = OSError("mail server unavailable")
    smtp_factory = MagicMock()
    smtp_factory.return_value.__enter__.return_value = smtp_instance
    monkeypatch.setattr("portal_automation.core.email_connector.smtplib.SMTP", smtp_factory)

    connector = EmailConnector(
        "smtp",
        artifacts,
        default_to="ops@example.com",
        smtp_host="smtp.example.com",
        smtp_port=2525,
        smtp_username="smtp-user",
        smtp_password="smtp-secret",
        smtp_from="from@example.com",
    )

    with pytest.raises(EmailDeliveryError) as error:
        connector.send_report(
            run_id="run-1",
            to=None,
            subject="Daily report",
            body="Report body",
        )

    assert "smtp-secret" not in str(error.value)


def test_unknown_backend_raises_value_error(tmp_path) -> None:
    """Verify that unknown backend raises value error.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    artifacts = ArtifactStore(str(tmp_path / "artifacts"))

    with pytest.raises(ValueError, match="Supported backends: dry_run, smtp"):
        EmailConnector("console", artifacts)


def test_email_connector_source_uses_stdlib_smtplib_without_demo_credentials() -> None:
    """Verify that email connector source uses stdlib smtplib without demo credentials.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    source = (ROOT / "src/portal_automation/core/email_connector.py").read_text(encoding="utf-8")

    assert "import smtplib" in source
    assert "secret_sauce" not in source
    assert "admin123" not in source


def test_forbidden_modules_were_not_created() -> None:
    """Verify that forbidden modules were not created.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    forbidden_paths = [
        "src/portal_automation/core/logging.py",
    ]

    assert [path for path in forbidden_paths if (ROOT / path).exists()] == []
