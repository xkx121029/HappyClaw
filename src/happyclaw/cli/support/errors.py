"""CLI error helpers."""

from __future__ import annotations

from typing import NoReturn

import click

from happyclaw.infra.errors import HappyclawError


def fail_octop(exc: HappyclawError) -> NoReturn:
    click.echo(f"error: {exc.message}", err=True)
    raise SystemExit(1) from exc
