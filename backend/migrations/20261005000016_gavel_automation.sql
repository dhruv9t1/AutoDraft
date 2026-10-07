-- Gavel-inspired workflow/document-automation foundations for AutoDraft v1.3.
-- Additive and tenant-scoped. Existing intake, facts, templates and document sets remain valid.

CREATE TABLE IF NOT EXISTS workflows (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  audience TEXT NOT NULL DEFAULT 'internal' CHECK (audience IN ('internal','client','both')),
  practice_area_id UUID REFERENCES practice_areas(id) ON DELETE SET NULL,
  matter_type TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','published','retired')),
  current_version INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_workflows_org ON workflows(organization_id,status,updated_at DESC);

CREATE TABLE IF NOT EXISTS workflow_versions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  workflow_id UUID NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
  version_number INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','published','retired')),
  definition JSONB NOT NULL DEFAULT '{"pages":[],"calculations":[]}'::jsonb,
  published_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(workflow_id,version_number)
);
CREATE INDEX IF NOT EXISTS idx_workflow_versions_workflow ON workflow_versions(workflow_id,version_number DESC);

CREATE TABLE IF NOT EXISTS workflow_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  workflow_version_id UUID NOT NULL REFERENCES workflow_versions(id) ON DELETE RESTRICT,
  matter_id UUID REFERENCES matters(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'in_progress' CHECK (status IN ('in_progress','completed','abandoned')),
  answers JSONB NOT NULL DEFAULT '{}'::jsonb,
  calculations JSONB NOT NULL DEFAULT '{}'::jsonb,
  current_page TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  expires_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_workflow_sessions_matter ON workflow_sessions(matter_id,created_at DESC);

-- Public bearer-token bootstrap table intentionally contains only token hash + tenant/session routing.
-- Like public_intake_tokens, it is outside tenant RLS because tenant identity is not yet known.
CREATE TABLE IF NOT EXISTS public_workflow_tokens (
  token_hash TEXT PRIMARY KEY,
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  session_id UUID NOT NULL UNIQUE REFERENCES workflow_sessions(id) ON DELETE CASCADE,
  expires_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS template_automation_drafts (
  template_id UUID PRIMARY KEY REFERENCES templates(id) ON DELETE CASCADE,
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  blueprint JSONB NOT NULL DEFAULT '{"bindings":[],"conditions":[],"repeaters":[]}'::jsonb,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS template_automation_versions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  template_id UUID NOT NULL REFERENCES templates(id) ON DELETE CASCADE,
  template_version_id UUID NOT NULL UNIQUE REFERENCES template_versions(id) ON DELETE CASCADE,
  blueprint JSONB NOT NULL DEFAULT '{"bindings":[],"conditions":[],"repeaters":[]}'::jsonb,
  preflight JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_template_automation_versions_template ON template_automation_versions(template_id,created_at DESC);

CREATE TABLE IF NOT EXISTS generation_artifacts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  matter_id UUID REFERENCES matters(id) ON DELETE CASCADE,
  generation_run_id UUID REFERENCES generation_runs(id) ON DELETE SET NULL,
  workflow_session_id UUID REFERENCES workflow_sessions(id) ON DELETE SET NULL,
  template_id UUID NOT NULL REFERENCES templates(id) ON DELETE RESTRICT,
  template_version_id UUID NOT NULL REFERENCES template_versions(id) ON DELETE RESTRICT,
  filename TEXT NOT NULL,
  mime_type TEXT NOT NULL DEFAULT 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  docx_base64 TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_generation_artifacts_matter ON generation_artifacts(matter_id,created_at DESC);

ALTER TABLE generation_runs ADD COLUMN IF NOT EXISTS workflow_session_id UUID REFERENCES workflow_sessions(id) ON DELETE SET NULL;
ALTER TABLE generation_runs ADD COLUMN IF NOT EXISTS artifact_ids JSONB NOT NULL DEFAULT '[]'::jsonb;

DO $$
DECLARE tbl TEXT;
BEGIN
  FOREACH tbl IN ARRAY ARRAY[
    'workflows','workflow_versions','workflow_sessions','template_automation_drafts',
    'template_automation_versions','generation_artifacts'
  ] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', tbl);
    EXECUTE format('DROP POLICY IF EXISTS autodraft_tenant_isolation ON %I', tbl);
    EXECUTE format(
      'CREATE POLICY autodraft_tenant_isolation ON %I USING (organization_id = COALESCE(NULLIF(current_setting(''autodraft.organization_id'', true), '''')::uuid, ''00000000-0000-0000-0000-000000000001''::uuid)) WITH CHECK (organization_id = COALESCE(NULLIF(current_setting(''autodraft.organization_id'', true), '''')::uuid, ''00000000-0000-0000-0000-000000000001''::uuid))',
      tbl
    );
  END LOOP;
END $$;
