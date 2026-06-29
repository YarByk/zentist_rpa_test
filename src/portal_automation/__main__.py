import argparse
import copy
import sys
import uuid
from datetime import date
from typing import Any

from portal_automation.core.artifact_store import ArtifactStore
from portal_automation.core.config import AppConfig
from portal_automation.core.email_connector import EmailConnector
from portal_automation.core.models import RunContext, RunStatus
from portal_automation.core.persistence import PersistenceConnector
from portal_automation.core.registry import PORTAL_RUNNERS, get_runner
from portal_automation.core.reporting import ReportGenerator

TRUE_VALUES = {"true", "1", "yes", "on"}
FALSE_VALUES = {"false", "0", "no", "off"}


class _NoOpLogger:
    def error(self, *args: Any, **kwargs: Any) -> None:
        return


class _NoOpMetrics:
    def __repr__(self) -> str:
        return "_NoOpMetrics()"


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
    subparsers = parser.add_subparsers(dest="portal", required=True)
    available = [*sorted(PORTAL_RUNNERS), "all"]
    for portal_name in available:
        subparser = subparsers.add_parser(portal_name)
        subparser.add_argument("--dry-run", action="store_true")
        subparser.add_argument("--business-date", type=_parse_business_date)
        subparser.add_argument("--input", dest="input_path")
        subparser.add_argument("--headless", type=_parse_bool)
        subparser.add_argument("--email-backend", choices=["dry_run", "smtp"])
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
    return RunContext(
        run_id=run_id,
        business_date=business_date,
        dry_run=dry_run,
        stale_item_timeout_seconds=config.stale_item_timeout_seconds,
        config=config,
        persistence=PersistenceConnector(config.db_path),
        reporter=ReportGenerator(artifacts),
        logger=_NoOpLogger(),
        metrics=_NoOpMetrics(),
        artifacts=artifacts,
        email=EmailConnector(config.email_backend, artifacts),
    )


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
        results.append(runner_class().run(context))
    return 0 if all(result.status is RunStatus.SUCCESS for result in results) else 1


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        parsed = parser.parse_args(argv)
        selected_portals = _selected_portals(parsed.portal)
        config = _apply_overrides(
            AppConfig.from_env(),
            parsed,
            selected_portals,
            parser,
        )
        business_date = _resolve_business_date(parsed, config)
        return _run_selected_portals(
            selected_portals,
            config=config,
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
