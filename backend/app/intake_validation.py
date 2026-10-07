from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from .safe_regex import (
    MAX_REGEX_INPUT_CHARS,
    MAX_REGEX_PATTERN_CHARS,
    UnsafeRegex,
    safe_fullmatch,
    validate_safe_regex,
)

UnsafeIntakeRegex = UnsafeRegex


MAX_TEXT_ANSWER_CHARS = 10000
MAX_MULTI_SELECT_ITEMS = 100

_ALLOWED_QUESTION_TYPES = {
    "text", "textarea", "date", "number", "currency", "email", "phone",
    "select", "boolean", "address", "person", "multi_select", "file",
}

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_PHONE_RE = re.compile(r"^[+()0-9 .\-]{7,32}$")


@dataclass(frozen=True)
class IntakeValidationResult:
    normalized: dict[str, Any]
    missing: list[str]
    invalid: list[str]
    unknown: list[str]

    @property
    def ok(self) -> bool:
        return not (self.missing or self.invalid or self.unknown)

def normalize_question_snapshot(question: dict[str, Any], *, index: int = 0) -> dict[str, Any]:
    qid = str(question.get("id") or f"legacy_question_{index + 1}").strip()
    qtype = str(question.get("type") or question.get("question_type") or "text").strip().lower()
    if qtype not in _ALLOWED_QUESTION_TYPES:
        qtype = "text"
    options = [str(x) for x in (question.get("options") or []) if str(x).strip()]
    validation = dict(question.get("validation") or {})
    return {
        "id": qid,
        "label": str(question.get("label") or question.get("question") or qid),
        "type": qtype,
        "required": bool(question.get("required", False)),
        "options": options,
        "mapsTo": str(question.get("mapsTo") or question.get("maps_to") or question.get("fact_key") or ""),
        "helpText": str(question.get("helpText") or question.get("help_text") or ""),
        "sectionId": question.get("sectionId") or question.get("section_id"),
        "sectionTitle": question.get("sectionTitle") or question.get("section_title") or "Questions",
        "sectionDescription": question.get("sectionDescription") or question.get("section_description") or "",
        "displayRule": question.get("displayRule") or question.get("display_rule"),
        "validation": validation,
    }


def normalize_questions(questions: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(questions):
        if not isinstance(raw, dict):
            continue
        q = normalize_question_snapshot(raw, index=index)
        if not q["id"] or q["id"] in seen:
            continue
        seen.add(q["id"])
        result.append(q)
    return result


def is_visible(question: dict[str, Any], answers: dict[str, Any]) -> bool:
    rule = question.get("displayRule") or question.get("display_rule")
    if not isinstance(rule, dict) or not rule.get("questionId"):
        return True
    actual = answers.get(str(rule["questionId"]))
    op = str(rule.get("operator") or "equals")
    expected = rule.get("value")
    values = [str(x) for x in actual] if isinstance(actual, list) else [str(actual or "")]
    if op == "equals":
        return str(expected or "") in values
    if op == "not_equals":
        return str(expected or "") not in values
    if op == "exists":
        return any(value.strip() for value in values)
    if op == "not_exists":
        return not any(value.strip() for value in values)
    if op == "contains":
        return any(str(expected or "").lower() in value.lower() for value in values)
    return False


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return any(_present(x) for x in value)
    return True


def _decimal(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise InvalidOperation
    try:
        result = Decimal(str(value).strip())
    except Exception as exc:
        raise InvalidOperation from exc
    if not result.is_finite():
        raise InvalidOperation
    return result


def _validate_scalar_text(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError
    text = value.strip()
    if len(text) > MAX_TEXT_ANSWER_CHARS:
        raise ValueError
    return text


def validate_intake_answers(
    questions: list[dict[str, Any]],
    answers: dict[str, Any],
    *,
    uploaded_file_question_ids: set[str] | None = None,
) -> IntakeValidationResult:
    normalized_questions = normalize_questions(questions)
    by_id = {str(q["id"]): q for q in normalized_questions}
    unknown = sorted(str(key) for key in answers if str(key) not in by_id)
    missing: list[str] = []
    invalid: list[str] = []
    normalized: dict[str, Any] = {}
    uploaded = uploaded_file_question_ids or set()

    for qid, q in by_id.items():
        if not is_visible(q, answers):
            continue
        qtype = q["type"]
        value = answers.get(qid)
        present = _present(value) or (qtype == "file" and qid in uploaded)
        if q.get("required") and not present:
            missing.append(qid)
            continue
        if not present:
            continue
        validation = dict(q.get("validation") or {})
        options = [str(x) for x in q.get("options") or []]

        try:
            if qtype in {"text", "textarea", "address", "person"}:
                normalized_value: Any = _validate_scalar_text(value)
            elif qtype == "email":
                normalized_value = _validate_scalar_text(value)
                if len(normalized_value) > 320 or not _EMAIL_RE.fullmatch(normalized_value):
                    raise ValueError
            elif qtype == "phone":
                normalized_value = _validate_scalar_text(value)
                if not _PHONE_RE.fullmatch(normalized_value) or len(re.sub(r"\D", "", normalized_value)) < 7:
                    raise ValueError
            elif qtype == "date":
                normalized_value = _validate_scalar_text(value)
                date.fromisoformat(normalized_value)
            elif qtype in {"number", "currency"}:
                number = _decimal(value)
                if validation.get("minValue") is not None and number < _decimal(validation["minValue"]):
                    raise ValueError
                if validation.get("maxValue") is not None and number > _decimal(validation["maxValue"]):
                    raise ValueError
                normalized_value = format(number, "f")
            elif qtype == "select":
                normalized_value = _validate_scalar_text(value)
                if options and normalized_value not in options:
                    raise ValueError
            elif qtype == "multi_select":
                if not isinstance(value, list) or len(value) > MAX_MULTI_SELECT_ITEMS:
                    raise ValueError
                normalized_value = []
                for item in value:
                    text = _validate_scalar_text(item)
                    if not text:
                        continue
                    if options and text not in options:
                        raise ValueError
                    if text not in normalized_value:
                        normalized_value.append(text)
            elif qtype == "boolean":
                if isinstance(value, bool):
                    normalized_value = "Yes" if value else "No"
                else:
                    normalized_value = _validate_scalar_text(value)
                    if normalized_value not in {"Yes", "No"}:
                        raise ValueError
            elif qtype == "file":
                if qid not in uploaded:
                    # Legacy forms cannot safely accept a fake filename as proof of upload.
                    raise ValueError
                normalized_value = _validate_scalar_text(value) if isinstance(value, str) and value.strip() else "uploaded"
            else:
                raise ValueError

            if isinstance(normalized_value, str):
                if validation.get("minLength") is not None and len(normalized_value) < int(validation["minLength"]):
                    raise ValueError
                if validation.get("maxLength") is not None and len(normalized_value) > int(validation["maxLength"]):
                    raise ValueError
                if validation.get("pattern") and not safe_fullmatch(str(validation["pattern"]), normalized_value):
                    raise ValueError
            normalized[qid] = normalized_value
        except (ValueError, TypeError, InvalidOperation, OverflowError):
            invalid.append(qid)

    return IntakeValidationResult(
        normalized=normalized,
        missing=list(dict.fromkeys(missing)),
        invalid=list(dict.fromkeys(invalid)),
        unknown=unknown,
    )
