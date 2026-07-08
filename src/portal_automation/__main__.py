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
    normalized = value.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    raise argparse.ArgumentTypeError(f"{value!r} must be true or false")


def _parse_business_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"{value!r} must use YYYY-MM-DD format"
        ) from exc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="portal_automation")
    subparsers = parser.add_subparsers(dest="command", required=True)
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
    if parsed.business_date is not None:
        return parsed.business_date
    if config.business_date is not None:
        return _parse_business_date(config.business_date)
    return date.today()


def _selected_portals(portal: str) -> list[str]:
    if portal == "all":
        return sorted(PORTAL_RUNNERS)
    return [portal]


def _collect_stale_runs(
    persistence: PersistenceConnector,
    business_date: date,
    timeout_seconds: int,
) -> list[dict[str, Any]]:
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
    runtime_config = copy.copy(config)
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
    runtime_config = copy.copy(config)
    loader = SecretsLoader(runtime_config)
    runtime_config.orangehrm_password = loader.get("ORANGEHRM_PASSWORD")
    runtime_config.saucedemo_password = loader.get("SAUCEDEMO_PASSWORD")
    runtime_config.smtp_password = loader.get("SMTP_PASSWORD")
    if dry_run:
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
    artifacts = ArtifactStore(config.artifacts_dir)
    run_id = f"{portal_name}-{uuid.uuid4().hex}"
    artifacts.run_dir(run_id)
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


def _build_pages_factory(portal_name: str, page: Any) -> Callable[[RunContext], Any]:
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
    if context.dry_run:
        return runner_class().run(context)

    with BrowserManager(context.config) as session:
        runner = runner_class(
            pages_factory=_build_pages_factory(portal_name, session.page),
        )
        return runner.run(context)


def _run_selected_portals(
    selected_portals: list[str],
    *,
    config: AppConfig,
    business_date: date,
    dry_run: bool,
) -> int:
    results = []
    for portal_name in selected_portals:
        runner_class = get_runner(portal_name)
        context = _build_context(
            portal_name=portal_name,
            config=config,
            business_date=business_date,
            dry_run=dry_run,
        )
        results.append(
            _run_portal(
                portal_name,
                runner_class=runner_class,
                context=context,
            )
        )
    return 0 if all(result.status is RunStatus.SUCCESS for result in results) else 1


def main(argv: list[str] | None = None) -> int:
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
