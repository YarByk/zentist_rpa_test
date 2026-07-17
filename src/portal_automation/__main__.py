import argparse
import copy
import sys
import uuid
from collections.abc import Callable
from datetime import date
from typing import Any

from portal_automation.core.artifact_store import ArtifactStore
from portal_automation.core.browser import BrowserManager
from portal_automation.core.config import AppConfig
from portal_automation.core.email_connector import EmailConnector
from portal_automation.core.models import RunContext, RunStatus
from portal_automation.core.observability import RunMetricsCollector, StructuredEventLogger
from portal_automation.core.persistence import PersistenceConnector
from portal_automation.core.registry import PORTAL_RUNNERS, get_runner
from portal_automation.core.reporting import ReportGenerator
from portal_automation.core.secrets import SecretsLoader
from portal_automation.portals.orangehrm.pages import OrangeHrmPages
from portal_automation.portals.saucedemo.pages import SauceDemoPages

TRUE_VALUES = {"true", "1", "yes", "on"}
FALSE_VALUES = {"false", "0", "no", "off"}


def _parse_bool(value: str) -> bool:
    """Parse a CLI boolean value.

    Args:
        value: Raw CLI value.

    Returns:
        Parsed boolean.

    Raises:
        argparse.ArgumentTypeError: If the value is not a supported boolean spelling.
    """
    normalized = value.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    raise argparse.ArgumentTypeError(f"{value!r} must be true or false")


def _parse_business_date(value: str) -> date:
    """Parse a CLI business date.

    Args:
        value: Raw CLI value in ``YYYY-MM-DD`` format.

    Returns:
        Parsed ``date``.

    Raises:
        argparse.ArgumentTypeError: If the value is not a valid ISO date.
    """
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{value!r} must use YYYY-MM-DD format") from exc


def _build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser.

    Returns:
        Configured argument parser for portal and recovery commands.
    """
    parser = argparse.ArgumentParser(prog="portal_automation")
    subparsers = parser.add_subparsers(dest="command", required=True)
    # Register one CLI command per portal plus the convenience "all" entrypoint.
    available = [*sorted(PORTAL_RUNNERS), "all"]
    for portal_name in available:
        subparser = subparsers.add_parser(portal_name)
        subparser.add_argument("--dry-run", action="store_true")
        subparser.add_argument("--business-date", type=_parse_business_date)
        subparser.add_argument("--input", dest="input_path")
        subparser.add_argument("--headless", type=_parse_bool)
        subparser.add_argument("--email-backend", choices=["dry_run", "smtp"])
    recover_parser = subparsers.add_parser("recover")
    recover_parser.add_argument("--business-date", type=_parse_business_date, required=True)
    recover_parser.add_argument("--dry-run", action="store_true")
    return parser


def _resolve_business_date(parsed: argparse.Namespace, config: AppConfig) -> date:
    """Resolve the effective business date for a run.

    Args:
        parsed: Parsed CLI namespace.
        config: Runtime configuration from environment variables.

    Returns:
        CLI business date, configured business date, or today's date.

    Raises:
        argparse.ArgumentTypeError: If ``config.business_date`` is invalid.
    """
    # CLI input wins over environment configuration, otherwise default to today.
    if parsed.business_date is not None:
        return parsed.business_date
    if config.business_date is not None:
        return _parse_business_date(config.business_date)
    return date.today()


def _selected_portals(portal: str) -> list[str]:
    """Expand a CLI portal selection into concrete portal keys.

    Args:
        portal: Portal key or ``all``.

    Returns:
        Ordered list of portal keys to run.
    """
    if portal == "all":
        return sorted(PORTAL_RUNNERS)
    return [portal]


def _collect_stale_runs(
    persistence: PersistenceConnector,
    business_date: date,
    timeout_seconds: int,
) -> list[dict[str, Any]]:
    """Collect stale unfinished runs for one business date.

    Args:
        persistence: Persistence connector to query.
        business_date: Business date to keep.
        timeout_seconds: Stale age threshold.

    Returns:
        Stale run rows for the requested business date.
    """
    target_business_date = business_date.isoformat()
    return [
        run
        for run in persistence.find_stale_runs(timeout_seconds)
        if run["business_date"] == target_business_date
    ]


def _collect_stale_items(
    persistence: PersistenceConnector,
    business_date: date,
    timeout_seconds: int,
    stale_runs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Collect stale in-progress item rows across known portals.

    Args:
        persistence: Persistence connector to query.
        business_date: Business date to query.
        timeout_seconds: Stale age threshold.
        stale_runs: Stale run rows used to include any portal names already present.

    Returns:
        Stale item rows ordered by portal scan order.
    """
    # Recovery scans every known portal so we can repair stale item state consistently.
    portal_names = sorted({*PORTAL_RUNNERS, *(run["portal_name"] for run in stale_runs)})
    stale_items: list[dict[str, Any]] = []
    for portal_name in portal_names:
        stale_items.extend(
            persistence.find_stale_items(
                portal_name,
                business_date,
                timeout_seconds,
            )
        )
    return stale_items


