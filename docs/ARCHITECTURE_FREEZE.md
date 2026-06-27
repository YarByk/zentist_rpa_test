
# Architecture Freeze

**Version:** 1.2

This document freezes the architecture for the Zentist RPA Lead take-home assignment.

It is normative. All implementation work, AI-assisted code generation, tests, and documentation must conform to this document.

Source priority:

1. `Zentist_RPA_Lead_Task.pdf`
2. `company_interview_addendum_to_task_FINAL_LOCKED (1).md`
3. `zentist_final_execution_plan_checked_v11_FINAL.md`
4. `outstanding_submission_plan_FINAL_LOCKED (1).md`

If implementation details conflict with this document, the implementation must be changed. If this document conflicts with the original task PDF, the task PDF wins.

---

## 1. Architectural Goal

This repository implements a production-oriented portal automation platform, not two isolated Playwright scripts.

OrangeHRM and Sauce Demo are independent portal implementations built on the same shared execution framework. The architecture must show how the same foundation can grow from two demo portals to many external portals without changing the core execution model.

---

## 2. Architectural Principles

The architecture must follow these principles:

* shared execution framework;
* strict separation between framework logic and portal-specific logic;
* per-item isolation;
* idempotent processing;
* deterministic artifacts and reports;
* reusable failure handling;
* observable execution;
* environment-driven configuration;
* no hardcoded secrets;
* extensibility through new portal runners;
* production-oriented simplicity.

The architectural idempotency key is:

```text
business_date + portal_name + item_key + operation
```

---

## 3. Repository Boundaries

The repository is organized around clear ownership boundaries.

### `core/`

`core/` owns shared platform behavior:

* execution lifecycle;
* shared models;
* persistence;
* retries;
* reporting;
* email integration;
* configuration;
* secrets access;
* metrics;
* structured logging;
* artifacts;
* document generation;
* portal registry.

`core/` must not contain portal-specific business logic, with one explicit exception: `core/registry.py` is allowed to import concrete portal runner classes only for registration.

### `portals/`

`portals/` owns portal-specific behavior:

* browser page objects;
* portal workflows;
* portal input schemas;
* portal-specific validation;
* portal runner subclasses.

Portal modules must not own persistence, reporting, configuration loading, email delivery, or application startup.

### `tests/`

`tests/` owns verification only.

Tests must not introduce runtime behavior that production code depends on.

### CLI

The CLI owns application startup.

The CLI assembles runtime dependencies, creates the run context, resolves the requested portal through the registry, and starts execution. The CLI must not implement portal business logic.

---

## 4. Dependency Rules

The allowed runtime direction is:

```text
CLI
  -> Registry
  -> BasePortalRunnerZX
  -> Portal Runner
  -> Portal Workflow
  -> Page Objects
```

Shared services are provided to the runner through runtime context.

Forbidden dependencies:

* portal modules must not access SQLite directly;
* portal modules must not generate final reports;
* portal modules must not send email;
* portal modules must not load secrets directly;
* portal modules must not implement CLI logic;
* reporting must not depend on Playwright;
* persistence must not depend on browser objects;
* configuration must not depend on portal implementations;
* page objects must not know persistence;
* `core/` must not import from concrete portal packages.

Explicit registry exception:

* `core/registry.py` is the only place where concrete portal runner classes may be imported by `core/`;
* this exception exists only to map portal names to runner classes;
* no other `core/` module may import concrete portal packages.

---

## 5. Fixed Names

The following names are architectural constants and must not be changed.

| Purpose                    | Required name                    | Forbidden alternatives                               |
| -------------------------- | -------------------------------- | ---------------------------------------------------- |
| Base runner class          | `BasePortalRunnerZX`             | `BaseRunner`, `BasePortalRunner`, `PortalRunnerBase` |
| OrangeHRM runner class     | `OrangeHrmRunner`                | `OrangeHRMRunner`, `OrangeHrmBot`, `OrangeRunner`    |
| Sauce Demo runner class    | `SauceDemoRunner`                | `SauceRunner`, `SauceDemoBot`                        |
| Logger module              | `core/logger.py`                 | `core/logging.py`                                    |
| OrangeHRM registry key     | `"orangehrm"`                    | `"OrangeHRM"`, `"orange_hrm"`                        |
| Sauce Demo registry key    | `"saucedemo"`                    | `"SauceDemo"`, `"sauce_demo"`                        |
| OrangeHRM operation        | `"sync_employee_state"`          | `"sync"`, `"process_employee"`                       |
| Sauce Demo operation       | `"checkout"`                     | `"purchase"`, `"buy"`                                |
| README marker              | `<!-- schema-ref:zentist-r7 -->` | any other first-line format                          |
| DESIGN first diagram title | `### Figure ZQ9`                 | any other title format                               |

