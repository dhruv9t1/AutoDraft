-- Runtime hardening discovered during the deep release audit.
--
-- Public intake requests intentionally do not carry an authenticated tenant
-- context. Keep a minimal token -> tenant/session lookup outside tenant RLS so
-- the server can establish the correct organization GUC before reading the
-- protected intake session. The token itself is already a 192-bit URL-safe
-- bearer secret and is stored on intake_sessions for backwards compatibility.
CREATE TABLE IF NOT EXISTS public_intake_tokens (
  token TEXT PRIMARY KEY,
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  session_id UUID NOT NULL UNIQUE REFERENCES intake_sessions(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO public_intake_tokens(token, organization_id, session_id)
SELECT token, organization_id, id
FROM intake_sessions
ON CONFLICT (token) DO UPDATE
SET organization_id = EXCLUDED.organization_id,
    session_id = EXCLUDED.session_id;

CREATE INDEX IF NOT EXISTS idx_public_intake_tokens_org
  ON public_intake_tokens(organization_id);

-- A single file question represents one current response. Retries replace the
-- previous upload instead of silently accumulating inaccessible duplicate blobs.
DELETE FROM intake_files a
USING intake_files b
WHERE a.session_id=b.session_id
  AND a.question_id=b.question_id
  AND (a.created_at < b.created_at OR (a.created_at=b.created_at AND a.id < b.id));

CREATE UNIQUE INDEX IF NOT EXISTS uq_intake_files_session_question
  ON intake_files(session_id, question_id);
