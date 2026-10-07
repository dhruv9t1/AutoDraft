-- SEC-004: derived_fact_rules is organization-owned and must be isolated exactly
-- like the rest of AutoDraft's tenant data.

ALTER TABLE derived_fact_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE derived_fact_rules FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS autodraft_tenant_isolation ON derived_fact_rules;
CREATE POLICY autodraft_tenant_isolation ON derived_fact_rules
  USING (organization_id = autodraft_current_organization_id())
  WITH CHECK (organization_id = autodraft_current_organization_id());

-- The unique constraint was introduced with the table and intentionally includes
-- organization_id. Keep a named defensive index as migration-time verification
-- and for efficient tenant/key lookups on databases upgraded from old snapshots.
CREATE UNIQUE INDEX IF NOT EXISTS uq_derived_fact_rules_org_fact_key
  ON derived_fact_rules(organization_id, fact_key);

COMMENT ON TABLE derived_fact_rules IS
  'Organization-owned derived fact rules protected by forced row-level security.';
