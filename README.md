# AutoDraft Word Add-in

AutoDraft is a Microsoft Word add-in with a Python/FastAPI backend for turning legal documents into reusable templates, identifying variable fields, wrapping them with Word content controls, and filling those variables later.

## Local development

Copy the example configuration instead of committing credentials:

```bash
cp backend/.env.example backend/.env
```

Set database/Ollama values locally. Shared/production deployments use `SECURITY_MODE=token`, a server-only `AUTH_HMAC_SECRET`, and Microsoft Entra/Office SSO. The Word add-in exchanges its Office identity token for a short-lived tenant-scoped AutoDraft token; no shared production bearer secret is compiled into the add-in.

The Word add-in can receive build-time configuration through:

```bash
REACT_APP_API_BASE_URL=https://your-backend.example
# Production auth is runtime Office/Entra SSO; no REACT_APP_API_AUTH_TOKEN is used.
# See SECURITY.md and docs/PRODUCTION_RELEASE_GATES.md.
```

Do **not** put real API keys, SSH keys, OCI private keys, or access tokens in this README or any tracked file.

## Security

See [`SECURITY.md`](SECURITY.md). Any credential that has previously been committed must be rotated and removed from the remote Git history; deleting it from the current tree does not invalidate the exposed credential.

## Draft source and reusable empty templates

The task pane now exposes a persistent **Start from** selector:

- **My document** — identify variables in the Word document currently open and create a reusable template.
- **Saved template** — load a previously saved empty master and fill it for a new case.

A fresh **My document** AutoDraft is intentionally unsaved while identification, renaming, manual field creation, and form filling are in progress. **Complete Drafting** completes only the current Word document and does not create a reusable template. Saving a reusable template is a separate explicit action. When the user chooses that action, AutoDraft captures a versioned full-DOCX snapshot where the Word host supports it, with body-OOXML fallback for reduced-capability hosts. Word field controls are preserved in the current document.

Variable extraction uses one backend job per logical run. The task pane prefers SSE events, with keep-alive heartbeats, and falls back to polling the **same job** if Word's WebView drops the stream; transport fallback therefore does not invoke Ollama twice.

Scanned PDF/image import is available through local OCR. The backend uses OCRmyPDF + Tesseract (`guj+eng`) to produce a searchable PDF and recognised text, and the task pane can import that text into Word before running the normal AutoDraft pipeline.

See `docs/GAVEL_ARCHITECTURE_PORT_2026-10-05.md` for the Gavel-inspired workflow/document-automation architecture. See `docs/CLIO_ARCHITECTURE_PORT_2026-10-05.md` for the Clio-inspired canonical legal-data/matter architecture. See `docs/LAWYER_FIRM_ARCHITECTURE_PORT_2026-10-04.md` for the lawyer-firm extraction/System-1 architecture port. See `docs/VNEXT_50_PERCENT_PASS.md` for the first-half implementation boundary, `docs/VNEXT_REMAINING_50_PERCENT_COMPLETE.md` for the second-half implementation ledger, `docs/JEV_TYPESAFE_AI_INTEGRATION.md` for the optional future TypeSafe AI / Jev provider path, and `docs/CUMULATIVE_CHANGES.md` for earlier cumulative changes.


## Gavel-inspired automation (v1.3)

AutoDraft now has a shared safe expression engine, immutable internal/client workflow versions and sessions, calculations, conditional Word regions, nested repeaters, template automation preflight, and headless DOCX generation for a single template or a published Document Set. Workflow answers are **not** silently promoted into canonical matter data; a lawyer must explicitly apply a completed session, and only existing active semantic field definitions are eligible. PDF conversion is not claimed by this build.


## Integrations and current architecture

The active backend is Python 3.11-3.13/FastAPI/PostgreSQL. Production authentication is Microsoft Office/Entra SSO exchanged for short-lived HMAC-signed AutoDraft tokens; no shared bearer token is compiled into the Word add-in. Webhook integrations use the durable outbox dispatcher (`python -m app.webhook_worker_process`) with signed, idempotent, retryable delivery. Historical Rust and superseded model-planning documents live under `docs/archive/` and are not implementation guidance. See `docs/CURRENT_ARCHITECTURE.md`.
