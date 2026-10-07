-- Medium-audit privacy hardening.
-- Webhook receiver bodies are third-party data and are no longer retained.
-- Clear historical excerpts and enforce that future attempts keep the field NULL.

UPDATE webhook_delivery_attempts
SET response_excerpt = NULL
WHERE response_excerpt IS NOT NULL;

ALTER TABLE webhook_delivery_attempts
  DROP CONSTRAINT IF EXISTS ck_webhook_attempts_no_response_body;
ALTER TABLE webhook_delivery_attempts
  ADD CONSTRAINT ck_webhook_attempts_no_response_body
  CHECK (response_excerpt IS NULL);

COMMENT ON COLUMN webhook_delivery_attempts.response_excerpt IS
  'Reserved compatibility column. Receiver response bodies are intentionally never persisted.';