def _print_recovery_summary(
    *,
    business_date: date,
    dry_run: bool,
    stale_runs: list[dict[str, Any]],
    stale_items: list[dict[str, Any]],
    recovered_runs: int = 0,
    recovered_items: int = 0,
) -> None:
    """Print a human-readable recovery summary.

    Args:
        business_date: Business date inspected by recovery.
        dry_run: Whether recovery is inspection-only.
        stale_runs: Stale run rows found.
        stale_items: Stale item rows found.
        recovered_runs: Number of runs marked stale.
        recovered_items: Number of items marked failed.
    """
    mode = "dry-run inspection" if dry_run else "recovery"
    print(f"Stale {mode} for business date {business_date.isoformat()}")
    print(f"stale_runs_found={len(stale_runs)}")
    print(f"stale_items_found={len(stale_items)}")
    for run in stale_runs:
        print(
            "stale_run "
            f"run_id={run['run_id']} portal={run['portal_name']} updated_at={run['updated_at']}"
        )
    for item in stale_items:
        print(
            "stale_item "
            f"run_id={item['run_id']} portal={item['portal_name']} "
            f"item_key={item['item_key']} operation={item['operation']} "
            f"updated_at={item['updated_at']}"
        )
    if dry_run:
        print("dry_run=true database_unchanged=true")
        return
    print(f"stale_runs_marked={recovered_runs}")
    print(f"stale_items_marked_failed={recovered_items}")


