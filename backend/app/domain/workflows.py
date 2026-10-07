from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from .expressions import ExpressionError, evaluate, evaluate_bool, validate_expression
from ..safe_regex import UnsafeRegex, safe_fullmatch, validate_safe_regex

ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")
QUESTION_TYPES = {
    "text", "textarea", "date", "datetime", "number", "currency", "email", "phone",
    "boolean", "select", "multi_select", "address", "person", "repeater", "display",
}

# Platform-wide workflow expansion guards. These mirror the DOCX renderer limits so
# a hostile public answer cannot grow without bound before document generation.
MAX_WORKFLOW_REPEATER_ITEMS = 250
MAX_WORKFLOW_TOTAL_REPEATED_ITEMS = 2000
CALCULATION_DATA_PREFIX = "calculated."


class WorkflowDefinitionError(ValueError):
    pass


class WorkflowEvaluationError(WorkflowDefinitionError):
    pass


class WorkflowAnswerValidationError(ValueError):
    def __init__(self, errors: list[dict[str, Any]]):
        self.errors = errors
        super().__init__("Workflow answers failed schema validation")


@dataclass(frozen=True)
class WorkflowEvaluation:
    calculations: dict[str, Any]
    visible_pages: list[dict[str, Any]]
    missing_required: list[dict[str, Any]]
    complete: bool


