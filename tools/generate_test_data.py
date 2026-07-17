from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from portal_automation.portals.orangehrm.input_schema import (  # noqa: E402
    InputValidationError,
    parse_employee_record,
)

# -----------------------------------------------------------------------------
# This helper generates deterministic local fixture data for OrangeHRM.
# SauceDemo is intentionally not generated because the public demo exposes a
# fixed account set that is already represented in the repository data file.
# -----------------------------------------------------------------------------
DEFAULT_REFERENCE_PATH = REPO_ROOT / "data" / "orangehrm_employees.json"
SAUCEDEMO_FIXED_MESSAGE = (
    "SauceDemo: fixed 6 accounts already covered by data/saucedemo_accounts.json. "
    "No generated file needed."
)
DEMO_EMPLOYEE_NAMES = [
    ("Mia", "Carter"),
    ("Noah", "Reed"),
    ("Lena", "Brooks"),
    ("Ethan", "Price"),
    ("Ava", "Morgan"),
    ("Lucas", "Hayes"),
    ("Sofia", "Bennett"),
    ("Mason", "Cole"),
    ("Ella", "Foster"),
    ("Logan", "Ward"),
    ("Chloe", "Parker"),
    ("Owen", "Morris"),
    ("Nora", "Bell"),
    ("Caleb", "Rivera"),
    ("Ivy", "Hughes"),
    ("Henry", "Cooper"),
    ("Grace", "Bailey"),
    ("Leo", "Simmons"),
    ("Ruby", "Nelson"),
    ("Miles", "Bryant"),
    ("Emma", "Powell"),
    ("Jack", "Griffin"),
    ("Zoe", "Russell"),
    ("Finn", "Jenkins"),
    ("Lily", "Howard"),
    ("Theo", "Sanders"),
    ("Maya", "Perry"),
    ("Aria", "Ross"),
    ("Elijah", "Diaz"),
    ("Harper", "Wells"),
    ("Nathan", "Stone"),
    ("Violet", "Reyes"),
    ("Julian", "Fisher"),
    ("Hannah", "Palmer"),
    ("Wyatt", "Grant"),
    ("Layla", "Knight"),
    ("Sebastian", "West"),
    ("Stella", "Fox"),
    ("Isaac", "Bishop"),
    ("Claire", "Warren"),
    ("Adrian", "Spencer"),
    ("Lucy", "Porter"),
    ("Eli", "Murray"),
    ("Sarah", "Holmes"),
    ("Aaron", "Dixon"),
    ("Alice", "Walsh"),
    ("Dylan", "Holland"),
    ("Naomi", "Cross"),
    ("Thomas", "Ford"),
    ("Eva", "Gibson"),
    ("Ryan", "Harper"),
    ("Mila", "Newton"),
    ("Jason", "Burke"),
    ("Audrey", "Mason"),
    ("Cole", "Barrett"),
    ("Bella", "Fleming"),
    ("Max", "Lawson"),
    ("Hazel", "Barker"),
    ("Adam", "Caldwell"),
    ("Elena", "Sharp"),
]


def _resolve_reference_path(reference_path: Path | None) -> Path:
    # Allow callers to override the reference file while keeping a sensible default.
    """Resolve reference path.

    Args:
        reference_path: Value supplied by the test or fixture for `reference_path`.

    Returns:
        The helper result used by the test-data generation workflow.

    Raises:
        Exception: If input validation, JSON handling, or file access fails.
    """
    return reference_path if reference_path is not None else DEFAULT_REFERENCE_PATH


def load_reference_payload(reference_path: Path | None = None) -> object:
    # Read the reference JSON exactly as-is so we can preserve its outer shape later.
    """Load reference payload.

    Args:
        reference_path: Value supplied by the test or fixture for `reference_path`.

    Returns:
        The helper result used by the test-data generation workflow.

    Raises:
        Exception: If input validation, JSON handling, or file access fails.
    """
    path = _resolve_reference_path(reference_path)
    return json.loads(path.read_text(encoding="utf-8"))


