import importlib.util
import json
import pathlib

import pytest

_TOOLS_DIR = pathlib.Path(__file__).parents[2] / "tools"
_DATA_DIR = pathlib.Path(__file__).parents[2] / "data"
REAL_DATA_PATH = _DATA_DIR / "orangehrm_employees.json"


def _load_generator():
    """Load generator.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    spec = importlib.util.spec_from_file_location(
        "generate_test_data",
        _TOOLS_DIR / "generate_test_data.py",
    )
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_gen = _load_generator()

generate_orangehrm_records = _gen.generate_orangehrm_records
generate_orangehrm_payload = _gen.generate_orangehrm_payload
validate_orangehrm_payload = _gen.validate_orangehrm_payload
load_reference_values = _gen.load_reference_values
build_output_path = _gen.build_output_path
write_json = _gen.write_json
main = _gen.main


def _salary_amounts(records):
    """Salary amounts.
    
    Args:
        records: Value supplied by the test or fixture for `records`.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    return [record["salary"]["amount"] for record in records]


def test_generate_orangehrm_records_creates_requested_count() -> None:
    """Verify that generate orangehrm records creates requested count.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    records = generate_orangehrm_records(count=5, seed=42, reference_path=REAL_DATA_PATH)

    assert len(records) == 5


def test_generate_orangehrm_payload_validates_against_schema() -> None:
    """Verify that generate orangehrm payload validates against schema.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    payload = generate_orangehrm_payload(count=3, seed=42, reference_path=REAL_DATA_PATH)

    validate_orangehrm_payload(payload)


def test_load_reference_values_returns_nonempty_lists() -> None:
    """Verify that load reference values returns nonempty lists.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    job_titles, statuses = load_reference_values(REAL_DATA_PATH)

    assert job_titles
    assert statuses


def test_generate_orangehrm_employee_keys_are_unique() -> None:
    """Verify that generate orangehrm employee keys are unique.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    records = generate_orangehrm_records(count=10, seed=42, reference_path=REAL_DATA_PATH)
    keys = [record["employee_key"] for record in records]

    assert len(keys) == len(set(keys))


def test_generate_orangehrm_employee_ids_fit_portal_limit() -> None:
    """Verify that generated OrangeHRM employee ids fit the portal limit."""
    records = generate_orangehrm_records(count=10, seed=42, reference_path=REAL_DATA_PATH)
    ids = [record["employee_id"] for record in records]

    assert len(ids) == len(set(ids))
    assert all(len(employee_id) <= 10 for employee_id in ids)


def test_generate_orangehrm_uses_human_readable_name_pool() -> None:
    """Verify that generated employees use human-readable demo names."""
    records = generate_orangehrm_records(count=3, seed=42, reference_path=REAL_DATA_PATH)

    assert [record["first_name"] for record in records] == ["Eli", "Sarah", "Aaron"]
    assert [record["last_name"] for record in records] == ["Murray", "Holmes", "Dixon"]
    assert all(not record["first_name"].startswith("ZentistBatch") for record in records)


def test_generate_orangehrm_seed_changes_employee_keys_and_ids() -> None:
    """Verify that fresh demo seeds create new item keys and portal ids."""
    first = generate_orangehrm_records(count=3, seed=42, reference_path=REAL_DATA_PATH)
    second = generate_orangehrm_records(count=3, seed=43, reference_path=REAL_DATA_PATH)

    assert [record["employee_key"] for record in first] != [
        record["employee_key"] for record in second
    ]
    assert [record["employee_id"] for record in first] != [
        record["employee_id"] for record in second
    ]


def test_generate_orangehrm_is_deterministic_for_same_seed() -> None:
    """Verify that generate orangehrm is deterministic for same seed.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    first = generate_orangehrm_records(count=5, seed=42, reference_path=REAL_DATA_PATH)
    second = generate_orangehrm_records(count=5, seed=42, reference_path=REAL_DATA_PATH)

    assert first == second


def test_generate_orangehrm_seed_changes_salary_sequence() -> None:
    """Verify that generate orangehrm seed changes salary sequence.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    first = generate_orangehrm_records(count=5, seed=42, reference_path=REAL_DATA_PATH)
    second = generate_orangehrm_records(count=5, seed=99, reference_path=REAL_DATA_PATH)

    assert _salary_amounts(first) != _salary_amounts(second)


