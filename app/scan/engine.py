r"""Keyword scan engine: pure, standard library only (D10, D11, D14).

Per rule: one alternation of the case-folded keywords, longest first, in one boundary assertion
over the case-folded text; ``finditer`` counts non-overlapping matches; detected iff
count >= threshold.

Complexity: ``re`` backtracks through the alternatives at each position, so the worst case is
O(len(text) * total keyword length) per rule, times the rules in a scan. No nested or ambiguous
quantifiers (``\s+`` only between literal tokens, fixed-width lookarounds), hence no exponential
backtracking: the bad case is a large constant that needs adversarial keywords, i.e. control of
the management API. Realistic keywords fail at the first character. Adversarial keywords (long
shared multi-token prefixes) are the slow case, worst at the schema limits of 100 Data Types x
1000 keywords x 1 MB (accepted, D11: the only attacker is the admin). Compiling is cheap for
realistic lists and ``re`` caches the last 512 patterns, so a per-Data-Type memo of
``_build_pattern`` would help little; Aho-Corasick is the real next step. Not ``\b``: it demands
a boundary on both sides, so "@company.com" could never match in "john@company.com".

Known limitations: simple case folding (i, I, İ, ı are equivalent, final sigma equals sigma,
ß does not match SS; the only pairs that stop being equal are Old Church Slavonic glyph variants
and one Greek combining mark); combining
marks are not ``\w``, so pointed Hebrew or Indic text can match inside a word (NFKC fixes only
decomposed Latin); attached Hebrew prefixes (ו, ה, ב, ל) are not stripped. Matching is
accent-sensitive ("resume" does not match "résumé"); scripts written without spaces (Chinese,
Japanese, Thai) have no word boundaries for ``\w``, so a keyword inside running text does not
match; attached Arabic prefixes (al-) and vowel marks behave like the Hebrew case.
"""

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from uuid import UUID

# "A match may not begin or end between two word characters", so a non-word keyword edge needs no
# boundary. Applied once around the whole alternation, not per keyword.
NOT_INSIDE_WORD = r"(?!(?<=\w)\w)"

# Soft hyphen, zero-width space, word joiner, zero-width no-break space: invisible, neither \w
# nor \s, so they would split or glue words. ZWNJ/ZWJ are kept: they carry meaning in Arabic and
# Indic scripts. A regex, not str.translate, which does a dict lookup per code point of non-ASCII
# text. Removed before NFKC: one of them between a letter and its accent would block composition.
_INVISIBLE = re.compile("[\u00ad\u200b\u2060\ufeff]")


@dataclass(frozen=True, slots=True)
class KeywordRule:
    """One Data Type as the engine sees it: no ORM, no HTTP."""

    id: UUID
    name: str
    keywords: tuple[str, ...]
    threshold: int

    def __post_init__(self) -> None:
        # A threshold of 0 would "detect" every text, even an empty one.
        if self.threshold < 1:
            raise ValueError("threshold must be >= 1")


@dataclass(frozen=True, slots=True)
class Detection:
    id: UUID
    name: str
    match_count: int


def fold(s: str) -> str:
    r"""Case-fold for matching: text and keywords both go through this, so the pattern can be
    compiled without ``re.IGNORECASE`` (much faster: letters then compile to plain literals with the
    fast first-character reject that only digits had). Not bare ``lower()``: it turns İ into
    i + U+0307 (two code points, the dot is not ``\w``, so "zmir" would match "İzmir") and applies
    the Greek final-sigma rule by context. The three replacements keep every code point one code
    point, keep its ``\w``-ness, and keep i/I/İ/ı and σ/ς equivalent (D11)."""
    return s.replace("İ", "i").replace("ı", "i").lower().replace("ς", "σ")


def _clean(s: str) -> str:
    """Drop invisible format chars, NFKC (ligatures, full-width forms, canonical forms), fold."""
    return fold(unicodedata.normalize("NFKC", _INVISIBLE.sub("", s)))


def _normalise(keywords: Iterable[str]) -> list[str]:
    """Strip invisible format characters, NFKC, fold case, collapse internal whitespace, drop
    empties, longest first."""
    # str.split() and the pattern's \s cover the same characters, so typed and matched agree.
    cleaned = (" ".join(_clean(k).split()) for k in keywords)
    # Longest first: "credit card" beats "card" at one position. No dedupe: can't change a count.
    return sorted((k for k in cleaned if k), key=lambda k: (-len(k), k))


def _build_pattern(keywords: Sequence[str]) -> re.Pattern[str] | None:
    if not keywords:  # an empty alternation would match "" at every position
        return None
    # Escape token by token and join with \s+: any whitespace run in the text, never zero chars.
    bodies = (r"\s+".join(re.escape(token) for token in k.split()) for k in keywords)
    alternation = "(?:" + "|".join(bodies) + ")"
    # No re.IGNORECASE: both sides are already folded (see fold).
    return re.compile(NOT_INSIDE_WORD + alternation + NOT_INSIDE_WORD)


def _count(pattern: re.Pattern[str] | None, text: str) -> int:
    # finditer is non-overlapping, so a span is never counted twice.
    return 0 if pattern is None else sum(1 for _ in pattern.finditer(text))


def count(rule: KeywordRule, text: str) -> int:
    """Occurrences of any of the rule's keywords in ``text``, ignoring the threshold."""
    return _count(_build_pattern(_normalise(rule.keywords)), _clean(text))


def scan(text: str, rules: Iterable[KeywordRule]) -> list[Detection]:
    """Evaluate every rule independently; return the detected ones, most matches first."""
    text = _clean(text)  # once per scan, not once per rule
    detections = [
        Detection(rule.id, rule.name, n)
        for rule in rules
        if (n := _count(_build_pattern(_normalise(rule.keywords)), text)) >= rule.threshold
    ]
    # Membership is a set (D19), so sort fully: count DESC, then name, then id for determinism.
    return sorted(detections, key=lambda d: (-d.match_count, d.name, str(d.id)))
