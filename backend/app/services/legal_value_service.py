from __future__ import annotations

import json
import uuid
from typing import Any

from ..domain.canonical_fields import REFERENCE_TYPES, display_value, storage_columns, validate_field_value
from ..repositories.legal_values import CanonicalLegalValueRepository


class LegalValueWriteService:
    """Universal canonical legal-value write boundary.

    Manual field edits, matter facts, intake/workflow promotion, extraction/AI
    promotion, derived rules and contact-field writes should enter here. The
    service owns type validation, reference integrity, repeatable-instance
    identity/order, conflict behavior for matter values and legacy projection.
    """

    def __init__(self):
        self.canonical = CanonicalLegalValueRepository()

    async def ensure_matter_definition(self, conn, **kwargs):
        return await self.canonical.ensure_matter_definition(conn, **kwargs)

    async def _validate_reference(self, conn, definition, value: Any) -> None:
        value_type = definition["value_type"]
        if value is None or value == "" or value_type not in REFERENCE_TYPES:
            return
        ref = uuid.UUID(str(value))
        table = {
            "contact_reference": "contacts",
            "matter_reference": "matters",
            "document_reference": "matter_documents",
        }[value_type]
        if not await conn.fetchval(f"SELECT 1 FROM {table} WHERE id=$1", ref):
            raise ValueError(f"Referenced {value_type.removesuffix('_reference')} does not exist in this organization")

    @staticmethod
    def _parse_repeatable(value: Any) -> list[dict[str, Any]]:
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError as exc:
                raise ValueError("A repeatable field value must be an array") from exc
        if not isinstance(value, list):
            raise ValueError("A repeatable field value must be an array")
        result: list[dict[str, Any]] = []
        seen: set[uuid.UUID] = set()
        for position, entry in enumerate(value):
            if isinstance(entry, dict) and "value" in entry and ("id" in entry or "provenance" in entry):
                item_value = entry.get("value")
                raw_id = entry.get("id")
                item_id = uuid.UUID(str(raw_id)) if raw_id else None
                item_provenance = dict(entry.get("provenance") or {})
            else:
                item_value = entry
                item_id = None
                item_provenance = {}
            if item_id:
                if item_id in seen:
                    raise ValueError("A repeatable item id may appear only once")
                seen.add(item_id)
            result.append({"id": item_id, "value": item_value, "position": position, "provenance": item_provenance})
        return result

    async def _replace_repeatable(
        self,
        conn,
        *,
        parent_type: str,
        parent_id: uuid.UUID,
        definition,
        value: Any,
        source: str,
        status: str,
        provenance: dict,
    ) -> list[Any]:
        if not definition.get("repeatable"):
            raise ValueError("Field is not repeatable")
        items = self._parse_repeatable(value)
        table = "matter_field_value_items" if parent_type == "matter" else "contact_field_value_items"
        parent_col = "matter_id" if parent_type == "matter" else "contact_id"
        current = await conn.fetch(
            f"SELECT id,position FROM {table} WHERE {parent_col}=$1 AND field_definition_id=$2 ORDER BY position,id FOR UPDATE",
            parent_id, definition["id"],
        )
        existing = {row["id"] for row in current}
        by_position = {row["position"]: row["id"] for row in current}
        # Backward-compatible clients may still send a plain value array. Reuse
        # the existing item at the same position so collection identities do not
        # churn merely because the client has not learned the item-id envelope.
        explicit_ids = {item["id"] for item in items if item["id"]}
        for item in items:
            if item["id"] is None:
                candidate = by_position.get(item["position"])
                if candidate and candidate not in explicit_ids:
                    item["id"] = candidate
                    explicit_ids.add(candidate)
        supplied = {item["id"] for item in items if item["id"]}
        unknown = supplied - existing
        if unknown:
            raise ValueError("Repeatable item id does not belong to this field collection")

        written = []
        for item in items:
            validate_field_value(definition, item["value"])
            await self._validate_reference(conn, definition, item["value"])
            cols = storage_columns(definition["value_type"], item["value"])
            item_provenance = {**provenance, **item["provenance"]}
            if item["id"]:
                row = await conn.fetchrow(
                    f"""UPDATE {table} SET position=$1,raw_text=$2,value_text=$3,value_number=$4,value_boolean=$5,
                       value_date=$6,value_datetime=$7,value_json=$8::jsonb,value_contact_id=$9,value_matter_id=$10,value_document_id=$11,
                       source=$12,status=$13,provenance=$14::jsonb,
                       confirmed_at=CASE WHEN $13 IN ('confirmed','accepted','derived') THEN COALESCE(confirmed_at,NOW()) ELSE NULL END,updated_at=NOW()
                       WHERE id=$15 AND {parent_col}=$16 AND field_definition_id=$17 RETURNING *""",
                    item["position"], cols["raw_text"], cols["value_text"], cols["value_number"], cols["value_boolean"],
                    cols["value_date"], cols["value_datetime"], cols["value_json"], cols["value_contact_id"], cols["value_matter_id"],
                    cols["value_document_id"], source, status, item_provenance, item["id"], parent_id, definition["id"],
                )
            else:
                row = await conn.fetchrow(
                    f"""INSERT INTO {table}(organization_id,{parent_col},field_definition_id,position,raw_text,value_text,value_number,value_boolean,
                       value_date,value_datetime,value_json,value_contact_id,value_matter_id,value_document_id,source,status,provenance,confirmed_at)
                       VALUES(autodraft_current_organization_id(),$1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11,$12,$13,$14,$15,$16::jsonb,
                       CASE WHEN $15 IN ('confirmed','accepted','derived') THEN NOW() ELSE NULL END) RETURNING *""",
                    parent_id, definition["id"], item["position"], cols["raw_text"], cols["value_text"], cols["value_number"], cols["value_boolean"],
                    cols["value_date"], cols["value_datetime"], cols["value_json"], cols["value_contact_id"], cols["value_matter_id"], cols["value_document_id"],
                    source, status, item_provenance,
                )
            written.append(row)
        removed = existing - supplied
        if removed:
            await conn.execute(f"DELETE FROM {table} WHERE id=ANY($1::uuid[])", list(removed))
        scalar_table = "matter_field_values" if parent_type == "matter" else "contact_field_values"
        await conn.execute(f"DELETE FROM {scalar_table} WHERE {parent_col}=$1 AND field_definition_id=$2", parent_id, definition["id"])
        return written

    async def _repeatable_values(self, conn, *, matter_id: uuid.UUID, definition) -> list[Any]:
        rows = await conn.fetch(
            """SELECT * FROM matter_field_value_items WHERE matter_id=$1 AND field_definition_id=$2 ORDER BY position,id FOR UPDATE""",
            matter_id, definition["id"],
        )
        return [display_value(dict(row), definition["value_type"]) for row in rows]

    async def _project_repeatable_legacy(self, conn, *, matter_id: uuid.UUID, definition, values: list[Any], source: str, status: str, provenance: dict):
        rendered = json.dumps(values, ensure_ascii=False, default=str)
        await conn.execute("SELECT set_config('autodraft.legacy_projection_write','on',true)")
        try:
            current = await conn.fetchrow(
                """SELECT id FROM matter_facts WHERE matter_id=$1 AND field_definition_id=$2 AND is_canonical=TRUE
                   ORDER BY COALESCE(updated_at,created_at) DESC LIMIT 1 FOR UPDATE""", matter_id, definition["id"],
            )
            if current:
                return await conn.fetchrow(
                    """UPDATE matter_facts SET field=$1,label=$1,fact=$2,source=$3,status=$4,fact_key=$5,value_type='json',value_json=$6::jsonb,
                       is_canonical=TRUE,derived_from=$7::jsonb,confirmed_at=CASE WHEN $4 IN ('confirmed','accepted','derived') THEN COALESCE(confirmed_at,NOW()) ELSE NULL END,
                       updated_at=NOW() WHERE id=$8 RETURNING *""",
                    definition["display_label"], rendered, source, status, definition["semantic_key"], values,
                    provenance.get("derivedFrom") or provenance.get("derived_from") or [], current["id"],
                )
            return await conn.fetchrow(
                """INSERT INTO matter_facts(organization_id,matter_id,field,fact,source,status,fact_key,label,value_type,value_json,is_canonical,field_definition_id,confirmed_at)
                   VALUES(autodraft_current_organization_id(),$1,$2,$3,$4,$5,$6,$2,'json',$7::jsonb,TRUE,$8,
                          CASE WHEN $5 IN ('confirmed','accepted','derived') THEN NOW() ELSE NULL END) RETURNING *""",
                matter_id, definition["display_label"], rendered, source, status, definition["semantic_key"], values, definition["id"],
            )
        finally:
            await conn.execute("SELECT set_config('autodraft.legacy_projection_write','off',true)")

    async def propose_matter_value(self, conn, *, matter_id: uuid.UUID, definition, value: Any, source: str, provenance: dict, desired_status: str = "confirmed"):
        await self._validate_reference(conn, definition, value if not definition.get("repeatable") else None)
        if not definition.get("repeatable"):
            return await self.canonical.propose_matter_value(
                conn, matter_id=matter_id, definition=definition, value=value, source=source, provenance=provenance, desired_status=desired_status,
            )
        requested = self._parse_repeatable(value)
        for item in requested:
            validate_field_value(definition, item["value"])
            await self._validate_reference(conn, definition, item["value"])
        current_rows = await conn.fetch(
            "SELECT * FROM matter_field_value_items WHERE matter_id=$1 AND field_definition_id=$2 ORDER BY position,id FOR UPDATE",
            matter_id, definition["id"],
        )
        current_values = [display_value(dict(row), definition["value_type"]) for row in current_rows]
        requested_values = [display_value(storage_columns(definition["value_type"], item["value"]), definition["value_type"]) for item in requested]
        protected = any(row.get("status") in {"confirmed", "accepted", "derived"} for row in current_rows)
        if current_rows and protected and current_values != requested_values:
            projection = await self._project_repeatable_legacy(
                conn, matter_id=matter_id, definition=definition, values=current_values,
                source=current_rows[0].get("source") or "canonical", status=current_rows[0].get("status") or "confirmed", provenance={},
            )
            candidate = await conn.fetchrow(
                """INSERT INTO matter_facts(organization_id,matter_id,field,fact,source,status,fact_key,label,value_type,value_json,is_canonical,field_definition_id)
                   VALUES(autodraft_current_organization_id(),$1,$2,$3,$4,'conflicted',$5,$2,'json',$6::jsonb,FALSE,$7) RETURNING *""",
                matter_id, definition["display_label"], json.dumps(requested_values, ensure_ascii=False, default=str), source,
                definition["semantic_key"], requested_values, definition["id"],
            )
            ids = [str(projection["id"]), str(candidate["id"])]
            conflict_id = await conn.fetchval(
                """INSERT INTO fact_conflicts(organization_id,matter_id,fact_key,candidate_fact_ids)
                   VALUES(autodraft_current_organization_id(),$1,$2,$3::jsonb) RETURNING id""",
                matter_id, definition["semantic_key"], ids,
            )
            return {"status": "conflict", "value_row": current_rows[0] if current_rows else None, "legacy": candidate, "conflict_id": conflict_id, "items": current_rows}
        rows = await self._replace_repeatable(
            conn, parent_type="matter", parent_id=matter_id, definition=definition, value=value, source=source, status=desired_status, provenance=provenance,
        )
        values = [display_value(dict(row), definition["value_type"]) for row in rows]
        legacy = await self._project_repeatable_legacy(
            conn, matter_id=matter_id, definition=definition, values=values, source=source, status=desired_status, provenance=provenance,
        )
        return {"status": "applied", "value_row": rows[0] if rows else None, "legacy": legacy, "conflict_id": None, "items": rows}

    async def upsert_matter_value(self, conn, *, matter_id: uuid.UUID, definition, value: Any, source: str, status: str, provenance: dict):
        """Privileged accepted write used only after conflict resolution/migration."""
        if definition.get("repeatable"):
            rows = await self._replace_repeatable(
                conn, parent_type="matter", parent_id=matter_id, definition=definition, value=value, source=source, status=status, provenance=provenance,
            )
            values = [display_value(dict(row), definition["value_type"]) for row in rows]
            legacy = await self._project_repeatable_legacy(
                conn, matter_id=matter_id, definition=definition, values=values, source=source, status=status, provenance=provenance,
            )
            return (rows[0] if rows else None), legacy
        await self._validate_reference(conn, definition, value)
        return await self.canonical.upsert_matter_value(
            conn, matter_id=matter_id, definition=definition, value=value, source=source, status=status, provenance=provenance,
        )

    async def upsert_contact_value(self, conn, *, contact_id: uuid.UUID, definition, value: Any, source: str, status: str, provenance: dict):
        if definition.get("repeatable"):
            rows = await self._replace_repeatable(
                conn, parent_type="contact", parent_id=contact_id, definition=definition, value=value, source=source, status=status, provenance=provenance,
            )
            return rows[0] if rows else None, rows
        validate_field_value(definition, value)
        await self._validate_reference(conn, definition, value)
        cols = storage_columns(definition["value_type"], value)
        row = await conn.fetchrow(
            """INSERT INTO contact_field_values(organization_id,contact_id,field_definition_id,raw_text,value_text,value_number,value_boolean,value_date,value_datetime,value_json,
               value_contact_id,value_matter_id,value_document_id,source,status,provenance,confirmed_at)
               VALUES(autodraft_current_organization_id(),$1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10,$11,$12,$13,$14,$15::jsonb,
                      CASE WHEN $14 IN ('confirmed','accepted','derived') THEN NOW() ELSE NULL END)
               ON CONFLICT(contact_id,field_definition_id) DO UPDATE SET raw_text=EXCLUDED.raw_text,value_text=EXCLUDED.value_text,value_number=EXCLUDED.value_number,
                 value_boolean=EXCLUDED.value_boolean,value_date=EXCLUDED.value_date,value_datetime=EXCLUDED.value_datetime,value_json=EXCLUDED.value_json,
                 value_contact_id=EXCLUDED.value_contact_id,value_matter_id=EXCLUDED.value_matter_id,value_document_id=EXCLUDED.value_document_id,
                 source=EXCLUDED.source,status=EXCLUDED.status,provenance=EXCLUDED.provenance,confirmed_at=EXCLUDED.confirmed_at,updated_at=NOW() RETURNING *""",
            contact_id, definition["id"], cols["raw_text"], cols["value_text"], cols["value_number"], cols["value_boolean"], cols["value_date"],
            cols["value_datetime"], cols["value_json"], cols["value_contact_id"], cols["value_matter_id"], cols["value_document_id"], source, status, provenance,
        )
        return row, None
