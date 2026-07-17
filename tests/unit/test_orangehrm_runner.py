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
from portal_automation.portals.orangehrm.workflow import FindResult

ROOT = Path(__file__).resolve().parents[2]


@dataclass
class ConfigStub:
    # Minimal config surface required by OrangeHrmRunner and OrangeHrmPages tests.
    orangehrm_input_path: str
    orangehrm_password: str | None = "pw"
    orangehrm_base_url: str = "https://orange.example"
    orangehrm_username: str = "Admin"
    report_email_to: str | None = "reviewer@example.com"


@dataclass
class ContextStub:
    # Small context substitute for runner methods that do not need the full RunContext.
    run_id: str
    business_date: date
    artifacts: ArtifactStore
    reporter: object
    config: object


class FakePersistence:
    # In-memory run/result store used to assert base-runner interactions.
    def __init__(self) -> None:
        """Initialize this test helper instance.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.created_runs = []
        self.finished_runs = []
        self.real_run_methods = []
        self.item_results: list[ItemResult] = []

    def create_run(self, run_id: str, portal_name: str, business_date: date) -> None:
        """Create run.

        Args:
            run_id: Value supplied by the test or fixture for `run_id`.
            portal_name: Value supplied by the test or fixture for `portal_name`.
            business_date: Value supplied by the test or fixture for `business_date`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.created_runs.append((run_id, portal_name, business_date))

    def finish_run(self, run_id: str, status: RunStatus, summary: dict[str, int]) -> None:
        """Finish run.

        Args:
            run_id: Value supplied by the test or fixture for `run_id`.
            status: Value supplied by the test or fixture for `status`.
            summary: Value supplied by the test or fixture for `summary`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.finished_runs.append((run_id, status, summary))

    def get_committed_items(self, portal_name: str, business_date: date) -> set[str]:
        """Get committed items.

        Args:
            portal_name: Value supplied by the test or fixture for `portal_name`.
            business_date: Value supplied by the test or fixture for `business_date`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
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
        """Mark item in progress.

        Args:
            run_id: Value supplied by the test or fixture for `run_id`.
            portal_name: Value supplied by the test or fixture for `portal_name`.
            business_date: Value supplied by the test or fixture for `business_date`.
            item_key: Value supplied by the test or fixture for `item_key`.
            operation: Value supplied by the test or fixture for `operation`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.real_run_methods.append("mark_item_in_progress")

    def upsert_item_result(self, *args: object) -> None:
        """Upsert item result.

        Args:
            *args: Value supplied by the test or fixture for `args`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.real_run_methods.append("upsert_item_result")
        self.item_results.append(args[0])

    def list_results_by_business_date(self, portal_name: str, business_date: date) -> list[object]:
        """List results by business date.

        Args:
            portal_name: Value supplied by the test or fixture for `portal_name`.
            business_date: Value supplied by the test or fixture for `business_date`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.real_run_methods.append("list_results_by_business_date")
        return list(self.item_results)


class ReporterStub:
    # Captures reports requested by finalize().
    def __init__(self) -> None:
        """Initialize this test helper instance.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.written_results: list[RunResult] = []

    def write_report(self, result: RunResult) -> None:
        """Write report.

        Args:
            result: Value supplied by the test or fixture for `result`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.written_results.append(result)

    def render(self, result: RunResult) -> str:
        """Render.

        Args:
            result: Value supplied by the test or fixture for `result`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        return f"rendered-report:{result.run_id}:{result.status.value}"


class EmailStub:
    # Captures outgoing notification parameters requested by finalize().
    def __init__(self) -> None:
        """Initialize this test helper instance.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.calls: list[dict[str, object]] = []

    def send_report(self, **kwargs: object) -> None:
        """Send report.

        Args:
            **kwargs: Value supplied by the test or fixture for `kwargs`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.calls.append(kwargs)


