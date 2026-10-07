-- Public intake/workflow hardening (items 36-41): content-based upload
-- validation metadata, quarantine storage, and quota-supporting indexes.

ALTER TABLE intake_files ADD COLUMN IF NOT EXISTS declared_mime TEXT;
ALTER TABLE intake_files ADD COLUMN IF NOT EXISTS detected_mime TEXT;
ALTER TABLE intake_files ADD COLUMN IF NOT EXISTS scan_status TEXT NOT NULL DEFAULT 'legacy_unscanned';
ALTER TABLE intake_files ADD COLUMN IF NOT EXISTS scan_engine TEXT NOT NULL DEFAULT '';

UPDATE intake_files
SET declared_mime = COALESCE(declared_mime, mime_type),
    detected_mime = COALESCE(detected_mime, mime_type)
WHERE declared_mime IS NULL OR detected_mime IS NULL;

CREATE INDEX IF NOT EXISTS idx_intake_files_org_created
  ON intake_files(organization_id, created_at);
CREATE INDEX IF NOT EXISTS idx_intake_files_session_created
  ON intake_files(organization_id, session_id, created_at);

CREATE TABLE IF NOT EXISTS intake_file_quarantine (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL DEFAULT autodraft_current_organization_id(),
  session_id UUID NOT NULL,
  question_id UUID NOT NULL,
  filename TEXT NOT NULL,
  declared_mime TEXT NOT NULL DEFAULT 'application/octet-stream',
  detected_mime TEXT,
  size_bytes BIGINT NOT NULL CHECK(size_bytes >= 0),
  sha256 TEXT NOT NULL,
  reason TEXT NOT NULL,
  scan_status TEXT NOT NULL,
  scan_engine TEXT NOT NULL DEFAULT '',
  content BYTEA NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT fk_intake_quarantine_session_tenant
    FOREIGN KEY (organization_id, session_id)
    REFERENCES intake_sessions(organization_id, id) ON DELETE CASCADE,
  CONSTRAINT fk_intake_quarantine_question_tenant
    FOREIGN KEY (organization_id, question_id)
    REFERENCES questionnaire_questions(organization_id, id)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_intake_file_quarantine_org_id
  ON intake_file_quarantine(organization_id, id);
CREATE INDEX IF NOT EXISTS idx_intake_file_quarantine_org_created
  ON intake_file_quarantine(organization_id, created_at);
CREATE INDEX IF NOT EXISTS idx_intake_file_quarantine_session_created
  ON intake_file_quarantine(organization_id, session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_intake_file_quarantine_sha
  ON intake_file_quarantine(organization_id, sha256);

ALTER TABLE intake_file_quarantine ENABLE ROW LEVEL SECURITY;
ALTER TABLE intake_file_quarantine FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS autodraft_tenant_isolation ON intake_file_quarantine;
CREATE POLICY autodraft_tenant_isolation ON intake_file_quarantine
  USING (organization_id = autodraft_current_organization_id())
  WITH CHECK (organization_id = autodraft_current_organization_id());

COMMENT ON TABLE intake_file_quarantine IS
  'Restricted tenant-owned quarantine for rejected/unverified public intake uploads; no public or normal download route exposes this content.';
