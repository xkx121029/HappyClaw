"""Dev Inspector - read-only git repository and listening port status.

Only fixed-argument, read-only git commands are executed; no shell is used.
"""

from __future__ import annotations

import os
import subprocess
from collections import Counter
from pathlib import Path

TIMEOUT_SECONDS = 20


def run_readonly(cmd: list[str], cwd: str | None = None) -> tuple[str, str]:
    """Run a fixed-argument command without a shell. Returns (stdout, error)."""
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT_SECONDS,
            shell=False,
            check=False,
        )
        return proc.stdout.strip(), proc.stderr.strip()
    except FileNotFoundError:
        return "", f"命令不存在: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return "", f"命令超时（{TIMEOUT_SECONDS}s）: {' '.join(cmd)}"
    except OSError as exc:
        return "", str(exc)


def summarize_status(lines: list[str]) -> tuple[Counter, Counter]:
    """Turn `git status --porcelain` lines into (change-type counts, dir counts)."""
    kinds: Counter = Counter()
    by_dir: Counter = Counter()
    for line in lines:
        if len(line) < 4:
            continue
        xy = line[:2]
        if "?" in xy:
            kind = "未跟踪"
        elif "D" in xy:
            kind = "删除"
        elif "A" in xy:
            kind = "新增"
        elif "M" in xy:
            kind = "修改"
        else:
            kind = "其他"
        kinds[kind] += 1
        raw = line[3:].split(" -> ")[-1].strip().strip('"')
        top = raw.split("/", 1)[0] if "/" in raw else "(根目录)"
        by_dir[top] += 1
    return kinds, by_dir


def parse_listening(text: str) -> list[tuple[str, str, str]]:
    """Parse Windows `netstat -ano` or Linux `ss -ltn` output.

    Returns a sorted list of (local address, port, pid); pid is "-" on Linux
    because `ss -ltn` does not include process information.
    """
    rows: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        head = parts[0].upper()
        is_windows = head.startswith("TCP") or head.startswith("TCP6")
        is_linux = head.startswith("LISTEN")
        if not (is_windows or is_linux):
            continue
        if is_windows and not parts[3].upper().startswith("LISTEN"):
            continue
        local = parts[1] if is_windows else parts[3]
        if ":" not in local:
            continue
        address, port = local.rsplit(":", 1)
        if not port.isdigit():
            continue
        pid = parts[-1] if is_windows and parts[-1].isdigit() else "-"
        row = (address or "*", port, pid)
        if row not in seen:
            seen.add(row)
            rows.append(row)
    rows.sort(key=lambda item: (int(item[1]), item[0]))
    return rows


async def repo_status(path: str = ".") -> str:
    """Summarize a git repo: branch, latest commit and uncommitted change counts.

    Args:
        path: Any directory inside the git repository. Defaults to current directory.
    """
    target = Path(path).expanduser()
    if not target.is_dir():
        return f"目录不存在: {target}"

    root, err = run_readonly(["git", "rev-parse", "--show-toplevel"], str(target))
    if err or not root:
        return f"不是 git 仓库: {target} ({err or 'rev-parse 无输出'})"

    branch, _ = run_readonly(["git", "branch", "--show-current"], root)
    latest, _ = run_readonly(["git", "log", "-1", "--oneline"], root)
    status_text, status_err = run_readonly(["git", "status", "--porcelain"], root)
    if status_err:
        return f"git status 失败: {status_err}"

    kinds, by_dir = summarize_status(status_text.splitlines())
    total = sum(kinds.values())
    lines = [
        f"仓库: {root}",
        f"分支: {branch or '(detached HEAD)'}",
        f"最近提交: {latest or '(无提交)'}",
        f"未提交变更: {total} 项"
        + (
            "（"
            + " / ".join(f"{name} {count}" for name, count in kinds.most_common())
            + "）"
            if total
            else ""
        ),
    ]
    if total:
        lines.append("按顶层目录:")
        for name, count in by_dir.most_common(12):
            lines.append(f"  {count:>5}  {name}")
    return "\n".join(lines)


async def listening_ports(port: int = 0) -> str:
    """List TCP ports currently in LISTEN state. Pass a port number to filter.

    Args:
        port: 0 lists all ports; any other value filters by that exact port.
    """
    try:
        wanted = int(port)
    except (TypeError, ValueError):
        wanted = 0

    if os.name == "nt":
        text, err = run_readonly(["netstat", "-ano", "-p", "TCP"])
    else:
        text, err = run_readonly(["ss", "-ltn"])
        if err or not text:
            text, err = run_readonly(["netstat", "-ltn"])
    if err:
        return f"读取端口失败: {err}"

    rows = parse_listening(text)
    if wanted:
        rows = [row for row in rows if row[1] == str(wanted)]
    lines = [f"监听中的 TCP 端口（共 {len(rows)} 个）:"]
    if not rows:
        lines.append("  (没有匹配的监听端口)")
    for address, number, pid in rows[:100]:
        lines.append(f"  {address}:{number:<6} pid={pid}")
    return "\n".join(lines)


def setup(ctx) -> None:
    ctx.tool(
        "repo_status",
        repo_status,
        description="查看 git 仓库的分支、最近提交和未提交变更统计",
    )
    ctx.tool(
        "listening_ports",
        listening_ports,
        description="列出本机监听中的 TCP 端口，可按端口过滤",
    )
