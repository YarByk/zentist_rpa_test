from datetime import date
from pathlib import Path

from portal_automation.core.artifact_store import ArtifactStore
from portal_automation.core.models import (
    ItemResult,
    ItemStatus,
    ReasonCode,
    RunResult,
    RunStatus,
)
from portal_automation.core.reporting import ReportGenerator

ROOT = Path(__file__).resolve().parents[2]


def run_result() -> RunResult:
    # Canonical mixed-result fixture used to exercise report rendering and redaction behavior.
    """Run result.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    return RunResult(
        run_id="run-1",
        portal_name="orangehrm",
        business_date=date(2026, 6, 29),
        status=RunStatus.PARTIAL_SUCCESS,
        results=[
            ItemResult(
                item_key="emp-001",
                operation="update_salary",
                status=ItemStatus.SUCCESS,
                reason_code=None,
                error_detail="secret_sauce should not leak",
                artifact_path="artifacts/runs/run-1/generated_documents/salary_emp-001.txt",
                attempts=1,
                details={"password": "admin123"},
            ),
            ItemResult(
                item_key="emp-002",
                operation="update_salary",
                status=ItemStatus.FAILED,
                reason_code=ReasonCode.PORTAL_TIMEOUT,
                error_detail="admin123 should not leak",
                artifact_path=None,
                attempts=2,
                details={"token": "secret_sauce"},
            ),
        ],
    )


def test_render_includes_run_header_fields(tmp_path) -> None:
    """Verify that render includes run header fields.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    report = ReportGenerator(ArtifactStore(str(tmp_path / "artifacts"))).render(run_result())

    assert "Run ID: run-1" in report
    assert "Portal: orangehrm" in report
    assert "Business date: 2026-06-29" in report
    assert "Run status: partial_success" in report


def test_render_includes_processed_success_and_failure_counts(tmp_path) -> None:
    """Verify that render includes processed success and failure counts.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    report = ReportGenerator(ArtifactStore(str(tmp_path / "artifacts"))).render(run_result())

    assert "Processed count: 2" in report
    assert "Success count: 1" in report
    assert "Failure count: 1" in report


def test_render_includes_per_item_outcomes_in_result_order(tmp_path) -> None:
    # Item order in the report should match the order supplied by the run result.
    """Verify that render includes per item outcomes in result order.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    report = ReportGenerator(ArtifactStore(str(tmp_path / "artifacts"))).render(run_result())

    first_item_index = report.index("1. item_key=emp-001")
    second_item_index = report.index("2. item_key=emp-002")

    assert first_item_index < second_item_index
    assert "status=success" in report
    assert "status=failed" in report


def test_render_includes_reason_codes(tmp_path) -> None:
    """Verify that render includes reason codes.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    report = ReportGenerator(ArtifactStore(str(tmp_path / "artifacts"))).render(run_result())

    assert "reason_code=PORTAL_TIMEOUT" in report
    assert "reason_code=" in report


def test_render_includes_artifact_paths(tmp_path) -> None:
    """Verify that render includes artifact paths.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    report = ReportGenerator(ArtifactStore(str(tmp_path / "artifacts"))).render(run_result())

    assert "artifact_path=artifacts/runs/run-1/generated_documents/salary_emp-001.txt" in report
    assert "artifact_path=" in report


def test_render_ends_with_exactly_one_trailing_newline(tmp_path) -> None:
    """Verify that render ends with exactly one trailing newline.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    report = ReportGenerator(ArtifactStore(str(tmp_path / "artifacts"))).render(run_result())

    assert report.endswith("\n")
    assert not report.endswith("\n\n")


def test_render_excludes_error_detail_and_details_secret_like_values(tmp_path) -> None:
    # Reports intentionally omit raw error details and arbitrary details to avoid leaking secrets.
    """Verify that render excludes error detail and details secret like values.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    report = ReportGenerator(ArtifactStore(str(tmp_path / "artifacts"))).render(run_result())

    assert "secret_sauce" not in report
    assert "admin123" not in report
    assert "password" not in report.lower()
    assert "token" not in report.lower()


def test_render_includes_safe_saucedemo_order_details(tmp_path) -> None:
    """Verify that safe Sauce Demo order details are visible in reports.

    Args:
        tmp_path: Temporary directory fixture.

    Returns:
        None. Assertions communicate the test outcome.

    Raises:
        AssertionError: If safe order details are omitted or secret details leak.
    """
    result = RunResult(
        run_id="run-sauce",
        portal_name="saucedemo",
        business_date=date(2026, 6, 29),
        status=RunStatus.SUCCESS,
        results=[
            ItemResult(
                item_key="standard_user",
                operation="checkout",
                status=ItemStatus.SUCCESS,
                reason_code=None,
                error_detail=None,
                artifact_path=None,
                attempts=1,
                details={
                    "cart_count": 3,
                    "item_names": ["Sauce Labs Backpack", "Sauce Labs Bike Light"],
                    "password": "must-not-leak",
                    "total": "Total: $43.18",
                },
            )
        ],
    )

    report = ReportGenerator(ArtifactStore(str(tmp_path / "artifacts"))).render(result)

    assert "cart_count=3" in report
    assert "Sauce Labs Backpack" in report
    assert "Total: $43.18" in report
    assert "must-not-leak" not in report


def test_write_report_writes_report_under_run_artifacts(tmp_path) -> None:
    """Verify that write report writes report under run artifacts.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    artifacts = ArtifactStore(str(tmp_path / "artifacts"))
    result = run_result()

    path = ReportGenerator(artifacts).write_report(result)

    assert path == tmp_path / "artifacts" / "runs" / "run-1" / "report.txt"
    assert path.read_text(encoding="utf-8") == ReportGenerator(artifacts).render(result)


def test_generate_from_persistence_uses_business_date_results(tmp_path) -> None:
    # Rerun reports should pull the persisted business-date result set, not just one run id.
    """Verify that generate from persistence uses business date results.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """

    class PersistenceStub:
        # Minimal persistence facade that records the query used by ReportGenerator.
        def __init__(self) -> None:
            """Initialize this test helper instance.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
            self.calls = []

        def list_results_by_business_date(self, portal_name, business_date):
            """List results by business date.

            Args:
                portal_name: Value supplied by the test or fixture for `portal_name`.
                business_date: Value supplied by the test or fixture for `business_date`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
            self.calls.append((portal_name, business_date))
            return run_result().results

    persistence = PersistenceStub()
    artifacts = ArtifactStore(str(tmp_path / "artifacts"))

    path = ReportGenerator(artifacts).generate_from_persistence(
        run_id="rerun-1",
        portal_name="orangehrm",
        business_date=date(2026, 6, 29),
        status=RunStatus.SUCCESS,
        persistence=persistence,
    )

    report = path.read_text(encoding="utf-8")
    assert persistence.calls == [("orangehrm", date(2026, 6, 29))]
    assert path == tmp_path / "artifacts" / "runs" / "rerun-1" / "report.txt"
    assert "Run ID: rerun-1" in report
    assert "item_key=emp-001" in report
    assert "item_key=emp-002" in report


def test_reporting_does_not_import_playwright_browser_or_page_modules() -> None:
    """Verify that reporting does not import playwright browser or page modules.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    source = (ROOT / "src/portal_automation/core/reporting.py").read_text(encoding="utf-8")

    assert "playwright" not in source.lower()
    assert "browser" not in source.lower()
    assert "page" not in source.lower()


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