class FakeTarget:
    # Lightweight fake element used by FakePage's label/role/locator helpers.
    def __init__(self, page: "FakePage", kind: str, name: str) -> None:
        """Initialize this test helper instance.

        Args:
            page: Value supplied by the test or fixture for `page`.
            kind: Value supplied by the test or fixture for `kind`.
            name: Value supplied by the test or fixture for `name`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.page = page
        self.kind = kind
        self.name = name

    def fill(self, value: str) -> None:
        """Fill.

        Args:
            value: Value supplied by the test or fixture for `value`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.page.calls.append((self.kind, self.name, "fill", value))

    def click(self) -> None:
        """Click.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.page.calls.append((self.kind, self.name, "click"))

    def text_content(self) -> str:
        """Text content.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.page.calls.append((self.kind, self.name, "text_content"))
        return self.page.text_values.get(self.name, "")

    def set_input_files(self, value: str) -> None:
        """Set input files.

        Args:
            value: Value supplied by the test or fixture for `value`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.page.calls.append((self.kind, self.name, "set_input_files", value))


class FakePage:
    # Fake page object that drives the non-real-page branches of OrangeHrmPages.
    def __init__(self) -> None:
        """Initialize this test helper instance.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
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
        """Goto.

        Args:
            url: Value supplied by the test or fixture for `url`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.calls.append(("goto", url))

    def get_by_label(self, name: str) -> FakeTarget:
        """Get by label.

        Args:
            name: Value supplied by the test or fixture for `name`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.calls.append(("get_by_label", name))
        return FakeTarget(self, "label", name)

    def get_by_role(self, role: str, *, name: str) -> FakeTarget:
        """Get by role.

        Args:
            role: Value supplied by the test or fixture for `role`.
            name: Value supplied by the test or fixture for `name`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.calls.append(("get_by_role", role, name))
        return FakeTarget(self, f"role:{role}", name)

    def locator(self, selector: str) -> FakeTarget:
        """Locator.

        Args:
            selector: Value supplied by the test or fixture for `selector`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.calls.append(("locator", selector))
        return FakeTarget(self, "locator", selector)


class FakeWorkflowPages:
    # Fake workflow page protocol used to test login caching and process_item behavior.
    def __init__(self, *, login_error: PortalError | None = None) -> None:
        """Initialize this test helper instance.

        Args:
            login_error: Value supplied by the test or fixture for `login_error`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.login_error = login_error
        self.calls: list[tuple | str] = []
        self.authenticated = True

    def login(self, username: str, password: str) -> None:
        """Login.

        Args:
            username: Value supplied by the test or fixture for `username`.
            password: Value supplied by the test or fixture for `password`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.calls.append(("login", username, password))
        if self.login_error is not None:
            raise self.login_error
        self.authenticated = True

    def is_authenticated(self) -> bool:
        """Return whether this fake page still represents a live authenticated session.

        Returns:
            ``True`` when the fake session is authenticated.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.calls.append("is_authenticated")
        return self.authenticated

    def find_employee_record(self, record: OrangeHrmEmployeeRecord):
        """Find employee record.

        Args:
            record: Value supplied by the test or fixture for `record`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.calls.append("find_employee_record")
        return FindResult.found()

    def add_employee(self, record: OrangeHrmEmployeeRecord) -> None:
        """Add employee.

        Args:
            record: Value supplied by the test or fixture for `record`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.calls.append("add_employee")

    def open_employee_profile(self, record: OrangeHrmEmployeeRecord) -> None:
        """Open employee profile.

        Args:
            record: Value supplied by the test or fixture for `record`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.calls.append("open_employee_profile")

    def update_job(self, record: OrangeHrmEmployeeRecord) -> None:
        """Update job.

        Args:
            record: Value supplied by the test or fixture for `record`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.calls.append("update_job")

    def read_job(self, record: OrangeHrmEmployeeRecord) -> dict[str, str]:
        """Read job.

        Args:
            record: Value supplied by the test or fixture for `record`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.calls.append("read_job")
        return {
            "job_title": record.job_title,
            "employment_status": record.employment_status,
        }

    def list_salary_attachments(self, record: OrangeHrmEmployeeRecord) -> list[str]:
        """List salary attachments.

        Args:
            record: Value supplied by the test or fixture for `record`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.calls.append("list_salary_attachments")
        return [f"salary_{record.employee_key}_2026-06-29.txt"]

    def upload_salary_attachment(self, record: OrangeHrmEmployeeRecord, path: Path) -> None:
        """Upload salary attachment.

        Args:
            record: Value supplied by the test or fixture for `record`.
            path: Value supplied by the test or fixture for `path`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.calls.append("upload_salary_attachment")

    def verify_salary_attachment(self, record: OrangeHrmEmployeeRecord, filename: str) -> bool:
        """Verify salary attachment.

        Args:
            record: Value supplied by the test or fixture for `record`.
            filename: Value supplied by the test or fixture for `filename`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.calls.append("verify_salary_attachment")
        return True


class SessionDropOnceWorkflowPages(FakeWorkflowPages):
    # Fake page adapter that expires once during an in-workflow browser action.
    def __init__(self) -> None:
        """Initialize the fake with one pending session-drop failure."""
        super().__init__()
        self.drop_next_find = True

    def find_employee_record(self, record: OrangeHrmEmployeeRecord):
        """Raise ``SESSION_DROPPED`` once, then behave like an authenticated page.

        Args:
            record: Employee record supplied by the workflow.

        Returns:
            Found lookup result after the relogin retry.

        Raises:
            PortalError: On the first call, to simulate OrangeHRM expiring the session.
        """
        self.calls.append("find_employee_record")
        if self.drop_next_find:
            self.drop_next_find = False
            self.authenticated = False
            raise PortalError(ReasonCode.SESSION_DROPPED, "Session expired.")
        return FindResult.found()


def employee() -> OrangeHrmEmployeeRecord:
    """Employee.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
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


