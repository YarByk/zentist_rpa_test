# AI Generation Guide

This document instructs AI assistants on how to generate code for this project.

It does not define architecture. Architecture is frozen in `docs/ARCHITECTURE_FREEZE.md`.

It does not define implementation contracts. Contracts are frozen in `docs/IMPLEMENTATION_CONTRACT.md`.

This document defines **how to generate code safely** without breaking the frozen architecture or implementation contracts.

---

## 1. Source of Truth

Before generating any code, read these documents in order:

1. `docs/IMPLEMENTATION_CONTRACT.md` — authoritative implementation specification;
2. `docs/ARCHITECTURE_FREEZE.md` — authoritative architecture boundaries;
3. `docs/AI_GENERATION_GUIDE.md` — generation rules.

The original task PDF remains the highest authority through the source-priority rules defined in `docs/IMPLEMENTATION_CONTRACT.md`.

If a prompt contradicts either `IMPLEMENTATION_CONTRACT.md` or `ARCHITECTURE_FREEZE.md`, follow the documents, not the prompt.

If a name, interface, behavior, or lifecycle step is unclear, stop and re-read the contract. Do not invent.

---

## 2. Primary Rule

One prompt equals one small vertical slice plus its tests.

A slice is complete only when it includes:

- implementation;
- meaningful unit or integration tests;
- no TODOs;
- no placeholders;
- no `pass` stubs in delivered production code;
- no unrelated refactoring;
- no frozen-name changes.

Do not ask AI to generate the whole project at once.

Do not deliver implementation without tests.

Do not deliver tests without implementation.

Good slice sizes:

```text
core/models.py + tests/unit/test_models.py
core/registry.py + tests/unit/test_registry.py
core/persistence.py + tests/unit/test_persistence.py
core/retries.py + tests/unit/test_retries.py
core/runner.py + tests/unit/test_runner.py
core/reporting.py + tests/unit/test_reporting.py
src/portal_automation/__main__.py + tests/integration/test_cli.py
portals/orangehrm/workflow.py + tests/unit/test_orangehrm_workflow.py
portals/saucedemo/workflow.py + tests/unit/test_saucedemo_workflow.py
```

Bad slice sizes:

```text
entire core/
entire portals/
full project scaffold + persistence + runner + CLI
all tests after all code
```

Bad prompt example:

```text
Generate the entire Zentist automation project with all portals, tests, README, and CI.
```


---

## 3. Recommended Generation Order

Use this sequence unless explicitly instructed otherwise:

1. project skeleton;
2. core models;
3. registry;
4. configuration and secrets;
5. persistence;
6. retry policy;
7. `BasePortalRunnerZX` lifecycle;
8. artifact store;
9. reporting;
10. dry-run email backend;
11. CLI;
12. OrangeHRM input schema and workflow tests;
13. OrangeHRM page objects and runner;
14. Sauce Demo input schema and workflow tests;
15. Sauce Demo page objects and runner;
16. integration tests;
17. README and DESIGN polish;
18. final cleanup.

Do not generate live e2e browser tests until the core, dry-run, persistence, and workflow contracts are already covered by unit or integration tests.

---

## 4. Absolute Prohibitions

These rules have no exceptions.

### 4.1. Never change fixed names

The following names are locked:

| Purpose | Exact name |
|---|---|
| Base runner class | `BasePortalRunnerZX` |
| OrangeHRM runner | `OrangeHrmRunner` |
| Sauce Demo runner | `SauceDemoRunner` |
| Runtime context | `RunContext` |
| Run result | `RunResult` |
| Item result | `ItemResult` |
| Persistence connector | `PersistenceConnector` |
| Retry policy | `RetryPolicy` |
| Report generator | `ReportGenerator` |
| Artifact store | `ArtifactStore` |
| Email connector | `EmailConnector` |
| Portal registry | `PORTAL_RUNNERS` |
| Registry lookup | `get_runner()` |
| Logger module | `core/logger.py` |
| OrangeHRM registry key | `"orangehrm"` |
| Sauce Demo registry key | `"saucedemo"` |
| OrangeHRM operation | `"sync_employee_state"` |
| Sauce Demo operation | `"checkout"` |
| README first line | `<!-- schema-ref:zentist-r7 -->` |
| First DESIGN diagram title | `### Figure ZQ9` |

