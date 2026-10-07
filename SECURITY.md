# AutoDraft security model

## Production authentication

Shared browser/add-in bearer secrets are not supported for production. Run shared/multi-user deployments with:

```text
SECURITY_MODE=token
AUTH_HMAC_SECRET=<at least 32 random bytes, e.g. secrets.token_urlsafe(32)>
ENTRA_TENANT_ID=<Microsoft Entra tenant GUID>
ENTRA_CLIENT_ID=<Office add-in application/client GUID>
ENTRA_RESOURCE_URI=api://<addin-host>/<client-guid>
ENTRA_REQUIRED_SCOPE=access_as_user
```

Generate `AUTH_HMAC_SECRET` from at least 32 random bytes (for example, `python -c "import secrets; print(secrets.token_urlsafe(32))"`). Token-mode startup rejects shorter secrets.

The Word add-in obtains a Microsoft Office/Entra access token at runtime, exchanges it at `/api/auth/office-exchange`, and keeps the resulting short-lived tenant-scoped AutoDraft token in `sessionStorage`. No shared production API credential is compiled into the JavaScript bundle. The backend verifies Microsoft's signature, issuer, audience, tenant and required scope, maps the Entra subject to an explicitly provisioned AutoDraft user, and rechecks the live user's active/role state on protected requests.

Provision Office identities with the admin-only `/api/auth/identity-bindings` endpoint. Generate the production SSO manifest with `scripts/render-production-manifest.py`; do not deploy the localhost development manifest.

## Local development

`SECURITY_MODE=local` is only for direct loopback development. Header-supplied local identity is rejected for externally reachable/proxied requests unless the explicit unsafe development override is set. `API_AUTH_TOKEN` is deprecated compatibility-only local behavior; new development setups should use loopback local identity headers, and production ignores this setting entirely.

## Tenant isolation

Production runtime database connections must use a non-owner, non-superuser, `NOBYPASSRLS` role. Tenant context fails closed, tenant-owned tables use forced RLS, and tenant-consistent parent/child relationships are enforced with composite constraints where applicable.

## Public bearer links

Workflow/intake links are bearer credentials. Their raw values must never be persisted or logged. Intake routing stores only SHA-256 token hashes; request logging redacts token path segments.

## Release proof

Production release requires `scripts/run-real-environment-gates.sh` to pass with real PostgreSQL, clean frontend install/build, live Ollama, a scanned Gujarati/English OCR fixture, an SSO-rendered/validated production manifest, and real Word Windows/Mac evidence. See `docs/PRODUCTION_RELEASE_GATES.md`.

## Authorization and browser boundary hardening

AutoDraft now uses a centralized action/resource permission matrix (`backend/app/permissions.py`) rather than treating every authenticated mutation as a generic `staff` action. Structural publishing/admin operations require named permissions such as `workflow.publish`, `template.publish`, `field_schema.admin`, and `derived_rule.admin`; authoritative generation requires `generation.execute`; generation data overrides additionally require `generation.override` and a non-empty audit reason.

Production HMAC tokens include an `auth_version`. Every token-mode request re-reads `app_users`, enforces the live `active`/`role` values, and rejects tokens whose version no longer matches. Role/active changes automatically bump the version, and administrators can explicitly revoke all outstanding tokens for a user.

Rate limiting is PostgreSQL-backed so counters are shared across API workers. Forwarded client IP headers are accepted only when the direct peer is within `TRUSTED_PROXY_IPS`. In token mode an empty `CORS_ORIGINS` means no cross-origin browser origins are permitted; there is no wildcard fallback. Production responses receive CSP with a per-request nonce, HSTS, `frame-ancestors`, nosniff, referrer and permissions policies.


## Webhook integrations

Webhook endpoints are organization-scoped and admin-managed. Signing secrets are generated per endpoint, encrypted at rest with `WEBHOOK_SECRET_ENCRYPTION_KEY`, and returned only when created/rotated. Deliveries use a stable `Idempotency-Key`, HMAC-SHA256 `X-AutoDraft-Signature`, timestamp, leasing, exponential retry, immutable attempt history, and dead-letter state. Run `python -m app.webhook_worker_process` in production. Webhook redirects are disabled and private/reserved targets are rejected unless an operator explicitly enables them.


## Object-store encryption

Production/token-mode startup requires `OBJECT_STORE_ENCRYPTION_KEY`, a 32-byte random AES-256 key encoded as URL-safe Base64 or 64 hexadecimal characters. Runtime OCR/job objects and immutable application binaries are encrypted with AES-256-GCM before filesystem persistence; the logical object key is authenticated as associated data. After enabling the key on an existing deployment, run `python -m app.object_store_encrypt` from `backend/` once to rewrite legacy plaintext objects. Keep the key in a secret manager and available to every API/worker instance that shares the object stores.
