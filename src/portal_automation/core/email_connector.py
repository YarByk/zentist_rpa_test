from pathlib import Path

from portal_automation.core.artifact_store import ArtifactStore

SUPPORTED_BACKENDS = frozenset({"dry_run", "smtp"})


class EmailConnector:
    def __init__(self, backend: str, artifacts: ArtifactStore) -> None:
        if backend not in SUPPORTED_BACKENDS:
            supported = ", ".join(sorted(SUPPORTED_BACKENDS))
            raise ValueError(
                f"Unsupported email backend {backend!r}. Supported backends: {supported}"
            )
        self.backend = backend
        self.artifacts = artifacts

    def send_report(
        self,
        *,
        run_id: str,
        to: str | None,
        subject: str,
        body: str,
    ) -> Path | None:
        if self.backend == "smtp":
            raise RuntimeError("SMTP sending is not implemented in this slice.")

        path = self.artifacts.email_report_path(run_id)
        content = f"To: {to or ''}\nSubject: {subject}\n\n{body}"
        return self.artifacts.write_text(path, content)
