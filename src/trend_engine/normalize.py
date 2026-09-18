"""Keyword normalization and fuzzy matching (Korean-aware, dependency-free).

Korean trend keywords vary mostly by spacing ('두산에너 빌리티' vs '두산에너빌리티') and by
extra words ('김성수 대법관 임명 재가' vs '김성수 대법관 재가'). We therefore compare
space-free keys, with containment + character-bigram Dice similarity.
"""

from __future__ import annotations

import re
import unicodedata

_NON_WORD = re.compile(r"[^\w]|_", re.UNICODE)


def norm_key(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    return _NON_WORD.sub("", text)


def _is_ascii(s: str) -> bool:
    return all(ord(c) < 128 for c in s)


def min_len_ok(key: str) -> bool:
    """Too-short keys ('m', 'ai') match everything; require 3 ASCII or 2 CJK chars."""
    return len(key) >= (3 if _is_ascii(key) else 2)


def bigrams(key: str) -> set[str]:
    return {key[i : i + 2] for i in range(len(key) - 1)} or {key}


def dice(a: str, b: str) -> float:
    ba, bb = bigrams(a), bigrams(b)
    return 2 * len(ba & bb) / (len(ba) + len(bb))


def similar(a: str, b: str, threshold: float = 0.8) -> bool:
    """Same interest? a, b are norm_key()s."""
    if not a or not b:
        return False
    if a == b:
        return True
    short, long_ = sorted((a, b), key=len)
    if min_len_ok(short) and short in long_ and len(short) / len(long_) >= 0.4:
        return True
    return min(len(a), len(b)) >= 3 and dice(a, b) >= threshold


def tokens(text: str) -> set[str]:
    """Meaningful word tokens: 'KT 로건, 연승 도전!' -> {'kt', '로건', '연승', '도전'}."""
    return {t for t in (norm_key(w) for w in re.split(r"[\s,.!?·'\"()\[\]/-]+", text)) if len(t) >= 2}


def similar_text(a: str, b: str) -> bool:
    """Like similar() on raw texts, plus word overlap for multi-word headlines."""
    if similar(norm_key(a), norm_key(b)):
        return True
    ta, tb = tokens(a), tokens(b)
    shared = ta & tb
    return len(shared) >= 2 and len(shared) / min(len(ta), len(tb)) >= 0.6


def mentions(key: str, text: str) -> bool:
    """Does content `text` (a headline / video title) mention keyword `key`?"""
    return min_len_ok(key) and key in norm_key(text)


def mentions_any(texts: set[str] | list[str], title: str) -> bool:
    """Does `title` mention any of the keyword texts? Whole-key containment, or for multi-word
    keywords at least half of the words (>=2) appearing — '여의도역 5번 출구 에스컬레이터 화재'
    matches '여의도역 에스컬레이터 화재 현장 영상'."""
    title_key = norm_key(title)
    for t in texts:
        if mentions(norm_key(t), title):
            return True
        words = tokens(t)
        if len(words) >= 2:
            hit = {w for w in words if w in title_key}
            if len(hit) >= 2 and len(hit) / len(words) >= 0.5 and any(min_len_ok(w) for w in hit):
                return True
    return False
