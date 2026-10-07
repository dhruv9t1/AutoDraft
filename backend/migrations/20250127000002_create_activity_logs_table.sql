-- Migration: Create activity_logs table
-- Following NestJS architecture pattern from 02-ai-variable-identification-architecture-summary.md
-- Created: 2025-01-27

-- Note: This migration assumes a documents/templates table exists
-- If not, you may need to create it first or adjust the foreign key constraint

CREATE TABLE IF NOT EXISTS activity_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id UUID, -- Made nullable initially - adjust if documents table exists
  template_id UUID, -- Added for template-based activity logging
  action_type VARCHAR(100) NOT NULL,
  details JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_activity_logs_document_id ON activity_logs(document_id);
CREATE INDEX IF NOT EXISTS idx_activity_logs_template_id ON activity_logs(template_id);
CREATE INDEX IF NOT EXISTS idx_activity_logs_created_at ON activity_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_activity_logs_action_type ON activity_logs(action_type);

-- Add comment
COMMENT ON TABLE activity_logs IS 'Stores activity logs for tracking user actions and AI processing history';