def employee_two() -> OrangeHrmEmployeeRecord:
    """Employee two.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    return OrangeHrmEmployeeRecord(
        employee_key="emp-bob-smith",
        first_name="Bob",
        last_name="Smith",
        job_title="Support Specialist",
        employment_status="Part-Time Contract",
        salary=SalaryDetails(
            amount="50000 USD",
            frequency="Annual",
            details="Base salary for 2026",
        ),
    )


def write_employee_input(tmp_path) -> str:
    """Write employee input.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
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


def write_two_employee_input(tmp_path) -> str:
    """Write two employee input.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    path = tmp_path / "employees_two.json"
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
  },
  {
    "employee_key": "emp-bob-smith",
    "first_name": "Bob",
    "last_name": "Smith",
    "job_title": "Support Specialist",
    "employment_status": "Part-Time Contract",
    "salary": {
      "amount": "50000 USD",
      "frequency": "Annual",
      "details": "Base salary for 2026"
    }
  }
]""",
        encoding="utf-8",
    )
    return str(path)


def make_run_context(tmp_path, *, reporter: object | None = None) -> RunContext:
    """Make run context.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
        reporter: Value supplied by the test or fixture for `reporter`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
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
    """Make process context.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
        reporter: Value supplied by the test or fixture for `reporter`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    return ContextStub(
        run_id="run-1",
        business_date=date(2026, 6, 29),
        artifacts=ArtifactStore(str(tmp_path / "artifacts")),
        reporter=reporter if reporter is not None else object(),
        config=ConfigStub(orangehrm_input_path=write_employee_input(tmp_path)),
    )


def test_runner_contract_constants_are_correct() -> None:
    """Verify that runner contract constants are correct.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    assert OrangeHrmRunner.portal_name == "orangehrm"
    assert OrangeHrmRunner.operation_name == "sync_employee_state"


def test_runner_inherits_base_and_does_not_override_run() -> None:
    """Verify that runner inherits base and does not override run.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    assert issubclass(OrangeHrmRunner, BasePortalRunnerZX)
    assert "run" not in OrangeHrmRunner.__dict__
    assert OrangeHrmRunner.run is BasePortalRunnerZX.run


