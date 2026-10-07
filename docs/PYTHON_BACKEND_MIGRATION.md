# Backend migration: Rust/Axum → Python/FastAPI

AutoDraft's backend runtime has been converted to Python so the project can be maintained primarily with Python expertise while preserving the Word add-in's HTTP contract.

## Why this migration is low-risk architecturally

The Word add-in already communicates with the backend only through HTTP/JSON/SSE. The frontend does not import Rust code. Therefore the server implementation can change from Axum to FastAPI while keeping endpoint paths and camelCase payloads stable.

## API compatibility retained

- `POST /api/documents/identify-variables`
- `POST /api/documents/identify-variables-stream` (SSE)
- analysis endpoints (`summarize`, `risk-assessment`, `deadlines`)
- template create/list/get
- template OOXML get/put
- chunked OOXML upload start/upload/finalize
- manual variable creation
- variable rename/value update
- bulk variable-value persistence
- API Bearer-token gate
- CORS controls

## Accuracy behavior retained

The Python implementation preserves the cumulative accuracy strategy rather than replacing it with a generic AI call:

1. deterministic Indian legal/financial extraction first;
2. 8K-character document chunks;
3. scoped deterministic/known-variable hints per chunk;
4. deterministic low-temperature generation;
5. second-pass coverage audit;
6. exact-substring anchoring of AI output;
7. same-value/different-position semantic fields are retained;
8. post-processing and role-aware naming;
9. server-produced Word wrapping plan.

Python Unicode strings also eliminate the Rust byte-slicing hazard that previously required explicit UTF-8 boundary handling.

## Database compatibility

No schema reset is required. The existing PostgreSQL migrations and tables are unchanged, so an existing AutoDraft database can be used directly by the Python backend after dependencies are installed.

## Files removed

The Rust `Cargo.toml`, `Cargo.lock`, `src/*.rs`, and Rust test tree were removed from the active backend. Their functionality is represented in `backend/app/` and `backend/tests/`.

## Local commands

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/migrate.py
pytest -q
python run.py
```
