-- Clio-inspired legal data foundations for AutoDraft v1.2.
-- Additive migration: preserves existing matters/facts/templates and backfills
-- canonical field definitions/values without changing legacy IDs.

CREATE TABLE IF NOT EXISTS practice_areas (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  key TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  active BOOLEAN NOT NULL DEFAULT TRUE,
  position INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(organization_id, key)
);

CREATE TABLE IF NOT EXISTS matter_stages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  practice_area_id UUID NOT NULL REFERENCES practice_areas(id) ON DELETE CASCADE,
  key TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  position INTEGER NOT NULL DEFAULT 0,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(organization_id, practice_area_id, key)
);

CREATE TABLE IF NOT EXISTS contacts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  contact_type TEXT NOT NULL DEFAULT 'person' CHECK (contact_type IN ('person','company')),
  display_name TEXT NOT NULL,
  first_name TEXT NOT NULL DEFAULT '',
  middle_name TEXT NOT NULL DEFAULT '',
  last_name TEXT NOT NULL DEFAULT '',
  company_name TEXT NOT NULL DEFAULT '',
  email TEXT NOT NULL DEFAULT '',
  phone TEXT NOT NULL DEFAULT '',
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  archived_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_contacts_org_name ON contacts(organization_id, lower(display_name)) WHERE archived_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_contacts_email ON contacts(organization_id, lower(email)) WHERE email <> '' AND archived_at IS NULL;

CREATE TABLE IF NOT EXISTS matter_participants (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  matter_id UUID NOT NULL REFERENCES matters(id) ON DELETE CASCADE,
  contact_id UUID NOT NULL REFERENCES contacts(id) ON DELETE RESTRICT,
  role_key TEXT NOT NULL,
  display_role TEXT NOT NULL,
  is_client BOOLEAN NOT NULL DEFAULT FALSE,
  is_primary BOOLEAN NOT NULL DEFAULT FALSE,
  represented_by_firm BOOLEAN NOT NULL DEFAULT FALSE,
  position INTEGER NOT NULL DEFAULT 0,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(matter_id, contact_id, role_key)
);
CREATE INDEX IF NOT EXISTS idx_matter_participants_matter ON matter_participants(matter_id, position, created_at);
CREATE INDEX IF NOT EXISTS idx_matter_participants_contact ON matter_participants(contact_id);

ALTER TABLE matters ADD COLUMN IF NOT EXISTS practice_area_id UUID REFERENCES practice_areas(id) ON DELETE SET NULL;
ALTER TABLE matters ADD COLUMN IF NOT EXISTS stage_id UUID REFERENCES matter_stages(id) ON DELETE SET NULL;
ALTER TABLE matters ADD COLUMN IF NOT EXISTS reference_code TEXT NOT NULL DEFAULT '';
ALTER TABLE matters ADD COLUMN IF NOT EXISTS stage_changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
CREATE INDEX IF NOT EXISTS idx_matters_practice_stage ON matters(organization_id, practice_area_id, stage_id) WHERE archived_at IS NULL;

CREATE TABLE IF NOT EXISTS field_groups (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  key TEXT NOT NULL,
  label TEXT NOT NULL,
  entity_scope TEXT NOT NULL DEFAULT 'matter' CHECK (entity_scope IN ('matter','contact')),
  role_key TEXT,
  practice_area_id UUID REFERENCES practice_areas(id) ON DELETE SET NULL,
  position INTEGER NOT NULL DEFAULT 0,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(organization_id, key)
);