def test_runner_item_key_uses_employee_key() -> None:
    """Verify that runner item key uses employee key.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    assert OrangeHrmRunner().item_key(employee()) == "emp-alice-johnson"


def test_dry_run_does_not_call_page_factory_or_process_item(tmp_path) -> None:
    """Verify that dry run does not call page factory or process item.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    factory_calls = []

    def pages_factory(context: RunContext) -> object:
        """Pages factory.

        Args:
            context: Value supplied by the test or fixture for `context`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        factory_calls.append(context)
        raise AssertionError("page factory must not be called in dry-run")

    runner = OrangeHrmRunner(pages_factory=pages_factory)
    context = make_run_context(tmp_path)

    result = runner.run(context)

    assert result.status is RunStatus.SUCCESS
    assert factory_calls == []
    assert context.persistence.real_run_methods == []


def test_process_item_uses_injected_page_factory_logs_in_then_calls_workflow(
    tmp_path,
    monkeypatch,
) -> None:
    """Verify that process item uses injected page factory logs in then calls workflow.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
        monkeypatch: Value supplied by the test or fixture for `monkeypatch`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    pages = FakeWorkflowPages()
    calls = []

    def pages_factory(context: ContextStub) -> object:
        """Pages factory.

        Args:
            context: Value supplied by the test or fixture for `context`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        calls.append(("factory", context))
        return pages

    def fake_process_employee(record, page_objects, context):
        """Fake process employee.

        Args:
            record: Value supplied by the test or fixture for `record`.
            page_objects: Value supplied by the test or fixture for `page_objects`.
            context: Value supplied by the test or fixture for `context`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
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
    assert calls[0] == ("factory", context)
    assert calls[1][0] == "workflow"
    assert calls[1][1] == employee()
    assert calls[1][2]._pages is pages
    assert calls[1][3] is context
    assert pages.calls == [("login", "Admin", "pw")]


def test_process_item_without_page_factory_raises_portal_unavailable(tmp_path) -> None:
    """Verify that process item without page factory raises portal unavailable.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    with pytest.raises(PortalError) as error:
        OrangeHrmRunner().process_item(make_process_context(tmp_path), employee())

    assert error.value.reason is ReasonCode.PORTAL_UNAVAILABLE
    assert "page factory" in error.value.detail


def test_process_item_logs_in_before_first_employee_business_action(tmp_path) -> None:
    """Verify that process item logs in before first employee business action.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    pages = FakeWorkflowPages()
    context = make_process_context(tmp_path)

    result = OrangeHrmRunner(pages_factory=lambda _: pages).process_item(context, employee())

    assert result.status is ItemStatus.SUCCESS
    assert pages.calls[:2] == [
        ("login", "Admin", "pw"),
        "find_employee_record",
    ]
    assert "add_employee" not in pages.calls


def test_runner_logs_in_once_for_multiple_items_in_same_session(tmp_path) -> None:
    """Verify that runner logs in once for multiple items in same session.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    pages = FakeWorkflowPages()
    context = make_process_context(tmp_path)
    runner = OrangeHrmRunner(pages_factory=lambda _: pages)

    first = runner.process_item(context, employee())
    second = runner.process_item(context, employee_two())

    assert first.status is ItemStatus.SUCCESS
    assert second.status is ItemStatus.SUCCESS
    assert pages.calls.count(("login", "Admin", "pw")) == 1
    assert pages.calls.count("find_employee_record") == 2
    assert pages.calls.index(("login", "Admin", "pw")) < pages.calls.index("find_employee_record")


def test_runner_relogs_in_when_cached_session_is_no_longer_authenticated(tmp_path) -> None:
    """Verify that runner reuses the page but logs in again after session loss.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    pages = FakeWorkflowPages()
    context = make_process_context(tmp_path)
    runner = OrangeHrmRunner(pages_factory=lambda _: pages)

    first = runner.process_item(context, employee())
    pages.authenticated = False
    second = runner.process_item(context, employee_two())

    assert first.status is ItemStatus.SUCCESS
    assert second.status is ItemStatus.SUCCESS
    assert pages.calls.count(("login", "Admin", "pw")) == 2
    assert pages.calls.count("is_authenticated") == 1