def _identifier(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not ID_RE.match(text):
        raise WorkflowDefinitionError(f"{label} must be a stable identifier (letters/numbers/._:-)")
    return text


def _condition(value: Any, label: str) -> None:
    if value is None:
        return
    try:
        validate_expression(value)
    except ExpressionError as exc:
        raise WorkflowDefinitionError(f"{label}: {exc}") from exc


def _validate_questions(questions: Any, *, seen: set[str], semantic_seen: set[str], depth: int = 0) -> None:
    if not isinstance(questions, list):
        raise WorkflowDefinitionError("Workflow page questions must be an array")
    if depth > 5:
        raise WorkflowDefinitionError("Repeating question nesting exceeds 5 levels")
    # Repeater child semantic keys are item-scoped, but siblings in the same item
    # must still be unique or answer normalization becomes last-one-wins.
    scope_semantic_seen: set[str] = set()
    for question in questions:
        if not isinstance(question, dict):
            raise WorkflowDefinitionError("Every question must be an object")
        qid = _identifier(question.get("id"), "Question id")
        if qid in seen:
            raise WorkflowDefinitionError(f"Duplicate question id: {qid}")
        seen.add(qid)
        qtype = str(question.get("type") or "text")
        if qtype not in QUESTION_TYPES:
            raise WorkflowDefinitionError(f"Unsupported question type {qtype!r}")
        _condition(question.get("condition"), f"Question {qid} condition")
        semantic = str(question.get("semanticKey") or question.get("semantic_key") or "").strip()
        if qtype not in {"display"} and not semantic:
            raise WorkflowDefinitionError(f"Question {qid} requires semanticKey")
        if semantic:
            if semantic in scope_semantic_seen:
                raise WorkflowDefinitionError(f"Duplicate question semanticKey in the same scope: {semantic}")
            scope_semantic_seen.add(semantic)
        # Only top-level answer keys share the workflow/global data namespace.
        # Keys may repeat in distinct nested repeater scopes, but never among
        # siblings within the same repeated item.
        if semantic and depth == 0:
            if semantic.startswith(CALCULATION_DATA_PREFIX):
                raise WorkflowDefinitionError(f"Question semanticKey uses reserved calculation namespace: {semantic}")
            if semantic in semantic_seen:
                raise WorkflowDefinitionError(f"Duplicate question semanticKey: {semantic}")
            semantic_seen.add(semantic)
        if qtype == "repeater":
            try:
                minimum = int(question.get("minItems", 0) or 0)
                maximum = int(question.get("maxItems", MAX_WORKFLOW_REPEATER_ITEMS) or MAX_WORKFLOW_REPEATER_ITEMS)
            except (TypeError, ValueError) as exc:
                raise WorkflowDefinitionError(f"Repeater {qid} minItems/maxItems must be integers") from exc
            if minimum < 0 or maximum < 0 or minimum > maximum:
                raise WorkflowDefinitionError(f"Repeater {qid} has invalid minItems/maxItems")
            if maximum > MAX_WORKFLOW_REPEATER_ITEMS:
                raise WorkflowDefinitionError(
                    f"Repeater {qid} maxItems exceeds platform limit {MAX_WORKFLOW_REPEATER_ITEMS}"
                )
            _validate_questions(question.get("children") or [], seen=seen, semantic_seen=semantic_seen, depth=depth + 1)
        elif question.get("children"):
            raise WorkflowDefinitionError(f"Only repeater questions may contain children ({qid})")
        options = question.get("options")
        if options is not None and not isinstance(options, list):
            raise WorkflowDefinitionError(f"Question {qid} options must be an array")
        pattern = _validation_rules(question).get("pattern")
        if pattern is not None:
            try:
                validate_safe_regex(str(pattern))
            except UnsafeRegex as exc:
                raise WorkflowDefinitionError(f"Question {qid} validation pattern is unsafe or invalid: {exc}") from exc



def _expression_references(expression: Any) -> dict[str, set[str]]:
    refs: dict[str, set[str]] = {"var": set(), "field": set(), "fact": set()}

    def visit(node: Any) -> None:
        if isinstance(node, list):
            for child in node:
                visit(child)
            return
        if not isinstance(node, dict):
            return
        for kind in ("var", "field", "fact"):
            value = node.get(kind)
            if isinstance(value, str) and value.strip():
                refs[kind].add(value.strip())
        for key, value in node.items():
            if key in {"var", "field", "fact", "item"}:
                continue
            visit(value)

    visit(expression)
    return refs


def _ordered_calculations(calculations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not calculations:
        return []
    by_key = {str(calc["key"]): calc for calc in calculations}
    keys = set(by_key)
    original_order = {str(calc["key"]): index for index, calc in enumerate(calculations)}
    dependencies: dict[str, set[str]] = {}
    for calc in calculations:
        key = str(calc["key"])
        refs = {"var": set(), "field": set(), "fact": set()}
        for node in (calc.get("condition"), calc.get("expression")):
            found = _expression_references(node)
            for kind in refs:
                refs[kind].update(found[kind])
        unknown = refs["var"] - keys
        if unknown:
            raise WorkflowDefinitionError(
                f"Calculation {key} references unknown calculation variable(s): {', '.join(sorted(unknown))}"
            )
        ambiguous = (refs["field"] | refs["fact"]) & keys
        if ambiguous:
            raise WorkflowDefinitionError(
                f"Calculation {key} references calculation key(s) through field/fact: {', '.join(sorted(ambiguous))}; use var references"
            )
        dependencies[key] = set(refs["var"])

    ready = sorted((key for key, deps in dependencies.items() if not deps), key=original_order.__getitem__)
    ordered: list[str] = []
    remaining = {key: set(deps) for key, deps in dependencies.items()}
    while ready:
        key = ready.pop(0)
        if key in ordered:
            continue
        ordered.append(key)
        for candidate in sorted(remaining, key=original_order.__getitem__):
            if key in remaining[candidate]:
                remaining[candidate].remove(key)
                if not remaining[candidate] and candidate not in ordered and candidate not in ready:
                    ready.append(candidate)
        ready.sort(key=original_order.__getitem__)
    if len(ordered) != len(calculations):
        cycle = [key for key in sorted(keys, key=original_order.__getitem__) if key not in ordered]
        raise WorkflowDefinitionError(f"Calculation dependency cycle detected: {' -> '.join(cycle)}")
    return [by_key[key] for key in ordered]


def _validate_condition_calculation_references(pages: list[dict[str, Any]], calculation_keys: set[str]) -> None:
    def check(node: Any, label: str) -> None:
        refs = _expression_references(node)
        unknown = refs["var"] - calculation_keys
        if unknown:
            raise WorkflowDefinitionError(f"{label} references unknown calculation variable(s): {', '.join(sorted(unknown))}")
        ambiguous = (refs["field"] | refs["fact"]) & calculation_keys
        if ambiguous:
            raise WorkflowDefinitionError(
                f"{label} references calculation key(s) through field/fact: {', '.join(sorted(ambiguous))}; use var references"
            )

    def walk_questions(questions: list[dict[str, Any]]) -> None:
        for question in questions:
            check(question.get("condition"), f"Question {question.get('id')} condition")
            walk_questions(list(question.get("children") or []))

    for page in pages:
        check(page.get("condition"), f"Page {page.get('id')} condition")
        walk_questions(list(page.get("questions") or []))


def validate_workflow_definition(definition: Any) -> dict[str, Any]:
    if not isinstance(definition, dict):
        raise WorkflowDefinitionError("Workflow definition must be an object")
    pages = definition.get("pages", [])
    calculations = definition.get("calculations", [])
    if not isinstance(pages, list) or not isinstance(calculations, list):
        raise WorkflowDefinitionError("Workflow pages and calculations must be arrays")
    page_ids: set[str] = set()
    question_ids: set[str] = set()
    question_semantic_keys: set[str] = set()
    calculation_keys: set[str] = set()
    for page in pages:
        if not isinstance(page, dict):
            raise WorkflowDefinitionError("Every page must be an object")
        pid = _identifier(page.get("id"), "Page id")
        if pid in page_ids:
            raise WorkflowDefinitionError(f"Duplicate page id: {pid}")
        page_ids.add(pid)
        _condition(page.get("condition"), f"Page {pid} condition")
        _validate_questions(page.get("questions") or [], seen=question_ids, semantic_seen=question_semantic_keys)
    for calc in calculations:
        if not isinstance(calc, dict):
            raise WorkflowDefinitionError("Every calculation must be an object")
        key = _identifier(calc.get("key"), "Calculation key")
        if key in calculation_keys:
            raise WorkflowDefinitionError(f"Duplicate calculation key: {key}")
        if key.startswith(CALCULATION_DATA_PREFIX):
            raise WorkflowDefinitionError(f"Calculation key must not include the reserved {CALCULATION_DATA_PREFIX!r} output prefix: {key}")
        if key in question_semantic_keys or f"{CALCULATION_DATA_PREFIX}{key}" in question_semantic_keys:
            raise WorkflowDefinitionError(f"Calculation key collides with question semanticKey: {key}")
        calculation_keys.add(key)
        if "expression" not in calc:
            raise WorkflowDefinitionError(f"Calculation {key} requires expression")
        _condition(calc.get("condition"), f"Calculation {key} condition")
        try:
            validate_expression(calc["expression"])
        except ExpressionError as exc:
            raise WorkflowDefinitionError(f"Calculation {key}: {exc}") from exc
    ordered_calculations = _ordered_calculations(calculations)
    _validate_condition_calculation_references(pages, calculation_keys)
    return {**definition, "pages": pages, "calculations": ordered_calculations}


def _validation_rules(question: Mapping[str, Any]) -> dict[str, Any]:
    rules = dict(question.get("validation") or {})
    for key in ("minLength", "maxLength", "pattern", "minValue", "maxValue", "min", "max"):
        if question.get(key) is not None and key not in rules:
            rules[key] = question[key]
    return rules


def _option_values(options: Any) -> list[Any]:
    values: list[Any] = []
    for option in options or []:
        if isinstance(option, dict):
            for key in ("value", "id", "key", "label"):
                if key in option:
                    values.append(option[key]); break
        else:
            values.append(option)
    return values


def _answer_error(errors: list[dict[str, Any]], *, path: str, semantic: str, reason: str, message: str) -> None:
    errors.append({"path": path, "semanticKey": semantic, "reason": reason, "message": message})


def _normalize_answer_value(question: Mapping[str, Any], value: Any, *, path: str, errors: list[dict[str, Any]], repeated_budget: dict[str, int]) -> Any:
    qtype = str(question.get("type") or "text")
    semantic = str(question.get("semanticKey") or question.get("semantic_key") or "")
    if value is None or value == "":
        return value
    rules = _validation_rules(question)

    if qtype == "repeater":
        if not isinstance(value, list):
            _answer_error(errors, path=path, semantic=semantic, reason="type", message="Expected an array of repeated items")
            return value
        minimum = question.get("minItems")
        declared_maximum = question.get("maxItems")
        maximum = min(int(declared_maximum), MAX_WORKFLOW_REPEATER_ITEMS) if declared_maximum is not None else MAX_WORKFLOW_REPEATER_ITEMS
        if minimum is not None and len(value) < int(minimum):
            _answer_error(errors, path=path, semantic=semantic, reason="min_items", message=f"Expected at least {minimum} items")
        if len(value) > maximum:
            _answer_error(errors, path=path, semantic=semantic, reason="max_items", message=f"Expected at most {maximum} items")
        repeated_budget["count"] += len(value)
        if repeated_budget["count"] > MAX_WORKFLOW_TOTAL_REPEATED_ITEMS:
            _answer_error(
                errors, path=path, semantic=semantic, reason="total_items",
                message=f"Workflow contains more than {MAX_WORKFLOW_TOTAL_REPEATED_ITEMS} total repeated items",
            )
        children = [q for q in (question.get("children") or []) if str(q.get("type") or "text") != "display"]
        allowed = {str(q.get("semanticKey") or q.get("semantic_key") or ""): q for q in children}
        normalized: list[Any] = []
        for index, item in enumerate(value):
            item_path = f"{path}[{index}]"
            if not isinstance(item, dict):
                _answer_error(errors, path=item_path, semantic=semantic, reason="type", message="Repeater items must be objects")
                normalized.append(item); continue
            unknown = sorted(str(k) for k in item.keys() if str(k) not in allowed)
            for key in unknown:
                _answer_error(errors, path=f"{item_path}.{key}", semantic=key, reason="unknown_key", message="Unknown repeater answer key")
            out: dict[str, Any] = {}
            for key, child in allowed.items():
                if key in item:
                    out[key] = _normalize_answer_value(child, item[key], path=f"{item_path}.{key}", errors=errors, repeated_budget=repeated_budget)
            normalized.append(out)
        return normalized

    if qtype in {"text", "textarea", "email", "phone", "address", "person", "date", "datetime", "select"}:
        if not isinstance(value, str):
            _answer_error(errors, path=path, semantic=semantic, reason="type", message=f"Expected a string for {qtype}")
            return value
        text = value
        if qtype == "date":
            try: date.fromisoformat(text)
            except ValueError: _answer_error(errors, path=path, semantic=semantic, reason="format", message="Expected an ISO date (YYYY-MM-DD)")
        elif qtype == "datetime":
            try: datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError: _answer_error(errors, path=path, semantic=semantic, reason="format", message="Expected an ISO datetime")
        elif qtype == "email" and re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", text) is None:
            _answer_error(errors, path=path, semantic=semantic, reason="format", message="Expected a valid email address")
        elif qtype == "phone" and re.fullmatch(r"[0-9+().\-\s]{3,64}", text) is None:
            _answer_error(errors, path=path, semantic=semantic, reason="format", message="Expected a valid phone number")
        if qtype == "select":
            options = _option_values(question.get("options"))
            if options and value not in options:
                _answer_error(errors, path=path, semantic=semantic, reason="choice", message="Value is not one of the allowed choices")
        if rules.get("minLength") is not None and len(text) < int(rules["minLength"]):
            _answer_error(errors, path=path, semantic=semantic, reason="min_length", message=f"Expected at least {rules['minLength']} characters")
        if rules.get("maxLength") is not None and len(text) > int(rules["maxLength"]):
            _answer_error(errors, path=path, semantic=semantic, reason="max_length", message=f"Expected at most {rules['maxLength']} characters")
        if rules.get("pattern"):
            try:
                if not safe_fullmatch(str(rules["pattern"]), text):
                    _answer_error(errors, path=path, semantic=semantic, reason="pattern", message="Value does not match the required format")
            except UnsafeRegex:
                _answer_error(errors, path=path, semantic=semantic, reason="definition", message="Workflow contains an unsafe or invalid validation pattern")
        return text

    if qtype in {"number", "currency"}:
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            _answer_error(errors, path=path, semantic=semantic, reason="type", message=f"Expected a numeric value for {qtype}")
            return value
        try:
            number = Decimal(str(value).replace(",", "").strip())
        except (InvalidOperation, ValueError):
            _answer_error(errors, path=path, semantic=semantic, reason="type", message=f"Expected a numeric value for {qtype}")
            return value
        minimum = rules.get("minValue", rules.get("min"))
        maximum = rules.get("maxValue", rules.get("max"))
        if minimum is not None and number < Decimal(str(minimum)):
            _answer_error(errors, path=path, semantic=semantic, reason="min_value", message=f"Value must be at least {minimum}")
        if maximum is not None and number > Decimal(str(maximum)):
            _answer_error(errors, path=path, semantic=semantic, reason="max_value", message=f"Value must be at most {maximum}")
        return int(number) if number == number.to_integral_value() else float(number)

    if qtype == "boolean":
        if not isinstance(value, bool):
            _answer_error(errors, path=path, semantic=semantic, reason="type", message="Expected true or false")
        return value

    if qtype == "multi_select":
        if not isinstance(value, list):
            _answer_error(errors, path=path, semantic=semantic, reason="type", message="Expected an array of choices")
            return value
        options = _option_values(question.get("options"))
        invalid = [item for item in value if options and item not in options]
        if invalid:
            _answer_error(errors, path=path, semantic=semantic, reason="choice", message="One or more values are not allowed choices")
        minimum = question.get("minItems")
        maximum = question.get("maxItems")
        if minimum is not None and len(value) < int(minimum):
            _answer_error(errors, path=path, semantic=semantic, reason="min_items", message=f"Expected at least {minimum} choices")
        if maximum is not None and len(value) > int(maximum):
            _answer_error(errors, path=path, semantic=semantic, reason="max_items", message=f"Expected at most {maximum} choices")
        return value

    _answer_error(errors, path=path, semantic=semantic, reason="type", message=f"Unsupported answer type {qtype}")
    return value


def validate_workflow_answers(definition: dict[str, Any], answers: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize a workflow answer object against its immutable definition.

    The schema is fail-closed: undeclared top-level keys and undeclared repeater-item
    keys are rejected. Required/visibility semantics remain in ``evaluate_workflow``
    because those requirements may be conditional on other answers/calculations.
    """
    definition = validate_workflow_definition(definition)
    questions: dict[str, dict[str, Any]] = {}
    for page in definition.get("pages", []):
        for question in page.get("questions") or []:
            if str(question.get("type") or "text") == "display":
                continue
            semantic = str(question.get("semanticKey") or question.get("semantic_key") or "")
            questions[semantic] = question
    errors: list[dict[str, Any]] = []
    for key in sorted(str(k) for k in answers.keys() if str(k) not in questions):
        _answer_error(errors, path=key, semantic=key, reason="unknown_key", message="Answer key is not declared by the published workflow")
    normalized: dict[str, Any] = {}
    repeated_budget = {"count": 0}
    for key, question in questions.items():
        if key in answers:
            normalized[key] = _normalize_answer_value(
                question, answers[key], path=key, errors=errors, repeated_budget=repeated_budget
            )
    if errors:
        raise WorkflowAnswerValidationError(errors)
    return normalized


def _value(data: Mapping[str, Any], semantic_key: str) -> Any:
    return evaluate({"field": semantic_key}, data).value


def _is_missing(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _question_visible(question: dict[str, Any], data: Mapping[str, Any], calculations: Mapping[str, Any], item: Any = None) -> bool:
    condition = question.get("condition")
    if condition is None:
        return True
    try:
        return evaluate_bool(condition, data, item=item, variables=calculations)
    except ExpressionError as exc:
        raise WorkflowEvaluationError(f"Question condition evaluation failed: {exc}") from exc


def _validate_required(
    questions: list[dict[str, Any]], data: Mapping[str, Any], calculations: Mapping[str, Any], missing: list[dict[str, Any]], *, item: Any = None, path: str = ""
) -> list[dict[str, Any]]:
    visible: list[dict[str, Any]] = []
    for question in questions:
        if not _question_visible(question, data, calculations, item=item):
            continue
        q = dict(question)
        qtype = str(q.get("type") or "text")
        semantic = str(q.get("semanticKey") or q.get("semantic_key") or "")
        value = None
        if qtype != "display":
            if item is not None and bool(q.get("itemScoped", True)):
                value = evaluate({"item": semantic}, data, item=item, variables=calculations).value
            else:
                value = _value(data, semantic)
        if qtype == "repeater":
            collection = value
            if collection is None:
                collection = []
            if not isinstance(collection, list):
                missing.append({"questionId": q.get("id"), "semanticKey": semantic, "label": q.get("label", semantic), "reason": "expected_collection", "path": path})
                collection = []
            minimum = int(q.get("minItems", 1 if q.get("required") else 0) or 0)
            if len(collection) < minimum:
                missing.append({"questionId": q.get("id"), "semanticKey": semantic, "label": q.get("label", semantic), "reason": "min_items", "minimum": minimum, "path": path})
            children = q.get("children") or []
            for index, entry in enumerate(collection):
                _validate_required(children, data, calculations, missing, item=entry, path=f"{path}{semantic}[{index}].")
        elif q.get("required") and _is_missing(value):
            missing.append({"questionId": q.get("id"), "semanticKey": semantic, "label": q.get("label", semantic), "reason": "required", "path": path})
        visible.append(q)
    return visible


def evaluate_workflow(definition: dict[str, Any], data: Mapping[str, Any] | None = None) -> WorkflowEvaluation:
    definition = validate_workflow_definition(definition)
    values: dict[str, Any] = dict(data or {})
    calculations: dict[str, Any] = {}
    for calc in definition.get("calculations", []):
        key = str(calc["key"])
        condition = calc.get("condition")
        try:
            enabled = True if condition is None else evaluate_bool(condition, values, variables=calculations)
            if enabled:
                result = evaluate(calc["expression"], values, variables=calculations).value
            else:
                result = calc.get("fallback")
        except ExpressionError as exc:
            raise WorkflowEvaluationError(f"Calculation {key} evaluation failed: {exc}") from exc
        calculations[key] = result
        # Calculation results intentionally remain in the separate ``variables``
        # namespace. Conditions/calculations must reference them with {var: key};
        # they never overwrite answer/canonical semantic keys.

    missing: list[dict[str, Any]] = []
    visible_pages: list[dict[str, Any]] = []
    for page in definition.get("pages", []):
        condition = page.get("condition")
        try:
            if condition is not None and not evaluate_bool(condition, values, variables=calculations):
                continue
        except ExpressionError as exc:
            raise WorkflowEvaluationError(f"Page condition evaluation failed for {page.get('id')}: {exc}") from exc
        visible_questions = _validate_required(page.get("questions") or [], values, calculations, missing)
        visible_pages.append({**page, "questions": visible_questions})
    return WorkflowEvaluation(calculations=calculations, visible_pages=visible_pages, missing_required=missing, complete=not missing)
