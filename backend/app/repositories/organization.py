from __future__ import annotations

from typing import Any

from ..db import Database


async def list_boilerplate(db: Database, *, active_only: bool = True) -> list[dict[str, Any]]:
    where = "WHERE active=TRUE" if active_only else ""
    rows = await db.p().fetch(
        f"SELECT id::text,value,normalized_key,label,kind,active,created_at,updated_at FROM organization_boilerplate {where} ORDER BY updated_at DESC"
    )
    return [dict(row) for row in rows]


async def upsert_boilerplate(
    db: Database, *, value: str, normalized_key: str, label: str, kind: str
) -> dict[str, Any]:
    row = await db.p().fetchrow(
        """
        INSERT INTO organization_boilerplate(organization_id,value,normalized_key,label,kind,active)
        VALUES(current_setting('autodraft.organization_id')::uuid,$1,$2,$3,$4,TRUE)
        ON CONFLICT(organization_id, normalized_key) DO UPDATE
        SET value=EXCLUDED.value,label=EXCLUDED.label,kind=EXCLUDED.kind,active=TRUE,updated_at=NOW()
        RETURNING id::text,value,label,kind,active
        """,
        value, normalized_key, label, kind,
    )
    return dict(row)


async def deactivate_boilerplate(db: Database, entry_id: str) -> bool:
    result = await db.p().execute(
        "UPDATE organization_boilerplate SET active=FALSE,updated_at=NOW() WHERE id=$1::uuid",
        entry_id,
    )
    return result.endswith("1")
