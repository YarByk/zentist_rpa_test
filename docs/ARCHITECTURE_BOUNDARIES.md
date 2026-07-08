# Architecture Boundaries

This document defines the ownership boundaries that keep the portal automation codebase maintainable as it grows from two take-home portals into a larger unattended automation platform.

It complements:

- `README.md`, which explains local setup, configuration, and execution.
- `DESIGN.md`, which explains the production-scale design for many portals and many daily work items.
- `docs/IMPLEMENTATION_CONTRACT.md`, which defines runtime lifecycle contracts and behavioral invariants.

## Purpose

The project should not become a collection of independent browser scripts. The goal is a shared automation framework where portal-specific implementations plug into a stable execution model.

The current portal packages are:

- OrangeHRM: employee synchronization.
- Sauce Demo: account checkout processing.

Adding a third portal should mean adding a new portal package and registering it. It should not require changing the existing OrangeHRM workflow, Sauce Demo workflow, persistence connector, report generator, or the base runner lifecycle.

## Boundary Principles

The architecture follows these principles:

- one shared runner lifecycle;
- strict separation between shared platform logic and portal-specific logic;
- per-item isolation so one failed account or employee does not abort the rest of the batch;
- same-day idempotency;
- persisted outcome for every attempted item;
- deterministic report and artifact locations;
- reusable failure classification;
- reusable retry primitives;
- environment-driven configuration;
- no secrets in source code, input samples, logs, reports, screenshots, or committed artifacts;
- a narrow extension path for new portals;
- tests that verify behavior without depending on public demo portals by default.

The standard same-day idempotency key is:

```text
business_date + portal_name + item_key + operation
```

## Repository Boundaries

### `src/portal_automation/core/`

`core/` owns reusable platform behavior:

- `BasePortalRunnerZX` and the shared run lifecycle;
- shared data models and reason codes;
- configuration loading;
- secret lookup abstractions;
- persistence and recovery helpers;
- retry primitives;
- artifact path management;
- report generation;
- email delivery abstraction;
- portal registry wiring.

`core/` must not contain OrangeHRM or Sauce Demo business rules.

The only acceptable concrete portal import inside `core/` is in `core/registry.py`, where portal keys are mapped to runner classes.

### `src/portal_automation/portals/`

`portals/` owns portal-specific behavior:

- input schema validation;
- page object methods;
- workflow steps;
- portal-specific runner hooks;
- portal-specific validation rules;
- portal-specific failure reason mapping.

Portal modules must not own global configuration, SQLite schema management, report rendering, email delivery, or CLI parsing.

### `data/`

`data/` contains non-secret sample input files used for local execution and tests.

It may contain example employee/account records. It must not contain real customer data, passwords, tokens, cookies, downloaded files, screenshots with sensitive information, or production portal exports.

### `artifacts/`

`artifacts/` is a runtime output location.

The repository should contain only:

```text
artifacts/.gitkeep
```

Generated reports, uploaded-document copies, screenshots, traces, SQLite databases, and per-run folders are runtime artifacts and should not be committed.

### `tests/`

`tests/` verifies shared lifecycle behavior, persistence, workflow behavior, reporting, and failure handling.

Recommended split:

- `tests/unit/` for models, schemas, retry policy, reporting, and workflow behavior with fakes;
- `tests/integration/` for CLI, SQLite-backed lifecycle, idempotency, recovery, and dry-run behavior;
- `tests/e2e/` for optional live browser checks against public demo portals.

Live tests should be opt-in because public demo portals may be slow, reset, or temporarily unavailable. Default CI should remain deterministic.

## Dependency Direction

The intended dependency direction is:

```text
CLI
  -> AppConfig
  -> Registry
  -> RunContext
  -> BasePortalRunnerZX
  -> Portal Runner
  -> Portal Workflow
  -> Page Objects
```

Shared connectors are injected through configuration, context, or runner construction. Portal code calls shared interfaces; it should not instantiate global infrastructure directly.

Forbidden dependencies:

- page objects must not know about SQLite, reports, email, or metrics storage;
- portal workflows must not write directly to the database;
- portal runners must not parse command-line arguments;
- report generation must not depend on Playwright page objects;
- persistence must not depend on browser/page objects;
- configuration loading must not import portal workflow modules;
- `core/` must not import concrete portals except inside the registry;
- production code must not depend on test-only fake classes.

## Shared Runner Boundary

`BasePortalRunnerZX.run()` owns the shared lifecycle:

1. create a run row;
2. load and validate input items through the portal runner;
3. skip live portal work in dry-run mode;
4. run portal preflight for real runs;
5. skip same-day committed successful items;
6. mark each new item as `in_progress` before processing;
7. call the portal-specific `process_item()` hook;
8. persist each final item outcome;
9. compute final run status;
10. finalize reporting and notification;
11. mark the run finished.

