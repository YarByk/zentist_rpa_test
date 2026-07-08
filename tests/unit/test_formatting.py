import re
from pathlib import Path

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
