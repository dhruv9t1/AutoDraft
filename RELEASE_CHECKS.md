# AutoDraft release checks

Run from the backend with the Python 3.13 virtual environment active:

```bash
python -m compileall -q app
python -m pytest -v
python -c "from app.main import app; print('BACKEND IMPORT OK')"
```

Run from `word-extension`:

```bash
npx tsc --noEmit
npm test -- --run
npm run build:dev
```

A real Microsoft Word host, PostgreSQL database, and configured Ollama model are still required for full end-to-end runtime validation.
