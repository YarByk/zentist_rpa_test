# Implementation Contract

This document translates the frozen architecture into concrete implementation requirements for the Zentist RPA Lead take-home assignment.

It is normative. All implementation work, tests, AI-assisted code generation, and documentation must conform to this contract.

Authority rules:

1. `Zentist_RPA_Lead_Task.pdf` is the highest authority.
2. `docs/ARCHITECTURE_FREEZE.md` is the highest derived architectural authority.
3. `zentist_final_execution_plan_checked_v11_FINAL.md` is the highest derived implementation plan.
4. `company_interview_addendum_to_task_FINAL_LOCKED (1).md` and `outstanding_submission_plan_FINAL_LOCKED (1).md` provide engineering and reviewer context.

If this contract conflicts with the original task PDF, the task PDF wins.

---

## 1. Implementation Goal

This repository SHALL implement a production-oriented portal automation platform with shared infrastructure and portal-specific runners.

OrangeHRM and Sauce Demo SHALL be implemented as two concrete portal runners using the same shared execution lifecycle, persistence layer, retry policy, reporting, artifact handling, configuration model, and dry-run behavior.

---

## 2. Fixed Names and Public Interfaces

The following names are fixed public implementation contracts.

| Purpose | Required name |
|---|---|
| Base runner class | `BasePortalRunnerZX` |
| OrangeHRM runner class | `OrangeHrmRunner` |
| Sauce Demo runner class | `SauceDemoRunner` |
| Runtime context | `RunContext` |
| Run result | `RunResult` |
| Item result | `ItemResult` |
| Persistence connector | `PersistenceConnector` |
| Retry policy | `RetryPolicy` |
| Report generator | `ReportGenerator` |
| Artifact store | `ArtifactStore` |
| Email connector | `EmailConnector` |
| Portal registry dictionary | `PORTAL_RUNNERS` |
| Registry lookup function | `get_runner()` |

No alternative names are allowed.

Additional fixed names:

| Purpose | Required value |
|---|---|
| Logger module | `core/logger.py` |
| Forbidden logger module | `core/logging.py` |
| OrangeHRM registry key | `"orangehrm"` |
| Sauce Demo registry key | `"saucedemo"` |
| OrangeHRM operation | `"sync_employee_state"` |
| Sauce Demo operation | `"checkout"` |
| README first line | `<!-- schema-ref:zentist-r7 -->` |
| First DESIGN diagram title | `### Figure ZQ9` |

---

## 3. Core Domain Model

The core domain model SHALL live in `src/portal_automation/core/models.py`.

### 3.1. `ReasonCode`

`ReasonCode` SHALL be the single source of truth for failure reasons. Raw string failure codes SHALL NOT be used in persistence, reports, logs, or tests.

Required values:

```python
class ReasonCode(str, Enum):
    LOGIN_FAILED = "LOGIN_FAILED"
    LOCKED_OUT = "LOCKED_OUT"
    CREDENTIAL_EXPIRED = "CREDENTIAL_EXPIRED"
    PORTAL_TIMEOUT = "PORTAL_TIMEOUT"
    PORTAL_UNAVAILABLE = "PORTAL_UNAVAILABLE"
    SESSION_DROPPED = "SESSION_DROPPED"
    INPUT_VALIDATION_FAILED = "INPUT_VALIDATION_FAILED"
    EMPLOYEE_NOT_FOUND = "EMPLOYEE_NOT_FOUND"
    EMPLOYEE_MATCH_AMBIGUOUS = "EMPLOYEE_MATCH_AMBIGUOUS"
    SEARCH_FAILED = "SEARCH_FAILED"
    ITEM_NOT_FOUND = "ITEM_NOT_FOUND"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    UPLOAD_FAILED = "UPLOAD_FAILED"
    DOCUMENT_GENERATION_FAILED = "DOCUMENT_GENERATION_FAILED"
    CHECKOUT_FAILED = "CHECKOUT_FAILED"
    LAYOUT_CHANGED = "LAYOUT_CHANGED"
    UNEXPECTED_ERROR = "UNEXPECTED_ERROR"
```

### 3.2. `ItemStatus`

Required values:

