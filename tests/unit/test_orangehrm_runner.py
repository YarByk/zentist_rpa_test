from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from portal_automation.core.artifact_store import ArtifactStore
from portal_automation.core.models import (
    ItemResult,
    ItemStatus,
    ReasonCode,
    RunContext,
    RunResult,
    RunStatus,
)
from portal_automation.core.retries import PortalError
from portal_automation.core.runner import BasePortalRunnerZX
from portal_automation.portals.orangehrm import runner as runner_module
from portal_automation.portals.orangehrm.input_schema import (
    OrangeHrmEmployeeRecord,
    SalaryDetails,
)
from portal_automation.portals.orangehrm.pages import OrangeHrmPages
from portal_automation.portals.orangehrm.runner import OrangeHrmRunner

ROOT = Path(__file__).resolve().parents[2]


@dataclass
class ConfigStub:
    orangehrm_input_path: str
    orangehrm_password: str | None = "pw"
    orangehrm_base_url: str = "https://orange.example"
    orangehrm_username: str = "Admin"


@dataclass
class ContextStub:
    run_id: str
    business_date: date
    artifacts: ArtifactStore
    reporter: object
    config: object


class FakePersistence:
    def __init__(self) -> None:
        self.created_runs = []
        self.finished_runs = []
        self.real_run_methods = []

    def create_run(self, run_id: str, portal_name: str, business_date: date) -> None:
        self.created_runs.append((run_id, portal_name, business_date))

    def finish_run(self, run_id: str, status: RunStatus, summary: dict[str, int]) -> None:
        self.finished_runs.append((run_id, status, summary))

    def get_committed_items(self, portal_name: str, business_date: date) -> set[str]:
        self.real_run_methods.append("get_committed_items")
        return set()

    def mark_item_in_progress(
        self,
        run_id: str,
        portal_name: str,
        business_date: date,
        item_key: str,
        operation: str,
    ) -> None:
        self.real_run_methods.append("mark_item_in_progress")

    def upsert_item_result(self, *args: object) -> None:
        self.real_run_methods.append("upsert_item_result")

    def list_results_by_business_date(self, portal_name: str, business_date: date) -> list[object]:
        self.real_run_methods.append("list_results_by_business_date")
        return []


class ReporterStub:
    def __init__(self) -> None:
        self.written_results: list[RunResult] = []

    def write_report(self, result: RunResult) -> None:
        self.written_results.append(result)


class FakeTarget:
    def __init__(self, page: "FakePage", kind: str, name: str) -> None:
        self.page = page
        self.kind = kind
        self.name = name

    def fill(self, value: str) -> None:
        self.page.calls.append((self.kind, self.name, "fill", value))

    def click(self) -> None:
        self.page.calls.append((self.kind, self.name, "click"))

    def text_content(self) -> str:
        self.page.calls.append((self.kind, self.name, "text_content"))
        return self.page.text_values.get(self.name, "")

    def set_input_files(self, value: str) -> None:
        self.page.calls.append((self.kind, self.name, "set_input_files", value))


class FakePage:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.employee_search_results = [employee().employee_key]
        self.job_values = {
            "job_title": employee().job_title,
            "employment_status": employee().employment_status,
        }
        self.attachment_filenames = ["salary_emp-alice-johnson_2026-06-29.txt"]
        self.login_succeeded = True
        self.text_values: dict[str, str] = {}

    def goto(self, url: str) -> None:
        self.calls.append(("goto", url))

    def get_by_label(self, name: str) -> FakeTarget:
        self.calls.append(("get_by_label", name))
        return FakeTarget(self, "label", name)

    def get_by_role(self, role: str, *, name: str) -> FakeTarget:
        self.calls.append(("get_by_role", role, name))
        return FakeTarget(self, f"role:{role}", name)

    def locator(self, selector: str) -> FakeTarget:
        self.calls.append(("locator", selector))
        return FakeTarget(self, "locator", selector)


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


def write_employee_input(tmp_path) -> str:
    path = tmp_path / "employees.json"
    path.write_text(
        """[
  {
    "employee_key": "emp-alice-johnson",
    "first_name": "Alice",
    "last_name": "Johnson",
    "job_title": "QA Engineer",
    "employment_status": "Full-Time Permanent",
    "salary": {
      "amount": "90000 USD",
      "frequency": "Annual",
      "details": "Base salary for 2026"
    }
  }
]""",
        encoding="utf-8",
    )
    return str(path)


