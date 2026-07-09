import re
from datetime import date
from pathlib import Path


def _sanitize_key(key: str) -> str:
    stripped = key.strip()
    sanitized = re.sub(r"[^A-Za-z0-9._-]", "_", stripped)
    return sanitized or "employee"


class ArtifactStore:
    def __init__(self, artifacts_dir: str) -> None:
        self.artifacts_dir = Path(artifacts_dir)

    def run_dir(self, run_id: str) -> Path:
        path = self.artifacts_dir / "runs" / run_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def report_path(self, run_id: str) -> Path:
        return self._run_file_path(run_id, "report.txt")

    def email_report_path(self, run_id: str) -> Path:
        return self._run_file_path(run_id, "email_report.txt")

    def screenshots_dir(self, run_id: str) -> Path:
        return self._run_subdir(run_id, "screenshots")

    def traces_dir(self, run_id: str) -> Path:
        return self._run_subdir(run_id, "traces")

    def generated_documents_dir(self, run_id: str) -> Path:
        return self._run_subdir(run_id, "generated_documents")

    def salary_document_path(self, run_id: str, employee_key: str, business_date: date) -> Path:
        filename = f"salary_{_sanitize_key(employee_key)}_{business_date.isoformat()}.txt"
        return self.generated_documents_dir(run_id) / filename

    def failure_screenshot_path(self, run_id: str, portal_name: str, item_key: str) -> Path:
        filename = f"{_sanitize_key(portal_name)}_{_sanitize_key(item_key)}_failure.png"
        return self.screenshots_dir(run_id) / filename

    def failure_trace_path(self, run_id: str, portal_name: str, item_key: str) -> Path:
        filename = f"{_sanitize_key(portal_name)}_{_sanitize_key(item_key)}_trace.zip"
        return self.traces_dir(run_id) / filename

    def write_text(self, path: Path, content: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def _run_file_path(self, run_id: str, filename: str) -> Path:
        return self.run_dir(run_id) / filename

    def _run_subdir(self, run_id: str, name: str) -> Path:
        path = self.run_dir(run_id) / name
        path.mkdir(parents=True, exist_ok=True)
        return path
