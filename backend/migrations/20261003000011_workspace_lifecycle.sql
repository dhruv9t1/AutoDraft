-- AutoDraft vNext workspace lifecycle improvements.
-- Adds soft-delete/archive support without invalidating existing document/template IDs.

ALTER TABLE templates ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_templates_active_created_at
  ON templates(created_at DESC)
  WHERE deleted_at IS NULL;

ALTER TABLE matters ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_matters_active_updated_at
  ON matters(updated_at DESC)
  WHERE archived_at IS NULL;

ALTER TABLE matter_facts ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
