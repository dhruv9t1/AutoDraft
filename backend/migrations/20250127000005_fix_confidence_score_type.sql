-- Migration: Fix confidence_score column type
-- Created: 2025-01-27
-- Purpose: Change confidence_score from DECIMAL(5,2) to DOUBLE PRECISION to support floating-point confidence scores

-- Convert DECIMAL to DOUBLE PRECISION
-- This allows sqlx to properly decode the column as Option<f64>
ALTER TABLE variables
ALTER COLUMN confidence_score TYPE DOUBLE PRECISION
USING confidence_score::DOUBLE PRECISION;

-- Add comment
COMMENT ON COLUMN variables.confidence_score IS 
'Confidence score for variable identification (0.0 to 1.0), stored as DOUBLE PRECISION to support floating-point confidence scores';
