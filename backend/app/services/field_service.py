from __future__ import annotations
from typing import Any
from ..runtime import dump
from ..post_processing import group_into_blocks
from ..variable_quality import audit_variables
from ..wrapping import build_wrapping_plan

def identification_complete_payload(document: str, data: dict[str, Any]) -> dict[str, Any]:
    ai_failed = bool(data.get("ai_failed"))
    mode = data.get("identificationMode", "general")
    coverage = list(data.get("coverageWarnings", []))
    if ai_failed:
        raw_preview = data.get("variables", []) or []
        # Preserve the original fail-closed invariant for arbitrary partial AI
        # results. Only the explicit deterministic/System-1 preview produced by
        # AIGateway is allowed through, and every one of those rows is marked
        # needs_review so Word cannot auto-bind it.
        preview = [
            v for v in raw_preview
            if getattr(v, "review_state", None) == "needs_review"
            and "system2_unavailable_preview" in getattr(v, "reason_codes", [])
        ]
        return {
            "variables": [dump(v) for v in preview],
            "variableBlocks": [dump(b) for b in group_into_blocks(preview)] if preview else [],
            "identificationPercentage": 0.0,
            "status": "unavailable",
            "message": "System-2 field detection is unavailable. Review-only candidates are shown, and the document was not modified.",
            "wrappingPlan": [],
            "identificationMode": mode,
            "coverageWarnings": coverage,
            "plan": data.get("plan"),
            "blocks": data.get("blocks"),
        }

    vars_ = data.get("variables", [])
    vars_, quality_warnings = audit_variables(document, vars_)
    coverage.extend(quality_warnings)
    review_vars = [v for v in vars_ if getattr(v, "review_state", None) == "needs_review"]
    if review_vars:
        coverage.append(
            f"{len(review_vars)} candidate(s) remain uncertain and were not auto-bound. Review them before linking to Word."
        )
    pct = 0.0 if not vars_ else min(100.0, sum(v.confidence_score or .5 for v in vars_) / len(vars_) * 100)
    if not vars_:
        status = "no_fields"
        message = "No reusable fields were found."
    elif coverage:
        status = "completed_with_review"
        message = "Field detection completed, but some items require review."
    else:
        status = "completed"
        message = None
    auto_bind_vars = [v for v in vars_ if getattr(v, "review_state", None) not in {"needs_review", "rejected"}]
    return {
        "variables": [dump(v) for v in vars_],
        "variableBlocks": [dump(b) for b in group_into_blocks(vars_)],
        "identificationPercentage": pct,
        "status": status,
        "message": message,
        "wrappingPlan": [dump(x) for x in build_wrapping_plan(auto_bind_vars)],
        "identificationMode": mode,
        "coverageWarnings": coverage,
        "plan": data.get("plan"),
        "blocks": data.get("blocks"),
    }
