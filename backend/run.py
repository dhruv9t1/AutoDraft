from __future__ import annotations

import asyncio
import sys
from urllib.parse import parse_qs, urlsplit

import asyncpg
import uvicorn

from app.config import get_settings


def _database_target(url: str) -> str:
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    host = parsed.hostname or (query.get("host", ["localhost"])[0] if query else "localhost")
    port = parsed.port or 5432
    database = parsed.path.lstrip("/") or "postgres"
    user = parsed.username or "current OS user"
    return f"user={user} database={database} host={host} port={port}"


def _format_database_startup_error(url: str, exc: BaseException) -> str:
    target = _database_target(url)
    header = f"Database startup preflight failed for {target}."

    if isinstance(exc, asyncpg.InvalidPasswordError):
        return (
            f"{header}\n"
            "PostgreSQL rejected the configured DATABASE_URL password.\n\n"
            "Fix one of these before running `python run.py` again:\n"
            "  1. Copy `backend/.env.example` to `backend/.env` and set DATABASE_URL/MIGRATION_DATABASE_URL to real local credentials.\n"
            "  2. For the default local-development role only, reset the password to match the built-in default:\n"
            "     psql -d postgres -c \"ALTER ROLE autodraft_app WITH PASSWORD 'autodraft_app';\"\n"
            "  3. If this is a new local database, create it and run migrations:\n"
            "     createdb wordaddin\n"
            "     python -m scripts.migrate"
        )
    if isinstance(exc, asyncpg.InvalidCatalogNameError):
        return (
            f"{header}\n"
            "The configured PostgreSQL database does not exist.\n\n"
            "Create the local database and then run migrations:\n"
            "  createdb wordaddin\n"
            "  python -m scripts.migrate"
        )
    if isinstance(exc, (ConnectionRefusedError, OSError)):
        return (
            f"{header}\n"
            "PostgreSQL is not reachable at the configured host/port.\n\n"
            "Start PostgreSQL or update DATABASE_URL in `backend/.env`."
        )
    return f"{header}\n{exc.__class__.__name__}: {exc}"


async def _preflight_database(url: str) -> None:
    conn = await asyncpg.connect(url, timeout=5)
    try:
        await conn.execute("SELECT 1")
    finally:
        await conn.close()


if __name__ == "__main__":
    s=get_settings()
    try:
        asyncio.run(_preflight_database(s.database_url))
    except Exception as exc:
        print(_format_database_startup_error(s.database_url, exc), file=sys.stderr)
        raise SystemExit(3) from None
    uvicorn.run("app.main:app",host=s.host,port=s.port,reload=False,access_log=False)
