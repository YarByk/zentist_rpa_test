from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from portal_automation.core.artifact_store import ArtifactStore
from portal_automation.core.document_generator import salary_document_filename
from portal_automation.core.models import ItemStatus, ReasonCode
from portal_automation.core.retries import PortalError
from portal_automation.portals.orangehrm import workflow
from portal_automation.portals.orangehrm.input_schema import (
    OrangeHrmEmployeeRecord,
    SalaryDetails,
)
from portal_automation.portals.orangehrm.workflow import (
    FindResult,
    FindStatus,
    process_employee,
)

ROOT = Path(__file__).resolve().parents[2]


@dataclass
class ContextStub:
    run_id: str
    business_date: date
    artifacts: ArtifactStore
    config: object


class FakePages:
    def __init__(
        self,
        find_results: list[FindResult] | None = None,
        attachments: list[str] | None = None,
        job: dict[str, str] | None = None,
        verify_upload: bool = True,
        failures: dict[str, list[Exception]] | None = None,
    ) -> None:
        self.find_results = find_results or [FindResult.found()]
        self.attachments = attachments or []
        self.job = job or {
            "job_title": employee().job_title,
            "employment_status": employee().employment_status,
        }
        self.verify_upload = verify_upload
        self.failures = {
            key: list(value)
            for key, value in (failures or {}).items()
        }
        self.calls: list[str] = []
        self.uploaded_paths: list[Path] = []

    def find_employee_record(self, record: OrangeHrmEmployeeRecord) -> FindResult:
        self.calls.append("find_employee_record")
        self._raise_if_configured("find_employee_record")
        return self.find_results.pop(0)

    def add_employee(self, record: OrangeHrmEmployeeRecord) -> None:
        self.calls.append("add_employee")
        self._raise_if_configured("add_employee")

    def open_employee_profile(self, record: OrangeHrmEmployeeRecord) -> None:
        self.calls.append("open_employee_profile")
        self._raise_if_configured("open_employee_profile")

    def update_job(self, record: OrangeHrmEmployeeRecord) -> None:
        self.calls.append("update_job")
        self._raise_if_configured("update_job")

    def read_job(self, record: OrangeHrmEmployeeRecord) -> dict[str, str]:
        self.calls.append("read_job")
        self._raise_if_configured("read_job")
        return self.job

    def list_salary_attachments(self, record: OrangeHrmEmployeeRecord) -> list[str]:
        self.calls.append("list_salary_attachments")
        self._raise_if_configured("list_salary_attachments")
        return self.attachments

    def upload_salary_attachment(self, record: OrangeHrmEmployeeRecord, path: Path) -> None:
        self.calls.append("upload_salary_attachment")
        self.uploaded_paths.append(path)
        self._raise_if_configured("upload_salary_attachment")

    def verify_salary_attachment(self, record: OrangeHrmEmployeeRecord, filename: str) -> bool:
        self.calls.append("verify_salary_attachment")
        self._raise_if_configured("verify_salary_attachment")
        return self.verify_upload

    def _raise_if_configured(self, method_name: str) -> None:
        queued = self.failures.get(method_name)
        if queued:
            raise queued.pop(0)


def employee() -> OrangeHrmEmployeeRecord:
    return OrangeHrmEmployeeRecord(
        employee_key="emp-alice-johnson",
        first_name="Alice",
        last_name="Johnson",
        job_title="QA Engineer",
        employment_status="Full-Time Permanent",
        salary=SalaryDetails(
            amount="90000 USD",
            frequency="Annual",
            details="Base salary for 2026",
        ),
    )


def context(tmp_path) -> ContextStub:
    return ContextStub(
        run_id="run-1",
        business_date=date(2026, 6, 29),
        artifacts=ArtifactStore(str(tmp_path / "artifacts")),
        config=SimpleNamespace(max_retries=2),
    )


def assert_portal_error(reason: ReasonCode, func) -> None:
    with pytest.raises(PortalError) as error:
        func()
    assert error.value.reason is reason


def test_find_result_constructors_produce_expected_statuses_and_details() -> None:
    assert FindResult.found() == FindResult(FindStatus.FOUND)
    assert FindResult.not_found() == FindResult(FindStatus.NOT_FOUND)
    assert FindResult.ambiguous("many").status is FindStatus.AMBIGUOUS
    assert FindResult.ambiguous("many").detail == "many"
    assert FindResult.error("failed").status is FindStatus.ERROR
    assert FindResult.error("failed").detail == "failed"


