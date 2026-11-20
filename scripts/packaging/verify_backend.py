"""Post-build smoke check for the standalone (PyInstaller) backend bundle.

Verifies the five things that break when a Python app is frozen and shipped to
a machine that has no Python:

0. the agent stack is importable and an agent graph compiles (``exe selfcheck``)
   — lazy deps like numpy/tiktoken only surface on the first chat turn;
1. ``OCTOP_HOME`` an env-provided home is honoured (DB / logs / data land there);
2. the bundled dashboard is served (SPA shell, ``index.html``, hashed assets)
   **and is the one built for this package** (index.html sha256 + version stamp);
3. Playwright is importable, its Chromium search path is reported, and a
   missing browser degrades to a Chinese hint instead of crashing;
4. logs go to ``<home>/logs`` — nothing is written into ``_internal``.

Usage (called by ``make package-backend``):

    python scripts/packaging/verify_backend.py --exe dist/backend/octop/octop.exe
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ASSET_RE = re.compile(r'/assets/[A-Za-z0-9._-]+\.(?:js|css)')

_failures: list[str] = []


def ok(label: str, detail: str = "") -> None:
    print(f"  [通过] {label}{('：' + detail) if detail else ''}")


def fail(label: str, detail: str) -> None:
    print(f"  [失败] {label}：{detail}")
    _failures.append(f"{label}: {detail}")


def opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get(op: urllib.request.OpenerDirector, url: str, timeout: float = 3.0):
    with op.open(url, timeout=timeout) as resp:
        return resp.status, resp.headers.get("content-type", ""), resp.read()


def tree_stats(root: Path) -> tuple[int, int]:
    count = 0
    size = 0
    for path in root.rglob("*"):
        if path.is_file():
            count += 1
            try:
                size += path.stat().st_size
            except OSError:
                pass
    return count, size


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def wait_health(op: urllib.request.OpenerDirector, base: str, proc, timeout: float) -> float | None:
    started = time.perf_counter()
    while time.perf_counter() - started < timeout:
        if proc.poll() is not None:
            return None
        try:
            if get(op, f"{base}/api/health", timeout=1.0)[0] == 200:
                return round(time.perf_counter() - started, 2)
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.2)
    return None


def wait_route(
    op: urllib.request.OpenerDirector, base: str, path: str, proc, timeout: float
) -> float | None:
    """Wait for a *deferred* router: those are mounted after the socket is up."""
    started = time.perf_counter()
    while time.perf_counter() - started < timeout:
        if proc.poll() is not None:
            return None
        try:
            if get(op, f"{base}{path}", timeout=2.0)[0] == 200:
                return round(time.perf_counter() - started, 2)
        except urllib.error.HTTPError as exc:
            if exc.code not in (404, 405):
                return None
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.5)
    return None


def probe_route_mounted(
    op: urllib.request.OpenerDirector, base: str, path: str, proc, timeout: float
) -> tuple[float | None, int | None]:
    """Probe a deferred route that may be auth-protected: 404/405 means not mounted."""
    started = time.perf_counter()
    while time.perf_counter() - started < timeout:
        if proc.poll() is not None:
            return None, None
        try:
            status, _, _ = get(op, f"{base}{path}", timeout=2.0)
            return round(time.perf_counter() - started, 2), status
        except urllib.error.HTTPError as exc:
            if exc.code not in (404, 405):
                return round(time.perf_counter() - started, 2), exc.code
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.5)
    return None, None


def run_selfcheck(exe: Path, env: dict[str, str], timeout: float) -> tuple[bool, str]:
    """Run ``exe selfcheck``: imports the agent stack + compiles a graph.

    This is the check that catches *lazy* dependencies (numpy via
    langchain_aws, tiktoken, ...) which boot fine but explode on the user's
    first chat message.
    """
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            [str(exe), "selfcheck"],
            cwd=str(exe.parent),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, f"selfcheck 超时（>{timeout:.0f}s）"
    elapsed = round(time.perf_counter() - started, 1)
    payload = None
    for line in reversed(proc.stdout.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                payload = json.loads(line)
            except ValueError:
                continue
            break
    if payload is None:
        tail = (proc.stderr or proc.stdout).strip().splitlines()[-3:]
        return False, f"selfcheck 未输出 JSON（exit={proc.returncode}）：{' / '.join(tail)}"
    if not payload.get("ok"):
        return False, f"selfcheck 失败：{json.dumps(payload.get('failures'), ensure_ascii=False)}"
    graph = payload.get("graph") or {}
    google = payload.get("google_discovery") or {}
    discovery = ""
    if google:
        state = "已有" if google.get("offline_documents") else "已裁剪→联网回退"
        discovery = f"，googleapiclient 离线文档{state}"
    return True, (
        f"{len(payload.get('imports', []))} 个模块导入成功，"
        f"agent 图编译 + 调用通过（{graph.get('messages')} 帧）{discovery}，{elapsed}s"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", required=True)
    parser.add_argument("--port", type=int, default=8117)
    parser.add_argument("--home", default="")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument(
        "--dashboard-dir",
        default=str(REPO_ROOT / "src" / "octop" / "dashboard"),
        help="dashboard build output produced by this packaging run",
    )
    args = parser.parse_args()

    exe = Path(args.exe).resolve()
    if not exe.is_file():
        print(f"[失败] 找不到可执行文件：{exe}")
        return 2

    internal = exe.parent / "_internal"
    stamp = time.strftime("%Y%m%d-%H%M%S")
    home = Path(args.home) if args.home else REPO_ROOT / "build" / "backend-verify" / f"home-{stamp}"
    home.mkdir(parents=True, exist_ok=True)
    base = f"http://127.0.0.1:{args.port}"

    print(f"[verify] exe    = {exe}")
    print(f"[verify] home   = {home}")

    before = tree_stats(internal) if internal.is_dir() else (0, 0)

    env = os.environ.copy()
    env["OCTOP_HOME"] = str(home)
    env["NO_PROXY"] = "127.0.0.1,localhost,::1"
    env["no_proxy"] = env["NO_PROXY"]
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY"):
        env.pop(key, None)

    # 0. Agent stack: a bundle that boots but cannot build an agent is broken.
    sc_ok, sc_detail = run_selfcheck(exe, env, timeout=max(240.0, args.timeout))
    if sc_ok:
        ok("agent 栈自检", sc_detail)
    else:
        fail("agent 栈自检", sc_detail)

    proc = subprocess.Popen(
        [str(exe), "run", "--port", str(args.port)],
        cwd=str(exe.parent),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    op = opener()
    try:
        health_s = wait_health(op, base, proc, args.timeout)
        if health_s is None:
            print("[失败] 服务在超时内没有就绪（health 未返回 200）")
            log = home / "logs" / "octop.log"
            if log.is_file():
                print("--- 日志尾部 ---")
                print("\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-30:]))
            return 1
        ok("服务就绪", f"{health_s}s")

        # 1. OCTOP_HOME
        written = [p for p in home.rglob("*") if p.is_file()]
        if written:
            sample = ", ".join(str(p.relative_to(home)) for p in written[:3])
            ok("OCTOP_HOME 生效", f"{len(written)} 个文件落在自定义 home（如 {sample}）")
        else:
            fail("OCTOP_HOME 生效", f"{home} 下没有任何文件")

        # 2. dashboard
        status, ctype, body = get(op, f"{base}/")
        if status == 200 and "text/html" in ctype and b"<div id=\"root\"" in body:
            ok("SPA 外壳", f"/ → {status}，{len(body)} B")
        else:
            fail("SPA 外壳", f"/ → {status} {ctype} {len(body)} B")
        status, ctype, body = get(op, f"{base}/index.html")
        if status == 200 and len(body) > 1000:
            ok("index.html", f"{len(body)} B")
        else:
            fail("index.html", f"{status} {len(body)} B")
        assets = ASSET_RE.findall(body.decode("utf-8", "replace"))
        if not assets:
            fail("静态资源", "index.html 中没有找到 /assets/* 引用")
        else:
            bad = []
            for asset in assets[:3]:
                try:
                    s, ct, payload = get(op, f"{base}{asset}")
                except urllib.error.HTTPError as exc:
                    bad.append(f"{asset} → {exc.code}")
                    continue
                if s != 200 or not payload:
                    bad.append(f"{asset} → {s}")
            if bad:
                fail("静态资源", "; ".join(bad))
            else:
                ok("静态资源", f"{len(assets)} 个引用中抽查 3 个均 200")

        # 2b. The bundled dashboard must be the one built for *this* package:
        # frontend edits do not take effect unless the backend is re-packaged.
        expected_hash = sha256_file(Path(args.dashboard_dir) / "index.html")
        bundled_dir = internal / "octop" / "dashboard"
        bundled_hash = sha256_file(bundled_dir / "index.html")
        try:
            build_stamp = json.loads((bundled_dir / "version.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            build_stamp = {}
        if expected_hash is None:
            fail("dashboard 版本", f"本次前端构建输出缺失：{args.dashboard_dir}\\index.html")
        elif bundled_hash != expected_hash:
            fail(
                "dashboard 版本",
                "产物 index.html 与本次前端构建不一致"
                f"（{str(bundled_hash)[:12]}… != {expected_hash[:12]}…），疑似用了旧产物",
            )
        elif build_stamp.get("index_sha256") != expected_hash:
            fail("dashboard 版本", "version.json 的 index_sha256 与产物入口文件不一致")
        else:
            ok(
                "dashboard 版本一致",
                f"sha256 {expected_hash[:12]}…，构建于 {build_stamp.get('dashboard_built_at')}，"
                f"commit {(build_stamp.get('git_commit') or '')[:12] or 'unknown'}",
            )

        # The same stamp is exposed at runtime so an installed bundle can be
        # traced back to the frontend it shipped with.
        try:
            _, _, raw = get(op, f"{base}/api/health")
            health_build = (json.loads(raw.decode("utf-8")) or {}).get("build") or {}
        except Exception:  # noqa: BLE001 - reported as a failure below
            health_build = {}
        if expected_hash and health_build.get("index_sha256") == expected_hash:
            ok("health 版本戳", f"/api/health.build.index_sha256 = {expected_hash[:12]}…")
        else:
            fail("health 版本戳", f"/api/health 未返回匹配的 build 信息：{health_build}")

        # Packaging record: keep both the whole-repo state and the version stamp
        # so a reviewer never has to trust a single boolean.
        dirty_paths = [str(p) for p in (build_stamp.get("git_dirty_paths") or [])]
        print(
            "  [记录] 版本戳："
            f"commit {(build_stamp.get('git_commit') or 'unknown')[:12]}，"
            f"构建于 {build_stamp.get('dashboard_built_at') or 'unknown'}，"
            f"index_sha256 {(build_stamp.get('index_sha256') or '')[:12]}…"
        )
        print(
            "  [记录] 全仓状态："
            f"git_dirty={build_stamp.get('git_dirty')}，"
            f"范围 {build_stamp.get('git_dirty_scope') or '未知'}，"
            f"未提交 {build_stamp.get('git_dirty_count', '未知')} 项"
            + (f"（如 {'、'.join(dirty_paths[:5])}）" if dirty_paths else "")
        )
        if build_stamp.get("git_dirty_scope") != "repo":
            fail(
                "版本戳范围",
                "version.json 的 git_dirty 未覆盖全仓"
                f"（git_dirty_scope={build_stamp.get('git_dirty_scope')!r}），重新打包后再交付",
            )
        else:
            ok("版本戳范围", "git_dirty 覆盖全仓，后端未提交改动不会被漏报")

        # 3. Playwright (deferred router — mounted only after the socket is up)
        mounted = wait_route(op, base, "/api/browser/env-status", proc, args.timeout)
        if mounted is None:
            fail("浏览器环境探测", "/api/browser/env-status 在超时内没有挂载")
            info = {}
        else:
            ok("延迟路由挂载", f"/api/browser/env-status 在 {mounted}s 可用")
            try:
                status, _, raw = get(op, f"{base}/api/browser/env-status")
                info = json.loads(raw.decode("utf-8"))
            except Exception as exc:  # noqa: BLE001
                fail("浏览器环境探测", f"/api/browser/env-status 调用失败：{exc}")
                info = {}
        if info:
            if not info.get("playwright"):
                fail("Playwright 可用", f"playwright=False（error={info.get('error')}）")
            else:
                ok("Playwright 可用", "导入成功，driver 已随包")
            chrome = info.get("chrome_path")
            if chrome:
                ok("Chromium 路径", f"{chrome}（来源 {info.get('chrome_source')}）")
            else:
                hint = info.get("hint_zh") or ""
                if hint:
                    ok("Chromium 缺失时降级", f"返回中文提示：{hint}")
                else:
                    fail("Chromium 缺失时降级", "未找到浏览器且没有中文提示字段 hint_zh")

        # 3b. Deferred feature routers must be really mounted, not just importable.
        # device-link/status may be auth-protected, so any non-404 answer counts.
        link_elapsed, link_status = probe_route_mounted(
            op, base, "/api/device-link/status", proc, args.timeout
        )
        if link_elapsed is None:
            fail("设备直连路由", "/api/device-link/status 在超时内仍是 404（整组未挂载）")
        else:
            ok("设备直连路由", f"/api/device-link/status 已挂载（HTTP {link_status}，{link_elapsed}s）")

        # The bundled default expert ships as package data; a missing directory
        # silently degrades the first-run experience.
        expert_manifest = (
            internal
            / "octop"
            / "infra"
            / "agents"
            / "experts"
            / "library"
            / "happyclaw"
            / "manifest.json"
        )
        if expert_manifest.is_file():
            ok("默认专家在包内", str(expert_manifest.relative_to(internal)))
        else:
            fail("默认专家在包内", f"包内缺少 {expert_manifest.relative_to(internal)}")

        # 4. logs + read-only _internal
        log = home / "logs" / "octop.log"
        if log.is_file() and log.stat().st_size > 0:
            ok("日志写入 home", f"{log}（{log.stat().st_size} B）")
        else:
            fail("日志写入 home", f"{log} 不存在或为空")
        leaked = list(internal.glob("logs/*")) if internal.is_dir() else []
        if leaked:
            fail("日志未写进 _internal", f"发现 {leaked[0]}")
        else:
            ok("日志未写进 _internal", "打包目录保持只读形态")
        after = tree_stats(internal) if internal.is_dir() else (0, 0)
        if after == before:
            ok("_internal 未被写入", f"{after[0]} 个文件 / {after[1]} B 启动前后一致")
        else:
            fail("_internal 未被写入", f"启动前 {before} → 启动后 {after}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=30)

    print("")
    if _failures:
        print(f"[结果] 失败 {len(_failures)} 项：")
        for item in _failures:
            print(f"  - {item}")
        return 1
    print("[结果] 全部检查通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