def _recover_stale_state(config: AppConfig, business_date: date, dry_run: bool) -> int:
    """Inspect or repair stale run and item state.

    Args:
        config: Runtime configuration.
        business_date: Business date to recover.
        dry_run: When true, print stale state without mutating the database.

    Returns:
        Process exit code.

    Raises:
        sqlite3.Error: If database reads or writes fail.
        OSError: If recovery artifacts cannot be written.
    """
    persistence = PersistenceConnector(config.db_path)
    artifacts = ArtifactStore(config.artifacts_dir)
    run_id = f"recover-{uuid.uuid4().hex}"
    metrics = RunMetricsCollector(
        artifacts,
        run_id=run_id,
        portal="recover",
        business_date=business_date,
    )
    logger = StructuredEventLogger(
        artifacts,
        run_id=run_id,
        portal="recover",
        business_date=business_date,
        metrics=metrics,
    )
    logger.info("recovery_started", dry_run=dry_run)
    # First inspect current stale state, then decide whether to mutate the database.
    stale_runs = _collect_stale_runs(
        persistence,
        business_date,
        config.stale_item_timeout_seconds,
    )
    stale_items = _collect_stale_items(
        persistence,
        business_date,
        config.stale_item_timeout_seconds,
        stale_runs,
    )
    if dry_run:
        metrics.items_total = len(stale_items)
        _print_recovery_summary(
            business_date=business_date,
            dry_run=True,
            stale_runs=stale_runs,
            stale_items=stale_items,
        )
        logger.info(
            "recovery_finished",
            dry_run=True,
            stale_runs_found=len(stale_runs),
            stale_items_found=len(stale_items),
        )
        metrics.write_metrics()
        return 0

    recovered_items = 0
    # Stale items are marked failed first so reruns can safely pick them up again.
    for item in stale_items:
        if persistence.mark_stale_item_failed(
            item["run_id"],
            item["portal_name"],
            business_date,
            item["item_key"],
            item["operation"],
            config.stale_item_timeout_seconds,
        ):
            recovered_items += 1

    recovered_runs = 0
    # Runs are marked stale after their child items have been repaired.
    for run in stale_runs:
        if persistence.mark_run_stale(
            run["run_id"],
            config.stale_item_timeout_seconds,
        ):
            recovered_runs += 1

    metrics.items_total = len(stale_items)
    metrics.items_failed = recovered_items

    _print_recovery_summary(
        business_date=business_date,
        dry_run=False,
        stale_runs=stale_runs,
        stale_items=stale_items,
        recovered_runs=recovered_runs,
        recovered_items=recovered_items,
    )
    logger.info(
        "recovery_finished",
        dry_run=False,
        stale_runs_found=len(stale_runs),
        stale_items_found=len(stale_items),
        stale_runs_marked=recovered_runs,
        stale_items_marked_failed=recovered_items,
    )
    metrics.write_metrics()
    return 0


def _apply_overrides(
    config: AppConfig,
    parsed: argparse.Namespace,
    selected_portals: list[str],
    parser: argparse.ArgumentParser,
) -> AppConfig:
    """Apply CLI runtime overrides to a copied config object.

    Args:
        config: Base runtime configuration.
        parsed: Parsed CLI namespace.
        selected_portals: Concrete portals selected for this run.
        parser: Parser used to report invalid argument combinations.

    Returns:
        New runtime configuration with CLI overrides applied.

    Raises:
        SystemExit: If ``--input`` is used with more than one portal.
    """
    runtime_config = copy.copy(config)
    # Runtime flags override environment defaults without mutating the base config object.
    if parsed.headless is not None:
        runtime_config.headless = parsed.headless
    if parsed.email_backend is not None:
        runtime_config.email_backend = parsed.email_backend
    if parsed.input_path is not None:
        if len(selected_portals) != 1:
            parser.error("--input can only be used with one portal")
        if selected_portals[0] == "orangehrm":
            runtime_config.orangehrm_input_path = parsed.input_path
        elif selected_portals[0] == "saucedemo":
            runtime_config.saucedemo_input_path = parsed.input_path
    return runtime_config


def _resolve_runtime_secrets(
    config: AppConfig,
    *,
    selected_portals: list[str],
    dry_run: bool,
) -> AppConfig:
    """Hydrate and validate runtime secrets for selected portals.

    Args:
        config: Runtime configuration.
        selected_portals: Concrete portals selected for this run.
        dry_run: Whether the run skips live portal work.

    Returns:
        New runtime configuration with secret fields populated.

    Raises:
        MissingSecretError: If a required live-run secret is missing.
    """
    runtime_config = copy.copy(config)
    loader = SecretsLoader(runtime_config)
    # Always hydrate optional secrets so downstream code has a consistent view of config.
    runtime_config.orangehrm_password = loader.get("ORANGEHRM_PASSWORD")
    runtime_config.saucedemo_password = loader.get("SAUCEDEMO_PASSWORD")
    runtime_config.smtp_password = loader.get("SMTP_PASSWORD")
    if dry_run:
        # Dry runs validate configuration shape but never require live portal credentials.
        return runtime_config
    if "orangehrm" in selected_portals:
        runtime_config.orangehrm_password = loader.require("ORANGEHRM_PASSWORD")
    if "saucedemo" in selected_portals:
        runtime_config.saucedemo_password = loader.require("SAUCEDEMO_PASSWORD")
    if runtime_config.email_backend == "smtp" and runtime_config.smtp_username:
        runtime_config.smtp_password = loader.require("SMTP_PASSWORD")
    return runtime_config


