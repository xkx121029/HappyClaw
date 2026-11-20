"""Text Kit - small text utilities with no network access."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def _json_indent(value: int | str) -> int:
    try:
        return max(0, min(int(value), 8))
    except (TypeError, ValueError):
        return 2


async def json_format(text: str, indent: int = 2) -> str:
    """Validate and pretty-print JSON text.

    Args:
        text: Raw JSON string.
        indent: Spaces per level, 0-8.
    """
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        return f"JSON 无效: 第 {exc.lineno} 行第 {exc.colno} 列 — {exc.msg}"
    return json.dumps(obj, ensure_ascii=False, indent=_json_indent(indent))


async def yaml_check(text: str) -> str:
    """Validate YAML text and report its top-level keys."""
    try:
        import yaml
    except ImportError:
        return "未安装 PyYAML，无法校验 YAML"
    try:
        obj = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return f"YAML 无效: {exc}"
    if isinstance(obj, dict):
        keys = ", ".join(str(key) for key in list(obj)[:20])
        suffix = " ..." if len(obj) > 20 else ""
        return f"YAML 有效，顶层共 {len(obj)} 个键: {keys}{suffix}"
    return f"YAML 有效，顶层类型: {type(obj).__name__}"


async def timestamp_convert(value: str, tz: str = "Asia/Shanghai") -> str:
    """Convert a Unix timestamp in seconds or milliseconds to local time.

    Args:
        value: Numeric timestamp string, e.g. 1763289599 or 1763289599000.
        tz: IANA timezone name, e.g. Asia/Shanghai or UTC.
    """
    raw = str(value).strip()
    try:
        number = float(raw)
    except (TypeError, ValueError):
        return f"无法解析时间戳: {value}"

    # 超过 1e11 的按毫秒处理（秒级时间戳目前远小于这个量级）
    if abs(number) > 1e11:
        number /= 1000
    try:
        zone = ZoneInfo(tz)
    except Exception:
        zone = timezone.utc
        tz = "UTC（时区名无效，已回退）"
    try:
        moment = datetime.fromtimestamp(number, tz=zone)
    except (OverflowError, OSError, ValueError) as exc:
        return f"时间戳超出可转换范围: {exc}"
    return f"{raw} -> {moment:%Y-%m-%d %H:%M:%S %Z} ({tz})"


async def base64_text(text: str, mode: str = "encode") -> str:
    """Base64 encode UTF-8 text, or decode Base64 back to text.

    Args:
        text: Input text.
        mode: encode or decode.
    """
    operation = mode.strip().lower()
    if operation not in ("encode", "decode"):
        return "mode 只能是 encode 或 decode"
    try:
        if operation == "encode":
            return base64.b64encode(text.encode("utf-8")).decode("ascii")
        return base64.b64decode(text, validate=True).decode("utf-8", errors="replace")
    except Exception as exc:
        return f"Base64 {operation} 失败: {exc}"


def setup(ctx) -> None:
    ctx.tool(
        "json_format",
        json_format,
        description="校验并格式化 JSON，解析失败时给出行列位置",
    )
    ctx.tool(
        "yaml_check",
        yaml_check,
        description="校验 YAML 语法并列出顶层键",
    )
    ctx.tool(
        "timestamp_convert",
        timestamp_convert,
        description="把 Unix 秒/毫秒时间戳转换成指定时区的可读时间",
    )
    ctx.tool(
        "base64_text",
        base64_text,
        description="Base64 编码 UTF-8 文本或解码 Base64 字符串",
    )
