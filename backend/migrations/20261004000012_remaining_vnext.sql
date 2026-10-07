-- AutoDraft vNext remaining reliability architecture.
-- This migration is additive and preserves all legacy rows/IDs.

CREATE TABLE IF NOT EXISTS organizations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO organizations(id, name)
VALUES ('00000000-0000-0000-0000-000000000001', 'Local AutoDraft')
ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS app_users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  email TEXT,
  display_name TEXT NOT NULL DEFAULT '',
  role TEXT NOT NULL DEFAULT 'lawyer' CHECK (role IN ('owner','admin','lawyer','staff','viewer')),
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_app_users_org ON app_users(organization_id);

ALTER TABLE matters ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES organizations(id);
UPDATE matters SET organization_id='00000000-0000-0000-0000-000000000001' WHERE organization_id IS NULL;
ALTER TABLE matters ALTER COLUMN organization_id SET DEFAULT '00000000-0000-0000-0000-000000000001';
ALTER TABLE matters ALTER COLUMN organization_id SET NOT NULL;

ALTER TABLE templates ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES organizations(id);
UPDATE templates SET organization_id='00000000-0000-0000-0000-000000000001' WHERE organization_id IS NULL;
ALTER TABLE templates ALTER COLUMN organization_id SET DEFAULT '00000000-0000-0000-0000-000000000001';
ALTER TABLE templates ALTER COLUMN organization_id SET NOT NULL;

ALTER TABLE intake_forms ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES organizations(id);
UPDATE intake_forms SET organization_id='00000000-0000-0000-0000-000000000001' WHERE organization_id IS NULL;
ALTER TABLE intake_forms ALTER COLUMN organization_id SET DEFAULT '00000000-0000-0000-0000-000000000001';
ALTER TABLE intake_forms ALTER COLUMN organization_id SET NOT NULL;

-- Complete DOCX template snapshots and immutable template versions.
ALTER TABLE templates ADD COLUMN IF NOT EXISTS docx_base64 TEXT;
ALTER TABLE templates ADD COLUMN IF NOT EXISTS snapshot_kind TEXT NOT NULL DEFAULT 'body_ooxml';
ALTER TABLE templates ADD COLUMN IF NOT EXISTS current_version INTEGER NOT NULL DEFAULT 1;

CREATE TABLE IF NOT EXISTS template_versions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  template_id UUID NOT NULL REFERENCES templates(id) ON DELETE CASCADE,
  version_number INTEGER NOT NULL,
  body_ooxml TEXT,
  docx_base64 TEXT,
  snapshot_kind TEXT NOT NULL DEFAULT 'body_ooxml',
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(template_id, version_number)
);
CREATE INDEX IF NOT EXISTS idx_template_versions_template ON template_versions(template_id, version_number DESC);

-- First-class Matter Documents repository.
CREATE TABLE IF NOT EXISTS matter_documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE DEFAULT '00000000-0000-0000-0000-000000000001',
  matter_id UUID NOT NULL REFERENCES matters(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  mime_type TEXT NOT NULL DEFAULT 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  docx_base64 TEXT NOT NULL,
  size_bytes BIGINT NOT NULL DEFAULT 0,
  source TEXT NOT NULL DEFAULT 'captured',
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  archived_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_matter_documents_matter ON matter_documents(matter_id, updated_at DESC) WHERE archived_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_matter_documents_org ON matter_documents(organization_id);

-- Backend record of immutable Word bindings / occurrences.
CREATE TABLE IF NOT EXISTS document_bindings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE DEFAULT '00000000-0000-0000-0000-000000000001',
  binding_id UUID NOT NULL,
  field_id UUID,
  matter_document_id UUID REFERENCES matter_documents(id) ON DELETE CASCADE,
  template_id UUID REFERENCES templates(id) ON DELETE CASCADE,
  semantic_key TEXT NOT NULL DEFAULT '',
  display_label TEXT NOT NULL DEFAULT '',
  occurrence_id UUID NOT NULL DEFAULT gen_random_uuid(),
  source_location JSONB NOT NULL DEFAULT '{}'::jsonb,
  state TEXT NOT NULL DEFAULT 'bound',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(binding_id, occurrence_id)
);
CREATE INDEX IF NOT EXISTS idx_document_bindings_binding ON document_bindings(binding_id);
CREATE INDEX IF NOT EXISTS idx_document_bindings_document ON document_bindings(matter_document_id);