CREATE TABLE IF NOT EXISTS field_definitions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  semantic_key TEXT NOT NULL,
  display_label TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  entity_scope TEXT NOT NULL DEFAULT 'matter' CHECK (entity_scope IN ('matter','contact')),
  value_type TEXT NOT NULL DEFAULT 'text' CHECK (value_type IN ('text','long_text','integer','decimal','currency','date','datetime','boolean','choice','multi_choice','email','phone','address','contact_reference','matter_reference','document_reference','json')),
  repeatable BOOLEAN NOT NULL DEFAULT FALSE,
  required BOOLEAN NOT NULL DEFAULT FALSE,
  validation JSONB NOT NULL DEFAULT '{}'::jsonb,
  formatting JSONB NOT NULL DEFAULT '{}'::jsonb,
  options JSONB NOT NULL DEFAULT '[]'::jsonb,
  aliases JSONB NOT NULL DEFAULT '[]'::jsonb,
  group_id UUID REFERENCES field_groups(id) ON DELETE SET NULL,
  practice_area_id UUID REFERENCES practice_areas(id) ON DELETE SET NULL,
  matter_type TEXT NOT NULL DEFAULT '',
  position INTEGER NOT NULL DEFAULT 0,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(organization_id, semantic_key)
);
CREATE INDEX IF NOT EXISTS idx_field_definitions_scope ON field_definitions(organization_id, entity_scope, active, position);
CREATE INDEX IF NOT EXISTS idx_field_definitions_group ON field_definitions(group_id, position);

CREATE TABLE IF NOT EXISTS matter_field_values (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  matter_id UUID NOT NULL REFERENCES matters(id) ON DELETE CASCADE,
  field_definition_id UUID NOT NULL REFERENCES field_definitions(id) ON DELETE RESTRICT,
  raw_text TEXT,
  value_text TEXT,
  value_number NUMERIC,
  value_boolean BOOLEAN,
  value_date DATE,
  value_datetime TIMESTAMPTZ,
  value_json JSONB,
  source TEXT NOT NULL DEFAULT 'user',
  status TEXT NOT NULL DEFAULT 'confirmed',
  provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
  confirmed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(matter_id, field_definition_id)
);
CREATE INDEX IF NOT EXISTS idx_matter_field_values_matter ON matter_field_values(matter_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS contact_field_values (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  contact_id UUID NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
  field_definition_id UUID NOT NULL REFERENCES field_definitions(id) ON DELETE RESTRICT,
  raw_text TEXT,
  value_text TEXT,
  value_number NUMERIC,
  value_boolean BOOLEAN,
  value_date DATE,
  value_datetime TIMESTAMPTZ,
  value_json JSONB,
  source TEXT NOT NULL DEFAULT 'user',
  status TEXT NOT NULL DEFAULT 'confirmed',
  provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
  confirmed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(contact_id, field_definition_id)
);
CREATE INDEX IF NOT EXISTS idx_contact_field_values_contact ON contact_field_values(contact_id, updated_at DESC);

ALTER TABLE matter_facts ADD COLUMN IF NOT EXISTS field_definition_id UUID REFERENCES field_definitions(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_matter_facts_definition ON matter_facts(field_definition_id);

-- Backfill a reusable field definition for every existing matter fact key.
INSERT INTO field_definitions(organization_id,semantic_key,display_label,entity_scope,value_type,aliases)
SELECT DISTINCT m.organization_id,
       mf.fact_key,
       COALESCE(NULLIF(mf.label,''), NULLIF(mf.field,''), mf.fact_key),
       'matter',
       CASE WHEN mf.value_type IN ('text','long_text','integer','decimal','currency','date','datetime','boolean','choice','multi_choice','email','phone','address','contact_reference','matter_reference','document_reference','json') THEN mf.value_type ELSE 'text' END,
       jsonb_build_array(mf.field)
FROM matter_facts mf
JOIN matters m ON m.id=mf.matter_id
WHERE COALESCE(mf.fact_key,'') <> ''
ON CONFLICT(organization_id,semantic_key) DO NOTHING;

UPDATE matter_facts mf
SET field_definition_id=fd.id
FROM matters m, field_definitions fd
WHERE m.id=mf.matter_id
  AND fd.organization_id=m.organization_id
  AND fd.semantic_key=mf.fact_key
  AND mf.field_definition_id IS NULL;

INSERT INTO matter_field_values(
  organization_id,matter_id,field_definition_id,raw_text,value_text,value_json,source,status,confirmed_at,provenance
)
SELECT DISTINCT ON (mf.matter_id,mf.field_definition_id)
       m.organization_id,mf.matter_id,mf.field_definition_id,mf.fact,mf.fact,mf.value_json,mf.source,mf.status,mf.confirmed_at,
       jsonb_build_object('legacyFactId',mf.id::text,'bridge','matter_facts')
FROM matter_facts mf
JOIN matters m ON m.id=mf.matter_id
WHERE mf.is_canonical=TRUE AND mf.field_definition_id IS NOT NULL
ORDER BY mf.matter_id,mf.field_definition_id,COALESCE(mf.updated_at,mf.created_at) DESC
ON CONFLICT(matter_id,field_definition_id) DO NOTHING;

CREATE TABLE IF NOT EXISTS document_sets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  practice_area_id UUID REFERENCES practice_areas(id) ON DELETE SET NULL,
  matter_type TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','published','retired')),
  current_version INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_document_sets_org ON document_sets(organization_id,status,updated_at DESC);

CREATE TABLE IF NOT EXISTS document_set_versions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  document_set_id UUID NOT NULL REFERENCES document_sets(id) ON DELETE CASCADE,
  version_number INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'published' CHECK (status IN ('published','retired')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  published_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(document_set_id,version_number)
);

CREATE TABLE IF NOT EXISTS document_set_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  version_id UUID NOT NULL REFERENCES document_set_versions(id) ON DELETE CASCADE,
  template_id UUID NOT NULL REFERENCES templates(id) ON DELETE RESTRICT,
  template_version_id UUID REFERENCES template_versions(id) ON DELETE RESTRICT,
  label TEXT NOT NULL DEFAULT '',
  position INTEGER NOT NULL DEFAULT 0,
  required BOOLEAN NOT NULL DEFAULT TRUE,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE(version_id,template_id)
);
CREATE INDEX IF NOT EXISTS idx_document_set_items_version ON document_set_items(version_id,position);

CREATE TABLE IF NOT EXISTS document_set_drafts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  document_set_id UUID NOT NULL REFERENCES document_sets(id) ON DELETE CASCADE,
  template_id UUID NOT NULL REFERENCES templates(id) ON DELETE CASCADE,
  label TEXT NOT NULL DEFAULT '',
  position INTEGER NOT NULL DEFAULT 0,
  required BOOLEAN NOT NULL DEFAULT TRUE,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE(document_set_id,template_id)
);

