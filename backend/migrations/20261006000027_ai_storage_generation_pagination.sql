-- AI policy/provenance + binary object metadata + queued-generation support.

CREATE TABLE IF NOT EXISTS organization_ai_policies (
  organization_id UUID PRIMARY KEY REFERENCES organizations(id) ON DELETE CASCADE,
  external_system1_enabled BOOLEAN NOT NULL DEFAULT FALSE,
  provider TEXT NOT NULL DEFAULT 'off' CHECK (provider IN ('off','jev')),
  provider_model TEXT NOT NULL DEFAULT '',
  consent_note TEXT NOT NULL DEFAULT '',
  consented_by_user_id UUID,
  consented_at TIMESTAMPTZ,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  FOREIGN KEY (organization_id, consented_by_user_id)
    REFERENCES app_users(organization_id,id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS candidate_decision_audit (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  actor_user_id UUID,
  request_id UUID NOT NULL,
  candidate_id TEXT NOT NULL,
  candidate_fingerprint TEXT NOT NULL,
  source_position INTEGER NOT NULL DEFAULT 0,
  source_length INTEGER NOT NULL DEFAULT 0,
  provider_chain JSONB NOT NULL DEFAULT '[]'::jsonb,
  provider_versions JSONB NOT NULL DEFAULT '{}'::jsonb,
  provider TEXT NOT NULL DEFAULT '',
  model_version TEXT NOT NULL DEFAULT '',
  rules_version TEXT NOT NULL DEFAULT '',
  prompt_schema_version TEXT NOT NULL DEFAULT '',
  classification TEXT NOT NULL DEFAULT '',
  decision_source TEXT NOT NULL DEFAULT '',
  review_state TEXT NOT NULL DEFAULT '',
  reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
  evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
  decision_path JSONB NOT NULL DEFAULT '[]'::jsonb,
  final_lawyer_disposition TEXT,
  lawyer_user_id UUID,
  lawyer_reason TEXT NOT NULL DEFAULT '',
  lawyer_reviewed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  FOREIGN KEY (organization_id, actor_user_id)
    REFERENCES app_users(organization_id,id) ON DELETE SET NULL,
  FOREIGN KEY (organization_id, lawyer_user_id)
    REFERENCES app_users(organization_id,id) ON DELETE SET NULL,
  UNIQUE (organization_id, request_id, candidate_id)
);
ALTER TABLE candidate_decision_audit ADD COLUMN IF NOT EXISTS provider_versions JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE candidate_decision_audit ADD COLUMN IF NOT EXISTS decision_path JSONB NOT NULL DEFAULT '[]'::jsonb;
CREATE INDEX IF NOT EXISTS idx_candidate_decision_audit_request
  ON candidate_decision_audit(organization_id,request_id,created_at);
CREATE INDEX IF NOT EXISTS idx_candidate_decision_audit_candidate
  ON candidate_decision_audit(organization_id,candidate_id,created_at DESC);

-- Binary DOCX bytes now live in the configured object store. Legacy Base64
-- columns remain nullable for lazy migration/backward-compatible reads only.
ALTER TABLE templates ADD COLUMN IF NOT EXISTS docx_object_key TEXT;
ALTER TABLE templates ADD COLUMN IF NOT EXISTS docx_sha256 TEXT;
ALTER TABLE templates ADD COLUMN IF NOT EXISTS docx_size_bytes BIGINT NOT NULL DEFAULT 0;
ALTER TABLE template_versions ADD COLUMN IF NOT EXISTS docx_object_key TEXT;
ALTER TABLE template_versions ADD COLUMN IF NOT EXISTS docx_sha256 TEXT;
ALTER TABLE template_versions ADD COLUMN IF NOT EXISTS docx_size_bytes BIGINT NOT NULL DEFAULT 0;
ALTER TABLE matter_documents ADD COLUMN IF NOT EXISTS object_key TEXT;
ALTER TABLE matter_documents ADD COLUMN IF NOT EXISTS sha256 TEXT;
ALTER TABLE generation_artifacts ADD COLUMN IF NOT EXISTS object_key TEXT;
ALTER TABLE generation_artifacts ADD COLUMN IF NOT EXISTS size_bytes BIGINT NOT NULL DEFAULT 0;
ALTER TABLE matter_documents ALTER COLUMN docx_base64 DROP NOT NULL;
ALTER TABLE generation_artifacts ALTER COLUMN docx_base64 DROP NOT NULL;
CREATE INDEX IF NOT EXISTS idx_matter_documents_object_key ON matter_documents(object_key) WHERE object_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_generation_artifacts_object_key ON generation_artifacts(object_key) WHERE object_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_template_versions_object_key ON template_versions(docx_object_key) WHERE docx_object_key IS NOT NULL;

-- RLS for new tenant-owned policy/audit tables.
DO $$
DECLARE tbl TEXT;
BEGIN
  FOREACH tbl IN ARRAY ARRAY['organization_ai_policies','candidate_decision_audit'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY',tbl);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY',tbl);
    EXECUTE format('DROP POLICY IF EXISTS autodraft_tenant_isolation ON %I',tbl);
    EXECUTE format(
      'CREATE POLICY autodraft_tenant_isolation ON %I USING (organization_id=autodraft_current_organization_id()) WITH CHECK (organization_id=autodraft_current_organization_id())',
      tbl
    );
  END LOOP;
END $$;

-- Keyset pagination support for large tenants.
CREATE INDEX IF NOT EXISTS idx_contacts_org_updated_cursor ON contacts(organization_id,updated_at DESC,id DESC) WHERE archived_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_matters_org_updated_cursor ON matters(organization_id,updated_at DESC,id DESC) WHERE archived_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_templates_org_updated_cursor ON templates(organization_id,updated_at DESC,id DESC) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_workflows_org_updated_cursor ON workflows(organization_id,updated_at DESC,id DESC);
CREATE INDEX IF NOT EXISTS idx_workflow_sessions_org_updated_cursor ON workflow_sessions(organization_id,updated_at DESC,id DESC);
CREATE INDEX IF NOT EXISTS idx_document_sets_org_updated_cursor ON document_sets(organization_id,updated_at DESC,id DESC);
CREATE INDEX IF NOT EXISTS idx_generation_artifacts_org_created_cursor ON generation_artifacts(organization_id,created_at DESC,id DESC);
