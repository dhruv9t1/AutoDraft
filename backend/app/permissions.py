from __future__ import annotations

import re
from dataclasses import dataclass

from fastapi import HTTPException

from .auth import ROLE_ORDER, SecurityContext


PERMISSION_MIN_ROLE: dict[str, str] = {
    "api.mutate": "staff",
    "matter.write": "staff",
    "contact.write": "staff",
    "document.process": "staff",
    "workflow.run": "staff",
    "intake.manage": "lawyer",
    "template.write": "lawyer",
    "generation.execute": "lawyer",
    "generation.override": "lawyer",
    "authority.verify": "lawyer",
    "workflow.admin": "admin",
    "workflow.publish": "admin",
    "template.publish": "admin",
    "document_set.admin": "admin",
    "field_schema.admin": "admin",
    "derived_rule.admin": "admin",
    "practice.admin": "admin",
    "organization.admin": "admin",
    "identity.admin": "admin",
    "integration.admin": "admin",
}


@dataclass(frozen=True)
class PermissionRule:
    methods: frozenset[str]
    pattern: re.Pattern[str]
    permission: str


def _rule(methods: str, pattern: str, permission: str) -> PermissionRule:
    return PermissionRule(frozenset(x.strip().upper() for x in methods.split(",")), re.compile(pattern), permission)


# Ordered most-specific-first. This is the single HTTP action/resource matrix.
PERMISSION_RULES: tuple[PermissionRule, ...] = (
    _rule("POST", r"^/api/auth/identity-bindings$", "identity.admin"),
    _rule("POST", r"^/api/auth/users/[0-9a-fA-F-]+/revoke-sessions$", "identity.admin"),
    _rule("POST,PATCH,DELETE", r"^/api/integrations(?:/.*)?$", "integration.admin"),
    _rule("POST,PATCH", r"^/api/practice-areas(?:/[^/]+)?$", "practice.admin"),
    _rule("POST,PATCH", r"^/api/matter-stages(?:/[^/]+)?$", "practice.admin"),
    _rule("POST,PATCH", r"^/api/field-(?:groups|definitions)(?:/[^/]+)?$", "field_schema.admin"),
    _rule("POST", r"^/api/derived-fact-rules$", "derived_rule.admin"),
    _rule("POST", r"^/api/workflows/[^/]+/publish$", "workflow.publish"),
    _rule("POST", r"^/api/workflows/[^/]+/sessions$", "workflow.run"),
    _rule("POST,PATCH", r"^/api/workflows(?:/[^/]+)?$", "workflow.admin"),
    _rule("POST", r"^/api/templates/[^/]+/automation/publish$", "template.publish"),
    _rule("POST,PUT,PATCH,DELETE", r"^/api/templates(?:/.*)?$", "template.write"),
    _rule("PUT", r"^/api/variables/[^/]+$", "template.write"),
    _rule("POST,PATCH,DELETE", r"^/api/document-sets(?:/.*)?$", "document_set.admin"),
    _rule("POST,PATCH", r"^/api/generation-runs(?:/[^/]+)?$", "generation.execute"),
    _rule("POST", r"^/api/generation/headless$", "generation.execute"),
    _rule("POST", r"^/api/workflow-sessions/[^/]+/(?:approve-for-generation|apply-to-matter)$", "generation.execute"),
    _rule("POST,PATCH", r"^/api/workflow-sessions(?:/.*)?$", "workflow.run"),
    _rule("POST", r"^/api/questionnaires(?:/.*)?$", "intake.manage"),
    _rule("POST", r"^/api/intake/(?:generate|share|[^/]+/revoke)$", "intake.manage"),
    _rule("POST", r"^/api/matters/[^/]+/authorities/[^/]+/verification$", "authority.verify"),
    _rule("POST,PUT,PATCH,DELETE", r"^/api/matters(?:/.*)?$", "matter.write"),
    _rule("POST,PUT,PATCH,DELETE", r"^/api/contacts(?:/.*)?$", "contact.write"),
    _rule("POST,DELETE", r"^/api/organization/boilerplate(?:/.*)?$", "organization.admin"),
    _rule("PUT", r"^/api/organization/ai-policy$", "organization.admin"),
    _rule("POST,DELETE", r"^/api/ocr(?:/.*)?$", "document.process"),
    _rule("POST,DELETE", r"^/api/documents(?:/.*)?$", "document.process"),
    _rule("POST", r"^/api/drafting/chat$", "document.process"),
)


def permission_for_request(method: str, path: str) -> str:
    method = method.upper()
    for rule in PERMISSION_RULES:
        if method in rule.methods and rule.pattern.match(path):
            return rule.permission
    return "api.mutate"


def require_permission(ctx: SecurityContext, permission: str) -> None:
    min_role = PERMISSION_MIN_ROLE.get(permission)
    if min_role is None:
        raise RuntimeError(f"Unknown AutoDraft permission: {permission}")
    if ROLE_ORDER.get(ctx.role, -1) < ROLE_ORDER[min_role]:
        raise HTTPException(status_code=403, detail=f"Permission required: {permission}")
