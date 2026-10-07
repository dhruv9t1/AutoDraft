from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


def fact_key(label: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "_", (label or "").strip().lower()).strip("_")
    return value or "fact"


def normalize_fact_value(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


@dataclass(frozen=True)
class DerivedEvaluation:
    value: str
    sources: tuple[str, ...]


def evaluate_expression(expression: dict[str, Any], facts: dict[str, str]) -> DerivedEvaluation | None:
    """Backward-compatible derived-fact wrapper around the shared automation expression engine."""
    from .expressions import ExpressionError, evaluate
    # Legacy rules used op=concat/sum/difference/multiply/format and {fact: key}.
    # `format` is preserved here because the new general engine intentionally avoids
    # Python format-string execution as a top-level automation operator.
    if isinstance(expression, dict) and str(expression.get("op") or "").lower() == "format":
        args=expression.get("args") or []
        values=[];sources=[]
        for arg in args:
            if isinstance(arg,dict) and "fact" in arg:
                key=str(arg["fact"]);sources.append(key);values.append(facts.get(key,""))
            elif isinstance(arg,dict) and "literal" in arg: values.append(arg["literal"])
            else: values.append(arg)
        try: result=str(expression.get("template") or "{}").format(*values).strip()
        except Exception: return None
        return DerivedEvaluation(result,tuple(dict.fromkeys(sources))) if result else None
    try:
        result=evaluate(expression,facts)
    except ExpressionError:
        return None
    if result.value is None or result.value is False:
        return None
    text=str(result.value).strip()
    return DerivedEvaluation(text,result.sources) if text else None