def _build_context(
    *,
    portal_name: str,
    config: AppConfig,
    business_date: date,
    dry_run: bool,
) -> RunContext:
    """Build the full runtime context for one portal run.

    Args:
        portal_name: Portal key.
        config: Runtime configuration.
        business_date: Business date for the run.
        dry_run: Whether the run should skip live item execution.

    Returns:
        Populated ``RunContext`` with storage, artifacts, reporting, metrics, and email helpers.
    """
    artifacts = ArtifactStore(config.artifacts_dir)
    run_id = f"{portal_name}-{uuid.uuid4().hex}"
    artifacts.run_dir(run_id)
    # Each portal run gets its own logger, metrics collector, artifacts, and persistence view.
    metrics = RunMetricsCollector(
        artifacts,
        run_id=run_id,
        portal=portal_name,
        business_date=business_date,
    )
    logger = StructuredEventLogger(
        artifacts,
        run_id=run_id,
        portal=portal_name,
        business_date=business_date,
        metrics=metrics,
    )
    return RunContext(
        run_id=run_id,
        business_date=business_date,
        dry_run=dry_run,
        stale_item_timeout_seconds=config.stale_item_timeout_seconds,
        config=config,
        persistence=PersistenceConnector(config.db_path),
        reporter=ReportGenerator(artifacts, logger=logger),
        logger=logger,
        metrics=metrics,
        artifacts=artifacts,
        email=EmailConnector(
            config.email_backend,
            artifacts,
            default_to=config.report_email_to or config.smtp_to,
            smtp_host=config.smtp_host,
            smtp_port=config.smtp_port,
            smtp_username=config.smtp_username,
            smtp_password=config.smtp_password,
            smtp_from=config.smtp_from,
            smtp_use_tls=config.smtp_use_tls,
            logger=logger,
        ),
    )


SAFE_CONSOLE_DETAIL_KEYS = frozenset(
    {
        "created_employee",
        "job_updated",
        "salary_document_uploaded",
        "created",
        "order_completed",
        "cart_count",
        "confirmation_text",
        "diagnostics",
        "expected_demo_failure",
        "item_names",
        "items_requested",
        "operator_notice",
        "subtotal",
        "tax",
        "total",
    }
)


def _build_pages_factory(portal_name: str, page: Any) -> Callable[[RunContext], Any]:
    """Build the page-object factory for a portal.

    Args:
        portal_name: Portal key.
        page: Playwright page object.

    Returns:
        Callable that creates the portal-specific page-object wrapper.

    Raises:
        ValueError: If ``portal_name`` is unknown.
    """
    # The runner only knows the portal key; this factory injects the correct page object layer.
    if portal_name == "orangehrm":
        return lambda ctx: OrangeHrmPages(page, ctx.config)
    if portal_name == "saucedemo":
        return lambda ctx: SauceDemoPages(page, ctx.config)
    raise ValueError(f"Unknown portal for pages factory: {portal_name}")


