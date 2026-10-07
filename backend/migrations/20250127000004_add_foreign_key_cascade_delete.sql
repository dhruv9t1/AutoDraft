-- Migration: Add foreign key constraint with CASCADE DELETE (idempotent)
-- Existing SQLx/Python installations may already have this constraint.

DELETE FROM variables
WHERE template_id IS NOT NULL
AND template_id NOT IN (SELECT id FROM templates);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'fk_variables_template_id'
      AND conrelid = 'variables'::regclass
  ) THEN
    ALTER TABLE variables
      ADD CONSTRAINT fk_variables_template_id
      FOREIGN KEY (template_id)
      REFERENCES templates(id)
      ON DELETE CASCADE;
  END IF;
END $$;

COMMENT ON CONSTRAINT fk_variables_template_id ON variables IS
'Foreign key constraint ensuring cascade delete: deleting a template automatically deletes all associated variables';
