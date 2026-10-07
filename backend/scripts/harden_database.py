from __future__ import annotations

import asyncio

from app.config import get_settings
from app.db import Database, run_migrations


async def run():
    settings = get_settings()
    migration_url = settings.migration_database_url.strip() or settings.database_url
    db = Database(migration_url)
    await db.connect()
    try:
        # RLS hardening now lives in the normal migration chain so every
        # environment receives the same fail-closed policy definition.
        await run_migrations(db)
        print("AutoDraft RLS/runtime hardening migrations applied.")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(run())