def test_generate_orangehrm_rejects_zero_count() -> None:
    """Verify that generate orangehrm rejects zero count.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    with pytest.raises(ValueError, match="count must be a positive integer"):
        generate_orangehrm_records(count=0, seed=42, reference_path=REAL_DATA_PATH)


def test_generate_orangehrm_rejects_negative_count() -> None:
    """Verify that generate orangehrm rejects negative count.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    with pytest.raises(ValueError, match="count must be a positive integer"):
        generate_orangehrm_records(count=-1, seed=42, reference_path=REAL_DATA_PATH)


def test_generated_records_do_not_contain_secret_like_values() -> None:
    """Verify that generated records do not contain secret like values.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    records = generate_orangehrm_records(count=5, seed=42, reference_path=REAL_DATA_PATH)
    serialized = json.dumps(records, ensure_ascii=False).lower()

    for forbidden in ("password", "secret", "admin123", "secret_sauce", "token"):
        assert forbidden not in serialized


def test_build_output_path_orangehrm_prefers_output_dir(tmp_path) -> None:
    """Verify that build output path orangehrm prefers output dir.
    
    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    output = tmp_path / "explicit.json"
    output_dir = tmp_path / "generated"

    path = build_output_path(
        portal="orangehrm",
        count=7,
        output=output,
        output_dir=output_dir,
    )

    assert path == output_dir / "orangehrm_employees_7.json"


def test_build_output_path_orangehrm_uses_output_when_no_output_dir(tmp_path) -> None:
    """Verify that build output path orangehrm uses output when no output dir.
    
    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    output = tmp_path / "explicit.json"

    path = build_output_path(portal="orangehrm", count=7, output=output, output_dir=None)

    assert path == output


def test_build_output_path_all_requires_output_dir() -> None:
    """Verify that build output path all requires output dir.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    with pytest.raises(ValueError, match="specify --output-dir for --portal all"):
        build_output_path(portal="all", count=5, output=None, output_dir=None)


def test_write_json_creates_parent_directory_and_trailing_newline(tmp_path) -> None:
    """Verify that write json creates parent directory and trailing newline.
    
    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    path = write_json({"test": 1}, tmp_path / "sub" / "out.json")

    assert path.exists()
    assert path.read_text(encoding="utf-8").endswith("\n")


def test_portal_all_generates_only_orangehrm_file(capsys, tmp_path) -> None:
    """Verify that portal all generates only orangehrm file.
    
    Args:
        capsys: Value supplied by the test or fixture for `capsys`.
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    result = main(["--portal", "all", "--count", "5", "--output-dir", str(tmp_path)])

    assert result == 0
    assert (tmp_path / "orangehrm_employees_5.json").exists()
    assert not list(tmp_path.glob("saucedemo*.json"))
    assert "SauceDemo: fixed 6 accounts" in capsys.readouterr().out


def test_cli_output_dir_uses_expected_filename(tmp_path) -> None:
    """Verify that cli output dir uses expected filename.
    
    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    result = main(["--portal", "orangehrm", "--count", "7", "--output-dir", str(tmp_path)])

    assert result == 0
    assert (tmp_path / "orangehrm_employees_7.json").exists()


def test_main_uses_explicit_output_path(tmp_path) -> None:
    """Verify that main uses explicit output path.
    
    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    output = tmp_path / "custom_orangehrm.json"

    result = main(["--portal", "orangehrm", "--count", "3", "--output", str(output)])

    assert result == 0
    assert output.exists()
    assert not (tmp_path / "orangehrm_employees_3.json").exists()


def test_main_rejects_zero_count(capsys, tmp_path) -> None:
    """Verify that main rejects zero count.
    
    Args:
        capsys: Value supplied by the test or fixture for `capsys`.
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    result = main(["--portal", "orangehrm", "--count", "0", "--output-dir", str(tmp_path)])

    assert result == 1
    assert "count must be a positive integer" in capsys.readouterr().err
