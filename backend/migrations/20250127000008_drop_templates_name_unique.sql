-- Migration: Allow duplicate template names
-- Created: 2026-04-19

ALTER TABLE templates DROP CONSTRAINT IF EXISTS templates_name_key;
