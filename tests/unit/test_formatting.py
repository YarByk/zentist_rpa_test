import json
import re
from pathlib import Path

from portal_automation.portals.orangehrm.input_schema import load_employee_records

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def source_files() -> list[Path]:
    return sorted(SRC.rglob("*.py"))


def source_text_by_file() -> dict[Path, str]:
    return {path: path.read_text(encoding="utf-8") for path in source_files()}


def test_readme_first_line_is_schema_marker() -> None:
    first_line = read_text("README.md").splitlines()[0]

    assert first_line == "<!-- schema-ref:zentist-r7 -->"


def test_design_contains_required_figure_title() -> None:
    assert "### Figure ZQ9" in read_text("DESIGN.md")


def test_forbidden_logging_module_does_not_exist() -> None:
    assert not (ROOT / "src/portal_automation/core/logging.py").exists()


def test_insert_or_replace_does_not_appear_in_src() -> None:
    offenders = [
        path.relative_to(ROOT).as_posix()
        for path, text in source_text_by_file().items()
        if "INSERT OR REPLACE" in text
    ]

    assert offenders == []


def test_demo_credentials_do_not_appear_in_src() -> None:
    forbidden_values = ("secret_sauce", "admin123")
    offenders = [
        f"{path.relative_to(ROOT).as_posix()}: {value}"
        for path, text in source_text_by_file().items()
        for value in forbidden_values
        if value in text
    ]

    assert offenders == []


def test_readme_does_not_contain_stale_self_damaging_phrases() -> None:
    readme = read_text("README.md")
    stale_phrases = [
        "No live Playwright dependency",
        "No default CLI browser/page factory wiring",
        "pages_factory is not configured",
        "Playwright not implemented",
        "no-op logger",
        "NoOp logger",
        "SMTP not implemented",
        "fake-only page objects",
        "no real browser runtime",
    ]
    found = [phrase for phrase in stale_phrases if phrase.lower() in readme.lower()]

    assert found == [], f"README contains stale phrases: {found}"


def test_readme_documents_playwright_install() -> None:
    readme = read_text("README.md")

    assert "playwright install chromium" in readme


def test_readme_documents_live_e2e_as_opt_in() -> None:
    readme = read_text("README.md")

    assert "RUN_LIVE_E2E" in readme
    assert "pytest -m e2e" in readme
    assert "opt-in" in readme


def test_production_placeholders_do_not_appear_in_src() -> None:
    line_patterns = {
        "TODO": re.compile(r"^\s*TODO\b"),
        "pass": re.compile(r"^\s*pass(?:\s*(#.*)?)?$"),
        "...": re.compile(r"^\s*\.\.\.(?:\s*(#.*)?)?$"),
        "raise NotImplementedError": re.compile(r"raise\s+NotImplementedError\b"),
        "implementation would go here": re.compile(r"implementation would go here"),
    }
    offenders = [
        f"{path.relative_to(ROOT).as_posix()}:{line_number}: {name}"
        for path, text in source_text_by_file().items()
        for line_number, line in enumerate(text.splitlines(), start=1)
        for name, pattern in line_patterns.items()
        if pattern.search(line)
    ]

    assert offenders == []


def test_readme_links_sanitized_sample_report() -> None:
    readme = read_text("README.md")

    assert "docs/sample_report.md" in readme


def test_sample_report_is_static_and_sanitized() -> None:
    sample = read_text("docs/sample_report.md")

    assert "sanitized static example" in sample
    assert "artifacts/runs/<run_id>/report.txt" in sample
    assert "reason_code" in sample.lower()
    assert "secret_sauce" not in sample
    assert "admin123" not in sample
    assert "passwds.txt" not in sample


def test_saucedemo_live_e2e_does_not_skip_real_portal_assertion_failures() -> None:
    source = read_text("tests/e2e/test_saucedemo_live.py")

    assert "ReasonCode.PORTAL_UNAVAILABLE" in source
    assert "ReasonCode.PORTAL_TIMEOUT" in source
    assert "raise" in source


def test_design_does_not_contain_stale_self_damaging_phrases() -> None:
    design = read_text("DESIGN.md")
    stale_phrases = [
        "current portal runner finalizers only call",
        "default CLI does not wire a live browser",
        "workflows do not invoke `RetryPolicy` directly",
        "_NoOpLogger",
        "_NoOpMetrics",
        "implemented SMTP delivery",
        "No default CLI browser/page factory wiring",
        "No live Playwright dependency",
        "SMTP not implemented",
        "no real browser runtime",
    ]
    found = [phrase for phrase in stale_phrases if phrase.lower() in design.lower()]

    assert found == [], f"DESIGN contains stale phrases: {found}"