def test_found_path_opens_profile_updates_job_and_reads_job(tmp_path) -> None:
    pages = FakePages(attachments=[salary_filename()])

    result = process_employee(employee(), pages, context(tmp_path))

    assert pages.calls == [
        "find_employee_record",
        "open_employee_profile",
        "update_job",
        "read_job",
        "list_salary_attachments",
    ]
    assert "add_employee" not in pages.calls
    assert result.status is ItemStatus.SUCCESS
    assert result.operation == "sync_employee_state"


def test_not_found_path_adds_employee_and_finds_again(tmp_path) -> None:
    pages = FakePages(
        find_results=[FindResult.not_found(), FindResult.found()],
        attachments=[salary_filename()],
    )

    result = process_employee(employee(), pages, context(tmp_path))

    assert pages.calls[:4] == [
        "find_employee_record",
        "add_employee",
        "find_employee_record",
        "open_employee_profile",
    ]
    assert result.details["created_employee"] is True
    assert result.attempts == 1


def test_ambiguous_first_find_maps_to_employee_match_ambiguous(tmp_path) -> None:
    pages = FakePages(find_results=[FindResult.ambiguous("too many")])

    assert_portal_error(
        ReasonCode.EMPLOYEE_MATCH_AMBIGUOUS,
        lambda: process_employee(employee(), pages, context(tmp_path)),
    )


def test_ambiguous_second_find_maps_to_employee_match_ambiguous(tmp_path) -> None:
    pages = FakePages(find_results=[FindResult.not_found(), FindResult.ambiguous("many")])

    assert_portal_error(
        ReasonCode.EMPLOYEE_MATCH_AMBIGUOUS,
        lambda: process_employee(employee(), pages, context(tmp_path)),
    )


def test_search_error_maps_to_search_failed(tmp_path) -> None:
    pages = FakePages(find_results=[FindResult.error("search failed")])

    assert_portal_error(
        ReasonCode.SEARCH_FAILED,
        lambda: process_employee(employee(), pages, context(tmp_path)),
    )


def test_second_find_still_not_found_maps_to_employee_not_found(tmp_path) -> None:
    pages = FakePages(find_results=[FindResult.not_found(), FindResult.not_found()])

    assert_portal_error(
        ReasonCode.EMPLOYEE_NOT_FOUND,
        lambda: process_employee(employee(), pages, context(tmp_path)),
    )


def test_job_title_mismatch_maps_to_validation_failed(tmp_path) -> None:
    pages = FakePages(job={"job_title": "Wrong", "employment_status": employee().employment_status})

    assert_portal_error(
        ReasonCode.VALIDATION_FAILED,
        lambda: process_employee(employee(), pages, context(tmp_path)),
    )


def test_employment_status_mismatch_maps_to_validation_failed(tmp_path) -> None:
    pages = FakePages(job={"job_title": employee().job_title, "employment_status": "Wrong"})

    assert_portal_error(
        ReasonCode.VALIDATION_FAILED,
        lambda: process_employee(employee(), pages, context(tmp_path)),
    )


def test_existing_salary_attachment_skips_document_generation_and_upload(tmp_path) -> None:
    pages = FakePages(attachments=[salary_filename()])

    result = process_employee(employee(), pages, context(tmp_path))

    assert "upload_salary_attachment" not in pages.calls
    assert "verify_salary_attachment" not in pages.calls
    assert result.artifact_path is None
    assert result.details["salary_document_uploaded"] is False


def test_missing_salary_attachment_generates_writes_uploads_and_verifies(tmp_path) -> None:
    pages = FakePages(attachments=[])
    run_context = context(tmp_path)

    result = process_employee(employee(), pages, run_context)

    expected_path = run_context.artifacts.salary_document_path(
        run_context.run_id,
        employee().employee_key,
        run_context.business_date,
    )
    assert pages.calls[-2:] == ["upload_salary_attachment", "verify_salary_attachment"]
    assert pages.uploaded_paths == [expected_path]
    assert expected_path.read_text(encoding="utf-8").startswith("Employee: Alice Johnson\n")
    assert result.artifact_path == str(expected_path)
    assert result.details["salary_document_uploaded"] is True