def test_runner_relogs_in_after_session_drops_inside_workflow_action(tmp_path) -> None:
    """Verify that a mid-item ``SESSION_DROPPED`` triggers relogin before workflow retry.

    Args:
        tmp_path: Temporary directory fixture.

    Returns:
        None. Assertions communicate the test outcome.

    Raises:
        AssertionError: If the runner does not restore login before retrying workflow work.
    """
    pages = SessionDropOnceWorkflowPages()
    context = make_process_context(tmp_path)
    context.config.max_retries = 1
    runner = OrangeHrmRunner(pages_factory=lambda _: pages)

    result = runner.process_item(context, employee())

    assert result.status is ItemStatus.SUCCESS
    assert pages.calls.count(("login", "Admin", "pw")) == 2
    assert pages.calls.count("find_employee_record") == 2
    assert pages.calls.index(("login", "Admin", "pw"), 1) < pages.calls.index(
        "find_employee_record",
        2,
    )


def test_login_failure_stops_employee_business_actions_and_is_cached(tmp_path) -> None:
    """Verify that login failure stops employee business actions and is cached.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    login_error = PortalError(ReasonCode.LOGIN_FAILED, "OrangeHRM login failed.")
    pages = FakeWorkflowPages(login_error=login_error)
    context = make_process_context(tmp_path)
    runner = OrangeHrmRunner(pages_factory=lambda _: pages)

    with pytest.raises(PortalError) as first_error:
        runner.process_item(context, employee())
    with pytest.raises(PortalError) as second_error:
        runner.process_item(context, employee_two())

    assert first_error.value.reason is ReasonCode.LOGIN_FAILED
    assert second_error.value.reason is ReasonCode.LOGIN_FAILED
    assert pages.calls == [("login", "Admin", "pw")]


def test_login_failure_in_run_marks_items_failed_without_business_actions(tmp_path) -> None:
    """Verify that login failure in run marks items failed without business actions.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    login_error = PortalError(ReasonCode.LOGIN_FAILED, "OrangeHRM login failed.")
    pages = FakeWorkflowPages(login_error=login_error)
    context = make_run_context(tmp_path)
    context.dry_run = False
    runner = OrangeHrmRunner(pages_factory=lambda _: pages)

    result = runner.run(context)

    assert result.status is RunStatus.FAILED
    assert pages.calls == [("login", "Admin", "pw")]
    assert context.persistence.real_run_methods.count("mark_item_in_progress") == 1
    assert context.persistence.real_run_methods.count("upsert_item_result") == 1


