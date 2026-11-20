"""Disk Doctor - read-only disk usage inspector.

Every tool here only calls os.scandir / os.stat / shutil.disk_usage.
Nothing is created, moved, modified or deleted.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

# 一次扫描最多访问多少条目，防止在超大目录上长时间卡住
MAX_SCAN_ENTRIES = 5000


def human_size(size: int | float) -> str:
    """Format a byte count as a short human readable string."""
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(value) < 1024 or unit == "TB":
            return f"{int(value)} B" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def dir_size(path: Path, budget: int = MAX_SCAN_ENTRIES) -> tuple[int, bool]:
    """Sum file sizes below *path*. Returns (bytes, truncated)."""
    total = 0
    visited = 0
    stack = [path]
    while stack and visited < budget:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    visited += 1
                    if visited > budget:
                        return total, True
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total, visited >= budget


async def disk_overview(path: str = "", top: int = 10) -> str:
    """Show drive capacity and the largest subdirectories under a path.

    Args:
        path: Directory to inspect. Empty means the current drive root.
        top: How many largest subdirectories to show (1-30).
    """
    try:
        limit = max(1, min(int(top), 30))
    except (TypeError, ValueError):
        limit = 10

    target = Path(path).expanduser() if path else Path(os.path.abspath(os.sep))
    try:
        target = target.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        return f"路径不可用: {path or os.sep} ({exc})"
    if not target.is_dir():
        return f"不是目录: {target}"

    lines: list[str] = []
    drive = os.path.splitdrive(str(target))[0] or os.sep
    try:
        usage = shutil.disk_usage(drive)
        pct = usage.used / usage.total * 100 if usage.total else 0.0
        lines.append(
            f"盘符 {drive}: 总 {human_size(usage.total)} / "
            f"已用 {human_size(usage.used)} / 可用 {human_size(usage.free)} "
            f"({pct:.1f}% 已用)"
        )
    except OSError as exc:
        lines.append(f"盘符容量读取失败: {exc}")

    rows: list[tuple[int, str]] = []
    truncated = False
    try:
        with os.scandir(target) as entries:
            children: list[Path] = []
            for entry in entries:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        children.append(Path(entry.path))
                except OSError:
                    continue
        for child in children:
            size, cut = dir_size(child)
            truncated = truncated or cut
            rows.append((size, child.name))
    except OSError as exc:
        return f"扫描失败: {exc}"

    rows.sort(key=lambda item: item[0], reverse=True)
    lines.append(f"\n{target} 下体积最大的子目录（显示前 {min(limit, len(rows))} 项，共 {len(rows)} 项）:")
    if not rows:
        lines.append("  (无子目录)")
    for size, name in rows[:limit]:
        lines.append(f"  {human_size(size):>10}  {name}")
    if truncated:
        lines.append(f"\n注意: 部分目录扫描超过 {MAX_SCAN_ENTRIES} 条目已截断，上述体积是下限。")
    return "\n".join(lines)


async def find_large_files(path: str, min_mb: float = 100, limit: int = 20) -> str:
    """Find the largest files under a directory, recursively (read-only).

    Args:
        path: Directory to scan.
        min_mb: Only report files at least this many MiB (0 reports all files).
        limit: Maximum number of files to report (1-50).
    """
    try:
        threshold = max(0.0, float(min_mb)) * 1024 * 1024
    except (TypeError, ValueError):
        threshold = 100 * 1024 * 1024
    try:
        limit = max(1, min(int(limit), 50))
    except (TypeError, ValueError):
        limit = 20

    target = Path(path).expanduser()
    try:
        target = target.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        return f"路径不可用: {path} ({exc})"
    if not target.is_dir():
        return f"不是目录: {target}"

    found: list[tuple[int, str]] = []
    visited = 0
    truncated = False
    for root, dirs, files in os.walk(target, followlinks=False):
        for name in files:
            visited += 1
            if visited > MAX_SCAN_ENTRIES:
                truncated = True
                break
            full = Path(root) / name
            try:
                size = full.stat().st_size
            except OSError:
                continue
            if size >= threshold:
                found.append((size, str(full)))
        if truncated:
            break

    found.sort(key=lambda item: item[0], reverse=True)
    lines = [f"{target} 中 ≥ {human_size(threshold)} 的文件，共找到 {len(found)} 个:"]
    if not found:
        lines.append("  (没有符合条件的文件)")
    for size, name in found[:limit]:
        lines.append(f"  {human_size(size):>10}  {name}")
    if truncated:
        lines.append(f"\n注意: 扫描超过 {MAX_SCAN_ENTRIES} 个文件已提前停止，结果不是全量。")
    return "\n".join(lines)


def setup(ctx) -> None:
    ctx.tool(
        "disk_overview",
        disk_overview,
        description="查看磁盘剩余空间，并列出指定路径下体积最大的子目录",
    )
    ctx.tool(
        "find_large_files",
        find_large_files,
        description="递归查找指定目录下的超大文件，只读不改动",
    )
