from __future__ import annotations

import asyncio
import logging

from .auth import validate_security_configuration
from .runtime import ai, db, log, ocr, runtime_state, settings, binary_object_store
from .runtime_worker import DurableRuntimeWorker


async def main() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    validate_security_configuration(settings)
    await db.connect()
    try:
        await db.assert_safe_runtime_role(allow_unsafe=settings.allow_unsafe_database_role)
        await db.assert_rls_hardening_migrated()
        worker = DurableRuntimeWorker(state=runtime_state, db=db, ai=ai, ocr=ocr, settings=settings, log=log, binary_store=binary_object_store)
        await worker.start()
        log.info(
            "Dedicated AutoDraft runtime worker started as %s (local concurrency=%s, cluster cap=%s)",
            worker.worker_id,
            settings.runtime_worker_concurrency,
            settings.runtime_cluster_concurrency,
        )
        try:
            await asyncio.Event().wait()
        finally:
            await worker.stop()
    finally:
        await ai.close()
        await db.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
