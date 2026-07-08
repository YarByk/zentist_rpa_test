# Implementation Contract

This document defines the implementation contracts that keep the project reviewable, testable, and extensible.

It is written for contributors who need to modify the code without breaking the architecture described in `DESIGN.md` and `docs/ARCHITECTURE_BOUNDARIES.md`.

## Fixed Names And Markers

The following names and markers are intentional and must not be changed without updating tests and documentation:

| Purpose | Required name |
|---|---|
| Base runner class | `BasePortalRunnerZX` |
| OrangeHRM runner | `OrangeHrmRunner` |
| Sauce Demo runner | `SauceDemoRunner` |
| Run context | `RunContext` |
| Run result | `RunResult` |
| Item result | `ItemResult` |
| Persistence connector | `PersistenceConnector` |
| Artifact store | `ArtifactStore` |
| Report generator | `ReportGenerator` |
| Email connector | `EmailConnector` |
| Retry policy | `RetryPolicy` |
| Portal registry | `PORTAL_RUNNERS` |
| Registry lookup | `get_runner()` |
| OrangeHRM registry key | `orangehrm` |
| Sauce Demo registry key | `saucedemo` |
| README first line | `<!-- schema-ref:zentist-r7 -->` |
| First DESIGN diagram title | `Figure ZQ9` |

## Runner Lifecycle

`BasePortalRunnerZX.run()` is the shared lifecycle. Portal runners must not override it for normal portal behavior.

The lifecycle is:

1. create the run record;
2. call `load_items(context)`;
3. if `context.dry_run` is true, skip preflight and live item processing;
4. otherwise call `preflight_check(context)`;
5. read same-day committed successful item keys;
6. for each uncommitted item:
   - derive `item_key`;
   - write an `in_progress` item row;
   - call `process_item(context, item)`;
   - convert known portal errors into failed `ItemResult` rows;
   - persist the final item result;
7. list business-date results from persistence;
8. compute run status;
9. call `finalize(context, result)`;
10. finish the run row with status and summary.

Portal runners implement these hooks:

```python
preflight_check(context) -> None
load_items(context) -> list[Any]
process_item(context, item) -> ItemResult
finalize(context, result) -> None
```

## Dry-Run Contract

Dry-run is a local smoke path. It validates wiring without touching live portals.

In dry-run mode:

- input files may be loaded and validated;
- database and artifact paths may be created;
- run rows and reports may be produced;
- portal `preflight_check()` is not called;
- portal `process_item()` is not called;
- browser/page objects are not required;
- live portal network calls must not be made;
- real email must not be sent.

Dry-run should be safe to execute repeatedly on a developer machine or in CI.

## Real-Run Contract

A real run is allowed to touch live portals and should use Playwright-backed page objects.

For real runs:

- required credentials must be supplied outside source code;
- browser/page objects must be created through a shared wiring layer or injected factory;
- portal preflight should fail early when required credentials, browser wiring, or portal availability are missing;
- page object methods should hide selectors and expose business-level actions;
- item failures should be converted to structured item outcomes whenever possible;
- the batch should continue after an item-level failure;
- final reporting and notification should still happen for partial runs.

Live browser tests may be opt-in, but real-run code paths should be implemented and documented.

## Idempotency Contract

Each item outcome is identified by:

```text
business_date + portal_name + item_key + operation
```

The persistence layer must enforce uniqueness for that key. Same-day successful items are considered committed and skipped on rerun.

A rerun should not duplicate successful item rows, corrupt the report, or lose failed outcomes from earlier attempts.

## Item Result Contract

Every attempted item should produce an `ItemResult` with:

- `item_key`;
- `operation`;
- `status`;
- `reason_code` for failures or skips;
- sanitized `error_detail` where applicable;
- optional `artifact_path`;
- `attempts`;
- non-secret `details`.

Expected portal failures must become item results. A single failed item must not abort the rest of the batch.

## Failure Taxonomy

Expected portal failures should use `PortalError` with a structured `ReasonCode`.

Retryable examples:

- `PORTAL_TIMEOUT`;
- `PORTAL_UNAVAILABLE`;
- `SESSION_DROPPED`.

Non-retryable examples:

