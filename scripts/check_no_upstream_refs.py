#!/usr/bin/env python3
"""Fail when this repository points at the pre-migration upstream project.

One-shot guard for the de-Octop pass: HappyClaw ships as its own product, so no
user-facing surface may link to ``TencentCloud/*`` repositories, the retired
``octop.cloud`` / ``download.octop.cloud`` / ``docs.octop.cloud`` domains, or the
upstream GHCR namespace.

    python scripts/check_no_upstream_refs.py             # scan the repo
    python scripts/check_no_upstream_refs.py --self-test  # negative control

``--self-test`` writes a synthetic violation into a temporary tree and asserts
the same scanner catches it, so a passing run over a clean tree cannot be blamed
on a broken matcher.

Every remaining hit needs an entry in ``ALLOWED`` with a stated reason. See
``reports/DEOCTOP-SWEEP.md`` for the full A/B/C/D classification.
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

# The scanner has to spell the patterns out, and ``--self-test`` plants them on
# purpose; every other file is in scope.
SKIP_FILES = {"scripts/check_no_upstream_refs.py"}

SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
}

RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("upstream GitHub repository", re.compile(r"github\.com/TencentCloud\b", re.I)),
    ("upstream container registry", re.compile(r"ghcr\.(?:io|nju\.edu\.cn)/tencentcloud/", re.I)),
    ("retired docs/download domain", re.compile(r"(?:docs|download)\.octop\.cloud", re.I)),
    ("retired portal domain", re.compile(r"(?<![\w.-])octop\.cloud\b", re.I)),
)

# path -> (regex for the allowed line, why it stays)
ALLOWED: dict[str, tuple[tuple[re.Pattern[str], str], ...]] = {
    "CHANGELOG.md": (
        (re.compile(r"TencentCloud|octop\.cloud", re.I), "release history: records what already shipped"),
    ),
    "tests/unit/test_fnos_docker_persist.py": (
        (re.compile(r'assert "TencentCloud" not in text'), "guard: asserts our own output carries no upstream name"),
    ),
    "tests/unit/test_release_download_links.py": (
        (re.compile(r'not in body'), "guard: asserts release notes carry no upstream link"),
    ),
    "dashboard/src/pages/Agent/Channels/components/constants.ts": (
        (re.compile(r'octopbot: "https://octop\.cloud\.tencent\.com"'),
         "functional endpoint of the OctopBot channel; the service is theirs, not a link to our code"),
    ),
    "dashboard/src/pages/Control/CloudHosts/index.tsx": (
        (re.compile(r'"octop\.cloud\.(?:snapshot|overview)\.v1"'),
         "localStorage keys: renaming them silently discards the owner's saved view state"),
    ),
    "src/octop/infra/plugins/market/sources/octop.py": (
        (re.compile(r'"origin": "octop\.cloud"'),
         "plugin provenance label stored with installed envelopes; must match what is already on disk"),
    ),
    "src/octop/infra/agents/providers/onnx_download.py": (
        (re.compile(r"COS_ENDPOINT_DEFAULT = \"https://octop-"),
         "default embedding-model bucket, overridable with OCTOP_ONNX_COS_BASE; clearing it degrades "
         "first-run downloads and needs an owner decision"),
    ),
}


def scan(root: Path) -> list[tuple[str, int, str, str]]:
    """Return ``(relative path, line number, rule name, line)`` for every hit."""
    hits: list[tuple[str, int, str, str]] = []
    for path in sorted(root.rglob("*")):
        rel_parts = set(path.relative_to(root).parts[:-1])
        if rel_parts & SKIP_DIRS or not path.is_file():
            continue
        try:
            if path.stat().st_size > 6_000_000:
                continue
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        rel = path.relative_to(root).as_posix()
        if rel in SKIP_FILES:
            continue
        allow = ALLOWED.get(rel, ())
        for number, line in enumerate(text.splitlines(), 1):
            for name, pattern in RULES:
                if not pattern.search(line):
                    continue
                if any(allow_pattern.search(line) for allow_pattern, _why in allow):
                    break
                hits.append((rel, number, name, line.strip()[:160]))
                break
    return hits


def self_test() -> int:
    """Negative control: the scanner must flag a planted upstream reference."""
    samples = (
        "see https://github.com/TencentCloud/Octop for the original\n",
        "curl -fsSL https://download.octop.cloud/octop/scripts/install.sh | bash\n",
        "docker pull ghcr.io/tencentcloud/octop:latest\n",
        "portal origin defaults to https://octop.cloud\n",
    )
    failures = 0
    for sample in samples:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "planted.md").write_text(sample, encoding="utf-8")
            found = scan(Path(tmp))
        if found:
            print(f"negative control ok: {sample.strip()[:70]!r} -> {found[0][2]}")
        else:
            print(f"negative control FAILED: {sample.strip()!r} was not detected")
            failures += 1
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    parser.add_argument("--self-test", action="store_true", help="run the negative control only")
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    root = Path(args.root).resolve()
    hits = scan(root)
    if hits:
        print(f"FAIL: {len(hits)} reference(s) still point at the pre-migration upstream project")
        for rel, number, name, line in hits:
            print(f"  {rel}:{number} [{name}] {line}")
        return 1
    print(f"OK: {root} has no link, domain, or registry path pointing at the pre-migration upstream project")
    print(f"    {len(ALLOWED)} documented exception file(s), each listed in reports/DEOCTOP-SWEEP.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