```python
class ItemStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    IN_PROGRESS = "in_progress"
```

### 3.3. `RunStatus`

Required values:

```python
class RunStatus(str, Enum):
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"
    STALE = "stale"
```

### 3.4. `RunContext`

`RunContext` SHALL contain all runtime dependencies assembled by the CLI.

Required fields:

| Field | Type | Required |
|---|---|---|
| `run_id` | `str` | yes |
| `business_date` | `date` | yes |
| `dry_run` | `bool` | yes |
| `stale_item_timeout_seconds` | `int` | yes |
| `config` | `AppConfig` | yes |
| `persistence` | `PersistenceConnector` | yes |
| `reporter` | `ReportGenerator` | yes |
| `logger` | `StructuredLogger` | yes |
| `metrics` | `MetricsCollector` | yes |
| `artifacts` | `ArtifactStore` | yes |
| `email` | `EmailConnector` | yes |

### 3.5. `ItemResult`

Required fields:

| Field | Type | Required |
|---|---|---|
| `item_key` | `str` | yes |
| `operation` | `str` | yes |
| `status` | `ItemStatus` | yes |
| `reason_code` | `ReasonCode | None` | on failure |
| `error_detail` | `str | None` | on failure |
| `artifact_path` | `str | None` | optional |
| `attempts` | `int` | yes |
| `details` | `dict` | yes |

`error_detail` and `details` SHALL NOT contain secrets.

### 3.6. `RunResult`

Required fields:

| Field | Type | Required |
|---|---|---|
| `run_id` | `str` | yes |
| `portal_name` | `str` | yes |
| `business_date` | `date` | yes |
| `status` | `RunStatus` | yes |
| `results` | `list[ItemResult]` | yes |

---

## 4. `BasePortalRunnerZX` Contract

`BasePortalRunnerZX` SHALL live in `src/portal_automation/core/runner.py`.

Required public interface:

```python
class BasePortalRunnerZX(ABC):
    portal_name: str
    operation_name: str

    def run(self, context: RunContext) -> RunResult:
        ...

    def preflight_check(self, context: RunContext) -> None:
        ...

    def load_items(self, context: RunContext) -> list[Any]:
        ...

    def process_item(self, context: RunContext, item: Any) -> ItemResult:
        ...

    def finalize(self, context: RunContext, result: RunResult) -> None:
        ...
```

Critical lifecycle rules:

- `run()` MUST be a concrete implementation in `BasePortalRunnerZX`.
- Portal runners MUST NOT override `run()`.
- Portal runners SHALL implement hooks only.
- The shared lifecycle MUST live in `BasePortalRunnerZX`.
- Portal runner constructors MUST NOT instantiate Playwright, browser, page, or portal page objects.

Ownership:

| Method | Responsibility |
|---|---|
| `run()` | Owns lifecycle orchestration |
| `preflight_check()` | Verifies portal readiness for real runs |
| `load_items()` | Loads and validates input |
| `process_item()` | Processes one item |
| `finalize()` | Performs report, email, and artifact finalization |

`run()` SHALL:

1. create a run row with status `running`;
2. load and validate items;
3. branch before any browser work if `context.dry_run` is true;
4. for real runs, call `preflight_check()`;
5. for real runs, load committed same-day item keys using `get_committed_items()`;
6. for real runs, process each non-committed item independently;
7. call `mark_item_in_progress()` immediately before each `process_item()` call;
8. convert known item-level failures into `ItemResult`;
9. convert unexpected item-level failures into `UNEXPECTED_ERROR`;
10. persist each final item result immediately;
11. continue the batch after item-level failure;
12. compute final `RunStatus`;
13. call `finalize()`;
14. finish the run row;
15. return `RunResult`.

Dry-run branch inside `run()` SHALL skip `preflight_check()`, `get_committed_items()`, `mark_item_in_progress()`, `process_item()`, portal workflows, and portal page object creation.

Dry-run lifecycle rule:

- after step 3, if `context.dry_run=True`, `run()` SHALL skip steps 4-11 and proceed directly to step 12;
- dry-run SHALL still compute final `RunStatus`, call `finalize()`, finish the run row, and return `RunResult`.

