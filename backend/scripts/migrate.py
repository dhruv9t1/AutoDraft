from __future__ import annotations

import asyncio
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings
from app.db import Database, run_migrations


async def main() -> None:
    settings = get_settings()
    migration_url = settings.migration_database_url.strip() or settings.database_url
    db = Database(migration_url)
    await db.connect()
    try:
        await run_migrations(db, BACKEND_ROOT / "migrations")
        print("AutoDraft migrations applied successfully.")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
