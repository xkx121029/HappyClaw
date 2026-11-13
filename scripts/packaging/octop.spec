# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — standalone (onedir) Octop backend.

Produced by ``make package-backend``; output lands in ``dist/backend/octop/``.
Nothing is written into the source tree: PyInstaller's work directory is
``build/pyinstaller`` (both ``build/`` and ``dist/`` are gitignored).

The onedir form is deliberate. A onefile build re-extracts ~183 MB into
``%TEMP%`` on *every* launch, which measured +73 s of cold start on the iSCSI
test box and pushed cold health from 23 s to 86 s. See
``docs/perf/backend-cold-start-baseline.md``.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

REPO_ROOT = Path(SPECPATH).resolve().parents[2]  # type: ignore[name-defined]
SRC = REPO_ROOT / "src"
ENTRY = Path(SPECPATH) / "entry_octop.py"  # type: ignore[name-defined]

hiddenimports = collect_submodules("octop")
# Imported lazily/via plugin registries, so static analysis can miss them.
hiddenimports += [
    "tiktoken_ext",
    "tiktoken_ext.openai_public",
    "tqdm",
    "numpy",
]

datas = []
for package in ("octop", "octop_harness", "octop_browser", "octop_gateway", "octop_memory"):
    try:
        datas += collect_data_files(package)
    except Exception as exc:  # package missing or ships no data files
        print(f"[spec] collect_data_files({package}) skipped: {exc}")

# Test suites, dev tooling and optional extras the server never imports at
# runtime. Anything on the boot path stays in.
excludes = [
    # test / dev tooling
    "pytest",
    "_pytest",
    "pytest_asyncio",
    "pytest_cov",
    "pytest_testmon",
    "pytest_xdist",
    "ruff",
    "mypy",
    "mypy_extensions",
    "pip",
    "test",
    # GUI / scientific stacks unused by the server
    "tkinter",
    "IPython",
    "matplotlib",
    "scipy",
    "pandas",
    # NOTE: numpy is *not* excluded. langchain_aws pulls it in through
    # langchain_aws.embeddings.bedrock during agent graph construction; dropping
    # it made the first chat turn die with ModuleNotFoundError.
    # optional extras (tos / local-embedding / knowledge-ocr / desktop input)
    "tos",
    "fastembed",
    "huggingface_hub",
    "rapidocr",
    "onnxruntime",
    "pymupdf",
    "fitz",
    "shapely",
    "xlwt",
    "mss",
    "pynput",
]

a = Analysis(
    [str(ENTRY)],
    pathex=[str(SRC)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

# Drop googleapiclient's offline discovery corpus: 586 files / ~98 MB used only
# by langchain-community's Google Drive / Gmail loaders, which this server does
# not expose as features. ``octop.infra.utils.google_discovery`` wraps
# ``build()`` so a missing static document falls back to the network (and raises
# a Chinese hint when offline). Same trade-off as
# ``desktop/portable/prune_packages.py``; ``octop selfcheck`` verifies it.
_DROPPED_DATA_PREFIXES = ("googleapiclient/discovery_cache/documents/",)
a.datas = [
    entry
    for entry in a.datas
    if not entry[0].replace("\\", "/").lower().startswith(_DROPPED_DATA_PREFIXES)
]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="octop",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="octop",
)