Portal runners implement hooks only:

- `load_items()`;
- `preflight_check()`;
- `process_item()`;
- `finalize()`.

Portal runners should not override `run()` unless a documented production requirement proves that the shared lifecycle is insufficient.

## Portal Boundaries

### OrangeHRM

OrangeHRM owns employee synchronization:

- locate an existing employee;
- create the employee when absent;
- locate the newly created record after creation;
- update Job Title and Employment Status;
- generate and upload the salary-details document only when missing;
- return one final item outcome per input employee.

The key portal constraint is the shared login. The implementation should treat OrangeHRM as a single-session portal unless a different credential strategy is introduced.

### Sauce Demo

Sauce Demo owns account checkout processing:

- log in for each configured account;
- add the expected number of items;
- complete checkout;
- capture confirmation/order details;
- persist order details before finishing the order;
- finish the order;
- return one final item outcome per account, including expected failures such as locked accounts.

The key portal constraint is per-account isolation. A failure for one account must not prevent the remaining accounts from being attempted.

## Browser Boundary

Browser automation belongs behind page objects and workflow functions.

Real runs should use page objects backed by Playwright. Unit and default integration tests may use fakes to keep the test suite deterministic and independent of public demo portal availability.

Browser/page objects should expose business-level actions, not low-level selectors to the rest of the codebase. Examples:

- `login()`;
- `find_employee()`;
- `create_employee()`;
- `update_job()`;
- `salary_attachment_exists()`;
- `upload_salary_attachment()`;
- `add_items_to_cart()`;
- `complete_checkout()`;
- `capture_order_details()`.

Selector details should stay inside page objects. Workflow code should describe the business process.

## Persistence Boundary

The database is a shared connector, not portal-specific storage.

It records:

- run start and finish state;
- item status;
- item reason code;
- attempt count;
- artifact paths;
- non-secret structured details.

Portal workflows should return structured results. They should not decide how those results are persisted.

A persistence failure is different from a portal failure. It should fail loudly because silently losing item state would break idempotency, recovery, and reporting.

## Failure Boundary

Portal failures should be represented as structured reason codes, not raw stack traces in user-facing reports.

Expected item-level failures should produce failed item outcomes and should not abort the batch.

Retryable categories include:

- portal timeout;
- temporary portal unavailability;
- dropped session;
- transient navigation failure;
- temporary stale element/layout timing issue.

Non-retryable categories include:

- locked account;
- invalid input;
- ambiguous employee match;
- expired or invalid credentials;
- validation mismatch after workflow completion.

The shared layer should own retry policy primitives. Portal workflows may classify failures, but they should not copy-paste retry loops for every step.

## Configuration And Secret Boundary

Runtime configuration belongs outside source code.

The repository may contain:

- `.env.example`;
- sample input files;
- non-secret default limits;
- documented environment variable names.

The repository must not contain:

- `.env`;
- real portal credentials;
- SMTP passwords;
- tokens;
- session cookies;
- downloaded customer files;
- reports containing sensitive information;
- screenshots with sensitive data.

Allowed secret sources:

- environment variables for local execution;
- CI/CD secrets for automation;
- a production secret manager for deployed environments.

## Observability Boundary

The implementation should make the following answerable without reading raw stack traces:

- which runs happened today;
- which portals succeeded, partially succeeded, or failed;
- which items failed and why;
- which items were skipped because they were already successful today;
- how many retries were attempted;
- which artifacts were produced;
- whether a portal stopped making progress.

At local take-home scale, SQLite rows and generated reports are acceptable foundations.

At production scale, the same events should be exported as structured logs, metrics, traces, dashboards, and alerts.

## Adding A New Portal

To add a new portal:

1. create `src/portal_automation/portals/<portal_name>/`;
2. add `input_schema.py`, `pages.py`, `workflow.py`, and `runner.py`;
3. make the runner inherit `BasePortalRunnerZX`;
4. implement only the runner hooks required by the shared lifecycle;
5. register the runner in `core/registry.py`;
6. add non-secret sample input data when useful;
7. add unit tests for schema and workflow behavior;
8. add integration tests for lifecycle, persistence, idempotency, and reporting behavior;
9. update `README.md` with the portal key and configuration notes.

Adding a portal should not require changing the base runner lifecycle or the existing portal workflows.

## Review Checklist

Before submitting the repository, check that:

- `README.md` explains local execution and configuration;
- `DESIGN.md` explains production-scale operation;
- `docs/IMPLEMENTATION_CONTRACT.md` explains runtime behavior and invariants;
- this document explains ownership boundaries;
- CI runs linting and tests;
- runtime artifacts are not committed;
- secrets are not committed;
- a dry run can be executed locally;
- real runs use Playwright-backed page objects;
- live browser tests, if present, are opt-in and clearly documented.
