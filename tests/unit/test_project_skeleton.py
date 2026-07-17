import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read_text(relative_path: str) -> str:
    """Read text.

    Args:
        relative_path: Value supplied by the test or fixture for `relative_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_readme_first_line_contains_schema_marker() -> None:
    """Verify that readme first line contains schema marker.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    first_line = read_text("README.md").splitlines()[0]

    assert first_line == "<!-- schema-ref:zentist-r7 -->"


def test_design_contains_required_first_diagram_title() -> None:
    """Verify that design contains required first diagram title.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    design = read_text("DESIGN.md")

    assert "### Figure ZQ9" in design


def test_input_json_files_are_valid() -> None:
    """Verify that input json files are valid.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    for relative_path in ("data/orangehrm_employees.json", "data/saucedemo_accounts.json"):
        parsed = json.loads(read_text(relative_path))

        assert isinstance(parsed, list)


def test_forbidden_logging_module_does_not_exist() -> None:
    """Verify that forbidden logging module does not exist.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    assert not (ROOT / "src/portal_automation/core/logging.py").exists()


def test_env_example_does_not_contain_demo_passwords() -> None:
    """Verify that env example does not contain demo passwords.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    env_example = read_text(".env.example")

    assert "secret_sauce" not in env_example
    assert "admin123" not in env_example


def test_live_demo_headed_script_runs_expected_helpers_in_order() -> None:
    """Verify that the PowerShell live demo orchestrator runs the expected headed helpers.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the script stops loading env first or changes helper order.
    """
    script = read_text("tools/run_live_demo_headed.ps1")
    common = read_text("tools/live_demo_common.ps1")

    env_load = script.index("Import-LiveDemoEnvironment -EnvScript $envScript")
    orange_helper = script.index("debug_orangehrm_demo_playwright_headed.py")
    sauce_helper = script.index("debug_saucedemo_playwright_headed.py")
    orange_call = script.index('-Title "OrangeHRM demo Playwright headed"')
    sauce_call = script.index('-Title "Sauce Demo Playwright headed"')

    assert env_load < orange_call < sauce_call
    assert orange_helper < sauce_helper
    assert 'SetEnvironmentVariable($name, $value, "Process")' in common


def test_saucedemo_headed_script_runs_only_saucedemo_helper() -> None:
    """Verify that the Sauce Demo-only PowerShell wrapper loads env and runs one helper.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the wrapper stops loading env or starts OrangeHRM work.
    """
    script = read_text("tools/run_saucedemo_headed.ps1")

    env_load = script.index("Import-LiveDemoEnvironment -EnvScript $envScript")
    sauce_helper = script.index("debug_saucedemo_playwright_headed.py")
    sauce_call = script.index('-Title "Sauce Demo Playwright headed"')

    assert env_load < sauce_call
    assert sauce_helper < sauce_call
    assert "debug_orangehrm" not in script


def test_orangehrm_headed_script_runs_only_orangehrm_helper() -> None:
    """Verify that the OrangeHRM-only PowerShell wrapper loads env and runs one helper.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the wrapper stops loading env or starts Sauce Demo work.
    """
    script = read_text("tools/run_orangehrm_headed.ps1")

    env_load = script.index("Import-LiveDemoEnvironment -EnvScript $envScript")
    orange_helper = script.index("debug_orangehrm_demo_playwright_headed.py")
    orange_call = script.index('-Title "OrangeHRM demo Playwright headed"')

    assert env_load < orange_call
    assert orange_helper < orange_call
    assert "debug_saucedemo" not in script


def test_live_demo_wrappers_report_expected_setup_problems_without_throw() -> None:
    """Verify that live demo wrappers use operator-friendly setup diagnostics.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If wrappers regress to PowerShell exceptions for expected setup problems.
    """
    wrapper_paths = (
        "tools/run_live_demo_headed.ps1",
        "tools/run_orangehrm_headed.ps1",
        "tools/run_saucedemo_headed.ps1",
    )
    wrappers = "\n".join(read_text(path) for path in wrapper_paths)
    common = read_text("tools/live_demo_common.ps1")

    assert "throw " not in wrappers.lower()
    assert "Live environment file was not found" in common
    assert "Could not read the live environment file" in common
    assert "Could not load the live environment file" in common
    assert "Could not parse the live environment file" in common
    assert "password is empty or not visible" in common
    assert "invalid credentials" in common
    deprecated_launcher_name = "Visual" + " Studio"
    assert deprecated_launcher_name not in wrappers
    assert deprecated_launcher_name not in common


def test_main_entrypoint_exists() -> None:
    """Verify that main entrypoint exists.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    assert (ROOT / "src/portal_automation/__main__.py").is_file()


def test_only_package_init_files_exist_under_runtime_packages() -> None:
    """Verify that only package init files exist under runtime packages.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    allowed_files = {
        "src/portal_automation/__main__.py",
        "src/portal_automation/core/__init__.py",
        "src/portal_automation/core/artifact_store.py",
        "src/portal_automation/core/browser.py",
        "src/portal_automation/core/config.py",
        "src/portal_automation/core/document_generator.py",
        "src/portal_automation/core/email_connector.py",
        "src/portal_automation/core/models.py",
        "src/portal_automation/core/observability.py",
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
