from __future__ import annotations

import asyncio
import logging

from .db import reset_request_organization, set_request_organization


class IntakeQuarantineJanitor:
    """Periodically expires rejected intake uploads independently of new uploads.

    ``intake_file_quarantine`` is FORCE-RLS tenant data. The janitor therefore
    enumerates tenant IDs from the deliberately public token-routing table, then
    performs each delete through the normal tenant-scoped pool instead of
    bypassing RLS with a privileged global delete.
    """

    def __init__(self, db, *, retention_seconds: int, interval_seconds: int, log: logging.Logger | None = None):
        self.db = db
        self.retention_seconds = max(300, int(retention_seconds))
        self.interval_seconds = max(60, int(interval_seconds))
        self.log = log or logging.getLogger("autodraft.intake_quarantine")
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def cleanup_once(self) -> int:
        async with self.db.raw_pool().acquire() as conn:
            rows = await conn.fetch("SELECT DISTINCT organization_id FROM public_intake_token_hashes")
        deleted = 0
        for row in rows:
            token = set_request_organization(str(row["organization_id"]))
            try:
                status = await self.db.p().execute(
                    "DELETE FROM intake_file_quarantine "
                    "WHERE created_at < NOW() - ($1 * INTERVAL '1 second')",
                    self.retention_seconds,
                )
                try:
                    deleted += int(str(status).rsplit(" ", 1)[-1])
                except (TypeError, ValueError):
                    pass
            finally:
                reset_request_organization(token)
        return deleted

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="autodraft-intake-quarantine-janitor")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                deleted = await self.cleanup_once()
                if deleted:
                    self.log.info("Expired %s quarantined intake file(s)", deleted)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.log.exception("Intake quarantine cleanup failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=float(self.interval_seconds))
            except asyncio.TimeoutError:
                pass