-- Rich lawyer-owned, versioned Intake model. Legacy intake_forms remains for compatibility.
CREATE TABLE IF NOT EXISTS questionnaire_templates (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE DEFAULT '00000000-0000-0000-0000-000000000001',
  title TEXT NOT NULL,
  matter_type TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'draft',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_questionnaire_templates_org ON questionnaire_templates(organization_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS questionnaire_versions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  template_id UUID NOT NULL REFERENCES questionnaire_templates(id) ON DELETE CASCADE,
  version_number INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','published','retired')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  published_at TIMESTAMPTZ,
  UNIQUE(template_id, version_number)
);

CREATE TABLE IF NOT EXISTS questionnaire_sections (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  version_id UUID NOT NULL REFERENCES questionnaire_versions(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  position INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_questionnaire_sections_version ON questionnaire_sections(version_id, position);

CREATE TABLE IF NOT EXISTS questionnaire_questions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  version_id UUID NOT NULL REFERENCES questionnaire_versions(id) ON DELETE CASCADE,
  section_id UUID REFERENCES questionnaire_sections(id) ON DELETE SET NULL,
  position INTEGER NOT NULL DEFAULT 0,
  label TEXT NOT NULL,
  help_text TEXT NOT NULL DEFAULT '',
  question_type TEXT NOT NULL DEFAULT 'text',
  required BOOLEAN NOT NULL DEFAULT FALSE,
  fact_key TEXT,
  options JSONB NOT NULL DEFAULT '[]'::jsonb,
  display_rule JSONB,
  validation JSONB NOT NULL DEFAULT '{}'::jsonb,
  approved BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_questionnaire_questions_version ON questionnaire_questions(version_id, position);

CREATE TABLE IF NOT EXISTS intake_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE DEFAULT '00000000-0000-0000-0000-000000000001',
  questionnaire_version_id UUID NOT NULL REFERENCES questionnaire_versions(id) ON DELETE RESTRICT,
  matter_id UUID REFERENCES matters(id) ON DELETE SET NULL,
  token TEXT UNIQUE NOT NULL,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','submitted','revoked','expired')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  expires_at TIMESTAMPTZ,
  submitted_at TIMESTAMPTZ,
  revoked_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_intake_sessions_token ON intake_sessions(token);

CREATE TABLE IF NOT EXISTS intake_session_questions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID NOT NULL REFERENCES intake_sessions(id) ON DELETE CASCADE,
  question_id UUID NOT NULL REFERENCES questionnaire_questions(id) ON DELETE RESTRICT,
  snapshot JSONB NOT NULL,
  position INTEGER NOT NULL DEFAULT 0,
  UNIQUE(session_id, question_id)
);

CREATE TABLE IF NOT EXISTS intake_answers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID NOT NULL REFERENCES intake_sessions(id) ON DELETE CASCADE,
  question_id UUID NOT NULL REFERENCES questionnaire_questions(id) ON DELETE RESTRICT,
  answer_text TEXT,
  answer_json JSONB,
  review_status TEXT NOT NULL DEFAULT 'pending' CHECK (review_status IN ('pending','accepted','rejected','conflict')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  reviewed_at TIMESTAMPTZ,
  UNIQUE(session_id, question_id)
);

-- Matter fact provenance/conflicts/derived facts.
ALTER TABLE matter_facts ADD COLUMN IF NOT EXISTS fact_key TEXT;
ALTER TABLE matter_facts ADD COLUMN IF NOT EXISTS label TEXT;
ALTER TABLE matter_facts ADD COLUMN IF NOT EXISTS value_type TEXT NOT NULL DEFAULT 'text';
ALTER TABLE matter_facts ADD COLUMN IF NOT EXISTS value_json JSONB;
ALTER TABLE matter_facts ADD COLUMN IF NOT EXISTS is_canonical BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE matter_facts ADD COLUMN IF NOT EXISTS derived_from JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE matter_facts ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMPTZ;
UPDATE matter_facts SET fact_key=COALESCE(NULLIF(fact_key,''), LOWER(REGEXP_REPLACE(field, '[^a-zA-Z0-9]+', '_', 'g'))), label=COALESCE(NULLIF(label,''), field) WHERE fact_key IS NULL OR label IS NULL;
CREATE INDEX IF NOT EXISTS idx_matter_facts_key ON matter_facts(matter_id, fact_key, is_canonical);

CREATE TABLE IF NOT EXISTS fact_conflicts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  matter_id UUID NOT NULL REFERENCES matters(id) ON DELETE CASCADE,
  fact_key TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved','dismissed')),
  candidate_fact_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
  resolution_fact_id UUID REFERENCES matter_facts(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  resolved_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_fact_conflicts_matter ON fact_conflicts(matter_id, status);

CREATE TABLE IF NOT EXISTS derived_fact_rules (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE DEFAULT '00000000-0000-0000-0000-000000000001',
  fact_key TEXT NOT NULL,
  label TEXT NOT NULL,
  value_type TEXT NOT NULL DEFAULT 'text',
  expression JSONB NOT NULL,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(organization_id, fact_key)
);

-- Audit expansion for production hardening.
ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES organizations(id);
ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS actor_user_id UUID REFERENCES app_users(id) ON DELETE SET NULL;
ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS request_id TEXT;
ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS ip_address INET;
CREATE INDEX IF NOT EXISTS idx_audit_events_org ON audit_events(organization_id, created_at DESC);

-- RLS policies are created but not forced for the local-development role. A
-- production deployment can enable FORCE ROW LEVEL SECURITY after setting
-- `autodraft.organization_id` on every request connection/transaction.
DO $$
DECLARE tbl TEXT;
BEGIN
  FOREACH tbl IN ARRAY ARRAY['matters','templates','matter_documents','questionnaire_templates','intake_sessions','document_bindings'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', tbl);
    EXECUTE format('DROP POLICY IF EXISTS autodraft_tenant_isolation ON %I', tbl);
    EXECUTE format(
      'CREATE POLICY autodraft_tenant_isolation ON %I USING (organization_id = COALESCE(NULLIF(current_setting(''autodraft.organization_id'', true), '''')::uuid, ''00000000-0000-0000-0000-000000000001''::uuid)) WITH CHECK (organization_id = COALESCE(NULLIF(current_setting(''autodraft.organization_id'', true), '''')::uuid, ''00000000-0000-0000-0000-000000000001''::uuid))',
      tbl
    );
  END LOOP;
END $$;

CREATE TABLE IF NOT EXISTS intake_files (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID NOT NULL REFERENCES intake_sessions(id) ON DELETE CASCADE,
  question_id UUID NOT NULL REFERENCES questionnaire_questions(id) ON DELETE RESTRICT,
  filename TEXT NOT NULL,
  mime_type TEXT NOT NULL DEFAULT 'application/octet-stream',
  size_bytes BIGINT NOT NULL,
  sha256 TEXT NOT NULL,
  content BYTEA NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_intake_files_session ON intake_files(session_id, question_id);