def extract_orangehrm_records(payload: object) -> list[dict[str, Any]]:
    # Accept either a top-level list or a wrapper object with a known record key.
    """Extract orangehrm records.

    Args:
        payload: Value supplied by the test or fixture for `payload`.

    Returns:
        The helper result used by the test-data generation workflow.

    Raises:
        Exception: If input validation, JSON handling, or file access fails.
    """
    if isinstance(payload, list):
        records = payload
    elif isinstance(payload, dict):
        records = None
        for key in ("employees", "items", "records"):
            value = payload.get(key)
            if isinstance(value, list):
                records = value
                break
        if records is None:
            raise ValueError("unsupported OrangeHRM payload shape")
    else:
        raise ValueError("unsupported OrangeHRM payload shape")

    if not all(isinstance(record, dict) for record in records):
        raise ValueError("OrangeHRM records must be objects")
    return list(records)


def build_payload_like_reference(
    reference_payload: object,
    records: list[dict[str, Any]],
) -> object:
    # Rebuild the generated payload using the same top-level structure as the source fixture.
    """Build payload like reference.

    Args:
        reference_payload: Value supplied by the test or fixture for `reference_payload`.
        records: Value supplied by the test or fixture for `records`.

    Returns:
        The helper result used by the test-data generation workflow.

    Raises:
        Exception: If input validation, JSON handling, or file access fails.
    """
    if isinstance(reference_payload, list):
        return list(records)
    if isinstance(reference_payload, dict):
        for key in ("employees", "items", "records"):
            value = reference_payload.get(key)
            if isinstance(value, list):
                payload = dict(reference_payload)
                payload[key] = list(records)
                return payload
    raise ValueError("unsupported OrangeHRM payload shape")


def _append_unique(values: list[str], candidate: object) -> None:
    """Append unique.

    Args:
        values: Value supplied by the test or fixture for `values`.
        candidate: Value supplied by the test or fixture for `candidate`.

    Returns:
        The helper result used by the test-data generation workflow.

    Raises:
        Exception: If input validation, JSON handling, or file access fails.
    """
    if isinstance(candidate, str):
        stripped = candidate.strip()
        if stripped and stripped not in values:
            values.append(stripped)


