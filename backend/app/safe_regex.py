from __future__ import annotations

import re
from re import _parser as sre_parse
from typing import Any

MAX_REGEX_PATTERN_CHARS = 256
MAX_REGEX_INPUT_CHARS = 4096


class UnsafeRegex(ValueError):
    """Raised when a user-configurable validation regex is unsafe or invalid."""


def _walk_regex(parsed: Any, *, inside_repeat: bool = False) -> None:
    for op, arg in parsed:
        if op in {sre_parse.GROUPREF, sre_parse.GROUPREF_EXISTS, sre_parse.ASSERT, sre_parse.ASSERT_NOT}:
            raise UnsafeRegex("Backreferences and look-around assertions are not allowed in validation patterns")
        if op in {sre_parse.MAX_REPEAT, sre_parse.MIN_REPEAT, sre_parse.POSSESSIVE_REPEAT}:
            if inside_repeat:
                raise UnsafeRegex("Nested repetition is not allowed in validation patterns")
            _min, _max, child = arg
            _walk_regex(child, inside_repeat=True)
            continue
        if op is sre_parse.SUBPATTERN:
            _walk_regex(arg[-1], inside_repeat=inside_repeat)
            continue
        if op is sre_parse.BRANCH:
            if inside_repeat:
                raise UnsafeRegex("Alternation inside a repeated group is not allowed in validation patterns")
            for branch in arg[1]:
                _walk_regex(branch, inside_repeat=inside_repeat)


def validate_safe_regex(pattern: str) -> re.Pattern[str]:
    text = str(pattern or "")
    if not text:
        raise UnsafeRegex("Validation pattern cannot be empty")
    if len(text) > MAX_REGEX_PATTERN_CHARS:
        raise UnsafeRegex("Validation pattern is too long")
    try:
        parsed = sre_parse.parse(text)
        _walk_regex(parsed)
        return re.compile(text)
    except UnsafeRegex:
        raise
    except re.error as exc:
        raise UnsafeRegex("Validation pattern is invalid") from exc


def safe_fullmatch(pattern: str, value: str) -> bool:
    if len(value) > MAX_REGEX_INPUT_CHARS:
        return False
    return validate_safe_regex(pattern).fullmatch(value) is not None
