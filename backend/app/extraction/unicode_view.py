from __future__ import annotations

import re
import sys
import unicodedata
from functools import lru_cache


@lru_cache(maxsize=1)
def _digit_map() -> dict[int, str]:
    """Unicode decimal digit -> ASCII digit, preserving one codepoint per input char."""
    out: dict[int, str] = {}
    for codepoint in range(128, sys.maxunicode + 1):
        char = chr(codepoint)
        if unicodedata.category(char) == "Nd":
            try:
                out[codepoint] = str(unicodedata.digit(char))
            except (TypeError, ValueError):
                pass
    return out


def fold_char(char: str) -> str:
    """Return a one-character regex view of *char*.

    This intentionally never changes string length. That means every offset in the
    folded view is the same offset in the original Word text, which is essential for
    safe content-control binding. Indian-script digits are folded to ASCII, Unicode
    spaces become normal spaces, and accented Latin letters become x/X only for word
    boundary matching (the source value is never replaced by this view).
    """
    if not char:
        return char
    codepoint = ord(char)
    digit = _digit_map().get(codepoint)
    if digit is not None:
        return digit
    if char in {"\n", "\r"}:
        return char
    if char.isspace():
        return " "
    category = unicodedata.category(char)
    if category.startswith("L") and (
        0x00C0 <= codepoint < 0x0250 or 0x1E00 <= codepoint < 0x1F00
    ):
        return "X" if category == "Lu" else "x"
    return char


def offset_view(text: str) -> str:
    """Return an offset-identical normalized shadow string."""
    return "".join(fold_char(ch) for ch in text or "")


def candidate_key(value: str) -> str:
    """Canonical comparison key without losing punctuation semantics.

    Whitespace and digit script differences are ignored, but punctuation is kept so
    values such as 1/11/2023 and 11/1/2023 remain distinct. Unlike lawyer-firm's
    prototype, this key is used for evidence grouping only; it never merges source
    occurrences or semantic field identities.
    """
    folded = "".join(_digit_map().get(ord(ch), ch) for ch in (value or ""))
    return re.sub(r"\s+", "", folded).upper()


def normalize_space(value: str) -> str:
    return re.sub(r"[\s\u00a0]+", " ", value or "").strip()
