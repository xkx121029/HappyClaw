"""The data directory moved from ``~/.octop`` to ``~/.happyclaw``.

Existing installations must keep working, so the first start copies the legacy
directory across. These tests pin the three properties that matter: the copy
happens, the new directory is then what the app uses, and the old data is still
there (nothing is moved or deleted).
"""

from __future__ import annotations

import pathlib

import pytest

from octop.infra.utils import paths


@pytest.fixture(autouse=True)
def _isolate_home(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: home))
    monkeypatch.delenv("HAPPYCLAW_HOME", raising=False)
    monkeypatch.delenv("OCTOP_HOME", raising=False)


def _seed_legacy(home: pathlib.Path) -> pathlib.Path:
    legacy = home / ".octop"
    (legacy / "logs").mkdir(parents=True)
    (legacy / "octop.db").write_text("rows", encoding="utf-8")
    (legacy / "config.json").write_text('{"a": 1}', encoding="utf-8")
    (legacy / "logs" / "run.log").write_text("line", encoding="utf-8")
    return legacy


def test_first_start_copies_the_legacy_directory(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home = pathlib.Path.home()
    legacy = _seed_legacy(home)

    layout = paths.PathLayout.from_env()

    assert layout.root == home / ".happyclaw"
    assert (layout.root / "octop.db").read_text(encoding="utf-8") == "rows"
    assert (layout.root / "config.json").read_text(encoding="utf-8") == '{"a": 1}'
    assert (layout.root / "logs" / "run.log").read_text(encoding="utf-8") == "line"
    # The old directory is intact: this is a copy, never a move.
    assert legacy.is_dir()
    assert (legacy / "octop.db").read_text(encoding="utf-8") == "rows"
    assert "moved the data directory" in capsys.readouterr().err


def test_migration_runs_only_once(tmp_path: pathlib.Path) -> None:
    home = pathlib.Path.home()
    _seed_legacy(home)
    first = paths.PathLayout.from_env()
    (first.root / "octop.db").write_text("edited-after-migration", encoding="utf-8")

    second = paths.PathLayout.from_env()

    assert second.root == first.root
    assert (second.root / "octop.db").read_text(encoding="utf-8") == "edited-after-migration"


def test_existing_new_directory_wins(tmp_path: pathlib.Path) -> None:
    home = pathlib.Path.home()
    _seed_legacy(home)
    fresh = home / ".happyclaw"
    fresh.mkdir()
    (fresh / "octop.db").write_text("already-migrated", encoding="utf-8")

    layout = paths.PathLayout.from_env()

    assert layout.root == fresh
    assert (fresh / "octop.db").read_text(encoding="utf-8") == "already-migrated"


def test_unreadable_legacy_directory_falls_back_to_it(monkeypatch: pytest.MonkeyPatch) -> None:
    home = pathlib.Path.home()
    legacy = _seed_legacy(home)
    monkeypatch.setattr(paths, "migrate_legacy_home", lambda old, new: False)

    layout = paths.PathLayout.from_env()

    # Starting empty in ~/.happyclaw would look like total data loss, so the
    # app keeps pointing at the directory the owner already has.
    assert layout.root == legacy
    assert (layout.root / "octop.db").read_text(encoding="utf-8") == "rows"


def test_happyclaw_home_wins(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    monkeypatch.setenv("HAPPYCLAW_HOME", str(tmp_path / "h-new"))
    monkeypatch.setenv("OCTOP_HOME", str(tmp_path / "h-old"))
    assert paths.PathLayout.from_env().root == tmp_path / "h-new"


def test_legacy_home_variable_still_honoured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    monkeypatch.setenv("OCTOP_HOME", str(tmp_path / "h-old"))
    assert paths.PathLayout.from_env().root == tmp_path / "h-old"


def test_env_alias_mirrors_new_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    from octop.infra.utils import env_alias

    env = {"HAPPYCLAW_PORT": "8080", "HAPPYCLAW_": "ignored", "PATH": "/usr/bin"}
    aliased = env_alias.alias_legacy_env(env)

    assert env["OCTOP_PORT"] == "8080"
    assert "OCTOP_" not in env
    assert aliased == ["OCTOP_PORT"]


def test_env_alias_never_overrides_an_explicit_legacy_value() -> None:
    from octop.infra.utils import env_alias

    env = {"HAPPYCLAW_PORT": "8080", "OCTOP_PORT": "9090"}
    env_alias.alias_legacy_env(env)

    assert env["OCTOP_PORT"] == "9090"