def test_design_covers_scale_and_operational_topics() -> None:
    design = read_text("DESIGN.md")
    required_phrases = [
        "100 portals",
        "30,000 jobs",
        "Backpressure",
        "retry",
        "recovery",
        "monitoring",
        "secrets",
        "CI",
        "deployment",
    ]
    missing = [phrase for phrase in required_phrases if phrase.lower() not in design.lower()]

    assert missing == []


def test_readme_documents_concrete_new_portal_steps() -> None:
    readme = read_text("README.md")
    required_phrases = [
        "input_schema.py",
        "pages.py",
        "workflow.py",
        "runner.py",
        "BasePortalRunnerZX",
        "core/registry.py",
        "sample input",
        "e2e",
    ]
    missing = [phrase for phrase in required_phrases if phrase not in readme]

    assert missing == []


def test_ci_runs_lint_format_and_pytest_without_live_e2e() -> None:
    ci = read_text(".github/workflows/ci.yml")

    assert 'python-version: "3.11"' in ci
    assert 'cache: "pip"' in ci
    assert 'python -m pip install -e ".[dev]"' in ci
    assert "ruff check ." in ci
    assert "ruff format --check ." in ci
    assert "pytest" in ci
    assert "RUN_LIVE_E2E" not in ci
    assert "playwright install" not in ci


def test_docs_describe_storage_state_as_production_enhancement() -> None:
    readme = read_text("README.md")
    design = read_text("DESIGN.md")
    combined = f"{readme}\n{design}"

    required_phrases = [
        "storage_state",
        "disabled",
        "fall back to a fresh",
        "cookies/tokens",
        "per-account",
        "Sauce Demo",
    ]
    missing = [phrase for phrase in required_phrases if phrase.lower() not in combined.lower()]

    assert missing == []
    assert "must not be committed" in readme
    assert "never be classified" in design


def test_readme_documents_per_portal_timeout_overrides() -> None:
    readme = read_text("README.md")

    assert "DEFAULT_TIMEOUT_SECONDS" in readme
    assert "ORANGEHRM_TIMEOUT_SECONDS" in readme
    assert "SAUCEDEMO_TIMEOUT_SECONDS" in readme
    assert "Per-portal timeout overrides" in readme


def test_design_documents_timeout_scaling_strategy() -> None:
    design = read_text("DESIGN.md")

    assert "portal-aware" in design
    assert "ORANGEHRM_TIMEOUT_SECONDS" in design
    assert "SAUCEDEMO_TIMEOUT_SECONDS" in design
    assert "per-operation timeout groups" in design
    assert "P50/P95/P99" in design
    assert "shipped runtime keeps timeout behavior deterministic" in design


def _load_edge_case_payload():
    path = ROOT / "data" / "orangehrm_employees_edge_cases.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _extract_edge_case_records(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("employees", "items", "records"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    raise AssertionError("Unsupported OrangeHRM fixture shape")


def test_orangehrm_edge_case_fixture_exists() -> None:
    assert (ROOT / "data" / "orangehrm_employees_edge_cases.json").exists()


def test_orangehrm_edge_case_fixture_loads_without_error() -> None:
    records = load_employee_records(ROOT / "data" / "orangehrm_employees_edge_cases.json")

    assert records


def test_orangehrm_edge_case_fixture_contains_unicode_case() -> None:
    records = _extract_edge_case_records(_load_edge_case_payload())

    assert any(
        any(ord(char) > 127 for char in record.get("first_name", "") + record.get("last_name", ""))
        for record in records
    )


def test_orangehrm_edge_case_fixture_has_no_secret_like_values() -> None:
    payload = _load_edge_case_payload()
    serialized = json.dumps(payload, ensure_ascii=False).lower()

    for forbidden in ("password", "secret", "admin123", "secret_sauce", "token"):
        assert forbidden not in serialized


def test_readme_documents_generate_test_data() -> None:
    assert "generate_test_data.py" in read_text("README.md")


def test_design_mentions_synthetic_input_generation() -> None:
    assert "deterministic synthetic input generation" in read_text("DESIGN.md")