CREATE TABLE IF NOT EXISTS generation_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  matter_id UUID NOT NULL REFERENCES matters(id) ON DELETE CASCADE,
  document_set_version_id UUID REFERENCES document_set_versions(id) ON DELETE SET NULL,
  status TEXT NOT NULL DEFAULT 'selection' CHECK (status IN ('selection','population','review','completed','failed')),
  selected_items JSONB NOT NULL DEFAULT '[]'::jsonb,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_generation_runs_matter ON generation_runs(matter_id,created_at DESC);

CREATE TABLE IF NOT EXISTS outbox_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  aggregate_type TEXT NOT NULL,
  aggregate_id UUID,
  matter_id UUID REFERENCES matters(id) ON DELETE CASCADE,
  event_type TEXT NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','published','dead')),
  attempts INTEGER NOT NULL DEFAULT 0,
  available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  published_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_outbox_pending ON outbox_events(status,available_at,created_at);
CREATE INDEX IF NOT EXISTS idx_outbox_matter ON outbox_events(matter_id,created_at DESC);

-- Tenant isolation for all new organization-owned tables.
DO $$
DECLARE tbl TEXT;
BEGIN
  FOREACH tbl IN ARRAY ARRAY[
    'practice_areas','matter_stages','contacts','matter_participants','field_groups','field_definitions',
    'matter_field_values','contact_field_values','document_sets','document_set_versions','document_set_items','document_set_drafts','generation_runs','outbox_events'
  ] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', tbl);
    EXECUTE format('DROP POLICY IF EXISTS autodraft_tenant_isolation ON %I', tbl);
    EXECUTE format(
      'CREATE POLICY autodraft_tenant_isolation ON %I USING (organization_id = COALESCE(NULLIF(current_setting(''autodraft.organization_id'', true), '''')::uuid, ''00000000-0000-0000-0000-000000000001''::uuid)) WITH CHECK (organization_id = COALESCE(NULLIF(current_setting(''autodraft.organization_id'', true), '''')::uuid, ''00000000-0000-0000-0000-000000000001''::uuid))',
      tbl
    );
  END LOOP;
END $$;
