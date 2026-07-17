<!-- schema-ref:zentist-r7 -->

# Portal Automation Platform Demo

This repository implements a production-oriented portal automation platform demo for the
Zentist RPA Lead take-home assignment. It is structured around shared execution,
idempotent persistence, per-item failure isolation, artifacts, reports, and portal-specific
workflows.

The implemented portal keys are:

- `orangehrm`
- `saucedemo`

Both portal runners inherit from `BasePortalRunnerZX`. The shared `run()` lifecycle stays in
the base class; portal runners implement hooks only.

## Setup

Python `>=3.11` is required.

```bash
python -m pip install -e ".[dev]"
python -m playwright install chromium
ruff check .
ruff format --check .
pytest
```

The default `pytest` configuration runs `tests/unit` and `tests/integration`. Live browser
e2e tests belong under `tests/e2e` and are excluded from the default test path.

`python -m playwright install chromium` is required for non-dry-run CLI invocations and for
opt-in live e2e tests. Dry-run and the default test suite do not start a browser and do not
require the Chromium binary.

## One-Click Live Demo On Windows

For the visible browser demo, use the PowerShell orchestrator from the repository root:

```powershell
.\tools\run_live_demo_headed.ps1
```

To run only the faster Sauce Demo headed flow:

```powershell
.\tools\run_saucedemo_headed.ps1
```

To run only the OrangeHRM headed demo flow:

```powershell
.\tools\run_orangehrm_headed.ps1
```

The combined script loads `tools\set_live_env.local.ps1` first, then runs the two headed
Playwright helpers in order:

1. OrangeHRM demo Playwright headed: generates a fresh three-employee input file, opens
   Chromium, and runs the OrangeHRM workflow.
2. Sauce Demo Playwright headed: opens Chromium and runs all Sauce Demo accounts from
   `data\saucedemo_accounts.json`.

Typical local timing: `OrangeHRM demo Playwright headed` can take about 10 minutes, while
`Sauce Demo Playwright headed` usually takes about 1 minute.

Before using it, copy `tools\set_live_env.example.ps1` to `tools\set_live_env.local.ps1` and
fill the live demo credentials. The local env file is intentionally ignored by git. The headed
helpers keep final browser result screens visible and store persistent browser profiles under
`artifacts\browser_profiles\orangehrm` and `artifacts\browser_profiles\saucedemo`.

The individual PowerShell wrappers are useful when you want to show or debug one portal at a
time. The combined PowerShell orchestrator is the shortest path when you want to show both
demos back-to-back.

## Configuration

`.env.example` documents the supported environment variables. The code reads environment
variables directly through `AppConfig.from_env()`; it does not load `.env` files by itself.

Important variables and defaults:

| Variable | Default / meaning |
|---|---|
| `DB_PATH` | `artifacts/portal_automation.sqlite` |
| `ARTIFACTS_DIR` | `artifacts` |
| `BUSINESS_DATE` | optional `YYYY-MM-DD`; defaults to today when unset |
| `HEADLESS` | `true` |
| `DEFAULT_TIMEOUT_SECONDS` | `30`; global fallback for Playwright waits |
| `ORANGEHRM_TIMEOUT_SECONDS` | optional; overrides `DEFAULT_TIMEOUT_SECONDS` for OrangeHRM-style slower portals |
| `SAUCEDEMO_TIMEOUT_SECONDS` | optional; overrides `DEFAULT_TIMEOUT_SECONDS` for Sauce Demo-style faster portals |
| `MAX_RETRIES` | `2` |
| `STALE_ITEM_TIMEOUT_SECONDS` | `300` |
| `PLAYWRIGHT_TRACE_ON_FAILURE` | `true`; save Playwright `trace.zip` when a non-dry-run item fails |
| `PLAYWRIGHT_SCREENSHOT_ON_FAILURE` | `true`; save `failure.png` when a non-dry-run item fails |
| `ORANGEHRM_BASE_URL` | `https://opensource-demo.orangehrmlive.com` |
| `ORANGEHRM_USERNAME` | `Admin` |
| `ORANGEHRM_PASSWORD` | required for real OrangeHRM runs |
| `ORANGEHRM_INPUT_PATH` | `data/orangehrm_employees.json` |
| `SAUCEDEMO_BASE_URL` | `https://www.saucedemo.com` |
| `SAUCEDEMO_PASSWORD` | required for real Sauce Demo runs |
| `SAUCEDEMO_INPUT_PATH` | `data/saucedemo_accounts.json` |
| `EMAIL_BACKEND` | `dry_run` |
| `REPORT_EMAIL_TO` | optional recipient address |
| `SMTP_HOST`, `SMTP_PORT` (`587`), `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_TO`, `SMTP_USE_TLS` | used when `EMAIL_BACKEND=smtp` |

