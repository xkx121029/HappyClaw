"""`octop init` — bootstrap a fresh HappyClaw install (dirs + DB migrations).

HappyClaw is a single-user tool: the install has no account step, and the local
owner is bound on first start. The ``--admin-*`` options only exist for legacy
deployments that still provision a named admin row (for example the fnOS
package); they never prompt, and they are ignored by the single-user path.
"""

from __future__ import annotations

import click


@click.command("init")
@click.option(
    "--admin-username",
    envvar="OCTOP_ADMIN_USERNAME",
    default=None,
    help="Legacy: also create a named admin row (or set OCTOP_ADMIN_USERNAME). "
    "Single-user installs need no account and pass neither admin option.",
)
@click.option(
    "--admin-password",
    envvar="OCTOP_ADMIN_PASSWORD",
    default=None,
    help="Legacy: password for --admin-username (or set OCTOP_ADMIN_PASSWORD).",
)
@click.option(
    "--admin-display-name",
    envvar="OCTOP_ADMIN_DISPLAY_NAME",
    default=None,
    help="Legacy: optional display name for the admin row.",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help=(
        "Delete HappyClaw application state under ~/.octop before bootstrapping. "
        "Keeps the install runtime (venv/, bin/)."
    ),
)
@click.option(
    "--yes",
    "non_interactive",
    is_flag=True,
    default=False,
    help="Skip the --force confirmation prompt.",
)
def init(
    admin_username: str | None,
    admin_password: str | None,
    admin_display_name: str | None,
    force: bool,
    non_interactive: bool,
) -> None:
    """Bootstrap a HappyClaw install (~/.octop dir, DB migrations)."""
    from happyclaw.config import load_config
    from happyclaw.infra.agents.plugins.manager import PluginManager
    from happyclaw.infra.db.factory import open_database
    from happyclaw.infra.db.migrate import run_migrations
    from happyclaw.infra.db.repos.users import UserRepo
    from happyclaw.infra.errors import OctopError
    from happyclaw.infra.users.password import hash_password, validate_password_policy
    from happyclaw.infra.utils.env_file import apply_env_file, env_file_path
    from happyclaw.infra.utils.install_reset import InstallResetError, wipe_octop_state
    from happyclaw.infra.utils.paths import PathLayout

    paths = PathLayout.from_env()
    home = paths.root

    # Sidecar files (octop-login.txt, NAS share metadata) must not block first
    # bootstrap. Only an existing control-plane DB counts as an install.
    has_db = (home / "octop.db").is_file()
    if home.exists() and any(home.iterdir()):
        if has_db and not force:
            click.echo(
                f"error: {home} already exists and is not empty. Use --force to reset.",
                err=True,
            )
            raise SystemExit(1)
        if force:
            if not non_interactive:
                from happyclaw.cli.support import prompts as _prompts

                if not _prompts.confirm(
                    f"Delete HappyClaw data under {home}? The install runtime (venv, bin) is kept.",
                    default=False,
                ):
                    click.echo("aborted", err=True)
                    raise SystemExit(1)
            try:
                _removed, kept = wipe_octop_state(home)
            except InstallResetError as exc:
                click.echo(f"error: {exc}", err=True)
                raise SystemExit(1) from None
            if kept:
                names = ", ".join(path.name for path in kept)
                click.echo(f"kept install runtime: {names}")

    if (admin_username is None) != (admin_password is None):
        click.echo(
            "error: --admin-username and --admin-password are only meaningful together "
            "(a single-user install creates no account and needs neither)",
            err=True,
        )
        raise SystemExit(1)
    if admin_password is not None:
        try:
            validate_password_policy(admin_password)
        except OctopError as exc:
            click.echo(f"error: {exc.message}", err=True)
            raise SystemExit(1) from None

    paths.ensure_root()
    PluginManager(plugins_dir=paths.plugins_dir, config_path=paths.config).seed_bundled()
    apply_env_file(env_file_path(paths.root))
    config = load_config(paths.config)
    db = open_database(config, paths)
    try:
        run_migrations(db)

        if admin_username is not None:
            user_repo = UserRepo(db)
            if user_repo.get_by_username(admin_username) is not None:
                # 幂等引导（issue #1866）：外部数据库（PostgreSQL）不会在 ~/.octop
                # 生成 octop.db，容器重启后 entrypoint 会重跑 init；此时跳过创建，
                # 避免管理员 INSERT 撞 UNIQUE(username) 直接崩溃。
                click.echo(f"  admin user '{admin_username}' already exists, skipping.")
            else:
                user_repo.create(
                    username=admin_username,
                    password_hash=hash_password(admin_password or ""),
                    role="admin",
                    display_name=admin_display_name,
                )
    finally:
        db.close()

    click.echo(f"\u2705 HappyClaw bootstrapped at {home}")
    if admin_username is not None:
        click.echo(f"   legacy admin user: {admin_username}")
    else:
        click.echo("   single user: no account needed (the local owner is bound on first start)")
    click.echo("   next: `octop run` (optional: `octop agent use <id>` to pin default agent)")
