from __future__ import annotations

import uuid
from typing import Any

from ..db import Database
from ..domain.canonical_fields import display_value, validate_field_value
from ..services.domain_events import emit_domain_event
from ..services.legal_value_service import LegalValueWriteService


class FieldRepository:
    def __init__(self, db: Database):
        self.db = db
        # Kept under the historical attribute name so every existing caller now
        # reaches the universal service without maintaining a second write path.
        self.legal_values = LegalValueWriteService()

    async def groups(self):
        return await self.db.p().fetch(
            "SELECT fg.*,pa.name AS practice_area_name FROM field_groups fg LEFT JOIN practice_areas pa ON pa.id=fg.practice_area_id WHERE fg.active=TRUE ORDER BY fg.position,lower(fg.label)"
        )

    async def create_group(self, data: dict):
        async with self.db.p().transaction() as conn:
            if data.get("practice_area_id") and not await conn.fetchval("SELECT 1 FROM practice_areas WHERE id=$1", data["practice_area_id"]):
                return None
            row = await conn.fetchrow(
                """INSERT INTO field_groups(organization_id,key,label,entity_scope,role_key,practice_area_id,position)
                   VALUES(autodraft_current_organization_id(),$1,$2,$3,$4,$5,$6)
                   ON CONFLICT(organization_id,key) DO UPDATE SET label=EXCLUDED.label,entity_scope=EXCLUDED.entity_scope,role_key=EXCLUDED.role_key,
                     practice_area_id=EXCLUDED.practice_area_id,position=EXCLUDED.position,active=TRUE,updated_at=NOW() RETURNING *""",
                data["key"], data["label"], data["entity_scope"], data.get("role_key"), data.get("practice_area_id"), data["position"],
            )
            await emit_domain_event(conn, aggregate_type="field_group", aggregate_id=row["id"], event_type="FieldGroupUpserted", payload={"key": row["key"], "label": row["label"]})
            return row

    async def definitions(self, *, scope: str | None = None, practice_area_id: uuid.UUID | None = None, matter_type: str | None = None, include_inactive: bool = False):
        clauses = []
        args = []
        if not include_inactive:
            clauses.append("fd.active=TRUE")
        if scope:
            args.append(scope)
            clauses.append(f"fd.entity_scope=${len(args)}")
        if practice_area_id:
            args.append(practice_area_id)
            clauses.append(f"(fd.practice_area_id IS NULL OR fd.practice_area_id=${len(args)})")
        if matter_type:
            args.append(matter_type)
            clauses.append(f"(fd.matter_type='' OR fd.matter_type=${len(args)})")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        return await self.db.p().fetch(
            f"""SELECT fd.*,fg.key AS group_key,fg.label AS group_label,fg.role_key AS group_role_key,pa.name AS practice_area_name
                FROM field_definitions fd LEFT JOIN field_groups fg ON fg.id=fd.group_id LEFT JOIN practice_areas pa ON pa.id=fd.practice_area_id
                {where} ORDER BY COALESCE(fg.position,999999),fd.position,lower(fd.display_label)""",
            *args,
        )

    async def get_definition(self, field_id: uuid.UUID):
        return await self.db.p().fetchrow("SELECT * FROM field_definitions WHERE id=$1", field_id)

    async def migration_errors(self, *, limit: int = 200):
        return await self.db.p().fetch(
            """SELECT e.*,fd.semantic_key,fd.display_label FROM field_value_migration_errors e
               LEFT JOIN field_definitions fd ON fd.id=e.field_definition_id
               ORDER BY e.created_at DESC LIMIT $1""", min(max(limit,1),1000),
        )

    @staticmethod
    async def _definition_value_rows(conn, field_id: uuid.UUID, *, repeatable: bool):
        if repeatable:
            return [
                *(await conn.fetch("SELECT i.*, 'matter' AS parent_type FROM matter_field_value_items i WHERE field_definition_id=$1", field_id)),
                *(await conn.fetch("SELECT i.*, 'contact' AS parent_type FROM contact_field_value_items i WHERE field_definition_id=$1", field_id)),
            ]
        return [
            *(await conn.fetch("SELECT v.*, 'matter' AS parent_type FROM matter_field_values v WHERE field_definition_id=$1", field_id)),
            *(await conn.fetch("SELECT v.*, 'contact' AS parent_type FROM contact_field_values v WHERE field_definition_id=$1", field_id)),
        ]

    async def _assert_definition_compatible(self, conn, current, proposed: dict) -> None:
        rows = await self._definition_value_rows(conn, current["id"], repeatable=bool(current["repeatable"]))
        if rows and proposed["value_type"] != current["value_type"]:
            raise ValueError("Cannot change valueType while persisted values exist; migrate/delete the values explicitly first")
        if rows and bool(proposed["repeatable"]) != bool(current["repeatable"]):
            raise ValueError("Cannot change repeatable while persisted values exist; migrate/delete the values explicitly first")

        # Options/validation/required changes are permitted only when every
        # existing persisted value still validates under the proposed schema.
        proposed_definition = dict(current)
        proposed_definition.update(proposed)
        for row in rows:
            value = display_value(dict(row), current["value_type"])
            try:
                validate_field_value(proposed_definition, value)
            except ValueError as exc:
                raise ValueError(f"Field schema change would invalidate existing value {row['id']}: {exc}") from exc

    async def _validate_group_and_practice(self, conn, *, entity_scope: str, group_id, practice_area_id):
        if practice_area_id and not await conn.fetchval("SELECT 1 FROM practice_areas WHERE id=$1", practice_area_id):
            return False
        if group_id:
            group = await conn.fetchrow("SELECT entity_scope,practice_area_id FROM field_groups WHERE id=$1 AND active=TRUE", group_id)
            if not group:
                return False
            if group["entity_scope"] != entity_scope:
                raise ValueError("Field group and field definition must use the same entity scope")
            if group["practice_area_id"] and practice_area_id and group["practice_area_id"] != practice_area_id:
                raise ValueError("Field group and field definition belong to different practice areas")
        return True

    async def create_definition(self, data: dict):
        async with self.db.p().transaction() as conn:
            if not await self._validate_group_and_practice(
                conn, entity_scope=data["entity_scope"], group_id=data.get("group_id"), practice_area_id=data.get("practice_area_id")
            ):
                return None
            current = await conn.fetchrow(
                "SELECT * FROM field_definitions WHERE organization_id=autodraft_current_organization_id() AND semantic_key=$1 FOR UPDATE",
                data["semantic_key"],
            )
            if current:
                if current["entity_scope"] != data["entity_scope"]:
                    raise ValueError("Cannot change entityScope for an existing canonical field definition")
                await self._assert_definition_compatible(conn, current, data)
                row = await conn.fetchrow(
                    """UPDATE field_definitions SET display_label=$1,description=$2,value_type=$3,repeatable=$4,required=$5,validation=$6::jsonb,
                       formatting=$7::jsonb,options=$8::jsonb,aliases=$9::jsonb,group_id=$10,practice_area_id=$11,matter_type=$12,position=$13,active=$14,updated_at=NOW()
                       WHERE id=$15 RETURNING *""",
                    data["display_label"], data["description"], data["value_type"], data["repeatable"], data["required"], data["validation"], data["formatting"],
                    data["options"], data["aliases"], data.get("group_id"), data.get("practice_area_id"), data["matter_type"], data["position"], data["active"], current["id"],
                )
            else:
                row = await conn.fetchrow(
                    """INSERT INTO field_definitions(organization_id,semantic_key,display_label,description,entity_scope,value_type,repeatable,required,validation,formatting,options,aliases,group_id,practice_area_id,matter_type,position,active)
                       VALUES(autodraft_current_organization_id(),$1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9::jsonb,$10::jsonb,$11::jsonb,$12,$13,$14,$15,$16) RETURNING *""",
                    data["semantic_key"], data["display_label"], data["description"], data["entity_scope"], data["value_type"], data["repeatable"], data["required"], data["validation"],
                    data["formatting"], data["options"], data["aliases"], data.get("group_id"), data.get("practice_area_id"), data["matter_type"], data["position"], data["active"],
                )
            await emit_domain_event(conn, aggregate_type="field_definition", aggregate_id=row["id"], event_type="FieldDefinitionUpserted", payload={"semanticKey": row["semantic_key"], "scope": row["entity_scope"], "valueType": row["value_type"]})
            return row

    async def update_definition(self, field_id: uuid.UUID, data: dict):
        async with self.db.p().transaction() as conn:
            cur = await conn.fetchrow("SELECT * FROM field_definitions WHERE id=$1 FOR UPDATE", field_id)
            if not cur:
                return None
            vals = {k: (data[k] if k in data else cur[k]) for k in ("display_label", "description", "value_type", "repeatable", "required", "validation", "formatting", "options", "aliases", "group_id", "practice_area_id", "matter_type", "position", "active")}
            if not await self._validate_group_and_practice(conn, entity_scope=cur["entity_scope"], group_id=vals["group_id"], practice_area_id=vals["practice_area_id"]):
                return None
            await self._assert_definition_compatible(conn, cur, vals)
            row = await conn.fetchrow(
                """UPDATE field_definitions SET display_label=$1,description=$2,value_type=$3,repeatable=$4,required=$5,validation=$6::jsonb,formatting=$7::jsonb,
                   options=$8::jsonb,aliases=$9::jsonb,group_id=$10,practice_area_id=$11,matter_type=$12,position=$13,active=$14,updated_at=NOW() WHERE id=$15 RETURNING *""",
                vals["display_label"], vals["description"], vals["value_type"], vals["repeatable"], vals["required"], vals["validation"], vals["formatting"], vals["options"],
                vals["aliases"], vals["group_id"], vals["practice_area_id"], vals["matter_type"], vals["position"], vals["active"], field_id,
            )
            await emit_domain_event(conn, aggregate_type="field_definition", aggregate_id=field_id, event_type="FieldDefinitionUpdated", payload={"semanticKey": row["semantic_key"], "active": row["active"]})
            return row

    async def _upsert_value(self, *, parent_type: str, parent_id: uuid.UUID, field_id: uuid.UUID, value: Any, source: str, status: str, provenance: dict):
        async with self.db.p().transaction() as conn:
            definition = await conn.fetchrow("SELECT * FROM field_definitions WHERE id=$1 AND active=TRUE", field_id)
            if not definition:
                return None
            if definition["entity_scope"] != parent_type:
                raise ValueError(f"Field belongs to {definition['entity_scope']}, not {parent_type}")
            parent_table = "matters" if parent_type == "matter" else "contacts"
            if not await conn.fetchval(f"SELECT 1 FROM {parent_table} WHERE id=$1", parent_id):
                return None

            if parent_type == "matter":
                outcome = await self.legal_values.propose_matter_value(
                    conn, matter_id=parent_id, definition=definition, value=value, source=source, provenance=provenance, desired_status=status,
                )
                row = {"id": definition["id"]} if definition.get("repeatable") else (outcome.get("value_row") or {"id": definition["id"]})
                if outcome["status"] == "conflict":
                    await emit_domain_event(conn, aggregate_type="fact_conflict", aggregate_id=outcome["conflict_id"], matter_id=parent_id, event_type="MatterFactConflictOpened", payload={"fieldDefinitionId": str(field_id), "semanticKey": definition["semantic_key"], "source": source})
                else:
                    await emit_domain_event(conn, aggregate_type="matter_field_value", aggregate_id=row["id"] if row else definition["id"], matter_id=parent_id, event_type="MatterFieldValueUpserted", payload={"fieldDefinitionId": str(field_id), "semanticKey": definition["semantic_key"], "status": status})
                return row, definition

            row, items = await self.legal_values.upsert_contact_value(
                conn, contact_id=parent_id, definition=definition, value=value, source=source, status=status, provenance=provenance,
            )
            if definition.get("repeatable"):
                row = {"id": definition["id"]}
            aggregate_id = row["id"] if row else definition["id"]
            await emit_domain_event(conn, aggregate_type="contact_field_value", aggregate_id=aggregate_id, event_type="ContactFieldValueUpserted", payload={"fieldDefinitionId": str(field_id), "semanticKey": definition["semantic_key"], "status": status})
            return (row or {"id": definition["id"]}), definition

    async def upsert_matter_value(self, matter_id, field_id, **kwargs):
        return await self._upsert_value(parent_type="matter", parent_id=matter_id, field_id=field_id, **kwargs)

    async def upsert_contact_value(self, contact_id, field_id, **kwargs):
        return await self._upsert_value(parent_type="contact", parent_id=contact_id, field_id=field_id, **kwargs)

    async def upsert_matter_value_by_key(self, matter_id: uuid.UUID, semantic_key: str, *, label: str, value: Any, value_type: str = "text", source: str = "user", status: str = "confirmed", provenance: dict | None = None):
        async with self.db.p().transaction() as conn:
            if not await conn.fetchval("SELECT 1 FROM matters WHERE id=$1", matter_id):
                return None
            definition = await self.legal_values.ensure_matter_definition(conn, matter_id=matter_id, semantic_key=semantic_key, display_label=label, value_type=value_type, aliases=[label])
            outcome = await self.legal_values.propose_matter_value(
                conn, matter_id=matter_id, definition=definition, value=value, source=source, provenance=provenance or {}, desired_status=status,
            )
            if outcome["status"] == "conflict":
                await emit_domain_event(conn, aggregate_type="fact_conflict", aggregate_id=outcome["conflict_id"], matter_id=matter_id, event_type="MatterFactConflictOpened", payload={"factKey": semantic_key, "source": source})
            else:
                row = outcome["value_row"]
                await emit_domain_event(conn, aggregate_type="matter_field_value", aggregate_id=row["id"] if row else definition["id"], matter_id=matter_id, event_type="MatterFieldValueUpserted", payload={"fieldDefinitionId": str(definition["id"]), "semanticKey": definition["semantic_key"], "status": status})
            return outcome, definition, outcome["legacy"]

    async def propose_matter_value(self, matter_id: uuid.UUID, field_definition_id: uuid.UUID, *, value: Any, source: str, status: str = "confirmed", provenance: dict):
        async with self.db.p().transaction() as conn:
            definition = await conn.fetchrow("SELECT * FROM field_definitions WHERE id=$1 AND entity_scope='matter' AND active=TRUE", field_definition_id)
            if not definition:
                return None
            if not await conn.fetchval("SELECT 1 FROM matters WHERE id=$1", matter_id):
                return None
            outcome = await self.legal_values.propose_matter_value(conn, matter_id=matter_id, definition=definition, value=value, source=source, provenance=provenance, desired_status=status)
            if outcome["status"] == "conflict":
                await emit_domain_event(conn, aggregate_type="fact_conflict", aggregate_id=outcome["conflict_id"], matter_id=matter_id, event_type="MatterFactConflictOpened", payload={"factKey": definition["semantic_key"], "source": source, "candidateFactId": str(outcome["legacy"]["id"])})
            else:
                row = outcome["value_row"]
                await emit_domain_event(conn, aggregate_type="matter_field_value", aggregate_id=row["id"] if row else definition["id"], matter_id=matter_id, event_type="MatterFieldValueUpserted", payload={"fieldDefinitionId": str(definition["id"]), "semanticKey": definition["semantic_key"], "status": status, "source": source})
            return outcome

    async def values(self, parent_type: str, parent_id: uuid.UUID):
        scalar_table = "matter_field_values" if parent_type == "matter" else "contact_field_values"
        item_table = "matter_field_value_items" if parent_type == "matter" else "contact_field_value_items"
        col = "matter_id" if parent_type == "matter" else "contact_id"
        rows = await self.db.p().fetch(
            f"""SELECT fv.*,fd.semantic_key,fd.display_label,fd.value_type,fd.entity_scope,fd.repeatable,fg.key AS group_key,fg.label AS group_label,fg.role_key AS group_role_key
                FROM {scalar_table} fv JOIN field_definitions fd ON fd.id=fv.field_definition_id LEFT JOIN field_groups fg ON fg.id=fd.group_id
                WHERE fv.{col}=$1 AND fd.repeatable=FALSE ORDER BY COALESCE(fg.position,999999),fd.position,lower(fd.display_label)""",
            parent_id,
        )
        result = []
        for r in rows:
            d = dict(r)
            d["value"] = display_value(d, d["value_type"])
            result.append(d)

        definitions = await self.db.p().fetch(
            """SELECT fd.*,fg.key AS group_key,fg.label AS group_label,fg.role_key AS group_role_key
               FROM field_definitions fd LEFT JOIN field_groups fg ON fg.id=fd.group_id
               WHERE fd.entity_scope=$1 AND fd.repeatable=TRUE AND fd.active=TRUE
               ORDER BY COALESCE(fg.position,999999),fd.position,lower(fd.display_label)""",
            parent_type,
        )
        for fdrow in definitions:
            fd = dict(fdrow)
            items = await self.db.p().fetch(
                f"SELECT * FROM {item_table} WHERE {col}=$1 AND field_definition_id=$2 ORDER BY position,id",
                parent_id, fd["id"],
            )
            item_payload = []
            for item in items:
                item_d = dict(item)
                item_payload.append({"id": str(item_d["id"]), "position": item_d["position"], "value": display_value(item_d, fd["value_type"]), "source": item_d["source"], "status": item_d["status"], "provenance": item_d.get("provenance") or {}})
            result.append({
                "id": fd["id"], "field_definition_id": fd["id"], "semantic_key": fd["semantic_key"], "display_label": fd["display_label"],
                "value_type": fd["value_type"], "entity_scope": parent_type, "repeatable": True, "value": [x["value"] for x in item_payload],
                "items": item_payload, "raw_text": None, "source": "collection", "status": "confirmed" if item_payload else "empty", "provenance": {},
                "group_key": fd.get("group_key"), "group_label": fd.get("group_label"), "group_role_key": fd.get("group_role_key"),
                "updated_at": max((item["updated_at"] for item in items), default=fd["updated_at"]),
            })
        result.sort(key=lambda d: (d.get("group_key") or "~", d.get("display_label") or ""))
        return result


    async def values_page(self, parent_type: str, parent_id: uuid.UUID, *, limit:int=50, cursor_updated_at=None, cursor_id:uuid.UUID|None=None):
        """Keyset-page canonical values without scanning every value for a large tenant."""
        scalar_table = "matter_field_values" if parent_type == "matter" else "contact_field_values"
        item_table = "matter_field_value_items" if parent_type == "matter" else "contact_field_value_items"
        col = "matter_id" if parent_type == "matter" else "contact_id"
        limit=max(1,min(int(limit),200))
        args=[parent_type,parent_id]
        cursor_clause=""
        if cursor_updated_at is not None:
            args.extend([cursor_updated_at,cursor_id])
            cursor_clause=f" AND (effective_updated_at,field_definition_id)<(${len(args)-1},${len(args)})"
        args.append(limit+1)
        page=await self.db.p().fetch(f"""
            WITH candidates AS (
              SELECT fd.id AS field_definition_id,
                     CASE WHEN fd.repeatable THEN COALESCE(MAX(fi.updated_at),fd.updated_at) ELSE fv.updated_at END AS effective_updated_at
                FROM field_definitions fd
                LEFT JOIN {scalar_table} fv ON fv.field_definition_id=fd.id AND fv.{col}=$2 AND fd.repeatable=FALSE
                LEFT JOIN {item_table} fi ON fi.field_definition_id=fd.id AND fi.{col}=$2 AND fd.repeatable=TRUE
               WHERE fd.entity_scope=$1 AND ((fd.repeatable=FALSE AND fv.id IS NOT NULL) OR (fd.repeatable=TRUE AND fd.active=TRUE))
               GROUP BY fd.id,fd.repeatable,fd.updated_at,fv.updated_at
            ) SELECT * FROM candidates WHERE TRUE {cursor_clause}
              ORDER BY effective_updated_at DESC,field_definition_id DESC LIMIT ${len(args)}
        """,*args)
        selected=list(page[:limit])
        if not selected:return [],page
        ids=[r["field_definition_id"] for r in selected]
        order={str(r["field_definition_id"]):idx for idx,r in enumerate(selected)}
        rows=await self.db.p().fetch(
            f"""SELECT fv.*,fd.semantic_key,fd.display_label,fd.value_type,fd.entity_scope,fd.repeatable,fg.key AS group_key,fg.label AS group_label,fg.role_key AS group_role_key
                FROM {scalar_table} fv JOIN field_definitions fd ON fd.id=fv.field_definition_id LEFT JOIN field_groups fg ON fg.id=fd.group_id
                WHERE fv.{col}=$1 AND fd.repeatable=FALSE AND fd.id=ANY($2::uuid[])""",parent_id,ids)
        result=[]
        for r in rows:
            d=dict(r);d["value"]=display_value(d,d["value_type"]);result.append(d)
        definitions=await self.db.p().fetch(
            """SELECT fd.*,fg.key AS group_key,fg.label AS group_label,fg.role_key AS group_role_key
               FROM field_definitions fd LEFT JOIN field_groups fg ON fg.id=fd.group_id
               WHERE fd.repeatable=TRUE AND fd.id=ANY($1::uuid[])""",ids)
        for fdrow in definitions:
            fd=dict(fdrow);items=await self.db.p().fetch(
                f"SELECT * FROM {item_table} WHERE {col}=$1 AND field_definition_id=$2 ORDER BY position,id",parent_id,fd["id"])
            item_payload=[]
            for item in items:
                item_d=dict(item);item_payload.append({"id":str(item_d["id"]),"position":item_d["position"],"value":display_value(item_d,fd["value_type"]),"source":item_d["source"],"status":item_d["status"],"provenance":item_d.get("provenance") or {}})
            result.append({"id":fd["id"],"field_definition_id":fd["id"],"semantic_key":fd["semantic_key"],"display_label":fd["display_label"],
                "value_type":fd["value_type"],"entity_scope":parent_type,"repeatable":True,"value":[x["value"] for x in item_payload],"items":item_payload,
                "raw_text":None,"source":"collection","status":"confirmed" if item_payload else "empty","provenance":{},"group_key":fd.get("group_key"),
                "group_label":fd.get("group_label"),"group_role_key":fd.get("group_role_key"),"updated_at":max((item["updated_at"] for item in items),default=fd["updated_at"])})
        result.sort(key=lambda d:order.get(str(d["field_definition_id"]),999999))
        return result,page

    async def sync_canonical_fact(self, matter_id: uuid.UUID, fact_row):
        """Compatibility importer for an existing legacy fact through the universal write service."""
        if not fact_row or not fact_row.get("is_canonical"):
            return None
        key = str(fact_row.get("fact_key") or "").strip()
        if not key:
            return None
        async with self.db.p().transaction() as conn:
            definition = await self.legal_values.ensure_matter_definition(
                conn, matter_id=matter_id, semantic_key=key, display_label=fact_row.get("label") or fact_row.get("field") or key,
                value_type=fact_row.get("value_type") or "text", aliases=[fact_row.get("field") or key],
            )
            row, legacy = await self.legal_values.upsert_matter_value(
                conn, matter_id=matter_id, definition=definition, value=fact_row.get("fact"), source=fact_row.get("source") or "legacy",
                status="confirmed" if fact_row.get("status") in {"confirmed", "derived"} else fact_row.get("status") or "confirmed",
                provenance={"legacyFactId": str(fact_row["id"]), "bridge": "matter_facts_import"},
            )
            if str(legacy["id"]) != str(fact_row["id"]):
                await conn.execute("SELECT set_config('autodraft.legacy_projection_write','on',true)")
                try:
                    await conn.execute("UPDATE matter_facts SET field_definition_id=$1,is_canonical=FALSE,status='superseded',updated_at=NOW() WHERE id=$2", definition["id"], fact_row["id"])
                finally:
                    await conn.execute("SELECT set_config('autodraft.legacy_projection_write','off',true)")
            return row, definition
