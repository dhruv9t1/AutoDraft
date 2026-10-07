# Webhook integrations

AutoDraft domain events use a transactional outbox: the legal-data transaction commits the `outbox_events` row first, while external delivery happens asynchronously in a dedicated worker.

## Production setup

1. Set a high-entropy `WEBHOOK_SECRET_ENCRYPTION_KEY` (32+ characters). This encrypts per-endpoint signing secrets at rest.
2. Create endpoints with the admin API under `/api/integrations/webhooks`. The generated signing secret is returned only on create/rotation.
3. Run one or more dispatchers:

```bash
cd backend
python -m app.webhook_worker_process
```

## Delivery contract

Every matching event is expanded to exactly one `webhook_deliveries` row per endpoint, protected by a unique `(organization_id,event_id,endpoint_id)` constraint and stable `Idempotency-Key`.

Requests contain canonical JSON and these headers:

- `Idempotency-Key: autodraft:<event-id>:<endpoint-id>`
- `X-AutoDraft-Delivery-Id`
- `X-AutoDraft-Event-Id`
- `X-AutoDraft-Timestamp`
- `X-AutoDraft-Signature: v1=<hex HMAC-SHA256>`

The signature input is `timestamp + "." + delivery_id + "." + raw_request_body`. Receivers should reject stale timestamps, compare signatures in constant time, and persist the idempotency key before processing side effects.

## Reliability

Deliveries are leased with `FOR UPDATE SKIP LOCKED`; expired leases are reclaimable after worker failure. Retryable transport failures, HTTP 408/425/429 and 5xx responses use exponential backoff. Non-retryable failures and exhausted retries move the delivery to `dead`, with immutable rows in `webhook_delivery_attempts`. Administrators can inspect and explicitly retry dead deliveries.

HTTP redirects are disabled. Production endpoints require HTTPS. Private/reserved destinations are rejected by default; `WEBHOOK_ALLOW_PRIVATE_TARGETS=true` is an explicit operator exception for controlled internal receivers.
