-- Stable Word binding IDs and matter workspace persistence.

ALTER TABLE variables ADD COLUMN IF NOT EXISTS binding_id UUID;
UPDATE variables SET binding_id = gen_random_uuid() WHERE binding_id IS NULL;
ALTER TABLE variables ALTER COLUMN binding_id SET DEFAULT gen_random_uuid();
CREATE UNIQUE INDEX IF NOT EXISTS idx_variables_template_binding_id
  ON variables(template_id, binding_id)
  WHERE template_id IS NOT NULL;

ALTER TABLE intake_forms ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;
ALTER TABLE intake_forms ADD COLUMN IF NOT EXISTS revoked_at TIMESTAMPTZ;
UPDATE intake_forms
SET expires_at = COALESCE(expires_at, created_at + INTERVAL '7 days');

CREATE TABLE IF NOT EXISTS matters (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  title TEXT NOT NULL,
  matter_type TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'open',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_matters_created_at ON matters(created_at DESC);

CREATE TABLE IF NOT EXISTS matter_facts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  matter_id UUID NOT NULL REFERENCES matters(id) ON DELETE CASCADE,
  field TEXT NOT NULL,
  fact TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'user',
  status TEXT NOT NULL DEFAULT 'client_claim',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_matter_facts_matter_id ON matter_facts(matter_id);

CREATE TABLE IF NOT EXISTS matter_authorities (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  matter_id UUID NOT NULL REFERENCES matters(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  citation TEXT NOT NULL DEFAULT '',
  source_url TEXT NOT NULL DEFAULT '',
  verified BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_matter_authorities_matter_id ON matter_authorities(matter_id);

CREATE TABLE IF NOT EXISTS audit_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  matter_id UUID REFERENCES matters(id) ON DELETE SET NULL,
  event_type TEXT NOT NULL,
  details JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_audit_events_matter_id ON audit_events(matter_id);
CREATE INDEX IF NOT EXISTS idx_audit_events_created_at ON audit_events(created_at DESC);
