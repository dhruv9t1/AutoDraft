-- Complete webhook/outbox delivery subsystem: endpoint registry, durable delivery
-- attempts, leasing, retries/backoff, dead-letter state and idempotency keys.

CREATE TABLE IF NOT EXISTS webhook_endpoints (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  url TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  event_types JSONB NOT NULL DEFAULT '[]'::jsonb,
  secret_ciphertext TEXT NOT NULL,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created_by_user_id UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (organization_id,id),
  CHECK (jsonb_typeof(event_types)='array')
);

CREATE TABLE IF NOT EXISTS webhook_deliveries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  event_id UUID NOT NULL,
  endpoint_id UUID NOT NULL,
  idempotency_key TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','leased','delivered','dead')),
  attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
  available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  lease_owner TEXT,
  lease_expires_at TIMESTAMPTZ,
  last_http_status INTEGER,
  last_error TEXT,
  delivered_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (organization_id,event_id,endpoint_id),
  UNIQUE (idempotency_key)
);

CREATE TABLE IF NOT EXISTS webhook_delivery_attempts (
  id BIGSERIAL PRIMARY KEY,
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  delivery_id UUID NOT NULL,
  attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
  requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  completed_at TIMESTAMPTZ,
  http_status INTEGER,
  error TEXT,
  response_excerpt TEXT,
  UNIQUE (organization_id,delivery_id,attempt_number)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_outbox_events_org_id ON outbox_events(organization_id,id);
-- Required target for the composite FK from webhook_delivery_attempts (organization_id,delivery_id).
CREATE UNIQUE INDEX IF NOT EXISTS uq_webhook_deliveries_org_id ON webhook_deliveries(organization_id,id);
CREATE INDEX IF NOT EXISTS idx_webhook_endpoints_org_active ON webhook_endpoints(organization_id,active,created_at);
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_ready ON webhook_deliveries(status,available_at,lease_expires_at,created_at);
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_event ON webhook_deliveries(organization_id,event_id,status);
CREATE INDEX IF NOT EXISTS idx_webhook_attempts_delivery ON webhook_delivery_attempts(organization_id,delivery_id,attempt_number DESC);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_webhook_endpoint_creator_tenant') THEN
    ALTER TABLE webhook_endpoints ADD CONSTRAINT fk_webhook_endpoint_creator_tenant
      FOREIGN KEY (organization_id,created_by_user_id) REFERENCES app_users(organization_id,id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_webhook_delivery_event_tenant') THEN
    ALTER TABLE webhook_deliveries ADD CONSTRAINT fk_webhook_delivery_event_tenant
      FOREIGN KEY (organization_id,event_id) REFERENCES outbox_events(organization_id,id) ON DELETE CASCADE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_webhook_delivery_endpoint_tenant') THEN
    ALTER TABLE webhook_deliveries ADD CONSTRAINT fk_webhook_delivery_endpoint_tenant
      FOREIGN KEY (organization_id,endpoint_id) REFERENCES webhook_endpoints(organization_id,id) ON DELETE CASCADE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_webhook_attempt_delivery_tenant') THEN
    ALTER TABLE webhook_delivery_attempts ADD CONSTRAINT fk_webhook_attempt_delivery_tenant
      FOREIGN KEY (organization_id,delivery_id) REFERENCES webhook_deliveries(organization_id,id) ON DELETE CASCADE;
  END IF;
END $$;

DO $$
DECLARE tbl TEXT;
BEGIN
  FOREACH tbl IN ARRAY ARRAY['webhook_endpoints','webhook_deliveries','webhook_delivery_attempts'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY',tbl);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY',tbl);
    EXECUTE format('DROP POLICY IF EXISTS autodraft_tenant_isolation ON %I',tbl);
    EXECUTE format(
      'CREATE POLICY autodraft_tenant_isolation ON %I USING (organization_id=autodraft_current_organization_id()) WITH CHECK (organization_id=autodraft_current_organization_id())',
      tbl
    );
  END LOOP;
END $$;

-- Convert pending outbox rows into one durable delivery per matching active
-- endpoint. No endpoint means the event is considered handled (published).
CREATE OR REPLACE FUNCTION autodraft_prepare_webhook_deliveries(p_limit INTEGER DEFAULT 100)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE ev RECORD;
DECLARE inserted_count INTEGER := 0;
DECLARE n INTEGER;
BEGIN
  -- Disabled endpoints cannot leave existing deliveries stuck forever.
  UPDATE public.webhook_deliveries d
     SET status='dead', lease_owner=NULL, lease_expires_at=NULL,
         last_error='Webhook endpoint disabled', updated_at=NOW()
    FROM public.webhook_endpoints w
   WHERE d.organization_id=w.organization_id AND d.endpoint_id=w.id
     AND w.active=FALSE AND d.status IN ('pending','leased');

  FOR ev IN
    SELECT e.id,e.organization_id,e.event_type
      FROM public.outbox_events e
     WHERE e.status='pending' AND e.available_at<=NOW()
     ORDER BY e.created_at,e.id
     FOR UPDATE SKIP LOCKED
     LIMIT GREATEST(1,LEAST(p_limit,1000))
  LOOP
    INSERT INTO public.webhook_deliveries(
      organization_id,event_id,endpoint_id,idempotency_key,status,available_at
    )
    SELECT ev.organization_id,ev.id,w.id,
           'autodraft:'||ev.id::text||':'||w.id::text,
           'pending',NOW()
      FROM public.webhook_endpoints w
     WHERE w.organization_id=ev.organization_id
       AND w.active=TRUE
       AND (jsonb_array_length(w.event_types)=0 OR w.event_types ? ev.event_type)
    ON CONFLICT(organization_id,event_id,endpoint_id) DO NOTHING;
    GET DIAGNOSTICS n = ROW_COUNT;
    inserted_count := inserted_count + n;

    IF NOT EXISTS(
      SELECT 1 FROM public.webhook_deliveries d
       WHERE d.organization_id=ev.organization_id AND d.event_id=ev.id
    ) THEN
      UPDATE public.outbox_events SET status='published',published_at=NOW()
       WHERE organization_id=ev.organization_id AND id=ev.id;
    END IF;
  END LOOP;

  -- Recompute terminal events, including deliveries killed because their endpoint
  -- was disabled after the event was emitted.
  UPDATE public.outbox_events e
     SET status = CASE
                    WHEN EXISTS(SELECT 1 FROM public.webhook_deliveries d WHERE d.organization_id=e.organization_id AND d.event_id=e.id AND d.status='dead') THEN 'dead'
                    ELSE 'published'
                  END,
         published_at = CASE
                          WHEN NOT EXISTS(SELECT 1 FROM public.webhook_deliveries d WHERE d.organization_id=e.organization_id AND d.event_id=e.id AND d.status='dead') THEN NOW()
                          ELSE e.published_at
                        END
   WHERE e.status='pending'
     AND EXISTS(SELECT 1 FROM public.webhook_deliveries d WHERE d.organization_id=e.organization_id AND d.event_id=e.id)
     AND NOT EXISTS(SELECT 1 FROM public.webhook_deliveries d WHERE d.organization_id=e.organization_id AND d.event_id=e.id AND d.status IN ('pending','leased'));

  RETURN inserted_count;
END;
$$;

CREATE OR REPLACE FUNCTION autodraft_claim_webhook_delivery(
  p_worker_id TEXT,
  p_lease_seconds INTEGER DEFAULT 60
)
RETURNS TABLE(
  delivery_id UUID,
  organization_id UUID,
  event_id UUID,
  endpoint_id UUID,
  endpoint_url TEXT,
  secret_ciphertext TEXT,
  event_type TEXT,
  aggregate_type TEXT,
  aggregate_id UUID,
  matter_id UUID,
  event_payload JSONB,
  event_created_at TIMESTAMPTZ,
  attempt_number INTEGER,
  idempotency_key TEXT
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE selected_id UUID;
DECLARE selected_org UUID;
DECLARE selected_attempt INTEGER;
BEGIN
  SELECT d.id INTO selected_id
    FROM public.webhook_deliveries d
    JOIN public.webhook_endpoints w ON w.organization_id=d.organization_id AND w.id=d.endpoint_id
   WHERE w.active=TRUE
     AND d.available_at<=NOW()
     AND (d.status='pending' OR (d.status='leased' AND COALESCE(d.lease_expires_at,'-infinity'::timestamptz)<NOW()))
   ORDER BY d.available_at,d.created_at,d.id
   FOR UPDATE OF d SKIP LOCKED
   LIMIT 1;
  IF selected_id IS NULL THEN RETURN; END IF;

  UPDATE public.webhook_deliveries d
     SET status='leased', lease_owner=p_worker_id,
         lease_expires_at=NOW()+make_interval(secs=>GREATEST(10,p_lease_seconds)),
         attempt_count=d.attempt_count+1, updated_at=NOW()
   WHERE d.id=selected_id
   RETURNING d.organization_id,d.attempt_count INTO selected_org,selected_attempt;

  INSERT INTO public.webhook_delivery_attempts(organization_id,delivery_id,attempt_number,requested_at)
  VALUES(selected_org,selected_id,selected_attempt,NOW())
  ON CONFLICT(organization_id,delivery_id,attempt_number) DO NOTHING;

  RETURN QUERY
  SELECT d.id,d.organization_id,d.event_id,d.endpoint_id,w.url,w.secret_ciphertext,
         e.event_type,e.aggregate_type,e.aggregate_id,e.matter_id,e.payload,e.created_at,
         d.attempt_count,d.idempotency_key
    FROM public.webhook_deliveries d
    JOIN public.webhook_endpoints w ON w.organization_id=d.organization_id AND w.id=d.endpoint_id
    JOIN public.outbox_events e ON e.organization_id=d.organization_id AND e.id=d.event_id
   WHERE d.id=selected_id;
END;
$$;

CREATE OR REPLACE FUNCTION autodraft_finish_webhook_delivery(
  p_delivery_id UUID,
  p_worker_id TEXT,
  p_success BOOLEAN,
  p_retryable BOOLEAN,
  p_http_status INTEGER,
  p_error TEXT,
  p_response_excerpt TEXT,
  p_max_attempts INTEGER DEFAULT 8,
  p_backoff_base_seconds INTEGER DEFAULT 5,
  p_backoff_max_seconds INTEGER DEFAULT 3600
)
RETURNS TEXT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE d RECORD;
DECLARE next_status TEXT;
DECLARE delay_seconds INTEGER;
BEGIN
  SELECT * INTO d FROM public.webhook_deliveries
   WHERE id=p_delivery_id AND status='leased' AND lease_owner=p_worker_id
   FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Webhook delivery lease is not owned by this worker' USING ERRCODE='42501'; END IF;

  UPDATE public.webhook_delivery_attempts
     SET completed_at=NOW(),http_status=p_http_status,error=left(p_error,2000),response_excerpt=left(p_response_excerpt,4000)
   WHERE organization_id=d.organization_id AND delivery_id=d.id AND attempt_number=d.attempt_count;

  IF p_success THEN
    next_status := 'delivered';
    UPDATE public.webhook_deliveries
       SET status='delivered', delivered_at=NOW(), lease_owner=NULL, lease_expires_at=NULL,
           last_http_status=p_http_status,last_error=NULL,updated_at=NOW()
     WHERE id=d.id;
  ELSIF (NOT p_retryable) OR d.attempt_count>=GREATEST(1,p_max_attempts) THEN
    next_status := 'dead';
    UPDATE public.webhook_deliveries
       SET status='dead',lease_owner=NULL,lease_expires_at=NULL,
           last_http_status=p_http_status,last_error=left(COALESCE(p_error,'delivery failed'),2000),updated_at=NOW()
     WHERE id=d.id;
  ELSE
    next_status := 'pending';
    delay_seconds := LEAST(GREATEST(1,p_backoff_max_seconds),
                           GREATEST(1,p_backoff_base_seconds) * (2 ^ LEAST(20,GREATEST(0,d.attempt_count-1)))::INTEGER);
    UPDATE public.webhook_deliveries
       SET status='pending',available_at=NOW()+make_interval(secs=>delay_seconds),
           lease_owner=NULL,lease_expires_at=NULL,last_http_status=p_http_status,
           last_error=left(COALESCE(p_error,'delivery failed'),2000),updated_at=NOW()
     WHERE id=d.id;
  END IF;

  IF NOT EXISTS(
      SELECT 1 FROM public.webhook_deliveries x
       WHERE x.organization_id=d.organization_id AND x.event_id=d.event_id AND x.status IN ('pending','leased')
  ) THEN
    UPDATE public.outbox_events e
       SET status=CASE WHEN EXISTS(
                          SELECT 1 FROM public.webhook_deliveries x
                           WHERE x.organization_id=d.organization_id AND x.event_id=d.event_id AND x.status='dead'
                        ) THEN 'dead' ELSE 'published' END,
           published_at=CASE WHEN EXISTS(
                          SELECT 1 FROM public.webhook_deliveries x
                           WHERE x.organization_id=d.organization_id AND x.event_id=d.event_id AND x.status='dead'
                        ) THEN e.published_at ELSE NOW() END
     WHERE e.organization_id=d.organization_id AND e.id=d.event_id;
  END IF;
  RETURN next_status;
END;
$$;

CREATE OR REPLACE FUNCTION autodraft_retry_webhook_delivery(p_delivery_id UUID)
RETURNS VOID
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, public
AS $$
BEGIN
  UPDATE public.webhook_deliveries
     SET status='pending',available_at=NOW(),lease_owner=NULL,lease_expires_at=NULL,last_error=NULL,updated_at=NOW()
   WHERE id=p_delivery_id AND organization_id=autodraft_current_organization_id() AND status='dead';
  UPDATE public.outbox_events e SET status='pending',published_at=NULL
   WHERE e.organization_id=autodraft_current_organization_id()
     AND EXISTS(SELECT 1 FROM public.webhook_deliveries d WHERE d.organization_id=e.organization_id AND d.event_id=e.id AND d.id=p_delivery_id);
END;
$$;

GRANT EXECUTE ON FUNCTION autodraft_prepare_webhook_deliveries(INTEGER) TO PUBLIC;
GRANT EXECUTE ON FUNCTION autodraft_claim_webhook_delivery(TEXT,INTEGER) TO PUBLIC;
GRANT EXECUTE ON FUNCTION autodraft_finish_webhook_delivery(UUID,TEXT,BOOLEAN,BOOLEAN,INTEGER,TEXT,TEXT,INTEGER,INTEGER,INTEGER) TO PUBLIC;
GRANT EXECUTE ON FUNCTION autodraft_retry_webhook_delivery(UUID) TO PUBLIC;
