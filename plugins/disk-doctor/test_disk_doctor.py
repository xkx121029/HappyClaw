from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "disk_doctor_main", Path(__file__).resolve().parent / "main.py"
)
plugin = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(plugin)


def call(coro):
    return asyncio.run(coro)


def test_human_size():
    assert plugin.human_size(0) == "0 B"
    assert plugin.human_size(1024) == "1.0 KB"
    assert plugin.human_size(1536) == "1.5 KB"


def test_dir_size_counts_only_files(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.bin").write_bytes(b"x" * 2048)
    size, truncated = plugin.dir_size(tmp_path)
    assert size == 2048
    assert truncated is False


def test_dir_size_budget_truncates(tmp_path):
    for index in range(20):
        (tmp_path / f"f{index}.bin").write_bytes(b"x")
    size, truncated = plugin.dir_size(tmp_path, budget=5)
    assert truncated is True
    assert size <= 5


def test_disk_overview_lists_largest_dir(tmp_path):
    (tmp_path / "alpha").mkdir()
    (tmp_path / "alpha" / "big.bin").write_bytes(b"x" * 4096)
    output = call(plugin.disk_overview(str(tmp_path), 5))
    assert "盘符" in output
    assert "alpha" in output
    assert "4.0 KB" in output


def test_disk_overview_missing_path():
    output = call(plugin.disk_overview("Z:/__definitely_missing__"))
    assert "路径不可用" in output or "不是目录" in output


def test_find_large_files(tmp_path):
    (tmp_path / "big.bin").write_bytes(b"x" * 2048)
    (tmp_path / "small.bin").write_bytes(b"x")
    output = call(plugin.find_large_files(str(tmp_path), min_mb=0, limit=5))
    assert "big.bin" in output
