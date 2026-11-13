"""Unit tests for StartupSelfCheck."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from octop.infra.selfcheck import SelfCheckReport, StartupSelfCheck


class _FakeProviderRow:
    def __init__(self, name: str, api_key: str | None) -> None:
        self.name = name
        self.api_key = api_key


class _FakeProviderRepo:
    def __init__(self, rows: list[_FakeProviderRow]) -> None:
        self._rows = rows

    def list_all(self) -> list[_FakeProviderRow]:
        return self._rows


class _FakePool:
    def __init__(self, fail: bool = False) -> None:
        self._fail = fail

    def connection(self) -> Any:
        if self._fail:
            raise RuntimeError("db down")
        conn = MagicMock()
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)
        return conn


def _paths(tmp_path: Path) -> MagicMock:
    paths = MagicMock()
    paths.home = str(tmp_path)
    paths.backups_dir = str(tmp_path / "backups")
    return paths


def test_all_checks_pass(tmp_path: Path) -> None:
    backups = tmp_path / "backups"
    backups.mkdir()
    (backups / "a.tar.gz").write_bytes(b"x")

    checker = StartupSelfCheck(
        paths=_paths(tmp_path),
        db_pool=_FakePool(),
        providers_provider=_FakeProviderRepo([_FakeProviderRow("openai", "sk-abcdefghij")]),
    )
    report = checker.run()
    assert report.ok is True
    names = [i.name for i in report.items]
    assert "数据库" in names
    assert "主目录" in names
    assert "备份目录" in names
    assert "模型配置" in names
    assert "磁盘空间" in names
    assert "通过" in report.summary


def test_database_failure_marks_report_not_ok(tmp_path: Path) -> None:
    checker = StartupSelfCheck(
        paths=_paths(tmp_path),
        db_pool=_FakePool(fail=True),
        providers_provider=_FakeProviderRepo([]),
    )
    report = checker.run()
    assert report.ok is False
    db_item = next(i for i in report.items if i.name == "数据库")
    assert db_item.ok is False
    assert "失败" in db_item.detail


def test_no_model_providers_marks_not_ok(tmp_path: Path) -> None:
    checker = StartupSelfCheck(
        paths=_paths(tmp_path),
        db_pool=_FakePool(),
        providers_provider=_FakeProviderRepo([]),
    )
    report = checker.run()
    model_item = next(i for i in report.items if i.name == "模型配置")
    assert model_item.ok is False
    assert "未配置" in model_item.detail


def test_api_key_is_masked(tmp_path: Path) -> None:
    checker = StartupSelfCheck(
        paths=_paths(tmp_path),
        db_pool=_FakePool(),
        providers_provider=_FakeProviderRepo([_FakeProviderRow("openai", "sk-1234567890abcdef")]),
    )
    report = checker.run()
    model_item = next(i for i in report.items if i.name == "模型配置")
    assert "sk-1***cdef" in model_item.detail
    assert "sk-1234567890abcdef" not in model_item.detail


def test_report_to_dict_has_summary(tmp_path: Path) -> None:
    (tmp_path / "backups").mkdir()
    checker = StartupSelfCheck(
        paths=_paths(tmp_path),
        db_pool=_FakePool(),
        providers_provider=_FakeProviderRepo([_FakeProviderRow("x", "k")]),
    )
    data = checker.run().to_dict()
    assert data["ok"] is True
    assert "summary" in data
    assert isinstance(data["items"], list)
