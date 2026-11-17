#!/usr/bin/env python3
"""Profile CPython ``-X importtime`` output and rank the heaviest imports.

Reads one or more ``-X importtime`` log files (or stdin), skips the PowerShell
wrapper noise that Windows emits on stderr, and reports:

  1. Top modules by cumulative time (includes children) -- who drags in a tree.
  2. Top modules by self time (excludes children) -- who burns CPU on itself.
  3. Third-party vs stdlib vs first-party split at the top level.

Usage::

    python scripts/profile_imports.py E:/HAPPYclaw/.perf/importtime-server.txt
    python scripts/profile_imports.py a.txt b.txt --top 30 --group octop
    python -X importtime -m octop 2> imports.txt && python scripts/profile_imports.py imports.txt
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# "import time:       525 |        525 | winreg"
# indentation before the module name encodes the import tree depth.
LINE_RE = re.compile(r"^import time:\s*(\d+)\s*\|\s*(\d+)\s*\|\s*( *)(\S.*)$")

# Top-level names that are part of the standard library / interpreter.
_STDLIB_TOP = {
    "abc", "argparse", "array", "ast", "asyncio", "base64", "binascii", "bisect",
    "builtins", "bz2", "calendar", "cmath", "codecs", "collections", "concurrent",
    "configparser", "contextlib", "contextvars", "copy", "copyreg", "csv", "ctypes",
    "dataclasses", "datetime", "decimal", "difflib", "dis", "email", "encodings",
    "enum", "errno", "fcntl", "fnmatch", "fractions", "functools", "gc", "genericpath",
    "getopt", "getpass", "gettext", "glob", "gzip", "hashlib", "heapq", "hmac",
    "html", "http", "importlib", "inspect", "io", "ipaddress", "itertools", "json",
    "keyword", "linecache", "locale", "logging", "lzma", "marshal", "math",
    "mimetypes", "multiprocessing", "nt", "ntpath", "numbers", "operator", "os",
    "pathlib", "pickle", "pkgutil", "platform", "pprint", "queue", "random", "re",
    "reprlib", "secrets", "select", "selectors", "shlex", "shutil", "signal",
    "site", "socket", "sqlite3", "ssl", "stat", "statistics", "string",
    "stringprep", "struct", "subprocess", "sys", "sysconfig", "tarfile", "tempfile",
    "textwrap", "threading", "time", "token", "tokenize", "traceback", "types",
    "typing", "unicodedata", "urllib", "uuid", "warnings", "weakref", "winreg",
    "winsound", "xml", "zipfile", "zipimport", "zlib", "_frozen_importlib",
    "_frozen_importlib_external", "_io", "_thread", "_collections_abc", "_weakrefset",
    "_codecs", "_signal", "_warnings", "_operator", "_functools", "_heapq",
    "_bisect", "_sre", "_json", "_socket", "_ssl", "_hashlib", "_datetime",
    "_random", "_string", "_locale", "_abc", "_stat", "_collections", "_imp",
    "_ctypes", "_queue", "_multiprocessing", "_decimal", "_lzma", "_bz2",
    "_compression", "_elementtree", "_uuid", "_zoneinfo", "_contextvars",
    "_ast", "_symtable", "_tokenize", "_tracemalloc", "_testcapi", "_typing",
    "msvcrt", "posixpath", "posix", "ntpath", "sre_compile", "sre_constants",
    "sre_parse", "encodings", "genericpath", "stat", "fnmatch", "fnmatchcase",
}


def _is_stdlib(top: str) -> bool:
    return top in _STDLIB_TOP or top.startswith("_")


def parse_lines(lines):
    """Yield (self_us, cum_us, depth, module_name) for each valid line."""
    for raw in lines:
        raw = raw.rstrip("\r\n")
        # strip BOM that PowerShell redirects prepend
        if raw.startswith("\ufeff"):
            raw = raw.lstrip("\ufeff")
        m = LINE_RE.match(raw)
        if not m:
            continue
        self_us, cum_us, indent, name = m.groups()
        yield int(self_us), int(cum_us), len(indent) // 2, name.strip()


def _fmt_us(us: int) -> str:
    if us >= 1_000_000:
        return f"{us / 1_000_000:6.2f}s"
    if us >= 1_000:
        return f"{us / 1_000:6.1f}ms"
    return f"{us:6d}us"


def _top_of(name: str) -> str:
    return name.split(".", 1)[0]


def report(records, top_n: int, group: str | None) -> None:
    rows = list(records.values())

    if group:
        rows = [r for r in rows if r["name"].startswith(group)]
        print(f"\n[filter] modules starting with '{group}'")

    print("\n=== Top modules by CUMULATIVE time (drags in a whole tree) ===")
    print(f"{'cumulative':>11} {'self':>9}  module")
    for r in sorted(rows, key=lambda x: -x["cum"])[:top_n]:
        print(f"{_fmt_us(r['cum']):>11} {_fmt_us(r['self']):>9}  {r['name']}")

    print("\n=== Top modules by SELF time (burns CPU on itself) ===")
    print(f"{'self':>9} {'cumulative':>11}  module")
    for r in sorted(rows, key=lambda x: -x["self"])[:top_n]:
        print(f"{_fmt_us(r['self']):>9} {_fmt_us(r['cum']):>11}  {r['name']}")

    # Aggregate self time by top-level package
    agg: dict[str, dict] = {}
    for r in rows:
        top = _top_of(r["name"])
        a = agg.setdefault(top, {"self": 0, "cum_max": 0, "count": 0})
        a["self"] += r["self"]
        a["cum_max"] = max(a["cum_max"], r["cum"])
        a["count"] += 1

    print("\n=== Self time by top-level package ===")
    print(f"{'self':>9} {'cat':<12}  package")
    for top, a in sorted(agg.items(), key=lambda x: -x[1]["self"])[:top_n]:
        cat = "stdlib" if _is_stdlib(top) else "third-party"
        print(f"{_fmt_us(a['self']):>9} {cat:<12}  {top}")

    total_self = sum(r["self"] for r in rows)
    std_self = sum(a["self"] for t, a in agg.items() if _is_stdlib(t))
    print(f"\n[total] recorded self={_fmt_us(total_self)}  "
          f"stdlib={_fmt_us(std_self)}  "
          f"non-stdlib={_fmt_us(total_self - std_self)}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("files", nargs="*", type=Path, help="importtime log files; omit to read stdin")
    p.add_argument("--top", type=int, default=25, help="how many rows per table (default 25)")
    p.add_argument("--group", default=None, help="only show modules with this prefix")
    args = p.parse_args()

    # one module may appear many times in the import tree; keep the deepest
    # (largest cumulative) occurrence so we don't double-count self time.
    records: dict[str, dict] = {}

    def feed(lines):
        for self_us, cum_us, depth, name in parse_lines(lines):
            prev = records.get(name)
            if prev is None or cum_us > prev["cum"]:
                records[name] = {"name": name, "self": self_us, "cum": cum_us, "depth": depth}

    if args.files:
        for path in args.files:
            if not path.exists():
                print(f"error: no such file: {path}", file=sys.stderr)
                return 2
            feed(path.read_text(encoding="utf-8", errors="replace").splitlines())
    else:
        feed(sys.stdin.readlines())

    if not records:
        print("error: no importtime lines found", file=sys.stderr)
        return 1

    print(f"[info] parsed {len(records)} unique modules from "
          f"{len(args.files) or 'stdin'} source(s)")
    report(records, args.top, args.group)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