def test_initial_login_page_unavailable_stops_remaining_batch_items(tmp_path) -> None:
    """Verify that a startup login-page outage stops the OrangeHRM batch immediately.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    login_error = PortalError(
        ReasonCode.PORTAL_UNAVAILABLE,
        "OrangeHRM login page opened but did not render the username field.",
    )
    pages = FakeWorkflowPages(login_error=login_error)
    context = make_run_context(tmp_path)
    context.config.orangehrm_input_path = write_two_employee_input(tmp_path)
    context.dry_run = False

    result = OrangeHrmRunner(pages_factory=lambda _: pages).run(context)

    assert result.status is RunStatus.FAILED
    assert [item.item_key for item in result.results] == ["emp-alice-johnson"]
    assert result.results[0].reason_code is ReasonCode.PORTAL_UNAVAILABLE
    assert pages.calls.count(("login", "Admin", "pw")) == 1
    assert context.persistence.real_run_methods.count("mark_item_in_progress") == 1
    assert context.persistence.real_run_methods.count("upsert_item_result") == 1
    assert "find_employee_record" not in pages.calls


def test_initial_login_timeout_stops_remaining_batch_items(tmp_path) -> None:
    """Verify that startup login timeouts do not repeat for every employee.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. Assertions communicate the test outcome.

    Raises:
        AssertionError: If a startup timeout continues into the remaining batch items.
    """
    login_error = PortalError(
        ReasonCode.PORTAL_TIMEOUT,
        "OrangeHRM login page navigation failed.",
    )
    pages = FakeWorkflowPages(login_error=login_error)
    context = make_run_context(tmp_path)
    context.config.orangehrm_input_path = write_two_employee_input(tmp_path)
    context.dry_run = False

    result = OrangeHrmRunner(pages_factory=lambda _: pages).run(context)

    assert result.status is RunStatus.FAILED
    assert [item.item_key for item in result.results] == ["emp-alice-johnson"]
    assert result.results[0].reason_code is ReasonCode.PORTAL_TIMEOUT
    assert pages.calls.count(("login", "Admin", "pw")) == 1
    assert context.persistence.real_run_methods.count("mark_item_in_progress") == 1
    assert context.persistence.real_run_methods.count("upsert_item_result") == 1
    assert "find_employee_record" not in pages.calls


def test_one_employee_failure_does_not_abort_remaining_batch_items(tmp_path) -> None:
    """Verify that one employee failure does not abort remaining batch items.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """

    class AmbiguousFirstEmployeePages(FakeWorkflowPages):
        def find_employee_record(self, record: OrangeHrmEmployeeRecord):
            """Find employee record.

            Args:
                record: Value supplied by the test or fixture for `record`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
            self.calls.append(("find_employee_record", record.employee_key))
            if record.employee_key == "emp-alice-johnson":
                return FindResult.ambiguous("duplicate Alice")
            return FindResult.found()

    pages = AmbiguousFirstEmployeePages()
    context = make_run_context(tmp_path)
    context.config.orangehrm_input_path = write_two_employee_input(tmp_path)
    context.dry_run = False

    result = OrangeHrmRunner(pages_factory=lambda _: pages).run(context)

    assert result.status is RunStatus.PARTIAL_SUCCESS
    assert [item.item_key for item in result.results] == [
        "emp-alice-johnson",
        "emp-bob-smith",
    ]
    assert result.results[0].status is ItemStatus.FAILED
    assert result.results[0].reason_code is ReasonCode.EMPLOYEE_MATCH_AMBIGUOUS
    assert result.results[1].status is ItemStatus.SUCCESS
    assert ("find_employee_record", "emp-bob-smith") in pages.calls
    assert pages.calls.count(("login", "Admin", "pw")) == 1


@pytest.mark.parametrize("password", [None, "", "   "])
def test_preflight_raises_credential_expired_when_password_missing_or_blank(
    tmp_path,
    password,
) -> None:
    """Verify that preflight raises credential expired when password missing or blank.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
        password: Value supplied by the test or fixture for `password`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    context = SimpleNamespace(
        config=ConfigStub(write_employee_input(tmp_path), orangehrm_password=password)
    )

    with pytest.raises(PortalError) as error:
        OrangeHrmRunner().preflight_check(context)

    assert error.value.reason is ReasonCode.CREDENTIAL_EXPIRED


def test_preflight_passes_with_required_non_browser_config(tmp_path) -> None:
    """Verify that preflight passes with required non browser config.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    context = SimpleNamespace(
        config=ConfigStub(write_employee_input(tmp_path), orangehrm_password="pw")
    )

    OrangeHrmRunner().preflight_check(context)


def test_preflight_does_not_create_page_objects(tmp_path) -> None:
    """Verify that preflight does not create page objects.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    factory_calls = []
    runner = OrangeHrmRunner(pages_factory=lambda context: factory_calls.append(context))
    context = SimpleNamespace(
        config=ConfigStub(write_employee_input(tmp_path), orangehrm_password="pw")
    )

    runner.preflight_check(context)

    assert factory_calls == []


def test_load_items_still_reads_validated_input_records(tmp_path) -> None:
    """Verify that load items still reads validated input records.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    context = SimpleNamespace(config=ConfigStub(write_employee_input(tmp_path)))

    items = OrangeHrmRunner().load_items(context)

    assert len(items) == 1
    assert items[0] == employee()