Item-level failure handling rule:

- `mark_item_in_progress()` SHALL be called inside the item-level `try` block immediately before `process_item()`;
- item-level `PortalError` and unexpected exceptions from `process_item()` SHALL be converted into `ItemResult`;
- persistence infrastructure failures during `mark_item_in_progress()` or final `upsert_item_result()` SHALL be logged as critical infrastructure failures and MAY fail the run, because durable item outcomes can no longer be guaranteed.

Exception behavior:

- `process_item()` MAY raise `PortalError` for known portal failures.
- Portal workflow helper functions MAY raise `PortalError`.
- `BasePortalRunnerZX.run()` MUST convert `PortalError` and unexpected item-level portal/workflow exceptions into `ItemResult`.
- Single item-level portal/workflow failure MUST NOT abort the batch.
- `finalize()` SHALL still run when all items fail.

---

## 5. Persistence Contract

Persistence SHALL live in `src/portal_automation/core/persistence.py`.

Persistence owns:

- SQLite connection handling;
- schema initialization;
- run rows;
- item result rows;
- idempotency;
- stale item detection;
- stale run detection.

Portal modules SHALL NOT access SQLite directly.

### 5.1. Tables

Required tables:

```sql
CREATE TABLE runs (
    run_id TEXT PRIMARY KEY,
    portal_name TEXT NOT NULL,
    business_date TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT,
    summary_json TEXT
);
```

`runs.updated_at` is required for stale run detection.

```sql
CREATE TABLE item_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    portal_name TEXT NOT NULL,
    business_date TEXT NOT NULL,
    item_key TEXT NOT NULL,
    operation TEXT NOT NULL,
    status TEXT NOT NULL,
    reason_code TEXT,
    error_detail TEXT,
    attempts INTEGER NOT NULL DEFAULT 1,
    artifact_path TEXT,
    details_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (business_date, portal_name, item_key, operation)
);
```

### 5.2. Idempotency

Required idempotency key:

```text
business_date + portal_name + item_key + operation
```

Required unique constraint:

```sql
UNIQUE (business_date, portal_name, item_key, operation)
```

### 5.3. UPSERT

Item writes MUST use:

```sql
INSERT ... ON CONFLICT DO UPDATE
```

Item writes MUST NOT use:

```sql
INSERT OR REPLACE
```

Item writes MUST NOT use:

```text
SELECT -> if not exists -> INSERT
```

UPSERT MUST preserve the original `created_at` value and update `updated_at`.

### 5.4. Required methods

`PersistenceConnector` SHALL expose:

```python
class PersistenceConnector:
    def create_run(self, run_id: str, portal_name: str, business_date: date) -> None:
        ...

    def finish_run(self, run_id: str, status: RunStatus, summary: dict) -> None:
        ...

    def mark_run_stale(self, run_id: str, timeout_seconds: int) -> bool:
        ...

    def mark_item_in_progress(
        self,
        run_id: str,
        portal_name: str,
        business_date: date,
        item_key: str,
        operation: str,
    ) -> None:
        ...

    def upsert_item_result(
        self,
        result: ItemResult,
        run_id: str,
        portal_name: str,
        business_date: date,
    ) -> None:
        ...

    def list_results_for_run(self, run_id: str) -> list[ItemResult]:
        ...

    def list_results_by_business_date(self, portal_name: str, business_date: date) -> list[ItemResult]:
        ...

    def get_committed_items(self, portal_name: str, business_date: date) -> set[str]:
        ...

    def find_stale_items(self, portal_name: str, business_date: date, timeout_seconds: int) -> list[dict]:
        ...

    def find_stale_runs(self, timeout_seconds: int) -> list[dict]:
        ...
```

`finish_run()` SHALL set `finished_at`, update `updated_at`, set final run status, and persist summary data.

`mark_run_stale()` MUST set run status to `stale` only when `finished_at IS NULL` and `updated_at` is older than the configured stale timeout. It SHALL update `updated_at` and return `True` only when a run was actually marked stale.

`list_results_by_business_date()` SHALL return the latest persisted item outcomes for the given `portal_name` and `business_date`.