def _run_portal(
    portal_name: str,
    *,
    runner_class: Any,
    context: RunContext,
) -> Any:
    """Run one selected portal.

    Args:
        portal_name: Portal key.
        runner_class: Runner class resolved from the registry.
        context: Runtime context for the portal.

    Returns:
        Run result returned by the runner.

    Raises:
        PortalError: If live browser startup or portal execution fails with a portal-domain error.
        Exception: Any unexpected runner or browser-management error is propagated.
    """
    if context.dry_run:
        # Dry runs exercise validation and reporting only, so no browser is created.
        return runner_class().run(context)

    timeout_seconds = context.config.portal_timeout_seconds(portal_name)
    # Playwright lives for exactly one portal run and is passed down as a single page session.
    with BrowserManager(context.config, timeout_seconds=timeout_seconds) as session:
        context.diagnostics = getattr(session, "diagnostics", None)
        runner = runner_class(
            pages_factory=_build_pages_factory(portal_name, session.page),
        )
        try:
            result = runner.run(context)
        except Exception as exc:
            diagnostics = getattr(session, "diagnostics", None)
            if hasattr(diagnostics, "pause_for_visible_error"):
                diagnostics.pause_for_visible_error(
                    f"{portal_name} run failed",
                    str(exc),
                )
            raise
        diagnostics = getattr(session, "diagnostics", None)
        if hasattr(diagnostics, "pause_for_visible_result"):
            diagnostics.pause_for_visible_result(
                f"{portal_name} run finished with {result.status.value}",
                _run_visible_result_detail(context, result),
            )
        elif result.status is not RunStatus.SUCCESS and hasattr(
            diagnostics,
            "pause_for_visible_error",
        ):
            diagnostics.pause_for_visible_error(
                f"{portal_name} run finished with {result.status.value}",
                _run_visible_result_detail(context, result),
            )
        return result


def _run_visible_result_detail(context: RunContext, result: Any) -> str:
    """Return headed-browser run detail for any final status.

    Args:
        context: Runtime context.
        result: Run result returned by a portal runner.

    Returns:
        Human-readable run detail.
    """
    lines = [
        f"Run ID: {context.run_id}",
        f"Report: {context.artifacts.report_path(context.run_id)}",
        "",
        _run_result_counts(result),
    ]
    human_detail_lines = _human_run_detail_lines(result)
    if human_detail_lines:
        lines.extend(["", *human_detail_lines])
    return "\n".join(lines)


def _run_failure_detail(result: Any) -> str:
    """Return concise failed-item detail for headed-browser diagnostics.

    Args:
        result: Run result returned by a portal runner.

    Returns:
        Human-readable failed item summary.
    """
    failed_items = [
        item for item in getattr(result, "results", []) if getattr(item, "error_detail", None)
    ]
    if not failed_items:
        return ""
    lines = ["Failed item details:"]
    for item in failed_items[:5]:
        reason_code = item.reason_code.value if item.reason_code is not None else ""
        lines.append(f"- {item.item_key}: {reason_code}: {item.error_detail}")
    if len(failed_items) > 5:
        lines.append(f"- ... {len(failed_items) - 5} more failed items")
    return "\n".join(lines)


def _run_result_counts(result: Any) -> str:
    """Return a short English status/count summary for one run.

    Args:
        result: Run result returned by a portal runner.

    Returns:
        Human-readable count summary.
    """
    results = list(getattr(result, "results", []) or [])
    total = len(results)
    status_values = [
        getattr(status, "value", str(status))
        for status in (getattr(item, "status", None) for item in results)
    ]
    success = status_values.count("success")
    failed = status_values.count("failed")
    skipped = status_values.count("skipped")
    return (
        f"Status: {result.status.value}. "
        f"Completed {total} item(s): {success} succeeded, {failed} failed, {skipped} skipped."
    )


def _item_status_value(item: Any) -> str:
    """Return a stable item status string.

    Args:
        item: Item result-like object.

    Returns:
        Status value or an empty string.
    """
    status = getattr(item, "status", None)
    return getattr(status, "value", str(status or ""))


def _reason_code_value(item: Any) -> str:
    """Return a stable item reason-code string.

    Args:
        item: Item result-like object.

    Returns:
        Reason code value or an empty string.
    """
    reason_code = getattr(item, "reason_code", None)
    return getattr(reason_code, "value", str(reason_code or ""))


