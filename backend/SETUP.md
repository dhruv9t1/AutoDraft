# Python Backend Setup

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev]"
cp .env.example .env
python -m scripts.migrate
python run.py
```

For hot reload use:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 3001 --reload
```

## Local PostgreSQL bootstrap

For a new local development database that uses the checked-in defaults, create the database and the runtime role before starting the app:

```bash
createdb wordaddin
psql -d postgres -c "CREATE ROLE autodraft_app LOGIN PASSWORD 'autodraft_app';"
psql -d postgres -c "ALTER ROLE autodraft_app NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;"
python -m scripts.migrate
python run.py
```

If the role already exists but `python run.py` reports `password authentication failed for user "autodraft_app"`, either set the correct `DATABASE_URL` in `backend/.env` or reset the local development password:

```bash
psql -d postgres -c "ALTER ROLE autodraft_app WITH PASSWORD 'autodraft_app';"
```

## PostgreSQL runtime-role safety

AutoDraft now separates the **migration/owner** connection from the **runtime** connection. `DATABASE_URL` must use a role that is not a superuser, does not own tenant tables, and has `NOBYPASSRLS`. Use `MIGRATION_DATABASE_URL` for schema-owner credentials when migrations are run by the application or `python -m scripts.migrate`.

A typical one-time role bootstrap, run as a PostgreSQL administrator, is:

```sql
CREATE ROLE autodraft_app LOGIN PASSWORD 'replace-with-a-secret';
ALTER ROLE autodraft_app NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
```

Run migrations with the owner/migrator connection after creating the role. Migration `20261005000017_rls_runtime_hardening.sql` grants the conventional `autodraft_app` role application DML privileges, forces RLS on the existing tenant-policy tables, and replaces default-organization policy fallbacks with a fail-closed tenant accessor. If you use a differently named runtime role, grant it equivalent DML/schema/sequence privileges explicitly.

For old local databases that still connect as `postgres`, `ALLOW_UNSAFE_DATABASE_ROLE=true` is an explicit development-only escape hatch. Do not enable it in production. The historical default organization is used only in `SECURITY_MODE=local`; token mode fails when tenant context is missing.

## Ollama

The vNext reliability default is `qwen3:4b`. Startup checks `/api/tags` and performs a small structured-output probe before reporting AI readiness. Override the purpose-specific model settings in `.env` if your installation deliberately uses another model.

```bash
ollama pull qwen3:4b
```

## Local Gujarati + English OCR (optional)

OCR runs locally; no cloud OCR service is required. On macOS:

```bash
brew install ocrmypdf
brew install tesseract-lang

tesseract --list-langs | grep '^eng$'
tesseract --list-langs | grep '^guj$'
```

The task pane accepts PDF/JPG/JPEG/PNG/TIFF. A searchable PDF is generated and the extracted text can be imported into Word for AutoDraft field identification.

## Verification

```bash
python -m compileall -q app scripts tests
python -m pytest -q
```

From `word-extension/`, install dependencies. This source snapshot may omit `package-lock.json` after a deliberate toolchain upgrade; the first install generates the fresh lockfile. Subsequent clean/release builds use `npm ci`.

```bash
npm install
npm run verify
```

PostgreSQL is required at runtime. The migration runner is idempotent and checksum-aware. Existing successful SQLx rows are imported only when the stored SQLx SHA-384 checksum exactly matches the local migration bytes; version-only equivalence is rejected.