Per-portal timeout overrides keep fast portals from waiting on a slow global timeout while
still giving slower portals enough time. Use larger values for slow portals and smaller values
for fast portals; unset portal overrides fall back to `DEFAULT_TIMEOUT_SECONDS`.

## CLI Usage

```bash
python -m portal_automation --help
python -m portal_automation all --dry-run
python -m portal_automation orangehrm --dry-run
python -m portal_automation saucedemo --dry-run
python -m portal_automation recover --business-date 2026-06-29 --dry-run
```

Useful options:

- `--business-date YYYY-MM-DD`
- `--input <path>` for one portal only
- `--headless true|false`
- `--email-backend dry_run|smtp`

`all` runs the registered portals sequentially. Non-dry-run examples require the relevant
password variables and Playwright Chromium:

```bash
export ORANGEHRM_PASSWORD="<demo-password>"
python -m portal_automation orangehrm --business-date 2026-06-29

export SAUCEDEMO_PASSWORD="<demo-password>"
python -m portal_automation saucedemo --business-date 2026-06-29
```

Use placeholder values in documentation and local shell history hygiene as appropriate; do not
commit real secrets.

## Dry Run

`python -m portal_automation all --dry-run` is the safe non-browser smoke path. It creates
run rows and report artifacts while skipping portal preflight, item processing, browser/page
objects, portal workflows, and live network portal work.

Dry-run still loads and validates input files. Invalid input can fail before any portal work
is attempted.

## Outputs

SQLite state is stored at `DB_PATH`. Runtime artifacts are stored under:

```text
ARTIFACTS_DIR/runs/<run_id>/
```

Important artifact paths:

- `report.txt` - generated by portal finalizers through `ReportGenerator`.
- `email_report.txt` - generated only when `EmailConnector.send_report()` is explicitly
  called with the `dry_run` backend.
- `generated_documents/` - salary document output for OrangeHRM workflows.
- `screenshots/` and `traces/` - failure diagnostics for non-dry-run Playwright
  execution. When enabled, failed items create `<portal>_<item>_failure.png` and
  `<portal>_<item>_trace.zip` under the current run directory. Open `trace.zip` with
  Playwright Trace Viewer, for example `python -m playwright show-trace <path-to-trace.zip>`.

Generated diagnostics are runtime artifacts and are ignored by git. Dry-run does not start
Playwright and does not create browser screenshots or traces.

Current real portal finalizers write reports and call `email.send_report()`. With the
default `dry_run` backend this produces `email_report.txt`; with `smtp` it sends through
standard-library SMTP.

At the end of each CLI portal run, the command prints a concise `run_summary` line with the
`run_id`, run status, run artifact directory, report path, email backend/result, events path,
and metrics path. A sanitized reviewer-facing example is available in
[`docs/sample_report.md`](docs/sample_report.md).

## Input Contracts

OrangeHRM input is a JSON list. Each object requires:

- `employee_key`
- `first_name`
- `last_name`
- `job_title`
- `employment_status`
- `salary.amount`
- `salary.frequency`
- `salary.details`

Sample file: `data/orangehrm_employees.json` with three employee records.

Sauce Demo input is a JSON list. Each object requires:

- `account_key`
- `username`
- `checkout_profile.first_name`
- `checkout_profile.last_name`
- `checkout_profile.postal_code`

`items_to_add` is optional and defaults to `3`; when present it must be a positive integer.
Sample file: `data/saucedemo_accounts.json` with all six required demo account records:
`standard_user`, `locked_out_user`, `problem_user`, `performance_glitch_user`,
`error_user`, and `visual_user`. Each account is processed independently; a locked-out or
downstream-failed account is recorded as a per-item failure and does not abort the remaining
accounts.

Sauce Demo input actively rejects password-like field names such as `password`, `secret`, and
`sauce_password`. Passwords belong in environment variables, not input files.

## Synthetic Test Data

SauceDemo supports exactly 6 built-in demo accounts fixed by the portal itself. All 6 are already included in `data/saucedemo_accounts.json`. New accounts or inventory items cannot be added to the public demo.

An OrangeHRM edge-case fixture covers unicode names, long names, and varied salaries:

```bash
python -m portal_automation orangehrm \
    --input data/orangehrm_employees_edge_cases.json --dry-run
```

Large local OrangeHRM input can be generated deterministically for batch and throughput validation:

```bash
python tools/generate_test_data.py --portal orangehrm --count 50 \
    --output generated_data/orangehrm_employees_50.json
```

```bash
python -m portal_automation orangehrm \
    --input generated_data/orangehrm_employees_50.json --dry-run
```

Generated files are local only and excluded from git. Live portal mutations are opt-in only. Public demo portals may reset at any time.

## Idempotency And Recovery

`item_results` has a unique idempotency key:

```text
business_date + portal_name + item_key + operation
```

The SQLite constraint is `(business_date, portal_name, item_key, operation)`. Before each
real item process, `BasePortalRunnerZX.run()` writes an `in_progress` row. Final item outcomes
are committed with `upsert_item_result()`.

Successful same-day items are treated as committed and skipped on rerun. Reports for reruns
include persisted business-date results.

Stale recovery helpers are exposed by `PersistenceConnector`:

- `find_stale_items()`
- `find_stale_runs()`
- `mark_run_stale()`

### Recovery of stale runs/items

Use:

```bash
python -m portal_automation recover --business-date YYYY-MM-DD --dry-run
python -m portal_automation recover --business-date YYYY-MM-DD
```

What counts as stale:

- a run with `finished_at IS NULL` whose `updated_at` is older than
  `STALE_ITEM_TIMEOUT_SECONDS`
- an item row still in `in_progress` whose `updated_at` is older than the same cutoff

What `--dry-run` does:

- finds stale runs and items for the requested business date
- prints a summary and the exact records that would be recovered
- does not change the SQLite database

What mutating recovery does:

- marks stale unfinished runs as `stale`
- marks stale `in_progress` item rows as `failed` with a recovery error detail
- does not delete data
- does not modify completed or successful items

Why this helps same-day rerun/resume:

- same-day reruns skip only committed `success` items
- after recovery, previously stuck `in_progress` items are no longer left hanging
- those failed rows can be safely retried by the next normal portal run

## Adding A Third Portal

A new portal should reuse the base lifecycle rather than changing it. The usual checklist is:

1. Create `src/portal_automation/portals/<portal>/`.
2. Add `input_schema.py` with a strict parser/validator for the portal input file. Reject
   password-like fields; secrets should stay in environment/config.
3. Add `pages.py` with page-object methods or a protocol that hides DOM selectors from the
   workflow. Keep fake-page compatibility for unit tests.
4. Add `workflow.py` with the business steps, state checks, idempotency checks, retry-aware
   reads, and reason-code mapping.
5. Add `runner.py` with a `BasePortalRunnerZX` subclass. Implement hooks such as
   `load_items()`, `process_item()`, and `finalize()`; do not override `run()`.
6. Register the runner in `src/portal_automation/core/registry.py`.
7. Add config/env entries in `AppConfig` and `.env.example` only when the portal needs them.
8. Add sample input under `data/` with sanitized business data and no credentials.
9. Add unit tests for schema, page-object branches, workflow behavior, and runner lifecycle; add
   integration tests for CLI/report/artifact behavior.
