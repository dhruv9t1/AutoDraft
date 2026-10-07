-- Centralized authorization/session revocation + shared rate limiting foundations.

ALTER TABLE app_users ADD COLUMN IF NOT EXISTS auth_version BIGINT NOT NULL DEFAULT 1;
UPDATE app_users SET auth_version=1 WHERE auth_version IS NULL OR auth_version < 1;

CREATE OR REPLACE FUNCTION autodraft_bump_auth_version_on_identity_change()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.role IS DISTINCT FROM OLD.role OR NEW.active IS DISTINCT FROM OLD.active THEN
    NEW.auth_version := GREATEST(1, OLD.auth_version + 1);
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_app_users_bump_auth_version ON app_users;
CREATE TRIGGER trg_app_users_bump_auth_version
BEFORE UPDATE OF role, active ON app_users
FOR EACH ROW EXECUTE FUNCTION autodraft_bump_auth_version_on_identity_change();

CREATE TABLE IF NOT EXISTS security_rate_limit_buckets (
  key_hash TEXT NOT NULL,
  window_start TIMESTAMPTZ NOT NULL,
  request_count INTEGER NOT NULL DEFAULT 0 CHECK (request_count >= 0),
  expires_at TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (key_hash, window_start)
);
CREATE INDEX IF NOT EXISTS idx_security_rate_limit_buckets_expiry ON security_rate_limit_buckets(expires_at);
