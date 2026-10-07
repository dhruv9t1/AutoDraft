-- Runtime queue completion: user ownership, external blob metadata, quotas and
-- cluster-wide worker admission. Large payload/blob/chunk bodies are no longer
-- persisted in PostgreSQL by new application code.

ALTER TABLE runtime_jobs ADD COLUMN IF NOT EXISTS owner_user_id UUID;
ALTER TABLE runtime_jobs ADD COLUMN IF NOT EXISTS payload_object_key TEXT;
ALTER TABLE runtime_jobs ADD COLUMN IF NOT EXISTS payload_bytes BIGINT NOT NULL DEFAULT 0;
ALTER TABLE runtime_jobs ADD COLUMN IF NOT EXISTS input_object_key TEXT;
ALTER TABLE runtime_jobs ADD COLUMN IF NOT EXISTS input_bytes BIGINT NOT NULL DEFAULT 0;
ALTER TABLE runtime_jobs ADD COLUMN IF NOT EXISTS result_object_key TEXT;
ALTER TABLE runtime_jobs ADD COLUMN IF NOT EXISTS result_bytes BIGINT NOT NULL DEFAULT 0;
ALTER TABLE runtime_jobs ADD COLUMN IF NOT EXISTS output_object_key TEXT;
ALTER TABLE runtime_jobs ADD COLUMN IF NOT EXISTS output_bytes BIGINT NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_runtime_jobs_owner ON runtime_jobs(organization_id,owner_user_id,created_at DESC);

ALTER TABLE runtime_job_events ADD COLUMN IF NOT EXISTS object_key TEXT;
ALTER TABLE runtime_job_events ADD COLUMN IF NOT EXISTS byte_length BIGINT NOT NULL DEFAULT 0;

ALTER TABLE runtime_chunk_sessions ADD COLUMN IF NOT EXISTS owner_user_id UUID;
CREATE INDEX IF NOT EXISTS idx_runtime_chunk_sessions_owner ON runtime_chunk_sessions(organization_id,owner_user_id,expires_at);

ALTER TABLE runtime_chunks ADD COLUMN IF NOT EXISTS object_key TEXT;
-- Legacy rows may still have content populated. New writes use object_key and
-- leave content NULL so chunk bodies do not amplify WAL/backups.
ALTER TABLE runtime_chunks ALTER COLUMN content DROP NOT NULL;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_runtime_jobs_owner_tenant') THEN
    ALTER TABLE runtime_jobs ADD CONSTRAINT fk_runtime_jobs_owner_tenant
      FOREIGN KEY (organization_id,owner_user_id) REFERENCES app_users(organization_id,id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_runtime_chunk_sessions_owner_tenant') THEN
    ALTER TABLE runtime_chunk_sessions ADD CONSTRAINT fk_runtime_chunk_sessions_owner_tenant
      FOREIGN KEY (organization_id,owner_user_id) REFERENCES app_users(organization_id,id);
  END IF;
END $$;

-- Existing in-flight rows predate user ownership. Leave them inaccessible to
-- user-facing owner-filtered APIs; workers may finish them through internal
-- queue access. New rows always supply owner_user_id.

DROP FUNCTION IF EXISTS autodraft_claim_runtime_job(TEXT,INTEGER);

CREATE OR REPLACE FUNCTION autodraft_claim_runtime_job(
  p_worker_id TEXT,
  p_lease_seconds INTEGER DEFAULT 90,
  p_cluster_concurrency INTEGER DEFAULT 4
)
RETURNS TABLE(job_id UUID, organization_id UUID, job_type TEXT)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE selected_id UUID;
DECLARE active_count INTEGER;
BEGIN
  IF NOT has_table_privilege(session_user,'public.runtime_jobs','SELECT,UPDATE') THEN
    RAISE EXCEPTION 'runtime worker role lacks runtime_jobs privileges' USING ERRCODE='42501';
  END IF;

  -- Serialize admission so concurrent API/worker processes cannot all observe
  -- the same available slot and exceed cluster-wide OCR/AI concurrency.
  PERFORM pg_advisory_xact_lock(hashtext('autodraft:runtime:claim'));
  SELECT COUNT(*)::int INTO active_count
    FROM public.runtime_jobs j
   WHERE j.status='running'
     AND COALESCE(j.lease_expires_at,'-infinity'::timestamptz) >= NOW();
  IF active_count >= GREATEST(1,p_cluster_concurrency) THEN RETURN; END IF;

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

CREATE OR REPLACE FUNCTION autodraft_expired_runtime_object_keys()
RETURNS SETOF TEXT
LANGUAGE sql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
  SELECT key FROM (
    SELECT payload_object_key AS key FROM public.runtime_jobs WHERE expires_at<NOW() AND status IN ('completed','failed','cancelled')
    UNION ALL SELECT input_object_key FROM public.runtime_jobs WHERE expires_at<NOW() AND status IN ('completed','failed','cancelled')
    UNION ALL SELECT result_object_key FROM public.runtime_jobs WHERE expires_at<NOW() AND status IN ('completed','failed','cancelled')
    UNION ALL SELECT output_object_key FROM public.runtime_jobs WHERE expires_at<NOW() AND status IN ('completed','failed','cancelled')
    UNION ALL
    SELECT e.object_key FROM public.runtime_job_events e
      JOIN public.runtime_jobs j ON j.organization_id=e.organization_id AND j.id=e.job_id
     WHERE j.expires_at<NOW() AND j.status IN ('completed','failed','cancelled')
    UNION ALL
    SELECT c.object_key FROM public.runtime_chunks c
      JOIN public.runtime_chunk_sessions s ON s.organization_id=c.organization_id AND s.id=c.session_id
     WHERE s.expires_at<NOW()
  ) q WHERE key IS NOT NULL;
$$;

GRANT EXECUTE ON FUNCTION autodraft_claim_runtime_job(TEXT,INTEGER,INTEGER) TO PUBLIC;
GRANT EXECUTE ON FUNCTION autodraft_expired_runtime_object_keys() TO PUBLIC;