def test_finalize_writes_report_when_reporter_supports_write_report(tmp_path) -> None:
    """Verify that finalize writes report when reporter supports write report.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    reporter = ReporterStub()
    context = make_process_context(tmp_path, reporter=reporter)
    context.email = object()
    result = RunResult(
        run_id="run-1",
        portal_name="orangehrm",
        business_date=date(2026, 6, 29),
        status=RunStatus.SUCCESS,
        results=[],
    )

    OrangeHrmRunner().finalize(context, result)

    assert reporter.written_results == [result]


def test_finalize_calls_email_send_report_with_written_report(tmp_path) -> None:
    """Verify that finalize calls email send report with written report.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    reporter = ReporterStub()
    email = EmailStub()
    context = make_process_context(tmp_path, reporter=reporter)
    context.email = email
    result = RunResult(
        run_id="run-1",
        portal_name="orangehrm",
        business_date=date(2026, 6, 29),
        status=RunStatus.SUCCESS,
        results=[],
    )

    OrangeHrmRunner().finalize(context, result)

    assert reporter.written_results == [result]
    assert email.calls == [
        {
            "run_id": "run-1",
            "to": "reviewer@example.com",
            "subject": "OrangeHRM run report: run-1",
            "body": "rendered-report:run-1:success",
            "report_path": None,
        }
    ]


def test_finalize_returns_without_error_when_reporter_has_no_write_report(tmp_path) -> None:
    """Verify that finalize returns without error when reporter has no write report.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    result = RunResult(
        run_id="run-1",
        portal_name="orangehrm",
        business_date=date(2026, 6, 29),
        status=RunStatus.SUCCESS,
        results=[],
    )

    OrangeHrmRunner().finalize(make_process_context(tmp_path), result)


def test_orangehrm_pages_login_uses_explicit_credentials_and_base_url() -> None:
    """Verify that orangehrm pages login uses explicit credentials and base url.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    page = FakePage()
    config = ConfigStub(
        orangehrm_input_path="input.json",
        orangehrm_base_url="https://orange.example",
        orangehrm_username="Admin",
        orangehrm_password="pw",
    )

    OrangeHrmPages(page, config).login("Admin", "pw")

    assert ("goto", "https://orange.example") in page.calls
    assert ("locator", OrangeHrmPages.USERNAME_INPUT, "fill", "Admin") in page.calls
    assert ("locator", OrangeHrmPages.PASSWORD_INPUT, "fill", "pw") in page.calls
    assert ("locator", OrangeHrmPages.LOGIN_BUTTON, "click") in page.calls


def test_orangehrm_pages_login_failed_attr_raises_login_failed() -> None:
    """Verify that orangehrm pages login failed attr raises login failed.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    page = FakePage()
    page.login_succeeded = False
    config = ConfigStub(orangehrm_input_path="input.json", orangehrm_base_url="https://x.example")

    with pytest.raises(PortalError) as error:
        OrangeHrmPages(page, config).login("Admin", "wrong")

    assert error.value.reason is ReasonCode.LOGIN_FAILED


def test_page_methods_operate_against_fake_page_and_record_expected_calls(tmp_path) -> None:
    """Verify that page methods operate against fake page and record expected calls.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
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

    assert ("label", "First Name", "fill", "Alice") in page.calls
    assert ("label", "Last Name", "fill", "Johnson") in page.calls
    assert ("label", "Job Title", "fill", "QA Engineer") in page.calls
    assert ("label", "Salary Attachment", "set_input_files", str(attachment_path)) in page.calls


def test_page_objects_do_not_import_persistence_or_sqlite_modules() -> None:
    """Verify that page objects do not import persistence or sqlite modules.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    source = (ROOT / "src/portal_automation/portals/orangehrm/pages.py").read_text(encoding="utf-8")

    assert "persistence" not in source
    assert "sqlite" not in source


def test_page_objects_do_not_contain_demo_credentials() -> None:
    """Verify that page objects do not contain demo credentials.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    source = (ROOT / "src/portal_automation/portals/orangehrm/pages.py").read_text(encoding="utf-8")

    assert "secret_sauce" not in source
    assert "admin123" not in source


def test_runner_and_page_source_do_not_import_playwright_directly() -> None:
    """Verify that runner and page source do not import playwright directly.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    paths = [
        ROOT / "src/portal_automation/portals/orangehrm/runner.py",
        ROOT / "src/portal_automation/portals/orangehrm/pages.py",
    ]

    for path in paths:
        source = path.read_text(encoding="utf-8").lower()
        assert "import playwright" not in source
        assert "from playwright" not in source


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
