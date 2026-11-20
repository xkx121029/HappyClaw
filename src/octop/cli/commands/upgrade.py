"""octop upgrade — one-shot upgrade of an Octop install to the projects model."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from octop.cli.support.db import open_cli_services, resolve_cli_locale


@click.group("upgrade")
def upgrade() -> None:
    """Upgrade an existing install: workspaces become projects, history is kept."""


@upgrade.command("plan")
@click.option(
    "--report-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Where to write plan.json / group-changes.md (default: a timestamped dir).",
)
def plan_cmd(report_dir: Path | None) -> None:
    """Scan the install read-only and write the migration reports."""
    from octop.infra.migration.octop_upgrade import scan_install, write_plan_reports

    locale = resolve_cli_locale()
    with open_cli_services() as services:
        plan = scan_install(services=services, locale=locale, report_dir=report_dir)
        write_plan_reports(plan)

    click.echo(f"report dir: {plan.report_dir}")
    click.echo(f"experts: {plan.agent_count}  threads: {plan.thread_count}")
    click.echo(f"workspaces: {len(plan.workspaces)}  conflicts: {len(plan.conflicts)}")
    if plan.requires_choice:
        click.echo("")
        click.echo("This install needs a grouping choice before apply:")
        click.echo(f"  - {CHOICE_DATA_FIRST_HELP}")
        click.echo(f"  - {CHOICE_MERGE_DEFAULT_HELP}")
        click.echo("See group-changes.md for the per-thread impact.")
    else:
        click.echo("No grouping conflict: all workspaces map 1:1 to projects.")


CHOICE_DATA_FIRST_HELP = (
    "data-first: files and history stay in place; sidebar grouping may change."
)
CHOICE_MERGE_DEFAULT_HELP = (
    "merge-default: grouping is kept, but files are copied, paths change, "
    "and checkpoints cannot be merged."
)


def _resolve_choice(choice: str | None) -> str | None:
    from octop.infra.migration.octop_upgrade import CHOICES

    if choice is not None:
        return choice
    if not sys.stdin.isatty():
        return None
    click.echo("")
    click.echo("Choose how to handle default workspaces that contain user files:")
    click.echo(f"  1. {CHOICE_DATA_FIRST_HELP}")
    click.echo(f"  2. {CHOICE_MERGE_DEFAULT_HELP}")
    picked = click.prompt("Choice", type=click.Choice(CHOICES))
    return str(picked)


@upgrade.command("apply")
@click.option(
    "--report-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Report directory produced by `octop upgrade plan`.",
)
@click.option(
    "--choice",
    type=click.Choice(["data-first", "merge-default"]),
    default=None,
    help="Required when a default workspace contains user files.",
)
@click.option("--dry-run", is_flag=True, help="Validate the plan; write nothing.")
@click.option("--no-backup", is_flag=True, help="Skip the pre-upgrade full backup.")
def apply_cmd(
    report_dir: Path | None, choice: str | None, dry_run: bool, no_backup: bool
) -> None:
    """Bind threads to projects and copy expert config into private directories."""
    from octop.infra.migration.octop_upgrade import (
        UpgradeChoiceRequired,
        UpgradeError,
        apply_upgrade,
        scan_install,
        verify_upgrade,
        write_plan_reports,
    )

    locale = resolve_cli_locale()
    try:
        with open_cli_services() as services:
            plan = scan_install(services=services, locale=locale, report_dir=report_dir)
            write_plan_reports(plan)
            resolved = _resolve_choice(choice)
            report = apply_upgrade(
                plan,
                services=services,
                choice=resolved,
                dry_run=dry_run,
                backup=not no_backup,
            )
            if not dry_run:
                failures = verify_upgrade(plan, services=services, report=report)
                report.failures.extend(failures)
    except UpgradeChoiceRequired as exc:
        raise click.ClickException(
            f"{exc.message}\nRun `octop upgrade apply --choice data-first|merge-default`."
        ) from exc
    except UpgradeError as exc:
        raise click.ClickException(exc.message) from exc

    click.echo(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    if not report.ok:
        raise SystemExit(1)


@upgrade.command("verify")
@click.option(
    "--report-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
)
def verify_cmd(report_dir: Path | None) -> None:
    """Re-check that every thread and project points at existing data."""
    from octop.infra.migration.octop_upgrade import scan_install, verify_upgrade, write_plan_reports

    locale = resolve_cli_locale()
    with open_cli_services() as services:
        plan = scan_install(services=services, locale=locale, report_dir=report_dir)
        write_plan_reports(plan)
        failures = verify_upgrade(plan, services=services)
        target = plan.report_dir
    click.echo(json.dumps({"ok": not failures, "failures": failures}, indent=2, ensure_ascii=False))
    click.echo(f"diff: {target / 'diff.md'}")
    if failures:
        raise SystemExit(1)


@upgrade.command("rollback")
@click.option(
    "--report-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    required=True,
    help="Report directory of the applied upgrade.",
)
def rollback_cmd(report_dir: Path) -> None:
    """Undo the recorded upgrade using the choice made at apply time."""
    from octop.infra.migration.octop_upgrade import UpgradeError, rollback_upgrade

    try:
        with open_cli_services() as services:
            failures = rollback_upgrade(services=services, report_dir=report_dir)
    except UpgradeError as exc:
        raise click.ClickException(exc.message) from exc
    click.echo(json.dumps({"ok": not failures, "failures": failures}, indent=2))
    if failures:
        raise SystemExit(1)
