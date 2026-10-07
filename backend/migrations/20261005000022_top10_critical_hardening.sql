-- AutoDraft v1.3 critical hardening consolidation.
-- 1) Hash public intake bearer tokens at rest.
-- 2) Make authority verification server/lawyer controlled.
-- 3) Add Entra/Office identity bootstrap mapping without storing access tokens.
-- 4) Add durable generation idempotency/attempt history.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ---------------------------------------------------------------------------
-- Intake bearer-token hashing. Public routing tables intentionally remain
-- outside tenant RLS, but now contain only non-reversible SHA-256 token hashes.
-- ---------------------------------------------------------------------------
ALTER TABLE intake_sessions ADD COLUMN IF NOT EXISTS token_hash TEXT;
UPDATE intake_sessions
SET token_hash = encode(digest(token, 'sha256'), 'hex')
WHERE token_hash IS NULL AND token IS NOT NULL;
ALTER TABLE intake_sessions ALTER COLUMN token_hash SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_intake_sessions_token_hash ON intake_sessions(token_hash);

ALTER TABLE intake_forms ADD COLUMN IF NOT EXISTS token_hash TEXT;
UPDATE intake_forms
SET token_hash = encode(digest(token, 'sha256'), 'hex')
WHERE token_hash IS NULL AND token IS NOT NULL;
ALTER TABLE intake_forms ALTER COLUMN token_hash SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_intake_forms_token_hash ON intake_forms(token_hash);

CREATE TABLE IF NOT EXISTS public_intake_token_hashes (
  token_hash TEXT PRIMARY KEY,
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  session_id UUID NOT NULL UNIQUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT fk_public_intake_hash_session_tenant
    FOREIGN KEY (organization_id, session_id)
    REFERENCES intake_sessions(organization_id, id) ON DELETE CASCADE
);
INSERT INTO public_intake_token_hashes(token_hash, organization_id, session_id)
SELECT token_hash, organization_id, id FROM intake_sessions
ON CONFLICT (token_hash) DO UPDATE
SET organization_id=EXCLUDED.organization_id, session_id=EXCLUDED.session_id;

CREATE TABLE IF NOT EXISTS public_legacy_intake_token_hashes (
  token_hash TEXT PRIMARY KEY,
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  form_id UUID NOT NULL UNIQUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT fk_public_legacy_intake_hash_form_tenant
    FOREIGN KEY (organization_id, form_id)
    REFERENCES intake_forms(organization_id, id) ON DELETE CASCADE
);
INSERT INTO public_legacy_intake_token_hashes(token_hash, organization_id, form_id)
SELECT token_hash, organization_id, id FROM intake_forms
ON CONFLICT (token_hash) DO UPDATE
SET organization_id=EXCLUDED.organization_id, form_id=EXCLUDED.form_id;

-- Remove every persisted raw bearer token after the hash routing tables exist.
DROP TABLE IF EXISTS public_intake_tokens CASCADE;
DROP TABLE IF EXISTS public_legacy_intake_tokens CASCADE;
ALTER TABLE intake_sessions DROP CONSTRAINT IF EXISTS intake_sessions_token_key;
DROP INDEX IF EXISTS idx_intake_sessions_token;
ALTER TABLE intake_sessions DROP COLUMN IF EXISTS token;
ALTER TABLE intake_forms DROP CONSTRAINT IF EXISTS intake_forms_token_key;
DROP INDEX IF EXISTS idx_intake_forms_token;
ALTER TABLE intake_forms DROP COLUMN IF EXISTS token;

-- ---------------------------------------------------------------------------
-- Per-user Office/Entra bootstrap mapping. The table contains no access tokens;
-- the subject is an Entra tenant/object-id pair established by an admin.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public_user_identities (
  provider TEXT NOT NULL CHECK (provider IN ('entra')),
  subject TEXT NOT NULL,
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  user_id UUID NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY(provider, subject),
  CONSTRAINT fk_public_user_identity_user_tenant
    FOREIGN KEY (organization_id, user_id)
    REFERENCES app_users(organization_id, id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_public_user_identities_user
  ON public_user_identities(organization_id, user_id);

-- ---------------------------------------------------------------------------
-- Authority verification is a controlled state transition. Existing booleans
-- are reset because prior clients were allowed to submit verified=true.
-- ---------------------------------------------------------------------------
ALTER TABLE matter_authorities ADD COLUMN IF NOT EXISTS verification_status TEXT NOT NULL DEFAULT 'unverified'
  CHECK (verification_status IN ('unverified','source_matched','lawyer_verified','rejected'));
ALTER TABLE matter_authorities ADD COLUMN IF NOT EXISTS verified_by_user_id UUID;
ALTER TABLE matter_authorities ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ;
ALTER TABLE matter_authorities ADD COLUMN IF NOT EXISTS verification_evidence JSONB NOT NULL DEFAULT '{}'::jsonb;
UPDATE matter_authorities
SET verified=FALSE,
    verification_status='unverified',
    verified_by_user_id=NULL,
    verified_at=NULL,
    verification_evidence='{}'::jsonb;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_matter_authorities_verifier_tenant') THEN
    ALTER TABLE matter_authorities
      ADD CONSTRAINT fk_matter_authorities_verifier_tenant
      FOREIGN KEY (organization_id, verified_by_user_id)
      REFERENCES app_users(organization_id, id);
  END IF;
END $$;

-- ---------------------------------------------------------------------------
-- Authoritative generation idempotency and immutable attempt history.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS generation_attempts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  idempotency_key TEXT NOT NULL,
  request_fingerprint TEXT NOT NULL,
  generation_run_id UUID REFERENCES generation_runs(id) ON DELETE SET NULL,
  status TEXT NOT NULL DEFAULT 'processing' CHECK (status IN ('processing','completed','failed')),
  artifact_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
  response_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  error TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(organization_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_generation_attempts_run ON generation_attempts(generation_run_id, created_at DESC);
ALTER TABLE generation_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE generation_attempts FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS autodraft_tenant_isolation ON generation_attempts;
CREATE POLICY autodraft_tenant_isolation ON generation_attempts
  USING (organization_id = autodraft_current_organization_id())
  WITH CHECK (organization_id = autodraft_current_organization_id());

CREATE UNIQUE INDEX IF NOT EXISTS uq_generation_attempts_org_id
  ON generation_attempts(organization_id,id);
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_generation_attempt_run_tenant') THEN
    ALTER TABLE generation_attempts
      ADD CONSTRAINT fk_generation_attempt_run_tenant
      FOREIGN KEY (organization_id,generation_run_id)
      REFERENCES generation_runs(organization_id,id);
  END IF;
END $$;
