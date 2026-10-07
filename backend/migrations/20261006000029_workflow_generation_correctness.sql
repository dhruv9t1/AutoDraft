-- Workflow/generation correctness hardening (issues 16-23).
-- Keep generation retries as first-class immutable attempts instead of reusing
-- and overwriting one row for an idempotency key.

ALTER TABLE generation_attempts
  ADD COLUMN IF NOT EXISTS retry_of_attempt_id UUID,
  ADD COLUMN IF NOT EXISTS attempt_number INTEGER NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS finished_at TIMESTAMPTZ;

UPDATE generation_attempts
SET started_at = COALESCE(started_at, created_at),
    finished_at = CASE
      WHEN status IN ('completed','failed') THEN COALESCE(finished_at, updated_at, created_at)
      ELSE NULL
    END
WHERE started_at IS NULL
   OR (status IN ('completed','failed') AND finished_at IS NULL);

ALTER TABLE generation_attempts
  ALTER COLUMN started_at SET DEFAULT NOW(),
  ALTER COLUMN started_at SET NOT NULL;

-- The original schema allowed only one row per idempotency key.  History now
-- uses one row per attempt; application-level advisory locking serializes retries.
DO $$
DECLARE c RECORD;
BEGIN
  FOR c IN
    SELECT conname
    FROM pg_constraint
    WHERE conrelid = 'generation_attempts'::regclass
      AND contype = 'u'
      AND pg_get_constraintdef(oid) LIKE '%(organization_id, idempotency_key)%'
  LOOP
    EXECUTE format('ALTER TABLE generation_attempts DROP CONSTRAINT %I', c.conname);
  END LOOP;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_generation_attempt_number
  ON generation_attempts(organization_id,idempotency_key,attempt_number);
CREATE INDEX IF NOT EXISTS idx_generation_attempt_history
  ON generation_attempts(organization_id,idempotency_key,attempt_number DESC,created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_generation_attempt_one_processing
  ON generation_attempts(organization_id,idempotency_key)
  WHERE status='processing';

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_generation_attempt_retry_tenant') THEN
    ALTER TABLE generation_attempts
      ADD CONSTRAINT fk_generation_attempt_retry_tenant
      FOREIGN KEY (organization_id,retry_of_attempt_id)
      REFERENCES generation_attempts(organization_id,id);
  END IF;
END $$;

-- Once an attempt has reached a terminal state its provenance is immutable.
CREATE OR REPLACE FUNCTION autodraft_generation_attempt_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.status IN ('completed','failed') THEN
    RAISE EXCEPTION 'generation attempt % is immutable after terminal state', OLD.id;
  END IF;
  IF NEW.organization_id IS DISTINCT FROM OLD.organization_id
     OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
     OR NEW.request_fingerprint IS DISTINCT FROM OLD.request_fingerprint
     OR NEW.generation_run_id IS DISTINCT FROM OLD.generation_run_id
     OR NEW.retry_of_attempt_id IS DISTINCT FROM OLD.retry_of_attempt_id
     OR NEW.attempt_number IS DISTINCT FROM OLD.attempt_number
     OR NEW.created_at IS DISTINCT FROM OLD.created_at
     OR NEW.started_at IS DISTINCT FROM OLD.started_at THEN
    RAISE EXCEPTION 'generation attempt identity/provenance is immutable';
  END IF;
  IF NEW.status IN ('completed','failed') AND NEW.finished_at IS NULL THEN
    NEW.finished_at := NOW();
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_generation_attempt_guard ON generation_attempts;
CREATE TRIGGER trg_generation_attempt_guard
BEFORE UPDATE ON generation_attempts
FOR EACH ROW EXECUTE FUNCTION autodraft_generation_attempt_guard();