---

## 6. Public Runtime Components

The public runtime architecture consists of these components.

### `BasePortalRunnerZX`

The single shared execution lifecycle for portal jobs.

It owns the shared runner lifecycle and exposes the runner hooks used by portal implementations: `run`, `preflight_check`, `load_items`, `process_item`, and `finalize`.

Portal runners must use this lifecycle instead of replacing it.

### Registry

The registry maps portal names to portal runner classes.

It is the only portal discovery mechanism.

### Persistence

Persistence owns durable run state, item outcomes, idempotency, and recovery support.

### Reporting

Reporting produces run summaries from persisted results.

### Artifact Store

The artifact store owns deterministic locations for generated files, reports, screenshots, traces, and dry-run outputs.

### Retry Policy

Retry policy provides shared retry behavior for unstable portal operations.

Portal implementations must not duplicate custom retry loops.

### Configuration

Configuration is environment-driven and loaded outside portal workflows.

### Secrets

Secrets are accessed through a dedicated secrets layer.

Secrets must never appear in source code, reports, logs, or committed files.

### Portal Runners

Portal runners implement portal-specific behavior while conforming to the shared lifecycle.

### CLI

The CLI creates runtime context and starts execution.

---

## 7. Runtime Lifecycle

The application must execute in this high-level order:

1. CLI loads configuration.
2. CLI loads secrets.
3. CLI creates runtime services.
4. CLI creates the run context.
5. Registry resolves the requested portal runner.
6. `BasePortalRunnerZX` starts the shared lifecycle.
7. Input is loaded and validated.
8. Each item is processed independently.
9. Each item outcome is persisted independently.
10. Run status is finalized.
11. Report is generated.
12. Email backend is executed.
13. Artifacts are finalized.
14. Execution terminates with a coherent run result.

Dry-run branch:

* if dry-run is active, browser-related execution is skipped before any Playwright, browser, browser context, page, or portal page object is created;
* in dry-run, steps 8 and 9 are skipped entirely; `process_item(...)`, portal workflows, and portal page objects must not be called;
* dry-run must not call `preflight_check(...)` if that hook would create or touch Playwright/browser/page objects;
* dry-run may still validate configuration, validate input, resolve the registry, create run/report artifacts, and exercise non-browser wiring;
* dry-run then proceeds directly to run finalization/reporting.

---

## 8. Extension Model

A third portal is added by creating a new package under `portals/`.

The new portal package must provide:

* `runner.py`;
* `workflow.py`;
* `pages.py`;
* `input_schema.py`.

The new runner must inherit from `BasePortalRunnerZX`.

The new portal must be added to `core/registry.py`.

This registry entry is the only required modification outside the new portal package.

No other existing file should require modification.

Adding a third portal must not require changing existing portal implementations.

---

## 9. Architectural Invariants

These rules must always remain true:

* `BasePortalRunnerZX` is the single shared execution entry point.
* Portal runners do not replace the shared lifecycle.
* Every portal executes through the same orchestration model.
* Portal-specific code stays inside `portals/`.
* Shared infrastructure stays inside `core/`.
* Every item outcome is persisted independently.
* A failed item must not stop the rest of the batch.
* Idempotency is enforced through the persistence layer.
* The idempotency key is `business_date + portal_name + item_key + operation`.
* Reports are generated from persisted results.
* Dry-run must not create browser objects.
* Dry-run must not call portal workflows or portal page objects.
* Secrets must not be hardcoded.
* Registry is the only portal discovery mechanism.
* `core/registry.py` is the only `core` module allowed to import concrete portal runners.
* Adding a portal must not require modifying existing portal workflows.
* Shared connectors must be reusable across portals.
* `core/logger.py` is used for logging; `core/logging.py` must not exist.

---

## 10. Explicit Non-goals

The architecture intentionally excludes:

* web UI;
* REST API;
* production deployment;
* Kubernetes;
* distributed queues;
* production scheduler;
* Temporal or Airflow deployment;
* plugin framework;
* dependency injection container;
* microservice architecture;
* real cloud secret manager integration;
* real SMTP credentials in the repository;
* unnecessary abstraction layers.

These are production design considerations, not implementation requirements for the take-home repository.

---

## 11. Architecture Completion Criteria

The architecture is complete when a reviewer can quickly answer:

* where execution begins;
* how portal implementations are isolated;
* how shared infrastructure is reused;
* how a third portal is added;
* where persistence lives;
* where reports are generated;
* where artifacts are stored;
* where configuration and secrets originate;
* why one failed item does not stop the batch;
* why dry-run is safe for CI;
* why the project is a platform foundation rather than two scripts.

No additional architectural decisions should be required before implementation begins.