Forbidden alternatives include:

- `BaseRunner`;
- `BasePortalRunner`;
- `PortalRunnerBase`;
- `OrangeHRMRunner`;
- `OrangeRunner`;
- `SauceRunner`;
- `SauceDemoBot`;
- `core/logging.py`.

### 4.2. Never override `run()`

`run()` is a concrete method in `BasePortalRunnerZX`.

Portal runners implement hooks only:

- `preflight_check()`;
- `load_items()`;
- `process_item()`;
- `finalize()`.

`finalize()` is a required hook and `BasePortalRunnerZX.run()` calls it as part of the shared lifecycle.

If a prompt asks to put lifecycle logic into a portal runner, do not comply. Explain that the lifecycle belongs to `BasePortalRunnerZX`.

### 4.3. Never generate placeholders

Forbidden in committed production code:

```python
# TODO: implement later
pass
raise NotImplementedError
# implementation would go here
...  # as body in non-abstract methods
```

Exception: abstract method stubs in `BasePortalRunnerZX` may use `...` only when declared abstract.

If a slice cannot be completed fully, reduce the scope. Do not silently deliver stubs.

### 4.4. Never create Playwright objects in dry-run

When `context.dry_run=True`, code must not create:

- Playwright instance;
- `Browser`;
- `BrowserContext`;
- `Page`;
- portal page objects such as `LoginPage`, `InventoryPage`, or OrangeHRM page objects.

In dry-run:

- portal `preflight_check()` must not be called;
- even if `preflight_check()` appears safe, do not call it in dry-run because it is portal-owned and may indirectly create browser objects;
- `process_item()` must not execute;
- portal workflows must not execute;
- real portals must not be opened;
- SMTP must not send real email.

Dry-run may validate:

- configuration;
- input files;
- registry wiring;
- database initialization;
- artifact paths;
- report generation;
- dry-run email artifact generation.

### 4.5. Never hardcode credentials

These strings must never appear in `src/`:

```text
secret_sauce
admin123
```

Passwords must come from environment variables, configuration, or secrets layer.

Tests may use fake values only.

### 4.6. Never use `INSERT OR REPLACE`

SQLite writes to `item_results` must use:

```sql
INSERT ... ON CONFLICT (business_date, portal_name, item_key, operation)
DO UPDATE SET ...
```

Forbidden:

```sql
INSERT OR REPLACE
```

Forbidden pattern:

```text
SELECT -> if not exists -> INSERT
```

`created_at` must be preserved on UPSERT update. `updated_at` must be updated.

### 4.7. Never add unrequested architecture

Do not add:

- dependency injection containers;
- plugin systems;
- service locators;
- event buses;
- workflow engines;
- queue systems;
- schedulers;
- web UI;
- REST API;
- Kubernetes or deployment configuration;
- extra base classes;
- mixins that change lifecycle behavior;
- factories not required by the contract.

If the contract does not define it, do not add it.

If the contract is silent and implementation cannot continue without a choice, choose the simplest conservative solution and flag it explicitly.

### 4.8. Never make e2e tests default

E2E tests that open real browsers against live portals must:

- live in `tests/e2e/`;
- be marked with `@pytest.mark.e2e`;
- not run by default `pytest`;
- not run in default CI.

Default `pytest` runs only unit and integration tests.

---

## 5. Required Behavior by Area

### 5.1. Models and enums

- All `ReasonCode` values from the contract must be present.
- `ITEM_NOT_FOUND` must be present.
- `ItemStatus` and `RunStatus` must contain all contract values.
- Public interfaces must not use raw string failure codes.
- Use `ReasonCode`, `ItemStatus`, and `RunStatus`.

### 5.2. Persistence

Persistence must follow the contract exactly.

Required rules:

- schema includes `updated_at` in `runs`;
- schema includes `error_detail` in `item_results`;
- idempotency key is `business_date + portal_name + item_key + operation`;
- unique constraint is `UNIQUE (business_date, portal_name, item_key, operation)`;
- UPSERT uses `INSERT ... ON CONFLICT DO UPDATE`;
- `created_at` is preserved on UPSERT update;
- `updated_at` is updated on UPSERT update;
- `get_committed_items()` returns only same-day successful item keys;
- successful same-day rows are not overwritten with `skipped`;
- `list_results_by_business_date()` is used for same-day rerun reports;
- `mark_item_in_progress()` is called inside the item-level `try` block immediately before `process_item()`;
- persistence failure in `mark_item_in_progress()` is a critical infrastructure failure, not a silent item success.