`get_committed_items()` SHALL return successful item keys for same-day deduplication. It SHALL return item keys with `status = 'success'` for the given `portal_name` and `business_date`.

`BasePortalRunnerZX.run()` SHALL use committed item keys before calling `mark_item_in_progress()` or `process_item()`. Committed successful same-day items SHALL NOT be reprocessed and SHALL NOT be overwritten with `skipped` rows. Reports SHALL use persisted business-date results so prior committed successes remain visible after same-day reruns.

### 5.5. Recovery rules

- Committed successful same-day items are detected before item processing.
- Committed successful same-day items are not reprocessed.
- Committed successful same-day rows are not overwritten with `skipped`.
- Item is marked `in_progress` by `mark_item_in_progress()` immediately before `process_item()` is called.
- Final item status is written immediately after processing.
- Stale items are detected by `status = 'in_progress'` and `updated_at` older than timeout.
- Stale runs are detected by `finished_at IS NULL` and `updated_at` older than timeout.
- Same-day rerun SHALL NOT duplicate item result rows.
- Same-day rerun SHALL preserve successful committed items unless explicitly reprocessed by contract.

---

## 6. Registry Contract

Registry SHALL live in `src/portal_automation/core/registry.py`.

Required registry:

```python
PORTAL_RUNNERS: dict[str, type[BasePortalRunnerZX]] = {
    "orangehrm": OrangeHrmRunner,
    "saucedemo": SauceDemoRunner,
}
```

Required lookup:

```python
def get_runner(portal_name: str) -> type[BasePortalRunnerZX]:
    ...
```

Rules:

- Registry is the only portal discovery mechanism.
- No scattered `if portal == ...` dispatch is allowed.
- `core/registry.py` is the only place where `core` may import concrete portal runners.
- Unknown portal MUST fail with a clear error listing available portals.
- Adding a third portal requires a new portal package and one registry entry.

---

## 7. Configuration and Secrets Contract

Configuration SHALL be environment-driven.

Required `.env.example` fields include:

```text
DB_PATH=artifacts/portal_automation.sqlite
ARTIFACTS_DIR=artifacts
BUSINESS_DATE=
HEADLESS=true
DEFAULT_TIMEOUT_SECONDS=30
MAX_RETRIES=2
STALE_ITEM_TIMEOUT_SECONDS=300

ORANGEHRM_BASE_URL=https://opensource-demo.orangehrmlive.com
ORANGEHRM_USERNAME=Admin
ORANGEHRM_PASSWORD=
ORANGEHRM_INPUT_PATH=data/orangehrm_employees.json

SAUCEDEMO_BASE_URL=https://www.saucedemo.com
SAUCEDEMO_PASSWORD=
SAUCEDEMO_INPUT_PATH=data/saucedemo_accounts.json

EMAIL_BACKEND=dry_run
REPORT_EMAIL_TO=
SMTP_HOST=
SMTP_PORT=
SMTP_USERNAME=
SMTP_PASSWORD=
```

Rules:

- If `--input` is not provided, default input paths SHALL come from configuration.
- Secrets MUST NOT be hardcoded.
- Passwords MUST come from environment or secrets layer.
- `secret_sauce` MUST NOT appear in `src/`.
- `admin123` MUST NOT appear in `src/`.
- Secrets MUST NOT appear in logs, reports, artifacts, or committed files.

---

## 8. Dry-run Contract

Dry-run command:

```bash
python -m portal_automation all --dry-run
```

Dry-run means:

- `RunContext.dry_run=True`;
- no Playwright object may be created;
- no `Browser` may be created;
- no `BrowserContext` may be created;
- no `Page` may be created;
- no portal page object may be instantiated;
- no real portal may be opened;
- no SMTP email may be sent;
- portal `preflight_check()` MUST be skipped in dry-run mode;
- non-browser dry-run validation belongs to configuration/input validation, not portal `preflight_check()`;
- `preflight_check()` MUST NOT create browser objects in dry-run mode;
- `process_item()` MUST NOT execute;
- portal workflows MUST NOT execute.

Dry-run may:

- validate configuration;
- validate input;
- resolve registry;
- instantiate runner;
- initialize database and artifact paths;
- create run/report artifacts;
- exercise non-browser wiring;
- generate dry-run email/report output.

