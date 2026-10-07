from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping


class ExpressionError(ValueError):
    """Raised when an automation expression is invalid or cannot be evaluated safely."""


MAX_DEPTH = 32
MAX_NODES = 1000
SUPPORTED_OPS = {
    "eq", "neq", "gt", "gte", "lt", "lte", "exists", "empty", "contains", "in",
    "and", "or", "not", "add", "subtract", "multiply", "divide", "sum", "difference",
    "concat", "coalesce", "if", "date_add", "date_diff", "format_date", "format_number",
    "lower", "upper", "title",
}

# (minimum arguments, maximum arguments). ``None`` means unbounded.
# Publication-time arity validation prevents malformed expressions from being
# accepted and later interpreted with accidental/default semantics.
OP_ARITY: dict[str, tuple[int, int | None]] = {
    "eq": (2, 2), "neq": (2, 2), "gt": (2, 2), "gte": (2, 2), "lt": (2, 2), "lte": (2, 2),
    "exists": (1, 1), "empty": (1, 1), "contains": (2, 2), "in": (2, 2),
    "and": (1, None), "or": (1, None), "not": (1, 1),
    "add": (1, None), "sum": (1, None), "subtract": (1, None), "difference": (1, None),
    "multiply": (1, None), "divide": (2, None), "concat": (1, None), "coalesce": (1, None),
    "if": (2, 3), "date_add": (2, 2), "date_diff": (2, 2),
    "format_date": (1, 1), "format_number": (1, 1), "lower": (1, 1), "upper": (1, 1), "title": (1, 1),
}


def _validate_operator_arity(op: str, args: list[Any]) -> None:
    minimum, maximum = OP_ARITY[op]
    count = len(args)
    if count < minimum or (maximum is not None and count > maximum):
        if maximum is None:
            expected = f"at least {minimum}"
        elif minimum == maximum:
            expected = str(minimum)
        else:
            expected = f"{minimum} to {maximum}"
        raise ExpressionError(f"{op} requires {expected} argument(s); got {count}")


@dataclass(frozen=True)
class EvaluationResult:
    value: Any
    sources: tuple[str, ...] = ()


def _path_get(root: Any, path: str, *, exact_first: bool = True) -> Any:
    if not path:
        return root
    if exact_first and isinstance(root, Mapping) and path in root:
        return root[path]
    value = root
    for part in path.split("."):
        if isinstance(value, Mapping):
            if part not in value:
                return None
            value = value[part]
        elif isinstance(value, (list, tuple)) and part.isdigit():
            index = int(part)
            if index >= len(value):
                return None
            value = value[index]
        else:
            return None
    return value


def _decimal(value: Any) -> Decimal:
    if isinstance(value, bool) or value is None or value == "":
        raise ExpressionError("A numeric value is required")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError) as exc:
        raise ExpressionError(f"Not a number: {value!r}") from exc


def _date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        raise ExpressionError("A date is required")
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(text)
        except ValueError as exc:
            raise ExpressionError(f"Expected an ISO date, got {value!r}") from exc


def _truthy(value: Any) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, str):
        return value.strip().lower() not in {"", "false", "no", "0", "none", "null"}
    if isinstance(value, (list, tuple, dict, set)):
        return bool(value)
    return bool(value)


def _json_number(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)


def _operator_node(expression: dict[str, Any]) -> tuple[str, list[Any], dict[str, Any]] | None:
    if "op" in expression:
        op = str(expression.get("op") or "").strip().lower()
        args = expression.get("args", [])
        if not isinstance(args, list):
            raise ExpressionError("Expression args must be an array")
        return op, args, expression
    matches = [key for key in expression if key in SUPPORTED_OPS]
    if len(matches) == 1:
        op = matches[0]
        raw = expression[op]
        args = raw if isinstance(raw, list) else [raw]
        return op, args, expression
    return None