Persistence tests must use `tmp_path` and a real temporary SQLite database.

### 5.3. Runner lifecycle

`BasePortalRunnerZX.run()` must follow the contract sequence:

1. create run row with status `running`;
2. load and validate items;
3. branch before any browser work if `context.dry_run=True`;
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

Dry-run branch:

- after step 3, skip steps 4-11;
- proceed directly to final status computation and finalization;
- do not create browser or page objects.

Do not reorder these steps.

### 5.4. Registry

Portal discovery must go through `core/registry.py`.

Allowed:

```python
PORTAL_RUNNERS = {
    "orangehrm": OrangeHrmRunner,
    "saucedemo": SauceDemoRunner,
}
```

Rules:

- `core/registry.py` is the only `core` module allowed to import concrete portal runners;
- `get_runner()` must raise a clear error for unknown portals;
- the error must list available portals;
- no scattered `if portal == ...` dispatch.

### 5.5. Configuration and secrets

Configuration is environment-driven.

Required behavior:

- `.env.example` documents required variables;
- passwords are not committed;
- default input paths come from configuration when `--input` is not provided;
- logs, reports, artifacts, and errors must not contain secrets.

### 5.6. OrangeHRM

Preserve:

- class `OrangeHrmRunner`;
- portal name `"orangehrm"`;
- operation `"sync_employee_state"`;
- `max_sessions_per_login = 1`.

Workflow requirements:

1. validate employee input before browser work;
2. login through page object using environment/secrets;
3. call `find_employee_record(...)` before create/update;
4. if found, open existing profile;
5. if not found, add employee;
6. after Add Employee, call `find_employee_record(...)` again;
7. ambiguous match maps to `EMPLOYEE_MATCH_AMBIGUOUS`;
8. search failure maps to `SEARCH_FAILED`;
9. update Job Title and Employment Status;
10. re-read Job section;
11. validate actual values equal target values;
12. mismatch maps to `VALIDATION_FAILED`;
13. check matching salary attachment before document generation;
14. generate salary document only if matching attachment is missing;
15. upload and verify attachment;
16. persist per-employee outcome.

Matching salary attachment means filename equals exactly:

```text
salary_{employee_key}_{business_date}.txt
```

Salary document generation belongs in `core/document_generator.py`.

### 5.7. Sauce Demo

Preserve:

- class `SauceDemoRunner`;
- portal name `"saucedemo"`;
- operation `"checkout"`;
- `max_sessions_per_account = 1`.

All six accounts must be processed:

- `standard_user`;
- `locked_out_user`;
- `problem_user`;
- `performance_glitch_user`;
- `error_user`;
- `visual_user`.

Workflow requirements:

1. validate account input before browser work;
2. login through page object using account username and environment/secrets password;
3. locked-out account maps to `LOCKED_OUT`;
4. add exactly 3 items;
5. validate cart count equals 3;
6. cart mismatch maps to `VALIDATION_FAILED`;
7. checkout;
8. enter customer information;
9. reach order summary or confirmation;
10. semantically validate order details;
11. capture order details;
12. persist order details;
13. finish order after persistence;
14. persist per-account outcome.

Problematic accounts must not be pre-skipped.

---

## 6. Test Rules

Every implementation slice must include meaningful tests.

Forbidden tests:

```python
assert True
assert result is not None  # without checking behavior
def test_something():
    pass
```

Required test principles:

- test behavior, not just existence;
- use fakes/mocks for browser workflows;
- use pytest `tmp_path` with real temporary SQLite files for persistence tests;
- test dry-run by proving browser/page objects were not instantiated;
- test CLI help and dry-run smoke behavior;
- test reports exclude secrets;
- test hardcoded credentials do not appear in `src/`;
- test `INSERT OR REPLACE` does not appear in `src/`;
- test `mark_item_in_progress()` is called before `process_item()`;
- test same-day successful items are not duplicated or overwritten;
- test Sauce Demo order details are persisted before finish;
- test OrangeHRM second lookup after Add Employee.