CLI smoke tests MUST prove that dry-run does not create Playwright objects, Browser, BrowserContext, Page, or portal page objects.

---

## 9. Retry Contract

Retry behavior SHALL live in `src/portal_automation/core/retries.py`.

Required public concepts:

```python
class PortalError(Exception):
    reason: ReasonCode
    detail: str
```

```python
class RetryPolicy:
    ...
```

Retryable known codes:

- `PORTAL_TIMEOUT`
- `PORTAL_UNAVAILABLE`
- `SESSION_DROPPED`

Non-retryable known codes:

- `LOCKED_OUT`
- `INPUT_VALIDATION_FAILED`
- `EMPLOYEE_MATCH_AMBIGUOUS`
- `CREDENTIAL_EXPIRED`

These lists are exhaustive for known retry categories in this demo. Any new retry classification MUST be explicit in the implementation contract and tests.

Retry rules:

- Retry only known retryable `PortalError` failures.
- Non-retryable `PortalError` failures SHALL re-raise immediately.
- Unexpected exceptions SHALL be mapped by `BasePortalRunnerZX.run()` to `UNEXPECTED_ERROR`.
- Each retry attempt SHALL be logged with attempt number and reason code.
- Final `ItemResult.attempts` SHALL reflect actual attempts.

---

## 10. OrangeHRM Contract

Runner:

```python
class OrangeHrmRunner(BasePortalRunnerZX):
    portal_name = "orangehrm"
    operation_name = "sync_employee_state"
    max_sessions_per_login = 1
```

Workflow SHALL execute in this order:

1. validate employee input before browser work;
2. call `LoginPage.login(...)` using credentials from environment/secrets;
3. call `find_employee_record(...)` before create/update;
4. if found: open existing profile;
5. if not found: Add Employee;
6. after Add Employee, call `find_employee_record(...)` again to locate the newly created record;
7. if ambiguous: fail with `EMPLOYEE_MATCH_AMBIGUOUS`;
8. if search fails: fail with `SEARCH_FAILED`;
9. update Job Title and Employment Status;
10. re-read Job section after update;
11. validate actual values equal target values;
12. if actual does not equal target: fail with `VALIDATION_FAILED`;
13. check existing salary attachments before generating any document;
14. if matching salary attachment exists: do not generate and do not upload duplicate;
15. if matching salary attachment is missing: generate deterministic salary text document;
16. upload attachment;
17. verify attachment state;
18. persist per-employee outcome.

Salary document generation SHALL live in shared core code, not inside OrangeHRM portal code.

A matching salary attachment means any existing attachment whose filename equals exactly:

```text
salary_{employee_key}_{business_date}.txt
```

Forbidden:

- skipping the first `find_employee_record(...)`;
- skipping the second `find_employee_record(...)` after Add Employee;
- trusting input JSON as source of truth for employee existence;
- generating salary document before matching attachment check;
- uploading duplicate matching salary attachment.

---

## 11. Sauce Demo Contract

Runner:

```python
class SauceDemoRunner(BasePortalRunnerZX):
    portal_name = "saucedemo"
    operation_name = "checkout"
    max_sessions_per_account = 1
```

Workflow SHALL process all six demo users:

- `standard_user`
- `locked_out_user`
- `problem_user`
- `performance_glitch_user`
- `error_user`
- `visual_user`

Problematic accounts SHALL NOT be pre-skipped.

Workflow SHALL execute in this order:

1. validate account input before browser work;
2. call `LoginPage.login(...)` using account username and password from environment/secrets;
3. detect locked-out account and map to `LOCKED_OUT`;
4. add exactly 3 items;
5. validate cart count equals 3;
6. if cart count mismatch: fail with `VALIDATION_FAILED`;
7. checkout;
8. enter customer information;
9. reach order confirmation / order summary;
10. semantically validate confirmation/order details;
11. capture order details;
12. persist order details;
13. finish order after persistence;
14. persist per-account outcome.

`finish_order()` MUST happen after order details are persisted, not before.

---

## 12. Reporting, Email, and Artifact Contract

Reporting SHALL live in `src/portal_automation/core/reporting.py`.