def _run_item_detail_lines(result: Any) -> list[str]:
    """Return English console detail lines for each item result.

    Args:
        result: Run result returned by a portal runner.

    Returns:
        One detail line per item.
    """
    lines = []
    for item in list(getattr(result, "results", []) or []):
        parts = [
            "run_item",
            f"portal={result.portal_name}",
            f"run_id={result.run_id}",
            f"item_key={getattr(item, 'item_key', '')}",
            f"operation={getattr(item, 'operation', '')}",
            f"status={_item_status_value(item)}",
            f"reason_code={_reason_code_value(item)}",
            f"attempts={getattr(item, 'attempts', '')}",
        ]
        artifact_path = getattr(item, "artifact_path", None)
        if artifact_path:
            parts.append(f"artifact_path={artifact_path}")
        error_detail = getattr(item, "error_detail", None)
        if error_detail:
            parts.append(f"error_detail={error_detail}")
        details = getattr(item, "details", None)
        if isinstance(details, dict):
            for key, value in sorted(details.items()):
                if key in SAFE_CONSOLE_DETAIL_KEYS:
                    parts.append(f"{key}={value}")
        lines.append(" ".join(parts))
    return lines


def _safe_item_details(item: Any) -> dict[str, Any]:
    """Return details safe to show in operator-facing console output.

    Args:
        item: Item result-like object.

    Returns:
        Safe detail mapping.
    """
    details = getattr(item, "details", None)
    if not isinstance(details, dict):
        return {}
    return {key: value for key, value in sorted(details.items()) if key in SAFE_CONSOLE_DETAIL_KEYS}


def _format_console_value(value: Any) -> str:
    """Format a detail value for concise human console output.

    Args:
        value: Detail value to format.

    Returns:
        Readable string value.
    """
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


