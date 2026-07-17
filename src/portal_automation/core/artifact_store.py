import re
from datetime import date
from pathlib import Path


def _sanitize_key(key: str) -> str:
    """Return a filesystem-safe key fragment.

    Args:
        key: Raw business key that may contain spaces or unsafe path characters.

    Returns:
        Sanitized filename fragment, or ``"employee"`` when no usable characters remain.
    """
    # -------------------------------------------------------------------------
    # Convert user-facing keys into safe filesystem fragments.
    # This keeps artifact filenames deterministic while avoiding unsafe symbols.
    # -------------------------------------------------------------------------
    stripped = key.strip()
    sanitized = re.sub(r"[^A-Za-z0-9._-]", "_", stripped)
    return sanitized or "employee"


class ArtifactStore:
    def __init__(self, artifacts_dir: str) -> None:
        """Create an artifact path resolver.

        Args:
            artifacts_dir: Root directory where run artifacts should be stored.
        """
        # ---------------------------------------------------------------------
        # All artifact paths are rooted under one configurable base directory.
        # Every helper below derives a concrete file or subdirectory from it.
        # ---------------------------------------------------------------------
        self.artifacts_dir = Path(artifacts_dir)

    def run_dir(self, run_id: str) -> Path:
        """Return and create the artifact directory for one run.

        Args:
            run_id: Unique runtime identifier for the portal run.

        Returns:
            Path to ``ARTIFACTS_DIR/runs/<run_id>``.

        Raises:
            OSError: If the directory cannot be created.
        """
        # Create the run directory eagerly so downstream writers can assume it exists.
        path = self.artifacts_dir / "runs" / run_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def report_path(self, run_id: str) -> Path:
        """Return the text report path for a run.

        Args:
            run_id: Unique runtime identifier for the portal run.

        Returns:
            Path to ``report.txt`` under the run directory.
        """
        return self._run_file_path(run_id, "report.txt")

    def email_report_path(self, run_id: str) -> Path:
        """Return the dry-run email artifact path for a run.

        Args:
            run_id: Unique runtime identifier for the portal run.

        Returns:
            Path to ``email_report.txt`` under the run directory.
        """
        return self._run_file_path(run_id, "email_report.txt")

    def screenshots_dir(self, run_id: str) -> Path:
        """Return and create the screenshot directory for a run.

        Args:
            run_id: Unique runtime identifier for the portal run.

        Returns:
            Path to the run's ``screenshots`` directory.

        Raises:
            OSError: If the directory cannot be created.
        """
        return self._run_subdir(run_id, "screenshots")

    def traces_dir(self, run_id: str) -> Path:
        """Return and create the trace directory for a run.

        Args:
            run_id: Unique runtime identifier for the portal run.

        Returns:
            Path to the run's ``traces`` directory.

        Raises:
            OSError: If the directory cannot be created.
        """
        return self._run_subdir(run_id, "traces")

    def generated_documents_dir(self, run_id: str) -> Path:
        """Return and create the generated-document directory for a run.

        Args:
            run_id: Unique runtime identifier for the portal run.

        Returns:
            Path to the run's ``generated_documents`` directory.

        Raises:
            OSError: If the directory cannot be created.
        """
        return self._run_subdir(run_id, "generated_documents")

    def salary_document_path(self, run_id: str, employee_key: str, business_date: date) -> Path:
        """Return the deterministic salary document path for one employee.

        Args:
            run_id: Unique runtime identifier for the portal run.
            employee_key: Employee business key from input data.
            business_date: Business date used in the generated filename.

        Returns:
            Path to the salary document artifact.
        """
        # Salary documents are keyed by employee and business date for repeatable reruns.
        filename = f"salary_{_sanitize_key(employee_key)}_{business_date.isoformat()}.txt"
        return self.generated_documents_dir(run_id) / filename

    def failure_screenshot_path(self, run_id: str, portal_name: str, item_key: str) -> Path:
        """Return the deterministic failure screenshot path for one item.

        Args:
            run_id: Unique runtime identifier for the portal run.
            portal_name: Portal key, such as ``orangehrm`` or ``saucedemo``.
            item_key: Business item key associated with the failure.

        Returns:
            Path to the failure screenshot artifact.
        """
        filename = f"{_sanitize_key(portal_name)}_{_sanitize_key(item_key)}_failure.png"
        return self.screenshots_dir(run_id) / filename

    def failure_trace_path(self, run_id: str, portal_name: str, item_key: str) -> Path:
        """Return the deterministic failure trace path for one item.

        Args:
            run_id: Unique runtime identifier for the portal run.
            portal_name: Portal key, such as ``orangehrm`` or ``saucedemo``.
            item_key: Business item key associated with the failure.

        Returns:
            Path to the failure trace artifact.
        """
        filename = f"{_sanitize_key(portal_name)}_{_sanitize_key(item_key)}_trace.zip"
        return self.traces_dir(run_id) / filename

    def write_text(self, path: Path, content: str) -> Path:
        """Write UTF-8 text to an artifact path.

        Args:
            path: Destination path.
            content: Text content to write.

        Returns:
            The destination path after writing succeeds.

        Raises:
            OSError: If parent directories or the file cannot be written.
        """
        # This is the single shared helper for text artifacts written by the platform.
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def _run_file_path(self, run_id: str, filename: str) -> Path:
        """Return a file path directly under a run directory.

        Args:
            run_id: Unique runtime identifier for the portal run.
            filename: File name to append to the run directory.

        Returns:
            Path to the requested run-level file.
        """
        return self.run_dir(run_id) / filename

    def _run_subdir(self, run_id: str, name: str) -> Path:
        """Return and create a named subdirectory under a run directory.

        Args:
            run_id: Unique runtime identifier for the portal run.
            name: Subdirectory name.

        Returns:
            Path to the requested subdirectory.

        Raises:
            OSError: If the directory cannot be created.
        """
        path = self.run_dir(run_id) / name
        path.mkdir(parents=True, exist_ok=True)
        return path