def make_run_context(tmp_path, *, reporter: object | None = None) -> RunContext:
    return RunContext(
        run_id="run-1",
        business_date=date(2026, 6, 29),
        dry_run=True,
        stale_item_timeout_seconds=300,
        config=ConfigStub(orangehrm_input_path=write_employee_input(tmp_path)),
        persistence=FakePersistence(),
        reporter=reporter if reporter is not None else object(),
        logger=object(),
        metrics=object(),
        artifacts=ArtifactStore(str(tmp_path / "artifacts")),
        email=object(),
    )


def make_process_context(tmp_path, *, reporter: object | None = None) -> ContextStub:
    return ContextStub(
        run_id="run-1",
        business_date=date(2026, 6, 29),
        artifacts=ArtifactStore(str(tmp_path / "artifacts")),
        reporter=reporter if reporter is not None else object(),
        config=ConfigStub(orangehrm_input_path=write_employee_input(tmp_path)),
    )


def test_runner_contract_constants_are_correct() -> None:
    assert OrangeHrmRunner.portal_name == "orangehrm"
    assert OrangeHrmRunner.operation_name == "sync_employee_state"
    assert OrangeHrmRunner.max_sessions_per_login == 1


def test_runner_inherits_base_and_does_not_override_run() -> None:
    assert issubclass(OrangeHrmRunner, BasePortalRunnerZX)
    assert "run" not in OrangeHrmRunner.__dict__
    assert OrangeHrmRunner.run is BasePortalRunnerZX.run


def test_runner_item_key_uses_employee_key() -> None:
    assert OrangeHrmRunner().item_key(employee()) == "emp-alice-johnson"


def test_dry_run_does_not_call_page_factory_or_process_item(tmp_path) -> None:
    factory_calls = []

    def pages_factory(context: RunContext) -> object:
        factory_calls.append(context)
        raise AssertionError("page factory must not be called in dry-run")

    runner = OrangeHrmRunner(pages_factory=pages_factory)
    context = make_run_context(tmp_path)

    result = runner.run(context)

    assert result.status is RunStatus.SUCCESS
    assert factory_calls == []
    assert context.persistence.real_run_methods == []


def test_process_item_uses_injected_page_factory_and_workflow(
    tmp_path,
    monkeypatch,
) -> None:
    pages = object()
    calls = []

    def pages_factory(context: ContextStub) -> object:
        calls.append(("factory", context))
        return pages

    def fake_process_employee(record, page_objects, context):
        calls.append(("workflow", record, page_objects, context))
        return ItemResult(
            item_key=record.employee_key,
            operation="sync_employee_state",
            status=ItemStatus.SUCCESS,
            reason_code=None,
            error_detail=None,
            artifact_path=None,
            details={},
        )

    monkeypatch.setattr(runner_module, "process_employee", fake_process_employee)
    context = make_process_context(tmp_path)

    result = OrangeHrmRunner(pages_factory=pages_factory).process_item(context, employee())

    assert result.status is ItemStatus.SUCCESS
    assert calls == [
        ("factory", context),
        ("workflow", employee(), pages, context),
    ]


def test_process_item_without_page_factory_raises_portal_unavailable(tmp_path) -> None:
    with pytest.raises(PortalError) as error:
        OrangeHrmRunner().process_item(make_process_context(tmp_path), employee())

    assert error.value.reason is ReasonCode.PORTAL_UNAVAILABLE
    assert "page factory" in error.value.detail


@pytest.mark.parametrize("password", [None, "", "   "])
def test_preflight_raises_credential_expired_when_password_missing_or_blank(
    tmp_path,
    password,
) -> None:
    context = SimpleNamespace(
        config=ConfigStub(write_employee_input(tmp_path), orangehrm_password=password)
    )

    with pytest.raises(PortalError) as error:
        OrangeHrmRunner().preflight_check(context)

    assert error.value.reason is ReasonCode.CREDENTIAL_EXPIRED


def test_preflight_passes_with_required_non_browser_config(tmp_path) -> None:
    context = SimpleNamespace(
        config=ConfigStub(write_employee_input(tmp_path), orangehrm_password="pw")
    )

    OrangeHrmRunner().preflight_check(context)


def test_preflight_does_not_create_page_objects(tmp_path) -> None:
    factory_calls = []
    runner = OrangeHrmRunner(pages_factory=lambda context: factory_calls.append(context))
    context = SimpleNamespace(
        config=ConfigStub(write_employee_input(tmp_path), orangehrm_password="pw")
    )

    runner.preflight_check(context)

    assert factory_calls == []