- `LOCKED_OUT`;
- `CREDENTIAL_EXPIRED`;
- `INPUT_VALIDATION_FAILED`;
- `EMPLOYEE_MATCH_AMBIGUOUS`;
- `VALIDATION_FAILED`.

Unexpected exceptions should be converted to `UNEXPECTED_ERROR` at item boundaries. Persistence errors should be raised rather than hidden.

## Retry Contract

Retry behavior belongs in shared infrastructure, not in copy-pasted portal loops.

The shared retry policy should define:

- retryable reason codes;
- maximum attempts;
- timeout boundaries;
- backoff behavior;
- how retry attempts are recorded in item details, logs, or metrics.

Portal workflows may classify a failure as retryable or non-retryable, but they should not each implement their own unrelated retry mechanism.

## Persistence Contract

`PersistenceConnector` owns database access. Portal code must not open SQLite connections directly.

Required responsibilities:

- initialize schema;
- create run row;
- mark item in progress;
- upsert final item result;
- list business-date results;
- return committed same-day successful item keys;
- finish run row;
- expose stale run and stale item recovery helpers.

Persistence values must not include raw secrets.

## Reporting And Email Contract

`ReportGenerator` owns report rendering. Portal runners may call report generation during `finalize()`, but they must not format their own independent final reports.

`EmailConnector` owns report delivery. It should support:

- a safe `dry_run` backend that writes an email artifact;
- an SMTP backend when SMTP configuration is provided.

A completed production-style run should generate a summary report and send it to the configured recipient. If email delivery fails, the failure should be visible in logs and/or run outcome rather than silently ignored.

## Configuration And Secrets Contract

`AppConfig` reads configuration from environment variables. `.env.example` documents supported variables. The application does not require real secrets to be committed.

Secrets must not appear in:

- source files;
- test fixtures, except harmless fake values;
- input JSON files;
- generated reports;
- logs;
- screenshots or traces committed to the repository.

Portal passwords belong in environment variables or a production secret manager.

## Portal Contracts

### OrangeHRM

Input items are employee records. Each item must include:

- employee key;
- first name;
- last name;
- target job title;
- target employment status;
- salary document details.

For each real item, the workflow must:

1. locate the employee;
2. create the employee if absent;
3. locate newly created employees after creation;
4. update job fields to target values;
5. ensure the salary-details attachment exists;
6. verify the intended state when possible;
7. return one final result.

### Sauce Demo

Input items are account records. Passwords are not stored in input files.

For each real item, the workflow must:

1. log in;
2. add the configured number of items, defaulting to three;
3. go through checkout;
4. capture order details;
5. persist details before finishing the order;
6. finish the order;
7. return one final result, including structured failure results for accounts that cannot complete.

## Testing Contract

The default test suite should run without live portal credentials.

Expected default checks:

```bash
ruff check .
pytest
```

Recommended coverage:

- fixed formatting markers;
- input validation;
- secret rejection;
- runner lifecycle;
- idempotent reruns;
- persistence schema and stale recovery helpers;
- report generation;
- email dry-run behavior;
- workflow success and failure branches with fake page objects;
- CLI integration smoke tests.

Live browser tests, if present, should be marked separately and excluded from default CI unless the CI environment is explicitly configured for them.

## Repository Hygiene Contract

Do not commit:

- `.env`;
- local SQLite databases;
- generated reports;
- screenshots or traces from live runs;
- `__pycache__/`;
- `.pytest_cache/`;
- `.ruff_cache/`;
- `*.egg-info/`;
- virtual environments;
- local browser profiles.

Runtime files should be created under `artifacts/`, with only `artifacts/.gitkeep` committed.

## Completion Checklist

Before submitting a change or delivery package:

1. `README.md` starts with the required schema marker.
2. `DESIGN.md` has `Figure ZQ9` as the first diagram title.
3. `BasePortalRunnerZX` exists and owns the lifecycle.
4. Portal runners inherit from the base and implement hooks only.
5. Real runs use Playwright-backed page objects.
6. No secrets are hardcoded in `src/`.
7. `ruff check .` passes.
8. `pytest` passes.
9. CI runs lint and tests.
10. The archive/repository contains no runtime artifacts or caches.
11. Documentation describes implemented behavior accurately.