def _compact_notice(value: Any) -> str:
    """Return a short operator notice for compact console and browser output.

    Args:
        value: Notice value from item details or error fields.

    Returns:
        First readable sentence, or an empty string when no notice exists.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    first_sentence, separator, _rest = text.partition(". ")
    return f"{first_sentence}." if separator else text


def _human_item_summary_lines(item: Any, index: int | None = None) -> list[str]:
    """Return compact multi-line operator-facing item details.

    Args:
        item: Item result-like object.
        index: Optional one-based item number in execution/result order.

    Returns:
        Lines ready to print in the console or show on the final browser screen.
    """
    item_key = getattr(item, "item_key", "")
    status = _item_status_value(item)
    reason_code = _reason_code_value(item)
    details = _safe_item_details(item)
    reason_suffix = f" ({reason_code})" if reason_code else ""
    prefix = f"{index}. " if index is not None else "- "

    if status == "success":
        lines = [f"{prefix}{item_key} - success"]
        if "salary_document_uploaded" in details:
            lines.append(
                "  Actions: "
                f"created_employee={details.get('created_employee')} | "
                f"job_updated={details.get('job_updated')} | "
                f"salary_document_uploaded={details.get('salary_document_uploaded')}"
            )
            return lines
        if "total" in details or "cart_count" in details:
            cart_count = details.get("cart_count", "")
            total = details.get("total", "")
            lines.append(f"  Checkout: {cart_count} product(s), {total}")
            item_names = details.get("item_names")
            if item_names:
                lines.append(f"  Products: {_format_console_value(item_names)}")
            return lines
        return lines

    if status == "skipped":
        lines = [f"{prefix}{item_key} - skipped{reason_suffix}"]
        notice = _compact_notice(
            details.get("operator_notice") or getattr(item, "error_detail", "")
        )
        if notice:
            lines.append(f"  Notice: {notice}")
        return lines

    lines = [f"{prefix}{item_key} - {status}{reason_suffix}"]
    error_detail = _compact_notice(getattr(item, "error_detail", "") or "")
    if error_detail:
        lines.append(f"  Error: {error_detail}")
    return lines


def _human_item_summary(item: Any) -> str:
    """Return human-readable item result text.

    Args:
        item: Item result-like object.

    Returns:
        Human-readable item summary.
    """
    return "\n".join(_human_item_summary_lines(item))


def _human_run_detail_lines(result: Any) -> list[str]:
    """Return operator-facing details for every item in the run.

    Args:
        result: Run result returned by the portal runner.

    Returns:
        Header plus formatted item detail lines, or an empty list when there are no items.
    """
    items = list(getattr(result, "results", []) or [])
    if not items:
        return []
    lines = ["Run details (execution order):"]
    for index, item in enumerate(items, start=1):
        lines.extend(_human_item_summary_lines(item, index=index))
    return lines


def _print_human_run_details(result: Any) -> None:
    """Print operator-facing details for the completed run.

    Args:
        result: Run result returned by the portal runner.
    """
    for line in _human_run_detail_lines(result):
        print(line)


def _run_artifact_path(context: RunContext, filename: str) -> str:
    """Return a run artifact path if it exists.

    Args:
        context: Runtime context.
        filename: Run-level artifact filename.

    Returns:
        String path or ``"not_created"``.
    """
    path = context.artifacts.run_dir(context.run_id) / filename
    return str(path) if path.exists() else "not_created"


def _print_portal_run_summary(context: RunContext, result: Any) -> None:
    """Print the concise machine-readable portal run summary line.

    Args:
        context: Runtime context.
        result: Run result returned by the portal runner.
    """
    artifacts_dir = context.artifacts.run_dir(context.run_id)
    report_path = context.artifacts.report_path(context.run_id)
    email_artifact = context.artifacts.email_report_path(context.run_id)
    email_result = str(email_artifact) if email_artifact.exists() else "not_created"
    _print_human_run_details(result)
    print("")
    print("Machine-readable details:")
    for line in _run_item_detail_lines(result):
        print(line)
    print(
        "run_summary "
        f"portal={result.portal_name} "
        f"run_id={context.run_id} "
        f"status={result.status.value} "
        f"artifacts_dir={artifacts_dir} "
        f"report_path={report_path if report_path.exists() else 'not_created'} "
        f"email_backend={context.config.email_backend} "
        f"email_artifact={email_result} "
        f"events_path={_run_artifact_path(context, 'events.jsonl')} "
        f"metrics_path={_run_artifact_path(context, 'metrics.json')}"
    )
    print(
        "run_result "
        f"portal={result.portal_name} "
        f"run_id={context.run_id} "
        f"{_run_result_counts(result)} "
        f"report_path={report_path if report_path.exists() else 'not_created'}"
    )


def _run_selected_portals(
    selected_portals: list[str],
    *,
    config: AppConfig,
    business_date: date,
    dry_run: bool,
) -> int:
    """Run all selected portals sequentially.

    Args:
        selected_portals: Portal keys to run.
        config: Runtime configuration.
        business_date: Business date for all selected portals.
        dry_run: Whether to skip live item execution.

    Returns:
        ``0`` when all selected runs succeed, otherwise ``1``.
    """
    results = []
    # The "all" command is sequential so each portal gets isolated state and artifacts.
    for portal_name in selected_portals:
        runner_class = get_runner(portal_name)
        context = _build_context(
            portal_name=portal_name,
            config=config,
            business_date=business_date,
            dry_run=dry_run,
        )
        result = _run_portal(
            portal_name,
            runner_class=runner_class,
            context=context,
        )
        results.append(result)
        _print_portal_run_summary(context, result)
    return 0 if all(result.status is RunStatus.SUCCESS for result in results) else 1


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint.

    Args:
        argv: Optional argument list; when ``None``, argparse reads process arguments.

    Returns:
        Process-style exit code.
    """
    parser = _build_parser()
    try:
        parsed = parser.parse_args(argv)
        config = AppConfig.from_env()
        if parsed.command == "recover":
            return _recover_stale_state(config, parsed.business_date, parsed.dry_run)
        selected_portals = _selected_portals(parsed.command)
        runtime_config = _apply_overrides(
            config,
            parsed,
            selected_portals,
            parser,
        )
        runtime_config = _resolve_runtime_secrets(
            runtime_config,
            selected_portals=selected_portals,
            dry_run=parsed.dry_run,
        )
        business_date = _resolve_business_date(parsed, runtime_config)
        return _run_selected_portals(
            selected_portals,
            config=runtime_config,
            business_date=business_date,
            dry_run=parsed.dry_run,
        )
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
