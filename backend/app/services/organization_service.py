from __future__ import annotations

from ..db import Database
from ..extraction.unicode_view import candidate_key
from ..repositories.organization import deactivate_boilerplate, list_boilerplate, upsert_boilerplate


async def get_boilerplate_entries(db: Database, *, active_only: bool = True):
    return await list_boilerplate(db, active_only=active_only)


async def get_boilerplate_values(db: Database) -> set[str]:
    return {str(row["value"]) for row in await list_boilerplate(db, active_only=True) if str(row.get("value") or "").strip()}


async def save_boilerplate_entry(db: Database, *, value: str, label: str = "", kind: str = "firm_value"):
    value = value.strip()
    if not value:
        raise ValueError("Boilerplate value cannot be empty")
    return await upsert_boilerplate(
        db,
        value=value,
        normalized_key=candidate_key(value),
        label=label.strip(),
        kind=(kind.strip() or "firm_value")[:60],
    )


async def remove_boilerplate_entry(db: Database, entry_id: str) -> bool:
    return await deactivate_boilerplate(db, entry_id)
