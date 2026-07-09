from datetime import date

import pytest

from portal_automation.core.artifact_store import ArtifactStore


def test_run_dir_returns_and_creates_run_directory(tmp_path) -> None:
    store = ArtifactStore(str(tmp_path / "artifacts"))

    path = store.run_dir("run-1")

    assert path == tmp_path / "artifacts" / "runs" / "run-1"
    assert path.is_dir()


def test_report_and_email_report_paths_are_under_run_directory(tmp_path) -> None:
    store = ArtifactStore(str(tmp_path / "artifacts"))

    assert store.report_path("run-1") == tmp_path / "artifacts" / "runs" / "run-1" / "report.txt"
    assert (
        store.email_report_path("run-1")
        == tmp_path / "artifacts" / "runs" / "run-1" / "email_report.txt"
    )
    assert (tmp_path / "artifacts" / "runs" / "run-1").is_dir()


def test_artifact_subdirectories_are_deterministic_and_created(tmp_path) -> None:
    store = ArtifactStore(str(tmp_path / "artifacts"))

    screenshots = store.screenshots_dir("run-1")
    traces = store.traces_dir("run-1")
    documents = store.generated_documents_dir("run-1")

    assert screenshots == tmp_path / "artifacts" / "runs" / "run-1" / "screenshots"
    assert traces == tmp_path / "artifacts" / "runs" / "run-1" / "traces"
    assert documents == tmp_path / "artifacts" / "runs" / "run-1" / "generated_documents"
    assert screenshots.is_dir()
    assert traces.is_dir()
    assert documents.is_dir()


def test_salary_document_path_uses_deterministic_filename(tmp_path) -> None:
    store = ArtifactStore(str(tmp_path / "artifacts"))

    path = store.salary_document_path("run-1", "emp-001", date(2026, 6, 29))

    assert path == (
        tmp_path
        / "artifacts"
        / "runs"
        / "run-1"
        / "generated_documents"
        / "salary_emp-001_2026-06-29.txt"
    )
    assert path.parent.is_dir()


def test_salary_document_path_sanitizes_unsafe_employee_key(tmp_path) -> None:
    store = ArtifactStore(str(tmp_path / "artifacts"))

    path = store.salary_document_path("run-1", " emp/00:1 ", date(2026, 6, 29))

    assert path.name == "salary_emp_00_1_2026-06-29.txt"


def test_salary_document_path_uses_employee_for_empty_sanitized_key(tmp_path) -> None:
    store = ArtifactStore(str(tmp_path / "artifacts"))

    path = store.salary_document_path("run-1", "   ", date(2026, 6, 29))

    assert path.name == "salary_employee_2026-06-29.txt"


def test_write_text_writes_utf8_content_and_creates_parent_dirs(tmp_path) -> None:
    store = ArtifactStore(str(tmp_path / "artifacts"))
    path = tmp_path / "artifacts" / "runs" / "run-1" / "nested" / "file.txt"

    written = store.write_text(path, "salary text\n")

    assert written == path
    assert path.read_text(encoding="utf-8") == "salary text\n"


def test_write_text_propagates_filesystem_failures(tmp_path) -> None:
    store = ArtifactStore(str(tmp_path / "artifacts"))
    path = tmp_path / "target-dir"
    path.mkdir()

    with pytest.raises(OSError):
        store.write_text(path, "content")


def test_failure_diagnostic_paths_are_deterministic_and_sanitized(tmp_path) -> None:
    store = ArtifactStore(str(tmp_path / "artifacts"))

    screenshot = store.failure_screenshot_path("run-1", "orangehrm", " emp/00:1 ")
    trace = store.failure_trace_path("run-1", "orangehrm", " emp/00:1 ")

    assert screenshot == (
        tmp_path / "artifacts" / "runs" / "run-1" / "screenshots" / "orangehrm_emp_00_1_failure.png"
    )
    assert trace == (
        tmp_path / "artifacts" / "runs" / "run-1" / "traces" / "orangehrm_emp_00_1_trace.zip"
    )
    assert screenshot.parent.is_dir()
    assert trace.parent.is_dir()
