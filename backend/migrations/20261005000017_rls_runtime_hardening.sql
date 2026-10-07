-- SEC-001 / SEC-002: production RLS/runtime hardening.
--
-- This migration intentionally does not create a login role or embed a password.
-- DATABASE_URL must point at a separately provisioned non-owner, non-superuser,
-- NOBYPASSRLS role. MIGRATION_DATABASE_URL may use the schema owner/migrator.

CREATE OR REPLACE FUNCTION autodraft_current_organization_id()
RETURNS UUID
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
  raw_org TEXT;
BEGIN
  raw_org := NULLIF(current_setting('autodraft.organization_id', true), '');
  IF raw_org IS NULL THEN
    RAISE EXCEPTION 'AutoDraft tenant context is required'
      USING ERRCODE = '42501',
            HINT = 'Set autodraft.organization_id inside the current transaction before accessing tenant-owned data.';
  END IF;
  RETURN raw_org::uuid;
EXCEPTION
  WHEN invalid_text_representation THEN
    RAISE EXCEPTION 'Invalid AutoDraft tenant context'
      USING ERRCODE = '42501';
END;
$$;

-- The historical default organization remains as seeded development data, but
-- tenant-owned rows must no longer acquire it from database column defaults.
ALTER TABLE IF EXISTS matters ALTER COLUMN organization_id DROP DEFAULT;
ALTER TABLE IF EXISTS templates ALTER COLUMN organization_id DROP DEFAULT;
ALTER TABLE IF EXISTS intake_forms ALTER COLUMN organization_id DROP DEFAULT;
ALTER TABLE IF EXISTS matter_documents ALTER COLUMN organization_id DROP DEFAULT;
ALTER TABLE IF EXISTS document_bindings ALTER COLUMN organization_id DROP DEFAULT;
ALTER TABLE IF EXISTS questionnaire_templates ALTER COLUMN organization_id DROP DEFAULT;
ALTER TABLE IF EXISTS intake_sessions ALTER COLUMN organization_id DROP DEFAULT;
ALTER TABLE IF EXISTS derived_fact_rules ALTER COLUMN organization_id DROP DEFAULT;

-- Legacy intake links still need a safe token -> tenant bootstrap before a
-- tenant-scoped query can run. Keep only routing metadata outside tenant RLS.
CREATE TABLE IF NOT EXISTS public_legacy_intake_tokens (
  token TEXT PRIMARY KEY,
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  form_id UUID NOT NULL UNIQUE REFERENCES intake_forms(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
INSERT INTO public_legacy_intake_tokens(token, organization_id, form_id)
SELECT token, organization_id, id FROM intake_forms
ON CONFLICT (token) DO UPDATE
SET organization_id = EXCLUDED.organization_id, form_id = EXCLUDED.form_id;

-- Replace fail-open policies with a fail-closed tenant function and force RLS on
-- every table that already participates in AutoDraft's tenant policy set.
DO $$
DECLARE
  tbl TEXT;
BEGIN
  FOREACH tbl IN ARRAY ARRAY[
    'matters','templates','matter_documents','questionnaire_templates','intake_sessions','document_bindings',
    'organization_boilerplate',
    'practice_areas','matter_stages','contacts','matter_participants','field_groups','field_definitions',
    'matter_field_values','contact_field_values','document_sets','document_set_versions','document_set_items',
    'document_set_drafts','generation_runs','outbox_events',
    'workflows','workflow_versions','workflow_sessions','template_automation_drafts',
    'template_automation_versions','generation_artifacts'
  ] LOOP
    IF to_regclass(tbl) IS NOT NULL THEN
      EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', tbl);
      EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', tbl);
      EXECUTE format('DROP POLICY IF EXISTS autodraft_tenant_isolation ON %I', tbl);
      EXECUTE format(
        'CREATE POLICY autodraft_tenant_isolation ON %I '
        'USING (organization_id = autodraft_current_organization_id()) '
        'WITH CHECK (organization_id = autodraft_current_organization_id())',
        tbl
      );
    END IF;
  END LOOP;
END $$;


-- If the conventional runtime role already exists, grant only application DML
-- privileges. Role creation/password management stays outside migrations.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'autodraft_app') THEN
    EXECUTE 'GRANT USAGE ON SCHEMA public TO autodraft_app';
    EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO autodraft_app';
    EXECUTE 'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO autodraft_app';
    EXECUTE 'GRANT EXECUTE ON FUNCTION autodraft_current_organization_id() TO autodraft_app';
    EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO autodraft_app';
    EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO autodraft_app';
  END IF;
END $$;

COMMENT ON FUNCTION autodraft_current_organization_id() IS
  'Fail-closed tenant accessor used by AutoDraft RLS policies and tenant-owned inserts.';
