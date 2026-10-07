from __future__ import annotations

from ..db import Database


class DerivedFactRuleRepository:
    """Tenant-safe access to organization-owned derived-fact rules."""

    def __init__(self, db: Database):
        self.db = db

    async def upsert(self, *, fact_key: str, label: str, value_type: str, expression, enabled: bool):
        return await self.db.p().fetchrow(
            """INSERT INTO derived_fact_rules(
                   organization_id,fact_key,label,value_type,expression,enabled
               )
               VALUES(autodraft_current_organization_id(),$1,$2,$3,$4::jsonb,$5)
               ON CONFLICT(organization_id,fact_key) DO UPDATE
               SET label=EXCLUDED.label,
                   value_type=EXCLUDED.value_type,
                   expression=EXCLUDED.expression,
                   enabled=EXCLUDED.enabled,
                   updated_at=NOW()
               WHERE derived_fact_rules.organization_id=autodraft_current_organization_id()
               RETURNING id,fact_key,label,value_type,expression,enabled,created_at,updated_at""",
            fact_key, label, value_type, expression, enabled,
        )

    async def list(self):
        return await self.db.p().fetch(
            """SELECT id,fact_key,label,value_type,expression,enabled,created_at,updated_at
               FROM derived_fact_rules
               WHERE organization_id=autodraft_current_organization_id()
               ORDER BY label"""
        )

    async def enabled(self):
        return await self.db.p().fetch(
            """SELECT fact_key,label,value_type,expression
               FROM derived_fact_rules
               WHERE organization_id=autodraft_current_organization_id()
                 AND enabled=TRUE
               ORDER BY created_at"""
        )
