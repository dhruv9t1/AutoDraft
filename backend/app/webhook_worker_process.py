from __future__ import annotations

import asyncio
import logging

from .auth import validate_security_configuration
from .runtime import db, log, settings
from .webhook_worker import WebhookDeliveryWorker


async def main() -> None:
    logging.basicConfig(level=getattr(logging,settings.log_level.upper(),logging.INFO),format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    validate_security_configuration(settings)
    await db.connect()
    try:
        await db.assert_safe_runtime_role(allow_unsafe=settings.allow_unsafe_database_role)
        await db.assert_rls_hardening_migrated()
        worker=WebhookDeliveryWorker(db=db,settings=settings,log=log)
        await worker.start()
        log.info("AutoDraft webhook worker started as %s",worker.worker_id)
        try: await asyncio.Event().wait()
        finally: await worker.stop()
    finally:
        await db.close()


if __name__=="__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: pass