Email integration SHALL live in `src/portal_automation/core/email_connector.py`.

Artifacts SHALL be managed by `src/portal_automation/core/artifact_store.py`.

Reports MUST be generated from persisted results.

For same-day reruns, reports SHALL use `list_results_by_business_date()` so previously committed successful items remain visible even when they are not reprocessed.

Reports MUST include:

- run status;
- processed count;
- success count;
- failure count;
- per-item outcomes;
- reason codes;
- relevant artifact paths.

Reports MUST NOT include secrets.

Dry-run email backend SHALL write an email/report artifact instead of sending SMTP.

Artifacts SHALL live under:

```text
artifacts/runs/<run_id>/
```

Expected artifacts:

- report;
- dry-run email output;
- generated salary documents;
- screenshots or traces on failure or suspicion.

---

## 13. CLI Contract

CLI SHALL live in `src/portal_automation/__main__.py`.

Required commands:

```bash
python -m portal_automation orangehrm
python -m portal_automation saucedemo
python -m portal_automation all
python -m portal_automation all --dry-run
python -m portal_automation --help
python -m portal_automation orangehrm --help
python -m portal_automation saucedemo --help
python -m portal_automation all --help
```

Required optional flags:

```bash
--business-date YYYY-MM-DD
--input <path>
--headless true|false
--email-backend dry_run|smtp
```

Unknown portal MUST exit with a clear error.

---

## 14. Test Contract

Default `pytest` SHALL run only unit and integration tests.

`pyproject.toml` SHALL include:

```toml
[tool.pytest.ini_options]
testpaths = ["tests/unit", "tests/integration"]
markers = [
    "e2e: live browser tests against demo portals; not run by default in CI",
]
```

E2E tests SHALL be marked and excluded from default CI.

Required tests:

- README marker smoke test;
- `Figure ZQ9` smoke test;
- `BasePortalRunnerZX` existence test;
- registry tests;
- model enum tests, including `ITEM_NOT_FOUND`;
- idempotent UPSERT tests;
- `created_at` preserved on UPSERT update;
- `INSERT ... ON CONFLICT DO UPDATE` behavior tests;
- explicit check that `INSERT OR REPLACE` does not appear in `src/`, for example `grep -rn "INSERT OR REPLACE" src/` returns no matches;
- `mark_item_in_progress()` test;
- explicit check that `mark_item_in_progress()` is called before `process_item()`;
- persistence failure in `mark_item_in_progress()` is treated as infrastructure failure, not silent item success;
- `get_committed_items()` returns successful same-day item keys;
- `list_results_by_business_date()` returns persisted business-date outcomes;
- same-day successful items are not duplicated;
- same-day successful rows are not overwritten with `skipped`;
- stale item recovery tests;
- stale run recovery tests;
- dry-run without Playwright objects;
- dry-run does not call portal `preflight_check()`;
- dry-run does not call `process_item()`;
- dry-run does not call browser/page object constructors;
- retry policy tests;
- report excludes secrets;
- hardcoded credential scan for `secret_sauce` and `admin123`;
- OrangeHRM second lookup after Add Employee;
- OrangeHRM re-read Job section and validate actual equals target;
- OrangeHRM attachment de-duplication;
- `OrangeHrmRunner.max_sessions_per_login == 1`;
- Sauce Demo all six accounts;
- Sauce Demo cart count validation;
- Sauce Demo persist-before-finish;
- `SauceDemoRunner.max_sessions_per_account == 1`;
- CLI smoke tests;
- subcommand help tests.

---

## 15. Explicit Non-goals

The implementation intentionally excludes:

- web UI;
- production deployment;
- real scheduler;
- real queue cluster;
- production secret manager integration;
- real SMTP credentials in repository;
- plugin framework;
- dependency injection container;
- unnecessary abstractions.

---

## 16. Acceptance Criteria

A reviewer should immediately understand:

- how to run it;
- where configuration lives;
- where secrets live;
- where persistence lives;
- where artifacts live;
- how idempotency works;
- how recovery works;
- how dry-run works;
- how to add a third portal;
- why one failed item does not stop the batch;
- why the platform can scale beyond two portals.
