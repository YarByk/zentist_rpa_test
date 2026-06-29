import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_readme_first_line_contains_schema_marker() -> None:
    first_line = read_text("README.md").splitlines()[0]

    assert first_line == "<!-- schema-ref:zentist-r7 -->"


def test_design_contains_required_first_diagram_title() -> None:
    design = read_text("DESIGN.md")

    assert "### Figure ZQ9" in design


def test_input_json_files_are_valid() -> None:
    for relative_path in ("data/orangehrm_employees.json", "data/saucedemo_accounts.json"):
        parsed = json.loads(read_text(relative_path))

        assert isinstance(parsed, list)


def test_forbidden_logging_module_does_not_exist() -> None:
    assert not (ROOT / "src/portal_automation/core/logging.py").exists()


def test_env_example_does_not_contain_demo_passwords() -> None:
    env_example = read_text(".env.example")

    assert "secret_sauce" not in env_example
    assert "admin123" not in env_example


def test_main_entrypoint_exists() -> None:
    assert (ROOT / "src/portal_automation/__main__.py").is_file()


def test_only_package_init_files_exist_under_runtime_packages() -> None:
    allowed_files = {
        "src/portal_automation/__main__.py",
        "src/portal_automation/core/__init__.py",
        "src/portal_automation/core/artifact_store.py",
        "src/portal_automation/core/config.py",
        "src/portal_automation/core/document_generator.py",
        "src/portal_automation/core/email_connector.py",
        "src/portal_automation/core/models.py",
        "src/portal_automation/core/persistence.py",
        "src/portal_automation/core/reporting.py",
        "src/portal_automation/core/registry.py",
        "src/portal_automation/core/retries.py",
        "src/portal_automation/core/runner.py",
        "src/portal_automation/core/secrets.py",
        "src/portal_automation/portals/__init__.py",
        "src/portal_automation/portals/orangehrm/__init__.py",
        "src/portal_automation/portals/orangehrm/input_schema.py",
        "src/portal_automation/portals/orangehrm/pages.py",
        "src/portal_automation/portals/orangehrm/runner.py",
        "src/portal_automation/portals/orangehrm/workflow.py",
        "src/portal_automation/portals/saucedemo/__init__.py",
        "src/portal_automation/portals/saucedemo/input_schema.py",
        "src/portal_automation/portals/saucedemo/pages.py",
        "src/portal_automation/portals/saucedemo/runner.py",
        "src/portal_automation/portals/saucedemo/workflow.py",
    }
    package_roots = [
        ROOT / "src/portal_automation/core",
        ROOT / "src/portal_automation/portals",
        ROOT / "src/portal_automation/portals/orangehrm",
        ROOT / "src/portal_automation/portals/saucedemo",
    ]
    unexpected_files = sorted(
        path.relative_to(ROOT).as_posix()
        for package_root in package_roots
        for path in package_root.iterdir()
        if path.is_file() and path.relative_to(ROOT).as_posix() not in allowed_files
    )

    assert unexpected_files == []