def test_load_items_still_reads_validated_input_records(tmp_path) -> None:
    context = SimpleNamespace(config=ConfigStub(write_employee_input(tmp_path)))

    items = OrangeHrmRunner().load_items(context)

    assert len(items) == 1
    assert items[0] == employee()


def test_finalize_writes_report_when_reporter_supports_write_report(tmp_path) -> None:
    reporter = ReporterStub()
    context = make_process_context(tmp_path, reporter=reporter)
    result = RunResult(
        run_id="run-1",
        portal_name="orangehrm",
        business_date=date(2026, 6, 29),
        status=RunStatus.SUCCESS,
        results=[],
    )

    OrangeHrmRunner().finalize(context, result)

    assert reporter.written_results == [result]


def test_finalize_returns_without_error_when_reporter_has_no_write_report(tmp_path) -> None:
    result = RunResult(
        run_id="run-1",
        portal_name="orangehrm",
        business_date=date(2026, 6, 29),
        status=RunStatus.SUCCESS,
        results=[],
    )

    OrangeHrmRunner().finalize(make_process_context(tmp_path), result)


def test_orangehrm_pages_login_uses_config_values_and_page_calls() -> None:
    page = FakePage()
    config = ConfigStub(
        orangehrm_input_path="input.json",
        orangehrm_base_url="https://orange.example",
        orangehrm_username="Admin",
        orangehrm_password="pw",
    )

    OrangeHrmPages(page, config).login()

    assert ("goto", "https://orange.example") in page.calls
    assert ("label", "Username", "fill", "Admin") in page.calls
    assert ("label", "Password", "fill", "pw") in page.calls
    assert ("role:button", "Login", "click") in page.calls


@pytest.mark.parametrize("password", [None, "", "   "])
def test_orangehrm_pages_login_maps_blank_password_to_credential_expired(password) -> None:
    page = FakePage()
    config = ConfigStub(orangehrm_input_path="input.json", orangehrm_password=password)

    with pytest.raises(PortalError) as error:
        OrangeHrmPages(page, config).login()

    assert error.value.reason is ReasonCode.CREDENTIAL_EXPIRED


def test_page_methods_operate_against_fake_page_and_record_expected_calls(tmp_path) -> None:
    page = FakePage()
    page.attachment_filenames = []
    pages = OrangeHrmPages(page, ConfigStub(orangehrm_input_path="input.json"))
    attachment_path = tmp_path / "salary.txt"

    assert pages.find_employee_record(employee()).status.value == "found"
    pages.add_employee(employee())
    pages.open_employee_profile(employee())
    pages.update_job(employee())
    assert pages.read_job(employee()) == {
        "job_title": "QA Engineer",
        "employment_status": "Full-Time Permanent",
    }
    assert pages.list_salary_attachments(employee()) == []
    pages.upload_salary_attachment(employee(), attachment_path)
    assert pages.verify_salary_attachment(employee(), "salary.txt") is False

    assert ("label", "Employee Name", "fill", "Alice Johnson") in page.calls
    assert ("label", "First Name", "fill", "Alice") in page.calls
    assert ("label", "Last Name", "fill", "Johnson") in page.calls
    assert ("label", "Job Title", "fill", "QA Engineer") in page.calls
    assert ("label", "Salary Attachment", "set_input_files", str(attachment_path)) in page.calls


def test_page_objects_do_not_import_persistence_or_sqlite_modules() -> None:
    source = (ROOT / "src/portal_automation/portals/orangehrm/pages.py").read_text(
        encoding="utf-8"
    )

    assert "persistence" not in source
    assert "sqlite" not in source


def test_page_objects_do_not_contain_demo_credentials() -> None:
    source = (ROOT / "src/portal_automation/portals/orangehrm/pages.py").read_text(
        encoding="utf-8"
    )

    assert "secret_sauce" not in source
    assert "admin123" not in source


def test_runner_and_page_source_do_not_import_playwright_directly() -> None:
    paths = [
        ROOT / "src/portal_automation/portals/orangehrm/runner.py",
        ROOT / "src/portal_automation/portals/orangehrm/pages.py",
    ]

    for path in paths:
        source = path.read_text(encoding="utf-8").lower()
        assert "import playwright" not in source
        assert "from playwright" not in source


def test_forbidden_modules_were_not_created() -> None:
    forbidden_paths = [
        "src/portal_automation/core/logging.py",
    ]

    assert [path for path in forbidden_paths if (ROOT / path).exists()] == []