10. Add an opt-in `tests/e2e/` smoke test only if the portal has a safe public/demo target, and
    keep it outside default `pytest`/CI.
11. Update README/docs with the portal key, setup requirements, inputs, and limitations.

## CI

The default GitHub Actions workflow runs the reviewer-safe checks on push and pull request:

```bash
ruff check .
ruff format --check .
pytest
```

Default CI does not run live e2e tests and does not require network access to OrangeHRM or
Sauce Demo. It also does not install Playwright Chromium because default tests do not launch a
real browser. Install Chromium locally only for non-dry-run CLI work or opt-in e2e tests.

## Live E2E Tests

Live browser tests are opt-in and not part of the default CI run. Public demo portals may be
temporarily unavailable, reset between runs, or change their DOM without notice.

**Unix / macOS:**

```bash
RUN_LIVE_E2E=1 pytest -m e2e tests/e2e/
```

**Windows PowerShell:**

```powershell
$env:RUN_LIVE_E2E="1"
pytest -m e2e tests\e2e\
Remove-Item Env:\RUN_LIVE_E2E -ErrorAction SilentlyContinue
```

### OrangeHRM live employee override

By default the OrangeHRM smoke test searches for `Emily Jones`, a confirmed employee in the
public demo. Override with:

```powershell
$env:RUN_LIVE_E2E="1"
$env:ORANGEHRM_E2E_EMPLOYEE_NAME="Emily Jones"
pytest -m e2e tests\e2e\test_orangehrm_live.py -vv -s
Remove-Item Env:\RUN_LIVE_E2E -ErrorAction SilentlyContinue
Remove-Item Env:\ORANGEHRM_E2E_EMPLOYEE_NAME -ErrorAction SilentlyContinue
```

### Verified locally

Live e2e tests were run locally against the public demo portals and passed:

- **Sauce Demo** (2 passed): `standard_user` login → success; `locked_out_user` login →
  locked_out. The opt-in live Sauce Demo login test now covers all six demo accounts, while
  full purchases for every account remain intentionally outside default CI.
- **OrangeHRM** (3 passed): Admin login → success; `Emily Jones` search → found;
  nonexistent name → not_found.

Public demo portals may be unavailable or reset at any time. These results are not guaranteed
to reproduce on every run.


## Production Hardening: Session Reuse

The runnable implementation creates a fresh Playwright browser context by default. This keeps
reviewer runs deterministic and avoids leaking authentication state between accounts. It is disabled by default. In a
production deployment, portals with strict authentication rate limits could opt into Playwright
`storage_state` session reuse after a successful login. That enhancement would save cookies and
localStorage under an ignored, sensitive artifact directory and load them on a later run to skip
the UI login step when the session is still valid.

Any implementation must verify the restored page is still authenticated before business actions
and must fall back to a fresh UI login when the session expires. An expired session should never
be reported as an employee/order not found error. Session state files contain auth cookies/tokens
and must not be committed, included in reports, or shared across unrelated accounts. Multi-account
flows such as Sauce Demo would require per-account state isolation; a single shared state file is
intentionally not used because it could leak one account session into another.

## Demo Limitations

This repository is a take-home implementation surface, not a deployed product.

- No web UI.
- No REST API.
- No production deployment packaging.
- No production scheduler (design covered in `DESIGN.md`).
- Non-dry-run CLI starts Playwright, creates a browser/context/page, and injects portal page
  objects through `pages_factory`. Requires `python -m playwright install chromium`.
- Dry-run does not start Playwright and does not require the Chromium binary.
- Observability is local-file based: structured events are written to `events.jsonl` and run
  metrics to `metrics.json` under `artifacts/runs/<run_id>/`. External observability backends
  are covered in `DESIGN.md`.
- Public demo portals may reset, change DOM, or be temporarily unavailable. Live e2e is
  opt-in and not run in default CI.
