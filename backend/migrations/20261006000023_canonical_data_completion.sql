-- Canonical-data completion: repeatable values, typed/reference integrity,
-- practice/stage compatibility, and corrective typed backfill.

CREATE OR REPLACE FUNCTION autodraft_try_numeric(p_text TEXT) RETURNS NUMERIC
LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
  IF p_text IS NULL OR btrim(p_text)='' THEN RETURN NULL; END IF;
  RETURN replace(btrim(p_text), ',', '')::numeric;
EXCEPTION WHEN others THEN RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION autodraft_try_boolean(p_text TEXT) RETURNS BOOLEAN
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE v TEXT := lower(btrim(COALESCE(p_text,'')));
BEGIN
  IF v IN ('true','yes','1') THEN RETURN TRUE; END IF;
  IF v IN ('false','no','0') THEN RETURN FALSE; END IF;
  RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION autodraft_try_date(p_text TEXT) RETURNS DATE
LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
  IF p_text IS NULL OR btrim(p_text)='' THEN RETURN NULL; END IF;
  RETURN btrim(p_text)::date;
EXCEPTION WHEN others THEN RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION autodraft_try_timestamptz(p_text TEXT) RETURNS TIMESTAMPTZ
LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
  IF p_text IS NULL OR btrim(p_text)='' THEN RETURN NULL; END IF;
  RETURN btrim(p_text)::timestamptz;
EXCEPTION WHEN others THEN RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION autodraft_try_uuid(p_text TEXT) RETURNS UUID
LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
  IF p_text IS NULL OR btrim(p_text)='' THEN RETURN NULL; END IF;
  RETURN btrim(p_text)::uuid;
EXCEPTION WHEN others THEN RETURN NULL;
END $$;

CREATE TABLE IF NOT EXISTS field_value_migration_errors (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  parent_type TEXT NOT NULL CHECK(parent_type IN ('matter','contact')),
  parent_id UUID NOT NULL,
  field_definition_id UUID NOT NULL,
  source_value_id UUID,
  raw_text TEXT,
  target_value_type TEXT NOT NULL,
  reason TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(parent_type,parent_id,field_definition_id,source_value_id,reason)
);

ALTER TABLE matter_field_values ADD COLUMN IF NOT EXISTS value_contact_id UUID;
ALTER TABLE matter_field_values ADD COLUMN IF NOT EXISTS value_matter_id UUID;
ALTER TABLE matter_field_values ADD COLUMN IF NOT EXISTS value_document_id UUID;
ALTER TABLE contact_field_values ADD COLUMN IF NOT EXISTS value_contact_id UUID;
ALTER TABLE contact_field_values ADD COLUMN IF NOT EXISTS value_matter_id UUID;
ALTER TABLE contact_field_values ADD COLUMN IF NOT EXISTS value_document_id UUID;

CREATE TABLE IF NOT EXISTS matter_field_value_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  matter_id UUID NOT NULL,
  field_definition_id UUID NOT NULL,
  position INTEGER NOT NULL DEFAULT 0 CHECK(position >= 0),
  raw_text TEXT,
  value_text TEXT,
  value_number NUMERIC,
  value_boolean BOOLEAN,
  value_date DATE,
  value_datetime TIMESTAMPTZ,
  value_json JSONB,
  value_contact_id UUID,
  value_matter_id UUID,
  value_document_id UUID,
  source TEXT NOT NULL DEFAULT 'user',
  status TEXT NOT NULL DEFAULT 'confirmed',
  provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
  confirmed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(matter_id,field_definition_id,id)
);
CREATE INDEX IF NOT EXISTS idx_matter_field_value_items_collection ON matter_field_value_items(matter_id,field_definition_id,position,id);

CREATE TABLE IF NOT EXISTS contact_field_value_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  contact_id UUID NOT NULL,
  field_definition_id UUID NOT NULL,
  position INTEGER NOT NULL DEFAULT 0 CHECK(position >= 0),
  raw_text TEXT,
  value_text TEXT,
  value_number NUMERIC,
  value_boolean BOOLEAN,
  value_date DATE,
  value_datetime TIMESTAMPTZ,
  value_json JSONB,
  value_contact_id UUID,
  value_matter_id UUID,
  value_document_id UUID,
  source TEXT NOT NULL DEFAULT 'user',
  status TEXT NOT NULL DEFAULT 'confirmed',
  provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
  confirmed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(contact_id,field_definition_id,id)
);
CREATE INDEX IF NOT EXISTS idx_contact_field_value_items_collection ON contact_field_value_items(contact_id,field_definition_id,position,id);

