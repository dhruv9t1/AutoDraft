-- RUNTIME-001: durable, cross-worker runtime state and queue.
-- API-facing access remains tenant-scoped by RLS. Worker claim/prune functions
-- are SECURITY DEFINER because they must select one job across all tenants; they
-- return only job identity/tenant/type, never legal-document payloads.

CREATE TABLE IF NOT EXISTS runtime_jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  job_type TEXT NOT NULL CHECK (job_type IN ('extraction','ocr')),
  status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','completed','failed','cancelled')),
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  result JSONB,
  error TEXT,
  input_blob BYTEA,
  input_filename TEXT,
  input_suffix TEXT,
  output_blob BYTEA,
  cancel_requested BOOLEAN NOT NULL DEFAULT FALSE,
  lease_owner TEXT,
  lease_expires_at TIMESTAMPTZ,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  expires_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '1 hour'),
  UNIQUE (organization_id,id)
);
CREATE INDEX IF NOT EXISTS idx_runtime_jobs_claim
  ON runtime_jobs(status,lease_expires_at,created_at)
  WHERE status IN ('queued','running');
CREATE INDEX IF NOT EXISTS idx_runtime_jobs_org_created
  ON runtime_jobs(organization_id,created_at DESC);

CREATE TABLE IF NOT EXISTS runtime_job_events (
  id BIGSERIAL PRIMARY KEY,
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  job_id UUID NOT NULL,
  event_type TEXT NOT NULL,
  data JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT fk_runtime_job_events_job_tenant
    FOREIGN KEY (organization_id,job_id)
    REFERENCES runtime_jobs(organization_id,id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_runtime_job_events_job
  ON runtime_job_events(organization_id,job_id,id);

CREATE TABLE IF NOT EXISTS runtime_chunk_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  session_kind TEXT NOT NULL CHECK (session_kind IN ('document','template_ooxml')),
  resource_id TEXT,
  total_chunks INTEGER NOT NULL CHECK (total_chunks > 0 AND total_chunks <= 10000),
  expected_total_size BIGINT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  expires_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '1 hour'),
  UNIQUE (organization_id,id)
);
CREATE INDEX IF NOT EXISTS idx_runtime_chunk_sessions_expiry ON runtime_chunk_sessions(expires_at);

CREATE TABLE IF NOT EXISTS runtime_chunks (
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  session_id UUID NOT NULL,
  chunk_index INTEGER NOT NULL CHECK (chunk_index >= 0),
  content TEXT NOT NULL,
  byte_length BIGINT NOT NULL CHECK (byte_length >= 0),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (organization_id,session_id,chunk_index),
  CONSTRAINT fk_runtime_chunks_session_tenant
    FOREIGN KEY (organization_id,session_id)
    REFERENCES runtime_chunk_sessions(organization_id,id) ON DELETE CASCADE
);

-- Runtime queue infrastructure deliberately uses ENABLE (not FORCE) RLS so the
-- migration-owner SECURITY DEFINER claim/prune functions can recover work across
-- tenants. The normal runtime role is non-owner/NOBYPASSRLS (SEC-001), so direct
-- application access still remains tenant-filtered.
DO $$
DECLARE tbl TEXT;
BEGIN
  FOREACH tbl IN ARRAY ARRAY['runtime_jobs','runtime_job_events','runtime_chunk_sessions','runtime_chunks'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', tbl);
    EXECUTE format('DROP POLICY IF EXISTS autodraft_tenant_isolation ON %I', tbl);
    EXECUTE format(
      'CREATE POLICY autodraft_tenant_isolation ON %I USING (organization_id = autodraft_current_organization_id()) WITH CHECK (organization_id = autodraft_current_organization_id())',
      tbl
    );
  END LOOP;
END $$;

CREATE OR REPLACE FUNCTION autodraft_claim_runtime_job(p_worker_id TEXT, p_lease_seconds INTEGER DEFAULT 90)
RETURNS TABLE(job_id UUID, organization_id UUID, job_type TEXT)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE selected_id UUID;
BEGIN
  IF NOT has_table_privilege(session_user,'public.runtime_jobs','SELECT,UPDATE') THEN
    RAISE EXCEPTION 'runtime worker role lacks runtime_jobs privileges' USING ERRCODE='42501';
  END IF;
  SELECT j.id INTO selected_id
  FROM public.runtime_jobs j
  WHERE j.cancel_requested=FALSE
    AND (
      j.status='queued'
      OR (j.status='running' AND COALESCE(j.lease_expires_at,'-infinity'::timestamptz) < NOW())
    )
  ORDER BY j.created_at,j.id
  FOR UPDATE SKIP LOCKED
  LIMIT 1;
  IF selected_id IS NULL THEN RETURN; END IF;

  RETURN QUERY
  UPDATE public.runtime_jobs j
  SET status='running',
      lease_owner=p_worker_id,
      lease_expires_at=NOW() + make_interval(secs => GREATEST(10,p_lease_seconds)),
      attempt_count=j.attempt_count+1,
      updated_at=NOW()
  WHERE j.id=selected_id
  RETURNING j.id,j.organization_id,j.job_type;
END;
$$;

CREATE OR REPLACE FUNCTION autodraft_prune_runtime_state()
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
  IF NOT has_table_privilege(session_user,'public.runtime_jobs','DELETE') THEN
    RAISE EXCEPTION 'runtime worker role lacks runtime state privileges' USING ERRCODE='42501';
  END IF;
  DELETE FROM public.runtime_jobs
   WHERE expires_at < NOW()
     AND status IN ('completed','failed','cancelled');
  DELETE FROM public.runtime_chunk_sessions WHERE expires_at < NOW();
END;
$$;

-- EXECUTE remains available to database roles, but both functions additionally
-- require the caller to hold the relevant runtime_jobs table privileges. This
-- supports custom non-owner runtime role names without exposing job payloads.
GRANT EXECUTE ON FUNCTION autodraft_claim_runtime_job(TEXT,INTEGER) TO PUBLIC;
GRANT EXECUTE ON FUNCTION autodraft_prune_runtime_state() TO PUBLIC;
