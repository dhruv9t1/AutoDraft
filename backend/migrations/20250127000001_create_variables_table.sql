-- Migration: Create variables table
-- Following NestJS architecture pattern from 02-ai-variable-identification-architecture-summary.md
-- Created: 2025-01-27

-- Note: This migration assumes a documents/templates table exists
-- If not, you may need to create it first or adjust the foreign key constraint

CREATE TABLE IF NOT EXISTS variables (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id UUID, -- Made nullable initially - adjust if documents table exists
  template_id UUID, -- Added for template-based variable storage
  variable_name VARCHAR(255) NOT NULL,
  original_text TEXT NOT NULL,
  position INTEGER NOT NULL,
  confidence_score DECIMAL(5,2),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_variables_document_id ON variables(document_id);
CREATE INDEX IF NOT EXISTS idx_variables_template_id ON variables(template_id);
CREATE INDEX IF NOT EXISTS idx_variables_position ON variables(position);

-- Add comment
COMMENT ON TABLE variables IS 'Stores variables identified by AI in documents/templates';
