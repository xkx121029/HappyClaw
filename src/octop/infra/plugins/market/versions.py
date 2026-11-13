"""SemVer comparison used to order releases and resolve cross-source conflicts."""

from __future__ import annotations

import re

_EXACT_SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)

_LOOSE_RE = re.compile(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:-([0-9A-Za-z.-]+))?$")


def is_exact_semver(text: str) -> bool:
    """True when ``text`` is an exact npm ``node-semver`` version string."""
    return _EXACT_SEMVER_RE.fullmatch(text) is not None


def is_prerelease(text: str) -> bool:
    match = _LOOSE_RE.fullmatch(text.strip())
    return bool(match and match.group(4))


def _split(text: str) -> tuple[tuple[int, int, int], tuple[str, ...]] | None:
    match = _LOOSE_RE.fullmatch(text.strip())
    if match is None:
        return None
    core = (
        int(match.group(1)),
        int(match.group(2) or 0),
        int(match.group(3) or 0),
    )
    pre = tuple(match.group(4).split(".")) if match.group(4) else ()
    return core, pre


def _compare_prerelease(left: tuple[str, ...], right: tuple[str, ...]) -> int:
    if not left and not right:
        return 0
    if not left:
        return 1
    if not right:
        return -1
    for a, b in zip(left, right, strict=False):
        if a == b:
            continue
        a_number = a.isdigit()
        b_number = b.isdigit()
        if a_number and b_number:
            return -1 if int(a) < int(b) else 1
        if a_number != b_number:
            return -1 if a_number else 1
        return -1 if a < b else 1
    if len(left) == len(right):
        return 0
    return 1 if len(left) > len(right) else -1


def compare_versions(left: str, right: str) -> int | None:
    """Compare two versions. ``None`` means at least one is not parseable."""
    parsed_left = _split(left)
    parsed_right = _split(right)
    if parsed_left is None or parsed_right is None:
        return None
    core_left, pre_left = parsed_left
    core_right, pre_right = parsed_right
    if core_left != core_right:
        return -1 if core_left < core_right else 1
    return _compare_prerelease(pre_left, pre_right)
