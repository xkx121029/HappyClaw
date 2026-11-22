"""Build the dashboard and stamp the output used by the backend bundle.

``make package-backend`` used to package whatever was left in
``src/happyclaw/dashboard`` from an older build, so a release could silently ship an
old UI. This script is now the first step of packaging:

1. installs npm deps when ``node_modules`` is missing/stale (``npm ci``);
2. runs the production Vite build (``tsc -b && vite build``) — any failure
   aborts packaging;
3. writes ``version.json`` (git commit + build time + sha256 of ``index.html``)
   into the build output so the running server can report which UI it ships.

The output directory is ``src/happyclaw/dashboard`` (``vite.config.ts`` ``outDir``),
which is gitignored and collected by ``octop.spec``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DASHBOARD_DIR = REPO_ROOT / "dashboard"
DEFAULT_OUT_DIR = REPO_ROOT / "src" / "octop" / "dashboard"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(cmd: list[str], cwd: Path, env: dict[str, str] | None = None, timeout: float = 1800.0) -> None:
    print(f"[dashboard] $ {' '.join(cmd)}", flush=True)
    try:
        proc = subprocess.run(cmd, cwd=str(cwd), env=env, check=False, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise SystemExit(f"[dashboard] 命令超时（>{timeout:.0f}s）：{' '.join(cmd)}") from None
    if proc.returncode != 0:
        raise SystemExit(f"[dashboard] 命令失败（exit={proc.returncode}）：{' '.join(cmd)}")


def npm_cmd(*args: str) -> list[str]:
    if os.name == "nt":
        return ["cmd", "/c", "npm", *args]
    return ["npm", *args]


def git(*args: str) -> str:
    try:
        out = subprocess.run(
            ["git", *args], cwd=str(REPO_ROOT), capture_output=True, text=True, check=False
        )
    except OSError:
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def dependencies_stale(dashboard_dir: Path) -> bool:
    lock = dashboard_dir / "package-lock.json"
    marker = dashboard_dir / "node_modules" / ".package-lock.json"
    if not marker.is_file():
        return True
    if not lock.is_file():
        return False
    return lock.stat().st_mtime > marker.stat().st_mtime


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dashboard-dir", default=str(DEFAULT_DASHBOARD_DIR))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--skip-install", action="store_true")
    parser.add_argument("--timeout", type=float, default=1800.0)
    args = parser.parse_args()

    dashboard_dir = Path(args.dashboard_dir).resolve()
    out_dir = Path(args.out_dir).resolve()
    if not (dashboard_dir / "package.json").is_file():
        print(f"[dashboard] 找不到 {dashboard_dir / 'package.json'}")
        return 2
    if shutil.which("npm") is None:
        print("[dashboard] 未找到 npm：请安装 Node.js 后再打包后端")
        return 2

    started = time.perf_counter()
    if not args.skip_install and dependencies_stale(dashboard_dir):
        run(npm_cmd("ci"), dashboard_dir, timeout=args.timeout)
    else:
        print("[dashboard] node_modules 已是最新，跳过 npm ci", flush=True)

    env = os.environ.copy()
    env["NODE_ENV"] = "production"
    env["NODE_OPTIONS"] = "--max-old-space-size=4096"
    env["VITE_BUILD_COMMIT"] = git("rev-parse", "HEAD")
    env["VITE_BUILD_TIME"] = datetime.now(tz=UTC).isoformat(timespec="seconds")

    # Never fall back to a previous build: Vite runs with emptyOutDir=true, and
    # this check makes a missing/empty result a hard failure.
    run(npm_cmd("run", "build"), dashboard_dir, env=env, timeout=args.timeout)

    index = out_dir / "index.html"
    if not index.is_file() or index.stat().st_size == 0:
        print(f"[dashboard] 构建没有产出有效入口文件：{index}")
        return 1

    stamp = {
        "git_commit": env["VITE_BUILD_COMMIT"],
        "git_dirty": bool(git("status", "--porcelain", "dashboard")),
        # Completion time: what a package reviewer means by "this build".
        "dashboard_built_at": datetime.now(tz=UTC).isoformat(timespec="seconds"),
        "index_sha256": sha256_file(index),
        "build_seconds": round(time.perf_counter() - started, 1),
    }
    (out_dir / "version.json").write_text(
        json.dumps(stamp, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[dashboard] 产物：{out_dir}", flush=True)
    print(f"[dashboard] 版本戳：{json.dumps(stamp, ensure_ascii=False)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