def validate_expression(expression: Any, *, max_depth: int = MAX_DEPTH, max_nodes: int = MAX_NODES) -> None:
    nodes = 0

    def visit(node: Any, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > max_nodes:
            raise ExpressionError(f"Expression exceeds {max_nodes} nodes")
        if depth > max_depth:
            raise ExpressionError(f"Expression exceeds nesting depth {max_depth}")
        if node is None or isinstance(node, (str, int, float, bool, Decimal, date, datetime)):
            return
        if isinstance(node, list):
            for child in node:
                visit(child, depth + 1)
            return
        if not isinstance(node, dict):
            raise ExpressionError(f"Unsupported expression value: {type(node).__name__}")
        refs = [key for key in ("field", "fact", "item", "var", "literal") if key in node]
        if refs:
            if len(refs) != 1:
                raise ExpressionError("Reference expression must contain exactly one reference kind")
            if refs[0] != "literal" and not isinstance(node[refs[0]], str):
                raise ExpressionError(f"{refs[0]} reference must be a string")
            if refs[0] == "literal":
                visit(node[refs[0]], depth + 1)
            return
        operator = _operator_node(node)
        if operator is None:
            raise ExpressionError("Expression object must be a reference, literal, or supported operator")
        op, args, _ = operator
        if not op:
            raise ExpressionError("Expression operator is required")
        if op not in SUPPORTED_OPS:
            raise ExpressionError(f"Unsupported operator: {op}")
        _validate_operator_arity(op, args)
        for child in args:
            visit(child, depth + 1)

    visit(expression, 0)


def evaluate(
    expression: Any,
    data: Mapping[str, Any] | None = None,
    *,
    item: Any = None,
    variables: Mapping[str, Any] | None = None,
    max_depth: int = MAX_DEPTH,
    max_nodes: int = MAX_NODES,
) -> EvaluationResult:
    validate_expression(expression, max_depth=max_depth, max_nodes=max_nodes)
    root: Mapping[str, Any] = data or {}
    calc: Mapping[str, Any] = variables or {}
    sources: list[str] = []

    def ev(node: Any) -> Any:
        if node is None or isinstance(node, (str, int, float, bool, Decimal, date, datetime)):
            return node
        if isinstance(node, list):
            return [ev(child) for child in node]
        if "literal" in node:
            return node["literal"]
        if "field" in node or "fact" in node:
            key = str(node.get("field") if "field" in node else node.get("fact"))
            sources.append(key)
            return _path_get(root, key)
        if "var" in node:
            key = str(node["var"])
            sources.append(f"calculation:{key}")
            return _path_get(calc, key)
        if "item" in node:
            return _path_get(item, str(node["item"]), exact_first=False)

        op, raw_args, metadata = _operator_node(node) or ("", [], node)

        # Branching/logical operators are deliberately lazy.  A hidden branch
        # must not fail the active path (for example, divide-by-zero inside the
        # false arm of an ``if``), and AND/OR should short-circuit normally.
        if op == "if":
            if not raw_args: return None
            condition = ev(raw_args[0])
            if _truthy(condition): return ev(raw_args[1]) if len(raw_args) > 1 else True
            return ev(raw_args[2]) if len(raw_args) > 2 else None
        if op == "and":
            for arg in raw_args:
                if not _truthy(ev(arg)): return False
            return True
        if op == "or":
            for arg in raw_args:
                if _truthy(ev(arg)): return True
            return False
        if op == "coalesce":
            for arg in raw_args:
                value = ev(arg)
                if value is not None and value != "" and value != []:
                    return value
            return None

        args = [ev(arg) for arg in raw_args]

        if op == "eq": return len(args) >= 2 and args[0] == args[1]
        if op == "neq": return len(args) >= 2 and args[0] != args[1]
        if op in {"gt", "gte", "lt", "lte"}:
            if len(args) < 2:
                raise ExpressionError(f"{op} requires two operands")
            left, right = args[0], args[1]

            # Ordering is deliberately type-aware and fail-closed.  Legal
            # thresholds must never fall back to lexicographic string ordering
            # (for example, "9" > "10").  ISO dates are supported when
            # both operands are date-like; otherwise both operands must be numeric.
            date_like = isinstance(left, (date, datetime)) or isinstance(right, (date, datetime))
            if not date_like and isinstance(left, str) and isinstance(right, str):
                date_like = bool(left.strip()) and bool(right.strip()) and ("-" in left or "T" in left or "-" in right or "T" in right)
            if date_like:
                try:
                    left_ordered, right_ordered = _date(left), _date(right)
                except ExpressionError as exc:
                    raise ExpressionError(f"{op} date comparison requires two ISO date/datetime operands") from exc
            else:
                try:
                    left_ordered, right_ordered = _decimal(left), _decimal(right)
                except ExpressionError as exc:
                    raise ExpressionError(f"{op} comparison requires numeric or ISO date/datetime operands") from exc
            return {
                "gt": left_ordered > right_ordered,
                "gte": left_ordered >= right_ordered,
                "lt": left_ordered < right_ordered,
                "lte": left_ordered <= right_ordered,
            }[op]
        if op == "exists": return bool(args) and args[0] is not None and args[0] != "" and args[0] != []
        if op == "empty": return not args or args[0] is None or args[0] == "" or args[0] == [] or args[0] == {}
        if op == "contains":
            container, member = args
            if container is None:
                return False
            if isinstance(container, str):
                if not isinstance(member, str):
                    raise ExpressionError("contains on text requires a text member")
                return member in container
            if isinstance(container, Mapping):
                return member in container
            if isinstance(container, (list, tuple, set, frozenset)):
                return member in container
            raise ExpressionError("contains requires a text, array, set, or object container")
        if op == "in":
            if len(args) < 2 or args[1] is None: return False
            try: return args[0] in args[1]
            except TypeError: return False
        if op == "not": return not _truthy(args[0] if args else None)
        if op in {"add", "sum"}:
            return _json_number(sum((_decimal(arg) for arg in args), Decimal("0")))
        if op in {"subtract", "difference"}:
            if not args: return 0
            result = _decimal(args[0])
            for arg in args[1:]: result -= _decimal(arg)
            return _json_number(result)
        if op == "multiply":
            result = Decimal("1")
            for arg in args: result *= _decimal(arg)
            return _json_number(result)
        if op == "divide":
            if len(args) < 2: raise ExpressionError("divide requires at least two arguments")
            result = _decimal(args[0])
            for arg in args[1:]:
                denominator = _decimal(arg)
                if denominator == 0: raise ExpressionError("Division by zero")
                result /= denominator
            return _json_number(result)
        if op == "concat":
            sep = str(metadata.get("separator", ""))
            return sep.join(str(arg) for arg in args if arg is not None)
        if op == "date_add":
            if len(args) < 2: raise ExpressionError("date_add requires a date and day count")
            try:
                return (_date(args[0]) + timedelta(days=int(_decimal(args[1])))).isoformat()
            except (OverflowError, ValueError) as exc:
                raise ExpressionError("date_add result is outside the supported date range") from exc
        if op == "date_diff":
            if len(args) < 2: raise ExpressionError("date_diff requires two dates")
            return (_date(args[0]) - _date(args[1])).days
        if op == "format_date":
            if not args: return ""
            fmt = str(metadata.get("format") or "%d/%m/%Y")
            try: return _date(args[0]).strftime(fmt)
            except (ValueError, OverflowError) as exc: raise ExpressionError("Invalid date format") from exc
        if op == "format_number":
            if not args: return ""
            try: decimals = int(metadata.get("decimals", 2))
            except (TypeError, ValueError) as exc: raise ExpressionError("format_number decimals must be an integer") from exc
            if decimals < 0 or decimals > 12: raise ExpressionError("format_number decimals must be between 0 and 12")
            grouping = bool(metadata.get("grouping", False))
            symbol = str(metadata.get("symbol", ""))
            try: number = float(_decimal(args[0]))
            except (OverflowError, ValueError) as exc: raise ExpressionError("Number is outside the supported formatting range") from exc
            spec = f",.{decimals}f" if grouping else f".{decimals}f"
            try: return f"{symbol}{format(number, spec)}"
            except (ValueError, OverflowError) as exc: raise ExpressionError("Invalid number format") from exc
        if op == "lower": return str(args[0] if args else "").lower()
        if op == "upper": return str(args[0] if args else "").upper()
        if op == "title": return str(args[0] if args else "").title()
        raise ExpressionError(f"Unsupported operator: {op}")

    value = ev(expression)
    return EvaluationResult(value=value, sources=tuple(dict.fromkeys(sources)))


def evaluate_bool(expression: Any, data: Mapping[str, Any] | None = None, **kwargs: Any) -> bool:
    return _truthy(evaluate(expression, data, **kwargs).value)
