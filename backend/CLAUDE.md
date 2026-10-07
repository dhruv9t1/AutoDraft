# AutoDraft Python Backend

- Runtime: Python 3.11+
- Framework: FastAPI
- Database: PostgreSQL via asyncpg
- AI HTTP client: httpx
- Models: Pydantic v2 with camelCase aliases matching the TypeScript frontend

Commands:
- Install: `pip install -r requirements.txt`
- Run: `python run.py`
- Dev: `uvicorn app.main:app --host 127.0.0.1 --port 3001 --reload`
- Test: `pytest -q`
- Migrate DB: `python scripts/migrate.py`

Core invariants:
- `originalText` must exist verbatim in document text before it reaches the frontend.
- Preserve exact source positions for deterministic hits.
- Do not collapse same-valued variables that have different semantic roles/positions.
- Deterministic legal extractors are authoritative anchors; AI expands recall.
- Never log document contents or AI request bodies.
- Production `/api/*` authentication uses Office/Entra SSO exchanged for short-lived HMAC-signed AutoDraft tokens. `API_AUTH_TOKEN` is deprecated local compatibility only.
