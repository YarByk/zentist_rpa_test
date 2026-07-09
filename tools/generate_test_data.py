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

DEFAULT_REFERENCE_PATH = REPO_ROOT / "data" / "orangehrm_employees.json"
SAUCEDEMO_FIXED_MESSAGE = (
    "SauceDemo: fixed 6 accounts already covered by data/saucedemo_accounts.json. "
    "No generated file needed."
)


def _resolve_reference_path(reference_path: Path | None) -> Path:
    return reference_path if reference_path is not None else DEFAULT_REFERENCE_PATH


def load_reference_payload(reference_path: Path | None = None) -> object:
    path = _resolve_reference_path(reference_path)
    return json.loads(path.read_text(encoding="utf-8"))


def extract_orangehrm_records(payload: object) -> list[dict[str, Any]]:
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
    if isinstance(candidate, str):
        stripped = candidate.strip()
        if stripped and stripped not in values:
            values.append(stripped)


def _extract_reference_values_from_records(
    records: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
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
    payload = load_reference_payload(reference_path)
    records = extract_orangehrm_records(payload)
    return _extract_reference_values_from_records(records)


def _validate_count(count: int) -> None:
    if count <= 0:
        raise ValueError("count must be a positive integer")


def _record_width(count: int) -> int:
    return max(3, len(str(count)))


def _build_orangehrm_records(
    count: int,
    seed: int,
    job_titles: list[str],
    employment_statuses: list[str],
) -> list[dict[str, Any]]:
    _validate_count(count)
    width = _record_width(count)
    records: list[dict[str, Any]] = []

    for index in range(count):
        display_index = index + 1
        salary_amount = 40000 + (((seed + index * 37) % 161) * 1000)
        records.append(
            {
                "employee_key": f"generated-{display_index:0{width}d}",
                "first_name": f"ZentistBatch{display_index:0{width}d}",
                "last_name": "Generated",
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
    try:
        records = extract_orangehrm_records(payload)
        for record in records:
            parse_employee_record(record)
    except (InputValidationError, ValueError, TypeError) as exc:
        raise ValueError(f"generated record validation failed: {exc}") from exc


def write_json(payload: object, output_path: Path) -> Path:
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
    parser = argparse.ArgumentParser(description="Generate deterministic local test input data.")
    parser.add_argument("--portal", choices=["orangehrm", "all"], required=True)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--seed", type=int, default=42)
    return parser


def main(argv: list[str] | None = None) -> int:
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