-- Tenant-safe FK prerequisites.
CREATE UNIQUE INDEX IF NOT EXISTS uq_matter_field_value_items_org_id ON matter_field_value_items(organization_id,id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_contact_field_value_items_org_id ON contact_field_value_items(organization_id,id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_matter_stages_org_practice_id ON matter_stages(organization_id,practice_area_id,id);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_matter_value_contact_ref_tenant') THEN
    ALTER TABLE matter_field_values ADD CONSTRAINT fk_matter_value_contact_ref_tenant FOREIGN KEY(organization_id,value_contact_id) REFERENCES contacts(organization_id,id) ON DELETE RESTRICT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_matter_value_matter_ref_tenant') THEN
    ALTER TABLE matter_field_values ADD CONSTRAINT fk_matter_value_matter_ref_tenant FOREIGN KEY(organization_id,value_matter_id) REFERENCES matters(organization_id,id) ON DELETE RESTRICT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_matter_value_document_ref_tenant') THEN
    ALTER TABLE matter_field_values ADD CONSTRAINT fk_matter_value_document_ref_tenant FOREIGN KEY(organization_id,value_document_id) REFERENCES matter_documents(organization_id,id) ON DELETE RESTRICT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_contact_value_contact_ref_tenant') THEN
    ALTER TABLE contact_field_values ADD CONSTRAINT fk_contact_value_contact_ref_tenant FOREIGN KEY(organization_id,value_contact_id) REFERENCES contacts(organization_id,id) ON DELETE RESTRICT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_contact_value_matter_ref_tenant') THEN
    ALTER TABLE contact_field_values ADD CONSTRAINT fk_contact_value_matter_ref_tenant FOREIGN KEY(organization_id,value_matter_id) REFERENCES matters(organization_id,id) ON DELETE RESTRICT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_contact_value_document_ref_tenant') THEN
    ALTER TABLE contact_field_values ADD CONSTRAINT fk_contact_value_document_ref_tenant FOREIGN KEY(organization_id,value_document_id) REFERENCES matter_documents(organization_id,id) ON DELETE RESTRICT;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_matter_value_items_matter_tenant') THEN
    ALTER TABLE matter_field_value_items ADD CONSTRAINT fk_matter_value_items_matter_tenant FOREIGN KEY(organization_id,matter_id) REFERENCES matters(organization_id,id) ON DELETE CASCADE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_matter_value_items_definition_tenant') THEN
    ALTER TABLE matter_field_value_items ADD CONSTRAINT fk_matter_value_items_definition_tenant FOREIGN KEY(organization_id,field_definition_id) REFERENCES field_definitions(organization_id,id) ON DELETE RESTRICT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_contact_value_items_contact_tenant') THEN
    ALTER TABLE contact_field_value_items ADD CONSTRAINT fk_contact_value_items_contact_tenant FOREIGN KEY(organization_id,contact_id) REFERENCES contacts(organization_id,id) ON DELETE CASCADE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_contact_value_items_definition_tenant') THEN
    ALTER TABLE contact_field_value_items ADD CONSTRAINT fk_contact_value_items_definition_tenant FOREIGN KEY(organization_id,field_definition_id) REFERENCES field_definitions(organization_id,id) ON DELETE RESTRICT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_matter_value_item_contact_ref_tenant') THEN
    ALTER TABLE matter_field_value_items ADD CONSTRAINT fk_matter_value_item_contact_ref_tenant FOREIGN KEY(organization_id,value_contact_id) REFERENCES contacts(organization_id,id) ON DELETE RESTRICT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_matter_value_item_matter_ref_tenant') THEN
    ALTER TABLE matter_field_value_items ADD CONSTRAINT fk_matter_value_item_matter_ref_tenant FOREIGN KEY(organization_id,value_matter_id) REFERENCES matters(organization_id,id) ON DELETE RESTRICT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_matter_value_item_document_ref_tenant') THEN
    ALTER TABLE matter_field_value_items ADD CONSTRAINT fk_matter_value_item_document_ref_tenant FOREIGN KEY(organization_id,value_document_id) REFERENCES matter_documents(organization_id,id) ON DELETE RESTRICT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_contact_value_item_contact_ref_tenant') THEN
    ALTER TABLE contact_field_value_items ADD CONSTRAINT fk_contact_value_item_contact_ref_tenant FOREIGN KEY(organization_id,value_contact_id) REFERENCES contacts(organization_id,id) ON DELETE RESTRICT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_contact_value_item_matter_ref_tenant') THEN
    ALTER TABLE contact_field_value_items ADD CONSTRAINT fk_contact_value_item_matter_ref_tenant FOREIGN KEY(organization_id,value_matter_id) REFERENCES matters(organization_id,id) ON DELETE RESTRICT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_contact_value_item_document_ref_tenant') THEN
    ALTER TABLE contact_field_value_items ADD CONSTRAINT fk_contact_value_item_document_ref_tenant FOREIGN KEY(organization_id,value_document_id) REFERENCES matter_documents(organization_id,id) ON DELETE RESTRICT;
  END IF;

  -- A stage is now valid for a matter only when it belongs to that exact practice area.
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='ck_matters_stage_requires_practice') THEN
    ALTER TABLE matters ADD CONSTRAINT ck_matters_stage_requires_practice CHECK(stage_id IS NULL OR practice_area_id IS NOT NULL) NOT VALID;
    ALTER TABLE matters VALIDATE CONSTRAINT ck_matters_stage_requires_practice;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_matters_practice_stage_compatible') THEN
    ALTER TABLE matters ADD CONSTRAINT fk_matters_practice_stage_compatible
      FOREIGN KEY(organization_id,practice_area_id,stage_id)
      REFERENCES matter_stages(organization_id,practice_area_id,id) ON DELETE RESTRICT NOT VALID;
    ALTER TABLE matters VALIDATE CONSTRAINT fk_matters_practice_stage_compatible;
  END IF;
END $$;

-- Move any pre-existing scalar rows for repeatable definitions into real item collections.
INSERT INTO matter_field_value_items(
  id,organization_id,matter_id,field_definition_id,position,raw_text,value_text,value_number,value_boolean,value_date,value_datetime,value_json,
  value_contact_id,value_matter_id,value_document_id,source,status,provenance,confirmed_at,created_at,updated_at
)
SELECT fv.id,fv.organization_id,fv.matter_id,fv.field_definition_id,0,fv.raw_text,fv.value_text,fv.value_number,fv.value_boolean,fv.value_date,fv.value_datetime,fv.value_json,
       fv.value_contact_id,fv.value_matter_id,fv.value_document_id,fv.source,fv.status,fv.provenance,fv.confirmed_at,fv.created_at,fv.updated_at
FROM matter_field_values fv JOIN field_definitions fd ON fd.id=fv.field_definition_id
WHERE fd.repeatable=TRUE
ON CONFLICT(id) DO NOTHING;
DELETE FROM matter_field_values fv USING field_definitions fd
WHERE fd.id=fv.field_definition_id AND fd.repeatable=TRUE
  AND EXISTS(SELECT 1 FROM matter_field_value_items i WHERE i.id=fv.id);

INSERT INTO contact_field_value_items(
  id,organization_id,contact_id,field_definition_id,position,raw_text,value_text,value_number,value_boolean,value_date,value_datetime,value_json,
  value_contact_id,value_matter_id,value_document_id,source,status,provenance,confirmed_at,created_at,updated_at
)
SELECT fv.id,fv.organization_id,fv.contact_id,fv.field_definition_id,0,fv.raw_text,fv.value_text,fv.value_number,fv.value_boolean,fv.value_date,fv.value_datetime,fv.value_json,
       fv.value_contact_id,fv.value_matter_id,fv.value_document_id,fv.source,fv.status,fv.provenance,fv.confirmed_at,fv.created_at,fv.updated_at
FROM contact_field_values fv JOIN field_definitions fd ON fd.id=fv.field_definition_id
WHERE fd.repeatable=TRUE
ON CONFLICT(id) DO NOTHING;
DELETE FROM contact_field_values fv USING field_definitions fd
WHERE fd.id=fv.field_definition_id AND fd.repeatable=TRUE
  AND EXISTS(SELECT 1 FROM contact_field_value_items i WHERE i.id=fv.id);

-- Corrective typed backfill. Conversion failures are recorded instead of silently
-- claiming typed canonical persistence.
INSERT INTO field_value_migration_errors(organization_id,parent_type,parent_id,field_definition_id,source_value_id,raw_text,target_value_type,reason)
SELECT fv.organization_id,'matter',fv.matter_id,fv.field_definition_id,fv.id,fv.raw_text,fd.value_type,'legacy value cannot be converted to declared canonical type'
FROM matter_field_values fv JOIN field_definitions fd ON fd.id=fv.field_definition_id
WHERE fv.raw_text IS NOT NULL AND (
  (fd.value_type IN ('integer','decimal','currency') AND fv.value_number IS NULL AND autodraft_try_numeric(fv.raw_text) IS NULL) OR
  (fd.value_type='boolean' AND fv.value_boolean IS NULL AND autodraft_try_boolean(fv.raw_text) IS NULL) OR
  (fd.value_type='date' AND fv.value_date IS NULL AND autodraft_try_date(fv.raw_text) IS NULL) OR
  (fd.value_type='datetime' AND fv.value_datetime IS NULL AND autodraft_try_timestamptz(fv.raw_text) IS NULL) OR
  (fd.value_type IN ('contact_reference','matter_reference','document_reference') AND autodraft_try_uuid(fv.raw_text) IS NULL)
) ON CONFLICT DO NOTHING;

INSERT INTO field_value_migration_errors(organization_id,parent_type,parent_id,field_definition_id,source_value_id,raw_text,target_value_type,reason)
SELECT fv.organization_id,'contact',fv.contact_id,fv.field_definition_id,fv.id,fv.raw_text,fd.value_type,'legacy value cannot be converted to declared canonical type'
FROM contact_field_values fv JOIN field_definitions fd ON fd.id=fv.field_definition_id
WHERE fv.raw_text IS NOT NULL AND (
  (fd.value_type IN ('integer','decimal','currency') AND fv.value_number IS NULL AND autodraft_try_numeric(fv.raw_text) IS NULL) OR
  (fd.value_type='boolean' AND fv.value_boolean IS NULL AND autodraft_try_boolean(fv.raw_text) IS NULL) OR
  (fd.value_type='date' AND fv.value_date IS NULL AND autodraft_try_date(fv.raw_text) IS NULL) OR
  (fd.value_type='datetime' AND fv.value_datetime IS NULL AND autodraft_try_timestamptz(fv.raw_text) IS NULL) OR
  (fd.value_type IN ('contact_reference','matter_reference','document_reference') AND autodraft_try_uuid(fv.raw_text) IS NULL)
) ON CONFLICT DO NOTHING;

UPDATE matter_field_values fv SET value_number=autodraft_try_numeric(fv.raw_text)
FROM field_definitions fd WHERE fd.id=fv.field_definition_id AND fd.value_type IN ('integer','decimal','currency') AND fv.value_number IS NULL AND autodraft_try_numeric(fv.raw_text) IS NOT NULL;
UPDATE matter_field_values fv SET value_boolean=autodraft_try_boolean(fv.raw_text)
FROM field_definitions fd WHERE fd.id=fv.field_definition_id AND fd.value_type='boolean' AND fv.value_boolean IS NULL AND autodraft_try_boolean(fv.raw_text) IS NOT NULL;
UPDATE matter_field_values fv SET value_date=autodraft_try_date(fv.raw_text)
FROM field_definitions fd WHERE fd.id=fv.field_definition_id AND fd.value_type='date' AND fv.value_date IS NULL AND autodraft_try_date(fv.raw_text) IS NOT NULL;
UPDATE matter_field_values fv SET value_datetime=autodraft_try_timestamptz(fv.raw_text)
FROM field_definitions fd WHERE fd.id=fv.field_definition_id AND fd.value_type='datetime' AND fv.value_datetime IS NULL AND autodraft_try_timestamptz(fv.raw_text) IS NOT NULL;
UPDATE contact_field_values fv SET value_number=autodraft_try_numeric(fv.raw_text)
FROM field_definitions fd WHERE fd.id=fv.field_definition_id AND fd.value_type IN ('integer','decimal','currency') AND fv.value_number IS NULL AND autodraft_try_numeric(fv.raw_text) IS NOT NULL;
UPDATE contact_field_values fv SET value_boolean=autodraft_try_boolean(fv.raw_text)
FROM field_definitions fd WHERE fd.id=fv.field_definition_id AND fd.value_type='boolean' AND fv.value_boolean IS NULL AND autodraft_try_boolean(fv.raw_text) IS NOT NULL;
UPDATE contact_field_values fv SET value_date=autodraft_try_date(fv.raw_text)
FROM field_definitions fd WHERE fd.id=fv.field_definition_id AND fd.value_type='date' AND fv.value_date IS NULL AND autodraft_try_date(fv.raw_text) IS NOT NULL;
UPDATE contact_field_values fv SET value_datetime=autodraft_try_timestamptz(fv.raw_text)
FROM field_definitions fd WHERE fd.id=fv.field_definition_id AND fd.value_type='datetime' AND fv.value_datetime IS NULL AND autodraft_try_timestamptz(fv.raw_text) IS NOT NULL;

-- Populate reference columns only when the referenced entity exists in the same tenant.
UPDATE matter_field_values fv SET value_contact_id=autodraft_try_uuid(fv.raw_text)
FROM field_definitions fd, contacts c WHERE fd.id=fv.field_definition_id AND fd.value_type='contact_reference' AND c.organization_id=fv.organization_id AND c.id=autodraft_try_uuid(fv.raw_text);
UPDATE matter_field_values fv SET value_matter_id=autodraft_try_uuid(fv.raw_text)
FROM field_definitions fd, matters m WHERE fd.id=fv.field_definition_id AND fd.value_type='matter_reference' AND m.organization_id=fv.organization_id AND m.id=autodraft_try_uuid(fv.raw_text);
UPDATE matter_field_values fv SET value_document_id=autodraft_try_uuid(fv.raw_text)
FROM field_definitions fd, matter_documents d WHERE fd.id=fv.field_definition_id AND fd.value_type='document_reference' AND d.organization_id=fv.organization_id AND d.id=autodraft_try_uuid(fv.raw_text);
UPDATE contact_field_values fv SET value_contact_id=autodraft_try_uuid(fv.raw_text)
FROM field_definitions fd, contacts c WHERE fd.id=fv.field_definition_id AND fd.value_type='contact_reference' AND c.organization_id=fv.organization_id AND c.id=autodraft_try_uuid(fv.raw_text);
UPDATE contact_field_values fv SET value_matter_id=autodraft_try_uuid(fv.raw_text)
FROM field_definitions fd, matters m WHERE fd.id=fv.field_definition_id AND fd.value_type='matter_reference' AND m.organization_id=fv.organization_id AND m.id=autodraft_try_uuid(fv.raw_text);
UPDATE contact_field_values fv SET value_document_id=autodraft_try_uuid(fv.raw_text)
FROM field_definitions fd, matter_documents d WHERE fd.id=fv.field_definition_id AND fd.value_type='document_reference' AND d.organization_id=fv.organization_id AND d.id=autodraft_try_uuid(fv.raw_text);

-- Record parseable-but-dangling/cross-tenant legacy references explicitly.
INSERT INTO field_value_migration_errors(organization_id,parent_type,parent_id,field_definition_id,source_value_id,raw_text,target_value_type,reason)
SELECT fv.organization_id,'matter',fv.matter_id,fv.field_definition_id,fv.id,fv.raw_text,fd.value_type,'referenced entity does not exist in this tenant'
FROM matter_field_values fv JOIN field_definitions fd ON fd.id=fv.field_definition_id
WHERE fd.value_type IN ('contact_reference','matter_reference','document_reference') AND autodraft_try_uuid(fv.raw_text) IS NOT NULL
AND ((fd.value_type='contact_reference' AND fv.value_contact_id IS NULL) OR (fd.value_type='matter_reference' AND fv.value_matter_id IS NULL) OR (fd.value_type='document_reference' AND fv.value_document_id IS NULL))
ON CONFLICT DO NOTHING;
INSERT INTO field_value_migration_errors(organization_id,parent_type,parent_id,field_definition_id,source_value_id,raw_text,target_value_type,reason)
SELECT fv.organization_id,'contact',fv.contact_id,fv.field_definition_id,fv.id,fv.raw_text,fd.value_type,'referenced entity does not exist in this tenant'
FROM contact_field_values fv JOIN field_definitions fd ON fd.id=fv.field_definition_id
WHERE fd.value_type IN ('contact_reference','matter_reference','document_reference') AND autodraft_try_uuid(fv.raw_text) IS NOT NULL
AND ((fd.value_type='contact_reference' AND fv.value_contact_id IS NULL) OR (fd.value_type='matter_reference' AND fv.value_matter_id IS NULL) OR (fd.value_type='document_reference' AND fv.value_document_id IS NULL))
ON CONFLICT DO NOTHING;

-- New canonical data tables are fail-closed tenant data.
DO $$ DECLARE tbl TEXT; BEGIN
  FOREACH tbl IN ARRAY ARRAY['matter_field_value_items','contact_field_value_items','field_value_migration_errors'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY',tbl);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY',tbl);
    EXECUTE format('DROP POLICY IF EXISTS autodraft_tenant_isolation ON %I',tbl);
    EXECUTE format('CREATE POLICY autodraft_tenant_isolation ON %I USING (organization_id=autodraft_current_organization_id()) WITH CHECK (organization_id=autodraft_current_organization_id())',tbl);
  END LOOP;
END $$;

COMMENT ON TABLE matter_field_value_items IS 'Stable ordered instances for repeatable matter canonical fields.';
COMMENT ON TABLE contact_field_value_items IS 'Stable ordered instances for repeatable contact canonical fields.';
COMMENT ON TABLE field_value_migration_errors IS 'Explicit report of legacy canonical values that could not be safely converted to typed/reference storage.';

-- Apply the same typed/reference correction to repeatable instances that were
-- migrated from legacy scalar rows above.
INSERT INTO field_value_migration_errors(organization_id,parent_type,parent_id,field_definition_id,source_value_id,raw_text,target_value_type,reason)
SELECT i.organization_id,'matter',i.matter_id,i.field_definition_id,i.id,i.raw_text,fd.value_type,'legacy repeatable value cannot be converted to declared canonical type'
FROM matter_field_value_items i JOIN field_definitions fd ON fd.id=i.field_definition_id
WHERE i.raw_text IS NOT NULL AND (
  (fd.value_type IN ('integer','decimal','currency') AND i.value_number IS NULL AND autodraft_try_numeric(i.raw_text) IS NULL) OR
  (fd.value_type='boolean' AND i.value_boolean IS NULL AND autodraft_try_boolean(i.raw_text) IS NULL) OR
  (fd.value_type='date' AND i.value_date IS NULL AND autodraft_try_date(i.raw_text) IS NULL) OR
  (fd.value_type='datetime' AND i.value_datetime IS NULL AND autodraft_try_timestamptz(i.raw_text) IS NULL) OR
  (fd.value_type IN ('contact_reference','matter_reference','document_reference') AND autodraft_try_uuid(i.raw_text) IS NULL)
) ON CONFLICT DO NOTHING;
INSERT INTO field_value_migration_errors(organization_id,parent_type,parent_id,field_definition_id,source_value_id,raw_text,target_value_type,reason)
SELECT i.organization_id,'contact',i.contact_id,i.field_definition_id,i.id,i.raw_text,fd.value_type,'legacy repeatable value cannot be converted to declared canonical type'
FROM contact_field_value_items i JOIN field_definitions fd ON fd.id=i.field_definition_id
WHERE i.raw_text IS NOT NULL AND (
  (fd.value_type IN ('integer','decimal','currency') AND i.value_number IS NULL AND autodraft_try_numeric(i.raw_text) IS NULL) OR
  (fd.value_type='boolean' AND i.value_boolean IS NULL AND autodraft_try_boolean(i.raw_text) IS NULL) OR
  (fd.value_type='date' AND i.value_date IS NULL AND autodraft_try_date(i.raw_text) IS NULL) OR
  (fd.value_type='datetime' AND i.value_datetime IS NULL AND autodraft_try_timestamptz(i.raw_text) IS NULL) OR
  (fd.value_type IN ('contact_reference','matter_reference','document_reference') AND autodraft_try_uuid(i.raw_text) IS NULL)
) ON CONFLICT DO NOTHING;

UPDATE matter_field_value_items i SET value_number=autodraft_try_numeric(i.raw_text) FROM field_definitions fd WHERE fd.id=i.field_definition_id AND fd.value_type IN ('integer','decimal','currency') AND i.value_number IS NULL AND autodraft_try_numeric(i.raw_text) IS NOT NULL;
UPDATE matter_field_value_items i SET value_boolean=autodraft_try_boolean(i.raw_text) FROM field_definitions fd WHERE fd.id=i.field_definition_id AND fd.value_type='boolean' AND i.value_boolean IS NULL AND autodraft_try_boolean(i.raw_text) IS NOT NULL;
UPDATE matter_field_value_items i SET value_date=autodraft_try_date(i.raw_text) FROM field_definitions fd WHERE fd.id=i.field_definition_id AND fd.value_type='date' AND i.value_date IS NULL AND autodraft_try_date(i.raw_text) IS NOT NULL;
UPDATE matter_field_value_items i SET value_datetime=autodraft_try_timestamptz(i.raw_text) FROM field_definitions fd WHERE fd.id=i.field_definition_id AND fd.value_type='datetime' AND i.value_datetime IS NULL AND autodraft_try_timestamptz(i.raw_text) IS NOT NULL;
UPDATE contact_field_value_items i SET value_number=autodraft_try_numeric(i.raw_text) FROM field_definitions fd WHERE fd.id=i.field_definition_id AND fd.value_type IN ('integer','decimal','currency') AND i.value_number IS NULL AND autodraft_try_numeric(i.raw_text) IS NOT NULL;
UPDATE contact_field_value_items i SET value_boolean=autodraft_try_boolean(i.raw_text) FROM field_definitions fd WHERE fd.id=i.field_definition_id AND fd.value_type='boolean' AND i.value_boolean IS NULL AND autodraft_try_boolean(i.raw_text) IS NOT NULL;
UPDATE contact_field_value_items i SET value_date=autodraft_try_date(i.raw_text) FROM field_definitions fd WHERE fd.id=i.field_definition_id AND fd.value_type='date' AND i.value_date IS NULL AND autodraft_try_date(i.raw_text) IS NOT NULL;
UPDATE contact_field_value_items i SET value_datetime=autodraft_try_timestamptz(i.raw_text) FROM field_definitions fd WHERE fd.id=i.field_definition_id AND fd.value_type='datetime' AND i.value_datetime IS NULL AND autodraft_try_timestamptz(i.raw_text) IS NOT NULL;

UPDATE matter_field_value_items i SET value_contact_id=autodraft_try_uuid(i.raw_text) FROM field_definitions fd, contacts c WHERE fd.id=i.field_definition_id AND fd.value_type='contact_reference' AND c.organization_id=i.organization_id AND c.id=autodraft_try_uuid(i.raw_text);
UPDATE matter_field_value_items i SET value_matter_id=autodraft_try_uuid(i.raw_text) FROM field_definitions fd, matters m WHERE fd.id=i.field_definition_id AND fd.value_type='matter_reference' AND m.organization_id=i.organization_id AND m.id=autodraft_try_uuid(i.raw_text);
UPDATE matter_field_value_items i SET value_document_id=autodraft_try_uuid(i.raw_text) FROM field_definitions fd, matter_documents d WHERE fd.id=i.field_definition_id AND fd.value_type='document_reference' AND d.organization_id=i.organization_id AND d.id=autodraft_try_uuid(i.raw_text);
UPDATE contact_field_value_items i SET value_contact_id=autodraft_try_uuid(i.raw_text) FROM field_definitions fd, contacts c WHERE fd.id=i.field_definition_id AND fd.value_type='contact_reference' AND c.organization_id=i.organization_id AND c.id=autodraft_try_uuid(i.raw_text);
UPDATE contact_field_value_items i SET value_matter_id=autodraft_try_uuid(i.raw_text) FROM field_definitions fd, matters m WHERE fd.id=i.field_definition_id AND fd.value_type='matter_reference' AND m.organization_id=i.organization_id AND m.id=autodraft_try_uuid(i.raw_text);
UPDATE contact_field_value_items i SET value_document_id=autodraft_try_uuid(i.raw_text) FROM field_definitions fd, matter_documents d WHERE fd.id=i.field_definition_id AND fd.value_type='document_reference' AND d.organization_id=i.organization_id AND d.id=autodraft_try_uuid(i.raw_text);
