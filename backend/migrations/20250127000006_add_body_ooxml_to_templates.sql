-- Migration: Add body_ooxml to templates table
-- Stores OOXML (Office Open XML) of the document body for template apply flow
-- Created: 2025-01-27

ALTER TABLE templates
  ADD COLUMN IF NOT EXISTS body_ooxml TEXT;

COMMENT ON COLUMN templates.body_ooxml IS 'OOXML of document body for inserting template into Word via body.insertOoxml()';
