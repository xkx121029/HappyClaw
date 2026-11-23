"""PyInstaller entry point for the standalone backend build.

Mirrors the ``octop`` console script (``happyclaw.cli.main:cli``) so the frozen
binary exposes exactly the same CLI surface as a pip install.
"""

from happyclaw.cli.main import cli

if __name__ == "__main__":
    cli()