def _extract_reference_values_from_records(
    records: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    # Collect reusable domain values so generated rows still look realistic.
    """Extract reference values from records.

    Args:
        records: Value supplied by the test or fixture for `records`.

    Returns:
        The helper result used by the test-data generation workflow.

    Raises:
        Exception: If input validation, JSON handling, or file access fails.
    """
    job_titles: list[str] = []
    employment_statuses: list[str] = []

    for record in records:
        _append_unique(job_titles, record.get("job_title"))
        _append_unique(employment_statuses, record.get("employment_status"))

    if not job_titles:
        raise ValueError("no job_title values found in OrangeHRM reference data")
    if not employment_statuses:
        raise ValueError("no employment_status values found in OrangeHRM reference data")
    return job_titles, employment_statuses


def load_reference_values(reference_path: Path | None = None) -> tuple[list[str], list[str]]:
    """Load reference values.

    Args:
        reference_path: Value supplied by the test or fixture for `reference_path`.

    Returns:
        The helper result used by the test-data generation workflow.

    Raises:
        Exception: If input validation, JSON handling, or file access fails.
    """
    payload = load_reference_payload(reference_path)
    records = extract_orangehrm_records(payload)
    return _extract_reference_values_from_records(records)


def _validate_count(count: int) -> None:
    # Reject invalid counts early before generating any fixture content.
    """Validate count.

    Args:
        count: Value supplied by the test or fixture for `count`.

    Returns:
        The helper result used by the test-data generation workflow.

    Raises:
        Exception: If input validation, JSON handling, or file access fails.
    """
    if count <= 0:
        raise ValueError("count must be a positive integer")


def _record_width(count: int) -> int:
    """Record width.

    Args:
        count: Value supplied by the test or fixture for `count`.

    Returns:
        The helper result used by the test-data generation workflow.

    Raises:
        Exception: If input validation, JSON handling, or file access fails.
    """
    return max(3, len(str(count)))


def _name_for_record(seed: int, index: int) -> tuple[str, str]:
    """Return a deterministic human-readable name for a generated record.

    Args:
        seed: Generation seed.
        index: Zero-based record index.

    Returns:
        First and last name.
    """
    return DEMO_EMPLOYEE_NAMES[(seed + index) % len(DEMO_EMPLOYEE_NAMES)]


def _portal_employee_id(seed: int, display_index: int) -> str:
    """Return a short OrangeHRM employee id that fits the 10-character portal limit.

    Args:
        seed: Generation seed.
        display_index: One-based record index.

    Returns:
        Stable short employee id.
    """
    return f"g{seed % 1000:03d}{display_index:03d}"


def _build_orangehrm_records(
    count: int,
    seed: int,
    job_titles: list[str],
    employment_statuses: list[str],
) -> list[dict[str, Any]]:
    # -------------------------------------------------------------------------
    # Build a deterministic batch of employee-like records.
    # The seed influences salary progression, while titles/statuses cycle through
    # reference values to keep the output stable and varied at the same time.
    # -------------------------------------------------------------------------
    """Build orangehrm records.

    Args:
        count: Value supplied by the test or fixture for `count`.
        seed: Value supplied by the test or fixture for `seed`.
        job_titles: Value supplied by the test or fixture for `job_titles`.
        employment_statuses: Value supplied by the test or fixture for `employment_statuses`.

    Returns:
        The helper result used by the test-data generation workflow.

    Raises:
        Exception: If input validation, JSON handling, or file access fails.
    """
    _validate_count(count)
    width = _record_width(count)
    records: list[dict[str, Any]] = []

    for index in range(count):
        display_index = index + 1
        first_name, last_name = _name_for_record(seed, index)
        salary_amount = 40000 + (((seed + index * 37) % 161) * 1000)
        records.append(
            {
                "employee_key": f"generated-{seed}-{display_index:0{width}d}",
                "employee_id": _portal_employee_id(seed, display_index),
                "first_name": first_name,
                "last_name": last_name,
                "job_title": job_titles[index % len(job_titles)],
                "employment_status": employment_statuses[index % len(employment_statuses)],
                "salary": {
                    "amount": f"{salary_amount} USD",
                    "frequency": "Annual",
                    "details": f"Generated record {display_index} seed {seed}",
                },
            }
        )
    return records


def generate_orangehrm_records(
    count: int,
    seed: int = 42,
    reference_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Generate orangehrm records.

    Args:
        count: Value supplied by the test or fixture for `count`.
        seed: Value supplied by the test or fixture for `seed`.
        reference_path: Value supplied by the test or fixture for `reference_path`.

    Returns:
        The helper result used by the test-data generation workflow.

    Raises:
        Exception: If input validation, JSON handling, or file access fails.
    """
    job_titles, employment_statuses = load_reference_values(reference_path)
    return _build_orangehrm_records(
        count=count,
        seed=seed,
        job_titles=job_titles,
        employment_statuses=employment_statuses,
    )


def generate_orangehrm_payload(
    count: int,
    seed: int = 42,
    reference_path: Path | None = None,
) -> object:
    """Generate orangehrm payload.

    Args:
        count: Value supplied by the test or fixture for `count`.
        seed: Value supplied by the test or fixture for `seed`.
        reference_path: Value supplied by the test or fixture for `reference_path`.

    Returns:
        The helper result used by the test-data generation workflow.

    Raises:
        Exception: If input validation, JSON handling, or file access fails.
    """
    reference_payload = load_reference_payload(reference_path)
    reference_records = extract_orangehrm_records(reference_payload)
    job_titles, employment_statuses = _extract_reference_values_from_records(reference_records)
    records = _build_orangehrm_records(
        count=count,
        seed=seed,
        job_titles=job_titles,
        employment_statuses=employment_statuses,
    )
    return build_payload_like_reference(reference_payload, records)


def validate_orangehrm_payload(payload: object) -> None:
    # Run the same schema validation used by the application itself.
    """Validate orangehrm payload.

    Args:
        payload: Value supplied by the test or fixture for `payload`.

    Returns:
        The helper result used by the test-data generation workflow.

    Raises:
        Exception: If input validation, JSON handling, or file access fails.
    """
    try:
        records = extract_orangehrm_records(payload)
        for record in records:
            parse_employee_record(record)
    except (InputValidationError, ValueError, TypeError) as exc:
        raise ValueError(f"generated record validation failed: {exc}") from exc


def write_json(payload: object, output_path: Path) -> Path:
    # Write human-readable JSON so generated fixtures can be inspected and diffed easily.
    """Write json.

    Args:
        payload: Value supplied by the test or fixture for `payload`.
        output_path: Value supplied by the test or fixture for `output_path`.

    Returns:
        The helper result used by the test-data generation workflow.

    Raises:
        Exception: If input validation, JSON handling, or file access fails.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return output_path


def build_output_path(
    portal: str,
    count: int,
    output: Path | None,
    output_dir: Path | None,
) -> Path:
    # Normalize CLI output arguments into one concrete destination path.
    """Build output path.

    Args:
        portal: Value supplied by the test or fixture for `portal`.
        count: Value supplied by the test or fixture for `count`.
        output: Value supplied by the test or fixture for `output`.
        output_dir: Value supplied by the test or fixture for `output_dir`.

    Returns:
        The helper result used by the test-data generation workflow.

    Raises:
        Exception: If input validation, JSON handling, or file access fails.
    """
    if portal == "orangehrm":
        if output_dir is not None:
            return output_dir / f"orangehrm_employees_{count}.json"
        if output is not None:
            return output
        raise ValueError("specify --output or --output-dir")
    if portal == "all":
        if output_dir is None:
            raise ValueError("specify --output-dir for --portal all")
        return output_dir / f"orangehrm_employees_{count}.json"
    raise ValueError(f"unsupported portal: {portal}")


def _build_parser() -> argparse.ArgumentParser:
    # Keep the CLI intentionally small because this script serves one focused job.
    """Build parser.

    Returns:
        The helper result used by the test-data generation workflow.

    Raises:
        Exception: If input validation, JSON handling, or file access fails.
    """
    parser = argparse.ArgumentParser(description="Generate deterministic local test input data.")
    parser.add_argument("--portal", choices=["orangehrm", "all"], required=True)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--seed", type=int, default=42)
    return parser


def main(argv: list[str] | None = None) -> int:
    # -------------------------------------------------------------
    # CLI flow:
    # 1. Resolve the output path.
    # 2. Generate deterministic payload data.
    # 3. Validate it using production parsing rules.
    # 4. Write the JSON file and print a helpful summary.
    # -------------------------------------------------------------
    """Main.

    Args:
        argv: Value supplied by the test or fixture for `argv`.

    Returns:
        Process exit code for the command-line entry point.

    Raises:
        Exception: If argument parsing, validation, or file writing fails unexpectedly.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        output_path = build_output_path(
            portal=args.portal,
            count=args.count,
            output=args.output,
            output_dir=args.output_dir,
        )
        payload = generate_orangehrm_payload(count=args.count, seed=args.seed)
        validate_orangehrm_payload(payload)
        write_json(payload, output_path)
        if args.portal == "all":
            print(SAUCEDEMO_FIXED_MESSAGE)
        print(f"Wrote OrangeHRM input: {output_path}")
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
