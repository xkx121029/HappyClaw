"""Weighted text budget used by compaction.

Chinese is measured per character and English per word. Counting raw
characters would charge an English word once per letter and understate the
real context cost, so every budget in this package goes through
:func:`measure_units` instead of ``len(text)``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "CJK_CHAR_UNITS",
    "DEFAULT_WEIGHTS",
    "LATIN_WORD_UNITS",
    "OTHER_CHAR_UNITS",
    "UnitWeights",
    "WeightedBudget",
    "measure_units",
    "trim_head",
    "trim_tail",
]

# A Chinese character maps to roughly one model token; an average English word
# is about five characters and tokenizes to roughly 1.3 tokens, so one word is
# charged more than one CJK character. Digits and punctuation are cheap.
CJK_CHAR_UNITS = 1.0
LATIN_WORD_UNITS = 1.5
OTHER_CHAR_UNITS = 0.25

_CJK_CLASS = "\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af"
_CJK_RE = re.compile(rf"[{_CJK_CLASS}]")
_LATIN_RE = re.compile(r"[A-Za-z]+(?:['\u2019-][A-Za-z]+)*")
_TOKEN_RE = re.compile(rf"\s+|[{_CJK_CLASS}]|[A-Za-z]+(?:['\u2019-][A-Za-z]+)*|\S")


@dataclass(frozen=True, slots=True)
class UnitWeights:
    """Unit price of each text token class."""

    cjk_char_units: float = CJK_CHAR_UNITS
    latin_word_units: float = LATIN_WORD_UNITS
    other_char_units: float = OTHER_CHAR_UNITS

    def measure(self, text: str) -> float:
        """Return the weighted unit count of ``text``."""
        return measure_units(
            text,
            cjk_char_units=self.cjk_char_units,
            latin_word_units=self.latin_word_units,
            other_char_units=self.other_char_units,
        )


DEFAULT_WEIGHTS = UnitWeights()


@dataclass(frozen=True, slots=True)
class WeightedBudget:
    """A unit limit plus the weights used to measure and trim text."""

    limit_units: float
    weights: UnitWeights = DEFAULT_WEIGHTS

    def measure(self, text: str) -> float:
        """Return the weighted unit count of ``text``."""
        return self.weights.measure(text)

    def fits(self, text: str) -> bool:
        """Return whether ``text`` stays inside the limit."""
        return self.measure(text) <= self.limit_units

    def trim(self, text: str) -> str:
        """Keep the longest prefix of ``text`` inside the limit."""
        return trim_head(text, self.limit_units, weights=self.weights)


def measure_units(
    text: str,
    *,
    cjk_char_units: float = CJK_CHAR_UNITS,
    latin_word_units: float = LATIN_WORD_UNITS,
    other_char_units: float = OTHER_CHAR_UNITS,
) -> float:
    """Measure ``text`` with CJK-per-character and Latin-per-word pricing."""
    if not text:
        return 0.0
    total = 0.0
    for token in _TOKEN_RE.findall(text):
        if token.isspace():
            continue
        one_cjk = len(token) == 1 and _CJK_RE.fullmatch(token) is not None
        if one_cjk:
            total += cjk_char_units
        elif _LATIN_RE.fullmatch(token) is not None:
            total += latin_word_units
        else:
            total += other_char_units * len(token)
    return round(total, 3)


def trim_head(text: str, limit_units: float, *, weights: UnitWeights = DEFAULT_WEIGHTS) -> str:
    """Return a prefix no heavier than ``limit_units``."""
    if not text or limit_units <= 0:
        return ""
    kept: list[str] = []
    used = 0.0
    for token in _TOKEN_RE.findall(text):
        cost = _token_units(token, weights)
        if cost and used + cost > limit_units:
            break
        kept.append(token)
        used += cost
    return "".join(kept).rstrip()


def trim_tail(text: str, limit_units: float, *, weights: UnitWeights = DEFAULT_WEIGHTS) -> str:
    """Return a suffix no heavier than ``limit_units``."""
    if not text or limit_units <= 0:
        return ""
    kept: list[str] = []
    used = 0.0
    for token in reversed(_TOKEN_RE.findall(text)):
        cost = _token_units(token, weights)
        if cost and used + cost > limit_units:
            break
        kept.append(token)
        used += cost
    return "".join(reversed(kept)).lstrip()


def _token_units(token: str, weights: UnitWeights) -> float:
    if token.isspace():
        return 0.0
    if len(token) == 1 and _CJK_RE.fullmatch(token) is not None:
        return weights.cjk_char_units
    if _LATIN_RE.fullmatch(token) is not None:
        return weights.latin_word_units
    return weights.other_char_units * len(token)
