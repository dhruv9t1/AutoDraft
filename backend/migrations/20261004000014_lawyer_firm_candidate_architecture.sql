-- Lawyer-firm extraction concepts, adapted to AutoDraft's tenant-safe architecture.

CREATE TABLE IF NOT EXISTS organization_boilerplate (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  value TEXT NOT NULL,
  normalized_key TEXT NOT NULL,
  label TEXT NOT NULL DEFAULT '',
  kind TEXT NOT NULL DEFAULT 'firm_value',
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(organization_id, normalized_key)
);
CREATE INDEX IF NOT EXISTS idx_organization_boilerplate_org
  ON organization_boilerplate(organization_id, active, updated_at DESC);

ALTER TABLE organization_boilerplate ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS autodraft_tenant_isolation ON organization_boilerplate;
CREATE POLICY autodraft_tenant_isolation ON organization_boilerplate
USING (
  organization_id = COALESCE(
    NULLIF(current_setting('autodraft.organization_id', true), '')::uuid,
    '00000000-0000-0000-0000-000000000001'::uuid
  )
)
WITH CHECK (
  organization_id = COALESCE(
    NULLIF(current_setting('autodraft.organization_id', true), '')::uuid,
    '00000000-0000-0000-0000-000000000001'::uuid
  )
);
