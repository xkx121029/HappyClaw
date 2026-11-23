#!/usr/bin/env python3
"""Fail when product code reads a ``HAPPYCLAW_*`` variable without the legacy fallback.

``env_get`` / ``env_has`` read the new name first and fall back to the pre-rename
``OCTOP_*`` spelling. Code that reaches into ``os.environ`` directly silently
ignores a deployment that still exports the old name — a switch then looks off,
a configured portal looks empty, and nothing reports it.

    python scripts/check_env_compat.py             # scan src/
    python scripts/check_env_compat.py --self-test  # negative control
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

# The compat layer itself has to spell the raw names out.
SKIP_FILES = {
    "src/happyclaw/infra/utils/env_alias.py",
}

RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("direct read", re.compile(r'os\.environ\.get\(\s*"HAPPYCLAW_[A-Z0-9_]+"')),
    ("direct read", re.compile(r'os\.getenv\(\s*"HAPPYCLAW_[A-Z0-9_]+"')),
    ("direct read", re.compile(r'os\.environ\[\s*"HAPPYCLAW_[A-Z0-9_]+"')),
    ("presence check", re.compile(r'"HAPPYCLAW_[A-Z0-9_]+"\s+(?:not\s+)?in\s+os\.environ')),
)


def scan(root: Path) -> list[tuple[str, int, str, str]]:
    hits: list[tuple[str, int, str, str]] = []
    for path in sorted(root.rglob("*.py")):
        rel = path.resolve().relative_to(root.resolve().parent).as_posix()
        if rel in SKIP_FILES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            # A line that spells the legacy name itself already does the fallback.
            if "OCTOP_" in line:
                continue
            for name, pattern in RULES:
                if pattern.search(line):
                    hits.append((rel, number, name, line.strip()[:140]))
                    break
    return hits


def self_test() -> int:
    samples = (
        'if "HAPPYCLAW_PORTAL_ORIGIN" not in os.environ:',
        'value = os.environ.get("HAPPYCLAW_DATABASE_URL")',
        'value = os.getenv("HAPPYCLAW_PORT")',
        'raw = os.environ["HAPPYCLAW_HOME"]',
    )
    failures = 0
    for sample in samples:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src" / "pkg"
            src.mkdir(parents=True)
            (src / "planted.py").write_text(sample + "\n", encoding="utf-8")
            found = scan(Path(tmp) / "src")
        if found:
            print(f"negative control ok: {sample[:60]!r} -> {found[0][2]}")
        else:
            print(f"negative control FAILED: {sample!r} was not detected")
            failures += 1
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parent.parent / "src"))
    parser.add_argument("--self-test", action="store_true", help="run the negative control only")
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    root = Path(args.root).resolve()
    hits = scan(root)
    if hits:
        print(f"FAIL: {len(hits)} direct env read(s) bypass the legacy fallback")
        for rel, number, name, line in hits:
            print(f"  {rel}:{number} [{name}] {line}")
        print("use env_get()/env_has() so a deployment that still exports OCTOP_* keeps working")
        return 1
    print(f"OK: {root} reads HAPPYCLAW_* variables only through env_get/env_has")
    return 0


if __name__ == "__main__":
    sys.exit(main())
