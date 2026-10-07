-- DATA-001: matter_field_values is the authoritative legal-value store.
-- matter_facts remains a compatibility/history/conflict ledger. Canonical rows
-- in matter_facts are a transactionally maintained projection only.

-- Ensure there is at most one canonical legacy projection for each canonical
-- field. Historical duplicates are demoted before the invariant is installed.
WITH ranked AS (
  SELECT id,
         ROW_NUMBER() OVER (
           PARTITION BY matter_id,field_definition_id
           ORDER BY COALESCE(updated_at,created_at) DESC,id DESC
         ) AS rn
  FROM matter_facts
  WHERE is_canonical=TRUE AND field_definition_id IS NOT NULL
)
UPDATE matter_facts mf
SET is_canonical=FALSE,status=CASE WHEN status='confirmed' THEN 'superseded' ELSE status END,updated_at=NOW()
FROM ranked r
WHERE mf.id=r.id AND r.rn>1;

-- Reconcile the surviving compatibility projection from the canonical typed
-- source before preventing future independent canonical writes.
UPDATE matter_facts mf
SET field=fd.display_label,
    label=fd.display_label,
    fact=COALESCE(fv.raw_text,fv.value_text,fv.value_number::text,fv.value_boolean::text,fv.value_date::text,fv.value_datetime::text,fv.value_json::text,''),
    source=fv.source,
    status=fv.status,
    fact_key=fd.semantic_key,
    value_type=fd.value_type,
    value_json=fv.value_json,
    confirmed_at=fv.confirmed_at,
    updated_at=NOW()
FROM matter_field_values fv
JOIN field_definitions fd ON fd.id=fv.field_definition_id
WHERE mf.matter_id=fv.matter_id
  AND mf.field_definition_id=fv.field_definition_id
  AND mf.is_canonical=TRUE;

INSERT INTO matter_facts(
  organization_id,matter_id,field,fact,source,status,fact_key,label,value_type,
  value_json,is_canonical,confirmed_at,field_definition_id
)
SELECT fv.organization_id,fv.matter_id,fd.display_label,
       COALESCE(fv.raw_text,fv.value_text,fv.value_number::text,fv.value_boolean::text,fv.value_date::text,fv.value_datetime::text,fv.value_json::text,''),
       fv.source,fv.status,fd.semantic_key,fd.display_label,fd.value_type,fv.value_json,
       TRUE,fv.confirmed_at,fv.field_definition_id
FROM matter_field_values fv
JOIN field_definitions fd ON fd.id=fv.field_definition_id
WHERE NOT EXISTS (
  SELECT 1 FROM matter_facts mf
  WHERE mf.matter_id=fv.matter_id
    AND mf.field_definition_id=fv.field_definition_id
    AND mf.is_canonical=TRUE
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_matter_facts_canonical_projection
  ON matter_facts(matter_id,field_definition_id)
  WHERE is_canonical=TRUE AND field_definition_id IS NOT NULL;

CREATE OR REPLACE FUNCTION autodraft_guard_legacy_canonical_fact_write()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
  projection_write BOOLEAN := COALESCE(current_setting('autodraft.legacy_projection_write',true),'off')='on';
BEGIN
  IF projection_write THEN
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
  END IF;

  IF TG_OP='DELETE' THEN
    IF OLD.is_canonical THEN
      RAISE EXCEPTION 'Canonical matter_facts rows are projections; write matter_field_values instead'
        USING ERRCODE='55000';
    END IF;
    RETURN OLD;
  END IF;

  IF NEW.is_canonical THEN
    RAISE EXCEPTION 'Canonical matter_facts rows are projections; write matter_field_values instead'
      USING ERRCODE='55000';
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_guard_legacy_canonical_fact_write ON matter_facts;
CREATE TRIGGER trg_guard_legacy_canonical_fact_write
BEFORE INSERT OR UPDATE OR DELETE ON matter_facts
FOR EACH ROW EXECUTE FUNCTION autodraft_guard_legacy_canonical_fact_write();

COMMENT ON TABLE matter_field_values IS
  'Authoritative typed matter legal values. All canonical legal-value writes must use this store.';
COMMENT ON TABLE matter_facts IS
  'Compatibility/history/conflict ledger. Rows with is_canonical=TRUE are projections of matter_field_values and are not an independent source of truth.';