def test_retryable_search_failure_is_retried_and_eventually_succeeds(tmp_path) -> None:
    pages = FakePages(
        attachments=[salary_filename()],
        failures={
            "find_employee_record": [PortalError(ReasonCode.PORTAL_TIMEOUT, "search timed out")]
        },
    )
    run_context = context(tmp_path)

    result = process_employee(employee(), pages, run_context)

    assert result.status is ItemStatus.SUCCESS
    assert result.attempts == 2
    assert pages.calls.count("find_employee_record") == 2


def test_exhausted_retryable_search_failure_raises_final_portal_error_with_attempts(
    tmp_path,
) -> None:
    pages = FakePages(
        failures={
            "find_employee_record": [
                PortalError(ReasonCode.PORTAL_TIMEOUT, "search timeout 1"),
                PortalError(ReasonCode.PORTAL_TIMEOUT, "search timeout 2"),
                PortalError(ReasonCode.PORTAL_TIMEOUT, "search timeout 3"),
            ]
        }
    )
    run_context = context(tmp_path)

    with pytest.raises(PortalError) as error:
        process_employee(employee(), pages, run_context)

    assert error.value.reason is ReasonCode.PORTAL_TIMEOUT
    assert error.value.attempts == 3


def test_add_employee_write_operation_is_not_retried_blindly(tmp_path) -> None:
    pages = FakePages(
        find_results=[FindResult.not_found(), FindResult.not_found()],
        failures={
            "add_employee": [PortalError(ReasonCode.PORTAL_TIMEOUT, "add timed out")]
        },
    )
    run_context = context(tmp_path)

    with pytest.raises(PortalError) as error:
        process_employee(employee(), pages, run_context)

    assert error.value.reason is ReasonCode.PORTAL_TIMEOUT
    assert pages.calls.count("add_employee") == 1
    assert pages.calls.count("find_employee_record") == 2


def test_runtime_workflow_uses_retry_policy_execute(tmp_path) -> None:
    pages = FakePages(attachments=[salary_filename()])
    run_context = context(tmp_path)

    original_execute = workflow.execute_with_context_retry
    calls = []

    def tracked_execute(context_obj, operation):
        calls.append("retry")
        return original_execute(context_obj, operation)

    workflow.execute_with_context_retry = tracked_execute
    try:
        result = process_employee(employee(), pages, run_context)
    finally:
        workflow.execute_with_context_retry = original_execute

    assert result.status is ItemStatus.SUCCESS
    assert calls != []


def test_salary_document_filename_exactly_matches_contract() -> None:
    assert salary_filename() == "salary_emp-alice-johnson_2026-06-29.txt"


@pytest.mark.parametrize("generated_content", [None, ""])
def test_document_generation_failure_maps_to_document_generation_failed(
    tmp_path,
    monkeypatch,
    generated_content,
) -> None:
    monkeypatch.setattr(workflow, "generate_salary_document", lambda **kwargs: generated_content)
    pages = FakePages(attachments=[])

    assert_portal_error(
        ReasonCode.DOCUMENT_GENERATION_FAILED,
        lambda: process_employee(employee(), pages, context(tmp_path)),
    )


def test_upload_verification_failure_maps_to_upload_failed(tmp_path) -> None:
    pages = FakePages(attachments=[], verify_upload=False)

    assert_portal_error(
        ReasonCode.UPLOAD_FAILED,
        lambda: process_employee(employee(), pages, context(tmp_path)),
    )


def test_workflow_does_not_import_persistence_or_sqlite_modules() -> None:
    source = workflow_source()

    assert "persistence" not in source
    assert "sqlite" not in source


def test_workflow_does_not_import_playwright_browser_or_page_modules() -> None:
    source = workflow_source().lower()

    assert "playwright" not in source
    assert "import browser" not in source
    assert "from browser" not in source
    assert "import page" not in source
    assert "from page" not in source


def test_workflow_source_does_not_contain_demo_credentials() -> None:
    source = workflow_source()

    assert "secret_sauce" not in source
    assert "admin123" not in source


def test_forbidden_modules_were_not_created() -> None:
    forbidden_paths = [
        "src/portal_automation/core/logging.py",
    ]

    assert [path for path in forbidden_paths if (ROOT / path).exists()] == []


def salary_filename() -> str:
    return salary_document_filename(employee().employee_key, date(2026, 6, 29))


def workflow_source() -> str:
    return (ROOT / "src/portal_automation/portals/orangehrm/workflow.py").read_text(
        encoding="utf-8"
    )