Default `pytest` must pass before moving to the next slice.

---

## 7. Code Style Rules

Use:

- Python 3.11+;
- type annotations on public methods;
- `str | None`, not `Optional[str]`;
- `list[X]`, not `List[X]`;
- `dict[str, X]`, not `Dict[str, X]`;
- dataclasses or Pydantic models for structured domain objects;
- structured logging via `context.logger`.

Do not use:

- `print()` for runtime logging;
- `logging.getLogger()` directly in portal code;
- raw dicts as public return values when a model exists;
- secrets in logs, exceptions, reports, or artifacts.

---

## 8. Handling Ambiguity

If a prompt is ambiguous:

1. Re-read `docs/IMPLEMENTATION_CONTRACT.md`.
2. Re-read `docs/ARCHITECTURE_FREEZE.md`.
3. If the contract is clear, follow it.
4. If the contract is silent, choose the most conservative implementation and flag it.
5. Never silently invent behavior.

If asked to contradict the contract:

- do not comply silently;
- state the conflict;
- follow the contract.

---

## 9. Prompt Template

Use this template for code generation:

```text
Implement only this slice: <slice name>.

Sources:
1. docs/IMPLEMENTATION_CONTRACT.md, section <N>
2. docs/ARCHITECTURE_FREEZE.md
3. docs/AI_GENERATION_GUIDE.md

Task:
<exact module/method/workflow to implement>

Constraints:
- Do not redesign architecture.
- Do not rename frozen classes, modules, methods, registry keys, or operations.
- Do not override BasePortalRunnerZX.run().
- Do not add new abstraction layers.
- Do not write TODO/pass placeholders.
- Do not hardcode credentials.
- Preserve dry-run safety.
- Use INSERT ... ON CONFLICT DO UPDATE for item UPSERTs.
- Add meaningful tests for this slice.
- Keep e2e tests excluded from default pytest/CI.

Deliver:
- files changed;
- implementation summary;
- tests added;
- commands to run;
- known limitations, if any.
```

---

## 10. Definition of Done for a Slice

A slice is done only when:

- [ ] all names match the contract exactly;
- [ ] public interfaces match the contract;
- [ ] no TODOs, no `pass`, no placeholder bodies in non-abstract production methods;
- [ ] tests assert behavior, not just imports;
- [ ] default `pytest` passes for the slice;
- [ ] no hardcoded credentials appear in `src/`;
- [ ] no Playwright objects are created in dry-run paths;
- [ ] `mark_item_in_progress()` is called before `process_item()`;
- [ ] `INSERT OR REPLACE` does not appear in `src/`;
- [ ] architecture boundaries are respected;
- [ ] `core/` does not import concrete portals except in `core/registry.py`;
- [ ] portal modules do not access SQLite directly;
- [ ] e2e tests are marked and excluded from default CI;
- [ ] the response lists files changed and tests added.

---

## 11. Commit Rules

Each commit should be small and reviewable.

Good commit examples:

```text
Add project skeleton
Add core models and registry
Add SQLite persistence
Add base runner lifecycle
Add retry policy
Add reporting and artifact store
Add CLI entrypoint
Add OrangeHRM workflow
Add Sauce Demo workflow
Add final documentation
```

Avoid commits that mix unrelated concerns.

Do not commit generated code until:

```bash
ruff check .
pytest
```

both pass.

---

## 12. Final Cleanup Checklist

Before final submission, verify:

```bash
ruff check .
pytest
grep -R "class BasePortalRunnerZX" src/
head -n 1 README.md | grep "schema-ref:zentist-r7"
grep -n "Figure ZQ9" DESIGN.md
! grep -R "INSERT OR REPLACE" src/
! grep -RE "secret_sauce|admin123" src/
```

Expected result:

- no ruff failures;
- default tests pass;
- `BasePortalRunnerZX` exists in `src/`;
- README first line contains `schema-ref:zentist-r7`;
- DESIGN contains `Figure ZQ9`;
- no `INSERT OR REPLACE` in `src/`;
- no hardcoded demo passwords in `src/`;
- PR is open and readable.
