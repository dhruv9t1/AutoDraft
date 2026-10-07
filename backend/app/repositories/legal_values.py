from __future__ import annotations

import uuid
from typing import Any

from ..domain.canonical_fields import display_value, storage_columns, validate_field_value


class CanonicalLegalValueRepository:
    """Single authoritative write path for matter legal values.

    ``matter_field_values`` is the source of truth. ``matter_facts`` is retained
    as a compatibility/history/conflict ledger; canonical rows in that table are
    transactionally projected from the typed canonical value and are never the
    authoritative write target.
    """

    @staticmethod
    async def ensure_matter_definition(
        conn,
        *,
        matter_id: uuid.UUID,
        semantic_key: str,
        display_label: str,
        value_type: str = "text",
        aliases: list[str] | None = None,
    ):
        definition = await conn.fetchrow(
            """SELECT fd.* FROM field_definitions fd
               JOIN matters m ON m.organization_id=fd.organization_id
               WHERE m.id=$1 AND fd.semantic_key=$2""",
            matter_id,
            semantic_key,
        )
        if definition:
            return definition
        return await conn.fetchrow(
            """INSERT INTO field_definitions(
                   organization_id,semantic_key,display_label,entity_scope,value_type,aliases
               )
               SELECT organization_id,$2,$3,'matter',$4,$5::jsonb
               FROM matters WHERE id=$1
               RETURNING *""",
            matter_id,
            semantic_key,
            display_label,
            value_type,
            aliases or [display_label],
        )

    @staticmethod
    async def canonical_value(conn, matter_id: uuid.UUID, field_definition_id: uuid.UUID):
        return await conn.fetchrow(
            """SELECT * FROM matter_field_values
               WHERE matter_id=$1 AND field_definition_id=$2
               FOR UPDATE""",
            matter_id,
            field_definition_id,
        )

    @staticmethod
    async def _project_legacy_fact(conn, *, matter_id: uuid.UUID, definition, value_row, provenance: dict):
        # raw_text is the stable textual compatibility representation generated
        # by the typed canonical storage layer. JSON values may have no raw_text;
        # display_value provides a deterministic fallback for those cases.
        rendered = value_row.get("raw_text")
        if rendered is None:
            displayed = display_value(dict(value_row), definition["value_type"])
            rendered = "" if displayed is None else str(displayed)

        derived_from = provenance.get("derivedFrom") or provenance.get("derived_from") or []
        status = value_row["status"]
        source = value_row["source"]

        # Canonical writes to legacy matter_facts are guarded at the database
        # layer. Open the projection gate only around this exact write.
        await conn.execute("SELECT set_config('autodraft.legacy_projection_write','on',true)")
        try:
            current = await conn.fetchrow(
                """SELECT id FROM matter_facts
                   WHERE matter_id=$1 AND field_definition_id=$2 AND is_canonical=TRUE
                   ORDER BY COALESCE(updated_at,created_at) DESC LIMIT 1 FOR UPDATE""",
                matter_id,
                definition["id"],
            )
            if current:
                return await conn.fetchrow(
                    """UPDATE matter_facts
                       SET field=$1,label=$1,fact=$2,source=$3,status=$4,fact_key=$5,
                           value_type=$6,value_json=$7::jsonb,is_canonical=TRUE,
                           derived_from=$8::jsonb,confirmed_at=$9,field_definition_id=$10,
                           updated_at=NOW()
                       WHERE id=$11
                       RETURNING id,organization_id,matter_id,field,fact,source,status,
                                 fact_key,label,value_type,value_json,is_canonical,derived_from,
                                 confirmed_at,field_definition_id,created_at,updated_at""",
                    definition["display_label"],
                    rendered,
                    source,
                    status,
                    definition["semantic_key"],
                    definition["value_type"],
                    value_row.get("value_json"),
                    derived_from,
                    value_row.get("confirmed_at"),
                    definition["id"],
                    current["id"],
                )
            return await conn.fetchrow(
                """INSERT INTO matter_facts(
                       organization_id,matter_id,field,fact,source,status,fact_key,label,
                       value_type,value_json,is_canonical,derived_from,confirmed_at,field_definition_id
                   ) VALUES(
                       autodraft_current_organization_id(),$1,$2,$3,$4,$5,$6,$2,
                       $7,$8::jsonb,TRUE,$9::jsonb,$10,$11
                   )
                   RETURNING id,organization_id,matter_id,field,fact,source,status,
                             fact_key,label,value_type,value_json,is_canonical,derived_from,
                             confirmed_at,field_definition_id,created_at,updated_at""",
                matter_id,
                definition["display_label"],
                rendered,
                source,
                status,
                definition["semantic_key"],
                definition["value_type"],
                value_row.get("value_json"),
                derived_from,
                value_row.get("confirmed_at"),
                definition["id"],
            )
        finally:
            await conn.execute("SELECT set_config('autodraft.legacy_projection_write','off',true)")


    @staticmethod
    def _matches_existing(definition, current, value: Any) -> bool:
        """Compare an incoming legal value using the canonical typed representation."""
        validate_field_value(definition, value)
        incoming = storage_columns(definition["value_type"], value)
        for key in ("value_text", "value_number", "value_boolean", "value_date", "value_datetime", "value_json", "value_contact_id", "value_matter_id", "value_document_id"):
            if incoming.get(key) != current.get(key):
                return False
        return True

    async def propose_matter_value(
        self,
        conn,
        *,
        matter_id: uuid.UUID,
        definition,
        value: Any,
        source: str,
        provenance: dict,
        desired_status: str = "confirmed",
    ) -> dict[str, Any]:
        """Apply a proposed legal value or open a lawyer-review conflict.

        Confirmed/accepted/derived canonical values are fail-closed: a different
        proposed value is retained only as a non-canonical candidate in
        ``matter_facts`` and an open ``fact_conflicts`` row is created/extended.
        Every ingestion source can call this method, so workflow promotion cannot
        bypass the same conflict semantics used by manual/imported facts.
        """
        if definition["entity_scope"] != "matter":
            raise ValueError(f"Field belongs to {definition['entity_scope']}, not matter")
        validate_field_value(definition, value)
        current = await self.canonical_value(conn, matter_id, definition["id"])
        protected = bool(current and current.get("status") in {"confirmed", "accepted", "derived"})
        if not current or self._matches_existing(definition, current, value) or not protected:
            row, legacy = await self.upsert_matter_value(
                conn, matter_id=matter_id, definition=definition, value=value, source=source,
                status=desired_status, provenance=provenance,
            )
            return {"status": "applied", "value_row": row, "legacy": legacy, "conflict_id": None}

        cols = storage_columns(definition["value_type"], value)
        rendered = cols.get("raw_text")
        if rendered is None:
            rendered = "" if value is None else str(value)

        projection = await conn.fetchrow(
            """SELECT id FROM matter_facts
               WHERE matter_id=$1 AND field_definition_id=$2 AND is_canonical=TRUE
               ORDER BY COALESCE(updated_at,created_at) DESC LIMIT 1 FOR UPDATE""",
            matter_id, definition["id"],
        )
        if not projection:
            projection = await self._project_legacy_fact(
                conn, matter_id=matter_id, definition=definition, value_row=current,
                provenance=dict(current.get("provenance") or {}),
            )

        candidate = await conn.fetchrow(
            """INSERT INTO matter_facts(
                   organization_id,matter_id,field,fact,source,status,fact_key,label,
                   value_type,value_json,is_canonical,field_definition_id
               ) VALUES(
                   autodraft_current_organization_id(),$1,$2,$3,$4,'conflicted',$5,$2,
                   $6,$7::jsonb,FALSE,$8
               )
               RETURNING id,organization_id,matter_id,field,fact,source,status,fact_key,label,
                         value_type,value_json,is_canonical,derived_from,confirmed_at,
                         field_definition_id,created_at,updated_at""",
            matter_id, definition["display_label"], rendered, source, definition["semantic_key"],
            definition["value_type"], cols.get("value_json"), definition["id"],
        )
        ids = [str(projection["id"]), str(candidate["id"])]
        open_conflict = await conn.fetchrow(
            """SELECT id,candidate_fact_ids FROM fact_conflicts
               WHERE matter_id=$1 AND fact_key=$2 AND status='open'
               ORDER BY created_at DESC LIMIT 1 FOR UPDATE""",
            matter_id, definition["semantic_key"],
        )
        if open_conflict:
            existing = [str(x) for x in (open_conflict["candidate_fact_ids"] or [])]
            merged = list(dict.fromkeys([*existing, *ids]))
            await conn.execute(
                "UPDATE fact_conflicts SET candidate_fact_ids=$1::jsonb WHERE id=$2",
                merged, open_conflict["id"],
            )
            conflict_id = open_conflict["id"]
        else:
            conflict_id = await conn.fetchval(
                """INSERT INTO fact_conflicts(organization_id,matter_id,fact_key,candidate_fact_ids)
                   VALUES(autodraft_current_organization_id(),$1,$2,$3::jsonb) RETURNING id""",
                matter_id, definition["semantic_key"], ids,
            )
        return {"status": "conflict", "value_row": current, "legacy": candidate, "conflict_id": conflict_id}

    async def upsert_matter_value(
        self,
        conn,
        *,
        matter_id: uuid.UUID,
        definition,
        value: Any,
        source: str,
        status: str,
        provenance: dict,
    ):
        if definition["entity_scope"] != "matter":
            raise ValueError(f"Field belongs to {definition['entity_scope']}, not matter")
        validate_field_value(definition, value)
        cols = storage_columns(definition["value_type"], value)
        row = await conn.fetchrow(
            """INSERT INTO matter_field_values(
                   organization_id,matter_id,field_definition_id,raw_text,value_text,
                   value_number,value_boolean,value_date,value_datetime,value_json,
                   value_contact_id,value_matter_id,value_document_id,source,status,provenance,confirmed_at
               ) VALUES(
                   autodraft_current_organization_id(),$1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,
                   $10,$11,$12,$13,$14,$15::jsonb,CASE WHEN $14 IN ('confirmed','accepted','derived') THEN NOW() ELSE NULL END
               )
               ON CONFLICT(matter_id,field_definition_id) DO UPDATE SET
                   raw_text=EXCLUDED.raw_text,value_text=EXCLUDED.value_text,
                   value_number=EXCLUDED.value_number,value_boolean=EXCLUDED.value_boolean,
                   value_date=EXCLUDED.value_date,value_datetime=EXCLUDED.value_datetime,
                   value_json=EXCLUDED.value_json,value_contact_id=EXCLUDED.value_contact_id,
                   value_matter_id=EXCLUDED.value_matter_id,value_document_id=EXCLUDED.value_document_id,
                   source=EXCLUDED.source,status=EXCLUDED.status,provenance=EXCLUDED.provenance,
                   confirmed_at=EXCLUDED.confirmed_at,updated_at=NOW()
               RETURNING *""",
            matter_id,
            definition["id"],
            cols["raw_text"],
            cols["value_text"],
            cols["value_number"],
            cols["value_boolean"],
            cols["value_date"],
            cols["value_datetime"],
            cols["value_json"],
            cols["value_contact_id"],
            cols["value_matter_id"],
            cols["value_document_id"],
            source,
            status,
            provenance,
        )
        legacy = await self._project_legacy_fact(
            conn,
            matter_id=matter_id,
            definition=definition,
            value_row=row,
            provenance=provenance,
        )
        return row, legacy
