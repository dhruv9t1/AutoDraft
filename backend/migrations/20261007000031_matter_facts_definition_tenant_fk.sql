-- Close a tenant-isolation gap: matter_facts.field_definition_id only had a bare
-- FK to field_definitions(id), so a fact could point at another tenant's field
-- definition. Add the same composite (organization_id, id) companion FK that
-- migration 20261005000019 added for every sibling relationship.

-- Defensive cleanup: detach any pre-existing cross-tenant references so the new
-- constraint can be validated. (Such rows are invalid by definition.)
UPDATE matter_facts mf
   SET field_definition_id = NULL
 WHERE mf.field_definition_id IS NOT NULL
   AND NOT EXISTS (
     SELECT 1 FROM field_definitions fd
      WHERE fd.id = mf.field_definition_id
        AND fd.organization_id = mf.organization_id
   );

CREATE UNIQUE INDEX IF NOT EXISTS uq_field_definitions_org_id ON field_definitions(organization_id,id);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_matter_facts_definition_tenant') THEN
    -- The bare FK keeps ON DELETE SET NULL; deleting a definition first nulls
    -- field_definition_id, so this MATCH SIMPLE composite FK is then not checked.
    ALTER TABLE matter_facts ADD CONSTRAINT fk_matter_facts_definition_tenant
      FOREIGN KEY (organization_id,field_definition_id) REFERENCES field_definitions(organization_id,id);
  END IF;
END $$;
