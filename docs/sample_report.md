# Sample Portal Automation Report

This is a sanitized static example for reviewers. It is not generated from a real
customer run and contains no real secrets, private employee data, or live portal
credentials.

## Run summary

| Field | Example value |
| --- | --- |
| Run ID | `sample-run-2026-06-29` |
| Business date | `2026-06-29` |
| Overall status | `partial_success` |
| Processed items | `8` |
| Successful items | `6` |
| Failed items | `2` |
| Skipped items | `0` |

## Portal breakdown

| Portal | Operation | Total | Success | Failed | Notes |
| --- | --- | ---: | ---: | ---: | --- |
| `orangehrm` | `sync_employee_state` | 2 | 1 | 1 | Employee sync, job status, salary attachment check/upload |
| `saucedemo` | `checkout` | 6 | 5 | 1 | All six SauceDemo demo accounts processed independently |

## Per-item status examples

| Portal | Item key | Operation | Status | reason_code | Attempts | Artifact path |
| --- | --- | --- | --- | --- | ---: | --- |
| `orangehrm` | `employee-001` | `sync_employee_state` | `success` |  | 1 | `artifacts/runs/sample-run/generated_documents/salary_employee-001_2026-06-29.txt` |
| `orangehrm` | `employee-ambiguous` | `sync_employee_state` | `failed` | `EMPLOYEE_MATCH_AMBIGUOUS` | 1 |  |
| `saucedemo` | `standard_user` | `checkout` | `success` |  | 1 |  |
| `saucedemo` | `locked_out_user` | `checkout` | `failed` | `LOCKED_OUT` | 1 |  |
| `saucedemo` | `problem_user` | `checkout` | `success` |  | 1 |  |
| `saucedemo` | `performance_glitch_user` | `checkout` | `success` |  | 1 |  |
| `saucedemo` | `error_user` | `checkout` | `success` |  | 1 |  |
| `saucedemo` | `visual_user` | `checkout` | `success` |  | 1 |  |

## reason_code examples

| Reason code | Meaning |
| --- | --- |
| `LOCKED_OUT` | SauceDemo returned a real login error for the locked-out demo account. |
| `EMPLOYEE_MATCH_AMBIGUOUS` | OrangeHRM search returned multiple visible matching employee rows. |
| `EMPLOYEE_NOT_FOUND` | Employee could not be located after search or after attempted creation. |
| `CHECKOUT_FAILED` | SauceDemo checkout or confirmation flow failed for that account. |
| `PORTAL_TIMEOUT` | A portal action timed out and was classified as retryable where appropriate. |

## Runtime artifact locations

For a real run, artifacts are written under:

```text
artifacts/runs/<run_id>/
```

Common files:

```text
artifacts/runs/<run_id>/report.txt
artifacts/runs/<run_id>/email_report.txt
artifacts/runs/<run_id>/events.jsonl
artifacts/runs/<run_id>/metrics.json
artifacts/runs/<run_id>/generated_documents/
artifacts/runs/<run_id>/screenshots/
artifacts/runs/<run_id>/traces/
```

`email_report.txt` is produced only when the email backend is `dry_run` and the portal
finalizer sends a report. With the `smtp` backend, the report is sent through SMTP and no
dry-run email artifact is expected.

Failure diagnostics, when enabled, are stored as:

```text
artifacts/runs/<run_id>/screenshots/<portal>_<item_key>_failure.png
artifacts/runs/<run_id>/traces/<portal>_<item_key>_trace.zip
```

Generated runtime artifacts are ignored by git. This sample document is intentionally static
and sanitized so it can be committed safely.
