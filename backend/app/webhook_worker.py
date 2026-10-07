from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any

import httpx

from .repositories.webhooks import WebhookWorkerRepository
from .webhook_security import (
    WebhookSecretBox,
    WebhookSecurityError,
    resolve_safe_webhook_target,
    canonical_webhook_body,
    sign_webhook,
)


class WebhookDeliveryWorker:
    def __init__(self, *, db, settings, log: logging.Logger | None = None):
        self.db=db
        self.settings=settings
        self.log=log or logging.getLogger("autodraft.webhooks")
        self.repo=WebhookWorkerRepository(db)
        self.worker_id=f"webhook-{uuid.uuid4().hex}"
        self._task: asyncio.Task | None=None
        self._stop=asyncio.Event()
        self._box=WebhookSecretBox(settings.webhook_secret_encryption_key)

    async def start(self) -> None:
        if self._task and not self._task.done(): return
        self._stop.clear()
        self._task=asyncio.create_task(self._run(),name=f"autodraft-webhook-{self.worker_id}")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try: await self._task
            except asyncio.CancelledError: pass
            self._task=None

    async def _run(self) -> None:
        semaphore=asyncio.Semaphore(max(1,int(self.settings.webhook_worker_concurrency)))
        active:set[asyncio.Task]=set()
        while not self._stop.is_set():
            try:
                await self.repo.prepare(int(self.settings.webhook_prepare_batch_size))
                while len(active)<max(1,int(self.settings.webhook_worker_concurrency)):
                    row=await self.repo.claim(self.worker_id,int(self.settings.webhook_lease_seconds))
                    if not row: break
                    task=asyncio.create_task(self._deliver(semaphore,row))
                    active.add(task); task.add_done_callback(active.discard)
                if not active:
                    await asyncio.wait_for(self._stop.wait(),timeout=float(self.settings.webhook_worker_poll_seconds))
                else:
                    done,_=await asyncio.wait(active,timeout=float(self.settings.webhook_worker_poll_seconds),return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        try: task.result()
                        except Exception: self.log.exception("Webhook delivery task failed")
            except asyncio.TimeoutError:
                pass
            except asyncio.CancelledError:
                raise
            except Exception:
                self.log.exception("Webhook dispatcher loop failed")
                await asyncio.sleep(min(5.0,max(0.1,float(self.settings.webhook_worker_poll_seconds))))
        if active:
            await asyncio.gather(*active,return_exceptions=True)

    async def _deliver(self, semaphore:asyncio.Semaphore, row:dict[str,Any]) -> None:
        async with semaphore:
            delivery_id=str(row["delivery_id"])
            endpoint_id=str(row["endpoint_id"])
            status:int|None=None; error:str|None=None; success=False; retryable=True
            try:
                url=str(row["endpoint_url"])
                target=await resolve_safe_webhook_target(url,allow_private=bool(self.settings.webhook_allow_private_targets))
                secret=self._box.decrypt(endpoint_id,str(row["secret_ciphertext"]))
                payload={
                    "id":str(row["event_id"]),
                    "type":str(row["event_type"]),
                    "organizationId":str(row["organization_id"]),
                    "aggregate":{"type":str(row["aggregate_type"]),"id":str(row["aggregate_id"]) if row.get("aggregate_id") else None},
                    "matterId":str(row["matter_id"]) if row.get("matter_id") else None,
                    "createdAt":row["event_created_at"].isoformat() if hasattr(row.get("event_created_at"),"isoformat") else str(row.get("event_created_at")),
                    "data":row.get("event_payload") or {},
                }
                body=canonical_webhook_body(payload)
                timestamp=str(int(time.time()))
                signature=sign_webhook(secret,timestamp,delivery_id,body)
                timeout=httpx.Timeout(float(self.settings.webhook_timeout_seconds),connect=min(10.0,float(self.settings.webhook_timeout_seconds)))
                # Use a per-delivery client: pooling by pinned IP could otherwise
                # reuse a TLS connection established for a different hostname that
                # happens to resolve to the same address, bypassing hostname checks.
                async with httpx.AsyncClient(timeout=timeout,follow_redirects=False,trust_env=False) as delivery_client:
                    response=await delivery_client.post(
                        target.url,content=body,
                        headers={
                            "Host":target.host_header,
                            "Content-Type":"application/json",
                            "User-Agent":"AutoDraft-Webhook/1.0",
                            "Idempotency-Key":str(row["idempotency_key"]),
                            "X-AutoDraft-Delivery-Id":delivery_id,
                            "X-AutoDraft-Event-Id":str(row["event_id"]),
                            "X-AutoDraft-Timestamp":signature.timestamp,
                            "X-AutoDraft-Signature":signature.value,
                        },
                        extensions={"sni_hostname":target.sni_hostname},
                    )
                status=response.status_code
                success=200<=status<300
                retryable=(status in {408,425,429} or 500<=status<=599)
                if not success:
                    error=f"Webhook receiver returned HTTP {status}"
            except WebhookSecurityError as exc:
                error=str(exc); retryable=False
            except (httpx.TimeoutException,httpx.NetworkError,httpx.RemoteProtocolError) as exc:
                error=f"{exc.__class__.__name__}: delivery transport failure"; retryable=True
            except Exception as exc:
                # Unknown local failures are retried but details are intentionally
                # reduced so endpoint secrets/request payloads cannot enter logs.
                error=f"{exc.__class__.__name__}: webhook delivery failed"; retryable=True
            final=await self.repo.finish(
                delivery_id,self.worker_id,success=success,retryable=retryable,http_status=status,error=error,
                response_excerpt=None,max_attempts=int(self.settings.webhook_max_attempts),
                backoff_base_seconds=int(self.settings.webhook_backoff_base_seconds),
                backoff_max_seconds=int(self.settings.webhook_backoff_max_seconds),
            )
            if success:
                self.log.info("Webhook delivery %s completed",delivery_id)
            elif final=="dead":
                self.log.error("Webhook delivery %s moved to dead-letter state after attempt %s",delivery_id,row.get("attempt_number"))
            else:
                self.log.warning("Webhook delivery %s scheduled for retry",delivery_id)
