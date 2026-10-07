from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
import uuid


REFERENCE_TYPES = {"contact_reference", "matter_reference", "document_reference"}
TEXT_TYPES = {"text", "long_text", "email", "phone", "address", "choice"}
NUMBER_TYPES = {"integer", "decimal", "currency"}


def _reference_uuid(value: Any) -> uuid.UUID:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value).strip())
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("Reference value must be a valid UUID") from exc


def storage_columns(value_type: str, value: Any) -> dict[str, Any]:
    """Normalize an API value into canonical typed storage columns.

    Reference values are persisted in dedicated UUID columns so PostgreSQL can
    enforce same-tenant referential integrity. ``raw_text`` remains a stable
    display/search representation, but is never the authority for references.
    """
    out = {
        "raw_text": None,
        "value_text": None,
        "value_number": None,
        "value_boolean": None,
        "value_date": None,
        "value_datetime": None,
        "value_json": None,
        "value_contact_id": None,
        "value_matter_id": None,
        "value_document_id": None,
    }
    if value is None:
        return out
    if value_type in TEXT_TYPES:
        text = str(value)
        out["raw_text"] = text
        out["value_text"] = text
        return out
    if value_type in REFERENCE_TYPES:
        ref = _reference_uuid(value)
        out["raw_text"] = str(ref)
        out[{"contact_reference": "value_contact_id", "matter_reference": "value_matter_id", "document_reference": "value_document_id"}[value_type]] = ref
        return out
    if value_type in NUMBER_TYPES:
        try:
            number = Decimal(str(value).replace(",", "").strip())
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"Value is not a valid {value_type}") from exc
        if value_type == "integer" and number != number.to_integral_value():
            raise ValueError("Value is not a whole number")
        out["raw_text"] = str(value)
        out["value_number"] = number
        return out
    if value_type == "boolean":
        if isinstance(value, bool):
            parsed = value
        elif str(value).strip().lower() in {"true", "yes", "1"}:
            parsed = True
        elif str(value).strip().lower() in {"false", "no", "0"}:
            parsed = False
        else:
            raise ValueError("Value is not a valid boolean")
        out["raw_text"] = "true" if parsed else "false"
        out["value_boolean"] = parsed
        return out
    if value_type == "date":
        try:
            parsed = value if isinstance(value, date) and not isinstance(value, datetime) else date.fromisoformat(str(value))
        except ValueError as exc:
            raise ValueError("Value is not a valid ISO date") from exc
        out["raw_text"] = parsed.isoformat()
        out["value_date"] = parsed
        return out
    if value_type == "datetime":
        try:
            parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("Value is not a valid ISO datetime") from exc
        out["raw_text"] = parsed.isoformat()
        out["value_datetime"] = parsed
        return out
    if value_type in {"multi_choice", "json"}:
        if value_type == "multi_choice" and not isinstance(value, list):
            raise ValueError("A multi-choice value must be an array")
        out["raw_text"] = ", ".join(map(str, value)) if isinstance(value, list) else str(value)
        out["value_json"] = value
        return out
    raise ValueError(f"Unsupported field value type: {value_type}")


def display_value(row: Any, value_type: str) -> Any:
    if value_type in TEXT_TYPES:
        return row.get("value_text")
    if value_type in REFERENCE_TYPES:
        key = {"contact_reference": "value_contact_id", "matter_reference": "value_matter_id", "document_reference": "value_document_id"}[value_type]
        ref = row.get(key)
        return str(ref) if ref is not None else row.get("raw_text")
    if value_type in NUMBER_TYPES:
        v = row.get("value_number")
        return str(v) if v is not None else row.get("raw_text")
    if value_type == "boolean":
        v = row.get("value_boolean")
        return v if v is not None else row.get("raw_text")
    if value_type == "date":
        v = row.get("value_date")
        return v.isoformat() if v else row.get("raw_text")
    if value_type == "datetime":
        v = row.get("value_datetime")
        return v.isoformat() if v else row.get("raw_text")
    v = row.get("value_json")
    return v if v is not None else row.get("raw_text")


def validate_field_value(definition: Any, value: Any) -> None:
    """Apply deterministic definition-level constraints before persistence."""
    required = bool(definition.get("required") if hasattr(definition, "get") else definition["required"])
    value_type = definition.get("value_type") if hasattr(definition, "get") else definition["value_type"]
    options = (definition.get("options") if hasattr(definition, "get") else definition["options"]) or []
    rules = (definition.get("validation") if hasattr(definition, "get") else definition["validation"]) or {}

    empty = value is None or value == "" or value == []
    if required and empty:
        raise ValueError("A value is required")
    if empty:
        return

    if value_type in REFERENCE_TYPES:
        _reference_uuid(value)

    if value_type == "choice" and options and value not in options:
        raise ValueError("Value is not one of the allowed choices")
    if value_type == "multi_choice" and options:
        if not isinstance(value, list):
            raise ValueError("A multi-choice value must be an array")
        invalid = [item for item in value if item not in options]
        if invalid:
            raise ValueError("One or more values are not allowed choices")

    if value_type in NUMBER_TYPES:
        try:
            number = Decimal(str(value).replace(",", "").strip())
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"Value is not a valid {value_type}") from exc
        if value_type == "integer" and number != number.to_integral_value():
            raise ValueError("Value is not a whole number")
        if rules.get("min") is not None and number < Decimal(str(rules["min"])):
            raise ValueError(f"Value must be at least {rules['min']}")
        if rules.get("max") is not None and number > Decimal(str(rules["max"])):
            raise ValueError(f"Value must be at most {rules['max']}")

    if isinstance(value, str):
        if rules.get("minLength") is not None and len(value) < int(rules["minLength"]):
            raise ValueError(f"Value must contain at least {rules['minLength']} characters")
        if rules.get("maxLength") is not None and len(value) > int(rules["maxLength"]):
            raise ValueError(f"Value must contain at most {rules['maxLength']} characters")
        pattern = rules.get("pattern")
        if pattern:
            import re
            try:
                if re.fullmatch(str(pattern), value) is None:
                    raise ValueError("Value does not match the required format")
            except re.error as exc:
                raise ValueError("Field definition has an invalid validation pattern") from exc
