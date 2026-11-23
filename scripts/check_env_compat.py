#!/usr/bin/env python3
"""Fail when product code reads a ``HAPPYCLAW_*`` variable without the legacy fallback.

``env_get`` / ``env_has`` read the new name first and fall back to the pre-rename
``OCTOP_*`` spelling. Code that reaches into ``os.environ`` directly silently
ignores a deployment that still exports the old name — a switch then looks off,
a configured portal looks empty, and nothing reports it.

Two shapes are caught:

* the variable spelled out at the call site — ``os.environ.get("HAPPYCLAW_X")``,
  ``"HAPPYCLAW_X" in os.environ``;
* the variable held in a module constant — ``_MASTER = "HAPPYCLAW_X"`` followed
  by ``os.environ.get(_MASTER)``. This one is easy to miss because the call site
  shows no prefix at all, and it is exactly how the DSH switches lost every
  stage for a deployment that still exported the old names.

    python scripts/check_env_compat.py             # scan src/
    python scripts/check_env_compat.py --self-test  # negative control
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
import tempfile
from pathlib import Path

# The compat layer itself has to spell the raw names out.
SKIP_FILES = {
    "src/happyclaw/infra/utils/env_alias.py",
}

DIRECT_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("direct read", re.compile(r'os\.environ\.get\(\s*"HAPPYCLAW_[A-Z0-9_]+"')),
    ("direct read", re.compile(r'os\.getenv\(\s*"HAPPYCLAW_[A-Z0-9_]+"')),
    ("direct read", re.compile(r'os\.environ\[\s*"HAPPYCLAW_[A-Z0-9_]+"')),
    ("presence check", re.compile(r'"HAPPYCLAW_[A-Z0-9_]+"\s+(?:not\s+)?in\s+os\.environ')),
)

CONST_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")


def prefixed_constants(text: str) -> dict[str, str]:
    """Module-level names bound to a string that starts with ``HAPPYCLAW_``."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return {}
    found: dict[str, str] = {}
    for node in tree.body:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets, value = list(node.targets), node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            continue
        if not value.value.startswith("HAPPYCLAW_"):
            continue
        for target in targets:
            if isinstance(target, ast.Name) and CONST_NAME.match(target.id):
                found[target.id] = value.value
    return found


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
        constants = prefixed_constants(text)
        const_rules = tuple(
            (f"read through constant {name} ({value})", re.compile(r"(?:os\.environ\.get|os\.getenv)\(\s*%s\b" % re.escape(name)))
            for name, value in constants.items()
        ) + tuple(
            (f"presence check through constant {name} ({value})", re.compile(r"\b%s\b\s+(?:not\s+)?in\s+os\.environ" % re.escape(name)))
            for name, value in constants.items()
        )
        for number, line in enumerate(text.splitlines(), 1):
            # A line that spells the legacy name itself already does the fallback.
            if "OCTOP_" in line:
                continue
            matched = None
            for name, pattern in DIRECT_RULES + const_rules:
                if pattern.search(line):
                    matched = name
                    break
            if matched:
                hits.append((rel, number, matched, line.strip()[:140]))
    return hits


def self_test() -> int:
    literal_samples = (
        'if "HAPPYCLAW_PORTAL_ORIGIN" not in os.environ:',
        'value = os.environ.get("HAPPYCLAW_DATABASE_URL")',
        'value = os.getenv("HAPPYCLAW_PORT")',
        'raw = os.environ["HAPPYCLAW_HOME"]',
    )
    constant_samples = (
        '_MASTER = "HAPPYCLAW_DSH_RUNTIME"\nvalue = os.environ.get(_MASTER, "")',
        '_REFS = "HAPPYCLAW_DSH_LLM_REFS"\nraw = os.getenv(_REFS)',
        '_HOME = "HAPPYCLAW_HOME"\nif _HOME not in os.environ: pass',
    )
    failures = 0
    for sample in literal_samples + constant_samples:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src" / "pkg"
            src.mkdir(parents=True)
            (src / "planted.py").write_text(sample + "\n", encoding="utf-8")
            found = scan(Path(tmp) / "src")
        label = sample.splitlines()[-1]
        if found:
            print(f"negative control ok: {label[:62]!r} -> {found[0][2].split(' (')[0]}")
        else:
            print(f"negative control FAILED: {label!r} was not detected")
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
        print(f"FAIL: {len(hits)} env read(s) bypass the legacy fallback")
        for rel, number, name, line in hits:
            print(f"  {rel}:{number} [{name}] {line}")
        print("use env_get()/env_has() so a deployment that still exports OCTOP_* keeps working")
        return 1
    print(f"OK: {root} reads HAPPYCLAW_* variables only through env_get/env_has")
    return 0


if __name__ == "__main__":
    sys.exit(main())
