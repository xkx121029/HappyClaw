from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "text_kit_main", Path(__file__).resolve().parent / "main.py"
)
plugin = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(plugin)


def call(coro):
    return asyncio.run(coro)


def test_json_format_pretty_prints():
    output = call(plugin.json_format('{"a": 1, "b": [2, 3]}', 2))
    assert '"a": 1' in output
    assert "\n" in output


def test_json_format_reports_position():
    output = call(plugin.json_format("{bad"))
    assert "JSON 无效" in output
    assert "第" in output


def test_yaml_check_keys():
    output = call(plugin.yaml_check("a: 1\nb: 2\n"))
    assert "YAML 有效" in output
    assert "2 个键" in output
    assert "a" in output and "b" in output


def test_yaml_check_invalid():
    output = call(plugin.yaml_check("a: [1,\n"))
    assert "YAML 无效" in output


def test_timestamp_convert_seconds_and_milliseconds():
    seconds = call(plugin.timestamp_convert("1763289599", "UTC"))
    millis = call(plugin.timestamp_convert("1763289599000", "UTC"))
    assert " -> " in seconds
    assert seconds.split(" -> ")[1] == millis.split(" -> ")[1]


def test_timestamp_convert_bad_input():
    assert "无法解析" in call(plugin.timestamp_convert("not-a-number"))


def test_base64_roundtrip_utf8():
    encoded = call(plugin.base64_text("你好，毛肚", "encode"))
    assert call(plugin.base64_text(encoded, "decode")) == "你好，毛肚"


def test_base64_bad_mode():
    assert "mode 只能" in call(plugin.base64_text("x", "nope"))
