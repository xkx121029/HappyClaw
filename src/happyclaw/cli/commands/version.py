"""happyclaw version command."""

from __future__ import annotations

import click


@click.command("version")
def version() -> None:
    """Show the installed HappyClaw version."""
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as _v

    v = "unknown"
    for dist in ("happyclaw", "octop"):
        try:
            v = _v(dist)
            break
        except PackageNotFoundError:
            continue
    click.echo(f"happyclaw v{v}")
