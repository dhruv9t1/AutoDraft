CREATE TABLE IF NOT EXISTS intake_forms(id UUID PRIMARY KEY DEFAULT gen_random_uuid(),token TEXT UNIQUE NOT NULL,title TEXT NOT NULL,matter_type TEXT NOT NULL DEFAULT '',questions JSONB NOT NULL DEFAULT '[]'::jsonb,answers JSONB,template_id TEXT,created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),submitted_at TIMESTAMPTZ);
CREATE INDEX IF NOT EXISTS idx_intake_forms_token ON intake_forms(token);
