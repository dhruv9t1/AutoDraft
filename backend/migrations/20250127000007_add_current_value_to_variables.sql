-- Add current_value column to variables table to persist user-filled values
-- This allows resuming form filling after navigating away or page reload
ALTER TABLE variables ADD COLUMN IF NOT EXISTS current_value TEXT;
