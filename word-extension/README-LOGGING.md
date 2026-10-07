# Frontend diagnostics (local development only)

AutoDraft's Word add-in diagnostics are privacy-first:

- Production builds do **not** emit AutoDraft frontend diagnostics.
- Local diagnostics are disabled unless `REACT_APP_ENABLE_DIAGNOSTIC_LOGGING=true`.
- Network forwarding is a second opt-in: `REACT_APP_ENABLE_REMOTE_LOGGING=true`.
- `REACT_APP_LOGGER_URL` must explicitly point to `localhost` or `127.0.0.1`; there is no network logger default.
- Arbitrary objects, document text, field values, matter data, API response bodies, error stacks, bearer tokens and DOCX/Base64 content are never serialized into diagnostic entries.

## Local console diagnostics

Start the Word development server with:

```bash
REACT_APP_ENABLE_DIAGNOSTIC_LOGGING=true npm run dev-server
```

Only metadata such as counts, operation names, status codes, and error **types** is logged.

## Optional local diagnostic receiver

The receiver is deliberately disabled by default and binds only to `127.0.0.1`.

```bash
# Terminal 1
FRONTEND_LOGGER_ENABLE=true npm run logger-server

# Terminal 2
REACT_APP_ENABLE_DIAGNOSTIC_LOGGING=true \\
REACT_APP_ENABLE_REMOTE_LOGGING=true \\
REACT_APP_LOGGER_URL=http://127.0.0.1:3002/logs \\
npm run dev-server
```

The receiver:

- accepts requests only from loopback browser origins;
- limits request bodies;
- ignores diagnostic context objects;
- does not persist logs;
- must never be exposed through a reverse proxy or production deployment.

Do not add logs containing client names, matter names, field names/values, document text, template contents, extracted variables, intake/workflow answers, API bodies, or raw error responses.
