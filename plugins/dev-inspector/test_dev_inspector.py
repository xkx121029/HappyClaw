from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "dev_inspector_main", Path(__file__).resolve().parent / "main.py"
)
plugin = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(plugin)


def call(coro):
    return asyncio.run(coro)


def test_summarize_status():
    lines = [" M dashboard/src/a.ts", "?? new.txt", " D old.py", "A  added.md"]
    kinds, by_dir = plugin.summarize_status(lines)
    assert kinds["修改"] == 1
    assert kinds["未跟踪"] == 1
    assert kinds["删除"] == 1
    assert kinds["新增"] == 1
    assert by_dir["dashboard"] == 1
    assert by_dir["(根目录)"] == 3


def test_parse_listening_windows_netstat():
    text = (
        "Proto  Local Address          Foreign Address        State           PID\n"
        "TCP    127.0.0.1:8088         0.0.0.0:0              LISTENING       1234\n"
        "TCP    0.0.0.0:5173           0.0.0.0:0              LISTENING       0\n"
        "TCP    127.0.0.1:9000         1.2.3.4:80             ESTABLISHED     9\n"
    )
    rows = plugin.parse_listening(text)
    assert ("127.0.0.1", "8088", "1234") in rows
    assert ("0.0.0.0", "5173", "0") in rows
    assert len(rows) == 2
    assert rows[0][1] == "5173"


def test_parse_listening_linux_ss():
    text = (
        "State   Recv-Q  Send-Q  Local Address:Port  Peer Address:Port\n"
        "LISTEN  0       128     127.0.0.1:8088      0.0.0.0:*\n"
        "LISTEN  0       128     [::]:5173           [::]:*\n"
    )
    rows = plugin.parse_listening(text)
    assert ("127.0.0.1", "8088", "-") in rows
    assert ("[::]", "5173", "-") in rows
    assert len(rows) == 2


def test_repo_status_on_this_repo():
    repo = Path(__file__).resolve().parents[2]
    output = call(plugin.repo_status(str(repo)))
    assert "仓库:" in output
    assert "分支:" in output
    assert "未提交变更:" in output


def test_repo_status_outside_git(tmp_path):
    output = call(plugin.repo_status(str(tmp_path)))
    assert "不是 git 仓库" in output
