import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from portal_automation.core.artifact_store import ArtifactStore

SUPPORTED_BACKENDS = frozenset({"dry_run", "smtp"})


class EmailConfigurationError(ValueError):
    """Raised when email backend configuration is invalid."""


class EmailDeliveryError(RuntimeError):
    """Raised when email delivery fails."""


class EmailConnector:
    def __init__(
        self,
        backend: str,
        artifacts: ArtifactStore,
        *,
        default_to: str | None = None,
        smtp_host: str | None = None,
        smtp_port: int = 587,
        smtp_username: str | None = None,
        smtp_password: str | None = None,
        smtp_from: str | None = None,
        smtp_use_tls: bool = True,
        logger: Any | None = None,
    ) -> None:
        if backend not in SUPPORTED_BACKENDS:
            supported = ", ".join(sorted(SUPPORTED_BACKENDS))
            raise ValueError(
                f"Unsupported email backend {backend!r}. Supported backends: {supported}"
            )
        self.backend = backend
        self.artifacts = artifacts
        self.default_to = default_to
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_username = smtp_username
        self.smtp_password = smtp_password
        self.smtp_from = smtp_from
        self.smtp_use_tls = smtp_use_tls
        self.logger = logger
        self._validate_backend_configuration()

    def send_report(
        self,
        *,
        run_id: str,
        to: str | None,
        subject: str,
        body: str,
        report_path: Path | None = None,
    ) -> Path | None:
        recipient = (to or self.default_to or "").strip()
        self._log_email_event(
            "email_send_attempt",
            backend=self.backend,
            has_attachment=report_path is not None,
            recipient_present=bool(recipient),
        )
        if self.backend == "dry_run":
            path = self.artifacts.email_report_path(run_id)
            content = self._render_dry_run_content(
                to=recipient,
                subject=subject,
                body=body,
                report_path=report_path,
            )
            written = self.artifacts.write_text(path, content)
            self._log_email_event(
                "email_sent",
                backend=self.backend,
                has_attachment=report_path is not None,
                path=str(written),
            )
            return written

        message = self._build_message(
            to=recipient,
            subject=subject,
            body=body,
            report_path=report_path,
        )
        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as client:
                if self.smtp_use_tls:
                    client.starttls()
                if self.smtp_username is not None:
                    client.login(self.smtp_username, self.smtp_password or "")
                client.send_message(message)
        except Exception as exc:  # pragma: no cover - covered via mocks in tests
            self._log_email_event("email_failed", backend=self.backend, error=str(exc))
            raise EmailDeliveryError(f"Email delivery failed via SMTP backend: {exc}") from exc
        self._log_email_event(
            "email_sent",
            backend=self.backend,
            has_attachment=report_path is not None,
        )
        return None

    def _log_email_event(self, event: str, **kwargs: Any) -> None:
        if self.logger is None or not hasattr(self.logger, "info"):
            return
        self.logger.info(event, **kwargs)

    def _validate_backend_configuration(self) -> None:
        if self.backend != "smtp":
            return
        missing = []
        if not self.smtp_host:
            missing.append("SMTP_HOST")
        if not self.smtp_from:
            missing.append("SMTP_FROM")
        if not (self.default_to or "").strip():
            missing.append("REPORT_EMAIL_TO or SMTP_TO")
        if self.smtp_username and not self.smtp_password:
            missing.append("SMTP_PASSWORD")
        if self.smtp_password and not self.smtp_username:
            missing.append("SMTP_USERNAME")
        if missing:
            joined = ", ".join(missing)
            raise EmailConfigurationError(
                f"SMTP backend is selected but required email configuration is missing: {joined}"
            )

    def _render_dry_run_content(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        report_path: Path | None,
    ) -> str:
        lines = [f"To: {to}", f"Subject: {subject}"]
        if report_path is not None:
            lines.append(f"Report-Path: {report_path}")
        lines.append("")
        lines.append(body)
        return "\n".join(lines)

    def _build_message(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        report_path: Path | None,
    ) -> EmailMessage:
        message = EmailMessage()
        message["To"] = to
        message["From"] = self.smtp_from or ""
        message["Subject"] = subject
        message.set_content(body)
        if report_path is not None:
            attachment_bytes = report_path.read_bytes()
            message.add_attachment(
                attachment_bytes,
                maintype="text",
                subtype="plain",
                filename=report_path.name,
            )
        return message
