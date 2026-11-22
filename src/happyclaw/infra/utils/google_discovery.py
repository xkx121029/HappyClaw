"""Keep ``googleapiclient`` usable when the offline discovery corpus is pruned.

The standalone bundle drops ``googleapiclient/discovery_cache/documents``
(586 files / ~98 MB) because ``octop`` never imports ``googleapiclient`` itself;
the corpus is only used by langchain-community's Google Drive / Gmail loaders.
``googleapiclient.discovery.build()`` defaults to ``static_discovery=True`` and
raises ``UnknownApiNameOrVersion`` when that corpus is missing, so those loaders
would break with an opaque English error.

The desktop portable package solves this by rewriting ``discovery.py`` at build
time (see ``desktop/portable/prune_packages.py``). A frozen module lives inside
the PYZ archive and cannot be rewritten, so the same fallback is installed at
runtime through a finder that wraps ``build`` the first time
``googleapiclient.discovery`` is imported. If the network fetch also fails, a
Chinese hint is raised instead of the original error.

The install itself imports nothing from googleapiclient (import time measured at
~4.6 s on the slow test box), so it costs nothing on the boot path.
"""

from __future__ import annotations

import importlib.abc
import sys
import threading
from pathlib import Path
from types import ModuleType
from typing import Any

_TARGET = "googleapiclient.discovery"
_MARKER = "__octop_static_discovery_fallback__"

HINT_ZH = (
    "Google Drive / Gmail 工具需要的离线 API 描述文件没有随安装包提供，"
    "正在改为联网获取；如果网络不可用，请检查代理设置后重试。"
)

_lock = threading.Lock()
_installed = False


def _is_missing_static_doc(exc: BaseException) -> bool:
    # googleapiclient is not imported on purpose: avoid paying its import cost
    # just to choose an exception type.
    return type(exc).__name__ == "UnknownApiNameOrVersion" or isinstance(exc, FileNotFoundError)


def _patch(module: ModuleType) -> None:
    original = getattr(module, "build", None)
    if original is None or getattr(original, _MARKER, False):
        return

    def build_with_fallback(*args: Any, **kwargs: Any):
        try:
            return original(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - only static misses are retried
            if not _is_missing_static_doc(exc):
                raise
            retry_kwargs = {**kwargs, "static_discovery": False}
            try:
                return original(*args, **retry_kwargs)
            except Exception as retry_exc:  # noqa: BLE001 - surface a readable hint
                raise RuntimeError(HINT_ZH) from retry_exc

    setattr(build_with_fallback, _MARKER, True)
    module.build = build_with_fallback


class _PatchingLoader(importlib.abc.Loader):
    """Delegate loading, then patch the module right after it executes."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def create_module(self, spec):  # noqa: ANN001 - signature fixed by importlib
        creator = getattr(self._inner, "create_module", None)
        return None if creator is None else creator(spec)

    def exec_module(self, module: ModuleType) -> None:
        self._inner.exec_module(module)
        _patch(module)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class _PatchingFinder(importlib.abc.MetaPathFinder):
    """Patch ``googleapiclient.discovery`` on first import, whatever imports it."""

    def find_spec(self, fullname: str, path=None, target=None):  # noqa: ANN001
        if fullname != _TARGET:
            return None
        for finder in tuple(sys.meta_path):
            if finder is self:
                continue
            find_spec = getattr(finder, "find_spec", None)
            if find_spec is None:
                continue
            spec = find_spec(fullname, path, target)
            if spec is None:
                continue
            if spec.loader is not None:
                spec.loader = _PatchingLoader(spec.loader)
            return spec
        return None


def install_google_discovery_fallback() -> None:
    """Install the finder once per process (idempotent, imports nothing)."""
    global _installed
    if _installed:
        return
    with _lock:
        if _installed:
            return
        sys.meta_path.insert(0, _PatchingFinder())
        _installed = True


def offline_documents_present() -> bool:
    """True when the bundled package still ships the offline discovery corpus."""
    try:
        import googleapiclient
    except Exception:  # noqa: BLE001 - absent package is reported as "no docs"
        return False
    location = getattr(googleapiclient, "__file__", None)
    if not location:
        return False
    return (Path(location).parent / "discovery_cache" / "documents").is_dir()


def patch_installed() -> bool:
    """True when ``build`` has already been wrapped in this process."""
    module = sys.modules.get(_TARGET)
    if module is None:
        return False
    return bool(getattr(getattr(module, "build", None), _MARKER, False))


def missing_documents_hint() -> str | None:
    """Chinese hint when the offline corpus is gone, otherwise ``None``."""
    return None if offline_documents_present() else HINT_ZH
