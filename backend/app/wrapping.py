import re
from .models import Variable, WrappingPlanEntry

_WORD_META = set("?*[]{}<>()@\\!")

def strip_braces(text: str) -> str:
    s = text.strip()
    while len(s) > 1 and s.startswith("{") and s.endswith("}"):
        s = s[1:-1]
    return s

def escape_word_wildcards(text: str) -> str:
    return "".join(("\\" + c) if c in _WORD_META else c for c in text)

def child_aware_pattern(parent: str, others: list[str]) -> str | None:
    if not parent:
        return None
    children = sorted({c for c in others if c and c.lower() != parent.lower() and c.lower() in parent.lower()}, key=len, reverse=True)
    work = parent
    for c in children:
        work = re.sub(re.escape(c), "\x01", work, flags=re.I)
    pieces = []
    for seg in work.split("\x01"):
        seg = re.sub(r"[\s\u00a0]+", "\x02", seg)
        pieces.append("*".join(escape_word_wildcards(x) for x in seg.split("\x02")))
    transformed = "*".join(pieces)
    transformed = re.sub(r"\*+", "*", transformed)
    return transformed if "*" in transformed else None

def build_wrapping_plan(variables: list[Variable]) -> list[WrappingPlanEntry]:
    # Uncertain candidates are intentionally visible to the lawyer but are not
    # auto-bound. This mirrors lawyer-firm's CHECK THESE principle while keeping
    # Word mutation fail-safe. variableIndex still refers to the original array.
    eligible = [
        i for i, v in enumerate(variables)
        if v.review_state not in {"needs_review", "rejected"}
    ]
    originals = {i: strip_braces(variables[i].original_text) for i in eligible}
    absorbed: dict[int, int | None] = {}
    for i in eligible:
        me = originals[i]
        parents = [j for j in eligible if j != i and len(originals[j]) > len(me) and me and me in originals[j]]
        absorbed[i] = min(parents, key=lambda j: len(originals[j])) if parents else None
    order = sorted(eligible, key=lambda i: len(originals[i]))
    result = []
    for i in order:
        others = [originals[j] for j in eligible if j != i]
        wildcard = child_aware_pattern(originals[i], others)
        result.append(WrappingPlanEntry(
            variableIndex=i,
            searchText=wildcard or originals[i],
            useWildcards=bool(wildcard),
            insertBraces=True,
            absorbedBy=absorbed[i],
        ))
    return result
