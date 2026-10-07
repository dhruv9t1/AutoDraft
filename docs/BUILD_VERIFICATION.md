# Build / verification status

Last verified: 2026-09-27

## Python backend

- All Python source files parse successfully with the available Python runtime.
- Backend regression suite: **3 passed** (`pytest -q`).
- Tests cover corpus-oriented deterministic extraction, preservation of same-valued fields with different semantic roles, PIN-vs-cheque-number protection, and wrapping-plan behavior.
- A local full FastAPI startup was not possible in this execution environment because `asyncpg` is not preinstalled and outbound package installation is blocked. `asyncpg` is declared in `backend/requirements.txt`; installing the requirements in a normal development environment resolves this runtime dependency.
- PostgreSQL integration and live Ollama calls therefore remain environment-dependent integration tests.

## Frontend

The React/Office.js frontend in this cumulative package is inherited from the previously verified template-workflow build. This backend migration preserves its HTTP/JSON/SSE contract. No Rust runtime is required by the frontend.

## Security packaging checks

The distributed ZIP excludes `.env`, private-key/PEM files, Git history, `node_modules`, Python virtual environments, `__pycache__`, and pytest caches.
