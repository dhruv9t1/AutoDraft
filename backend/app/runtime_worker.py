from __future__ import annotations

import asyncio
import logging
import shutil
import socket
import uuid
from pathlib import Path
from typing import Any

from fastapi.encoders import jsonable_encoder

from .config import Settings
from .db import Database, reset_request_organization, set_request_organization
from .errors import AutoDraftError
from .models import Variable, VariableIdentificationRequest
from .ocr_service import OcrDependencyError, OcrProcessingError, OcrService
from .runtime_state import ClaimedRuntimeJob, DurableRuntimeState
from .binary_store import BinaryObjectStore
from .services.generation_service import GenerationService
from .models import HeadlessGenerationRequest
from .services.field_service import identification_complete_payload
from .services.organization_service import get_boilerplate_values
from .variable_quality import audit_variables
from .repositories.ai_governance import AIGovernanceRepository


class DurableRuntimeWorker:
    """Lease-based PostgreSQL worker for extraction and OCR jobs.

    Any API process may claim work. A process crash only loses the lease; the
    next worker can reclaim and deterministically restart the job from its
    persisted payload/input bytes.
    """

    def __init__(self, *, state: DurableRuntimeState, db: Database, ai: Any, ocr: OcrService, settings: Settings, log: logging.Logger, binary_store: BinaryObjectStore | None = None):
        self.state = state
        self.db = db
        self.ai = ai
        self.ocr = ocr
        self.settings = settings
        self.log = log
        self.worker_id = f"{socket.gethostname()}:{uuid.uuid4()}"
        self._stop = asyncio.Event()
        self._manager: asyncio.Task | None = None
        self._running: set[asyncio.Task] = set()
        self.ai_governance=AIGovernanceRepository(db)
        self.generation=GenerationService(db,binary_store)

    async def start(self) -> None:
        if self._manager and not self._manager.done():
            return
        self._stop.clear()
        self._manager = asyncio.create_task(self._loop(), name="autodraft-durable-runtime-worker")

    async def stop(self) -> None:
        self._stop.set()
        if self._manager and not self._manager.done():
            self._manager.cancel()
        if self._manager:
            await asyncio.gather(self._manager, return_exceptions=True)
        tasks = list(self._running)
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._running.clear()

    async def _loop(self) -> None:
        poll = max(0.1, float(self.settings.runtime_worker_poll_seconds))
        concurrency = max(1, int(self.settings.runtime_worker_concurrency))
        last_prune = 0.0
        loop = asyncio.get_running_loop()
        try:
            while not self._stop.is_set():
                now = loop.time()
                if now - last_prune > 60:
                    try:
                        await self.state.prune_global()
                    except Exception:
                        self.log.exception("Durable runtime-state pruning failed")
                    last_prune = now

                self._running = {task for task in self._running if not task.done()}
                claimed_any = False
                while len(self._running) < concurrency and not self._stop.is_set():
                    try:
                        claim = await self.state.claim_job(self.worker_id)
                    except Exception:
                        self.log.exception("Durable runtime job claim failed")
                        claim = None
                    if not claim:
                        break
                    claimed_any = True
                    task = asyncio.create_task(self._execute(claim), name=f"runtime-job:{claim.job_id}")
                    self._running.add(task)
                    task.add_done_callback(self._running.discard)
                if not claimed_any:
                    try:
                        await asyncio.wait_for(self._stop.wait(), timeout=poll)
                    except TimeoutError:
                        pass
                else:
                    await asyncio.sleep(0)
        except asyncio.CancelledError:
            raise

    async def _execute(self, claim: ClaimedRuntimeJob) -> None:
        tenant_token = set_request_organization(claim.organization_id)
        processor: asyncio.Task | None = None
        watchdog: asyncio.Task | None = None
        cancelled_by_user = False
        try:
            job = await self.state.get_job(claim.job_id, include_blob=True, internal=True)
            if not job:
                return
            if job.get("cancel_requested"):
                await self.state.mark_cancelled(claim.job_id)
                return

            if claim.job_type == "extraction":
                processor = asyncio.create_task(self._process_extraction(claim.job_id, job))
            elif claim.job_type == "ocr":
                processor = asyncio.create_task(self._process_ocr(claim.job_id, job))
            elif claim.job_type == "generation":
                processor = asyncio.create_task(self._process_generation(claim.job_id, job))
            else:
                await self.state.fail_job(claim.job_id, f"Unsupported durable job type: {claim.job_type}")
                return

            async def lease_watchdog() -> None:
                nonlocal cancelled_by_user
                interval = max(2.0, float(self.settings.runtime_worker_lease_seconds) / 3.0)
                while processor and not processor.done():
                    await asyncio.sleep(interval)
                    should_cancel = await self.state.heartbeat(claim.job_id, self.worker_id)
                    if should_cancel and processor and not processor.done():
                        cancelled_by_user = True
                        processor.cancel()
                        return

            watchdog = asyncio.create_task(lease_watchdog())
            try:
                await processor
            except asyncio.CancelledError:
                if cancelled_by_user:
                    await self.state.mark_cancelled(claim.job_id)
                elif self._stop.is_set():
                    await self.state.release_for_retry(claim.job_id, self.worker_id)
                else:
                    raise
        except asyncio.CancelledError:
            if processor and not processor.done():
                processor.cancel()
                await asyncio.gather(processor, return_exceptions=True)
            try:
                await self.state.release_for_retry(claim.job_id, self.worker_id)
            except Exception:
                self.log.exception("Could not release durable job %s after worker cancellation", claim.job_id)
            raise
        except Exception as exc:
            self.log.exception("Durable runtime job %s failed", claim.job_id)
            try:
                await self.state.fail_job(claim.job_id, str(exc))
                await self.state.append_event(claim.job_id, "fatal_error", {"message": str(exc)})
            except Exception:
                self.log.exception("Could not persist durable job failure for %s", claim.job_id)
        finally:
            if watchdog and not watchdog.done():
                watchdog.cancel()
                await asyncio.gather(watchdog, return_exceptions=True)
            reset_request_organization(tenant_token)

    async def _process_extraction(self, job_id: str, job: dict[str, Any]) -> None:
        req = VariableIdentificationRequest.model_validate(job.get("payload") or {})
        boilerplate = await get_boilerplate_values(self.db)
        try:
            async for item in self.ai.stream_variables(req.document_content, req.known_variables or [], boilerplate):
                if item["event"] == "_final":
                    final_vars=[Variable.model_validate(v) if isinstance(v,dict) else v for v in item["data"].get("variables",[])]
                    policy=await self.ai.external_system1_policy()
                    descriptor=self.ai.provenance_descriptor(external_system1_enabled=bool(policy.get("enabled")))
                    request_uuid=uuid.UUID(str(job_id))
                    mapping=await self.ai_governance.persist_candidates(document=req.document_content,variables=final_vars,actor_user_id=str(job.get("owner_user_id")),request_id=request_uuid,provider=descriptor["provider"],model_version=descriptor["model"],provider_chain=descriptor["providerChain"],provider_versions=descriptor.get("providerVersions"))
                    for variable in final_vars:
                        if variable.candidate_id and variable.candidate_id in mapping:
                            variable.decision_record_id=mapping[variable.candidate_id]
                    final_data={**item["data"],"variables":final_vars}
                    payload = identification_complete_payload(req.document_content, final_data)
                    payload = jsonable_encoder(payload)
                    payload["provenanceRequestId"]=str(request_uuid)
                    await self.state.append_event(job_id, "complete", payload)
                    await self.state.complete_job(job_id, result=payload)
                    return
                data = item["data"]
                if item["event"] == "chunk_done" and isinstance(data, dict):
                    chunk_vars = [Variable.model_validate(v) if isinstance(v, dict) else v for v in data.get("variables", [])]
                    chunk_vars, _ = audit_variables(req.document_content, chunk_vars)
                    data = {**data, "variables": [jsonable_encoder(v) for v in chunk_vars]}
                await self.state.append_event(job_id, str(item["event"]), jsonable_encoder(data))
            raise RuntimeError("Extraction stream ended without a final result")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            payload = {"message": str(exc)}
            if isinstance(exc, AutoDraftError):
                payload.update({"code": exc.code, "recoverable": exc.recoverable})
            await self.state.append_event(job_id, "fatal_error", payload)
            await self.state.fail_job(job_id, str(exc))

    async def _process_generation(self,job_id:str,job:dict[str,Any])->None:
        payload=dict(job.get('payload') or {})
        req=HeadlessGenerationRequest.model_validate(payload.get('request') or {})
        actor_user_id=str(payload.get('actorUserId') or job.get('owner_user_id') or '')
        actor_role=str(payload.get('actorRole') or '')
        async def progress(data:dict[str,Any])->None:
            await self.state.append_event(job_id,'progress',data)
        await self.state.append_event(job_id,'progress',{'stage':'starting','completed':0,'total':0})
        result=await self.generation.generate(
            matter_id=uuid.UUID(req.matter_id) if req.matter_id else None,template_id=uuid.UUID(req.template_id) if req.template_id else None,
            template_version=req.template_version,document_set_version_id=uuid.UUID(req.document_set_version_id) if req.document_set_version_id else None,
            workflow_session_id=uuid.UUID(req.workflow_session_id) if req.workflow_session_id else None,generation_run_id=uuid.UUID(req.generation_run_id) if req.generation_run_id else None,
            overrides=req.data_overrides,save_to_matter=req.save_to_matter,idempotency_key=req.idempotency_key,override_reason=(req.override_reason or '').strip() or None,
            override_actor_user_id=actor_user_id,override_actor_role=actor_role,progress_callback=progress)
        # Job state keeps metadata only; binary bytes remain in the application object store.
        for artifact in result.get('artifacts',[]):artifact.pop('docxBase64',None)
        await self.state.append_event(job_id,'complete',{'artifactCount':len(result.get('artifacts',[]))})
        await self.state.complete_job(job_id,result=result)

    async def _process_ocr(self, job_id: str, job: dict[str, Any]) -> None:
        source_bytes = job.get("input_blob")
        if not isinstance(source_bytes, (bytes, bytearray)):
            await self.state.fail_job(job_id, "Persisted OCR input is missing")
            return
        suffix = str(job.get("input_suffix") or ".pdf")
        session = self.ocr.new_session_dir()
        source = session / ("source" + suffix)
        source.write_bytes(bytes(source_bytes))
        try:
            result = await self.ocr.process_path(source, session)
            output = result.searchable_pdf.read_bytes()
            payload = {
                "text": result.text,
                "pages": result.pages,
                "ocrPerformed": result.ocr_performed,
                "hadCompleteTextLayer": result.had_complete_text_layer,
                "languages": list(result.languages),
                "extractedCharacters": len(result.text),
            }
            await self.state.complete_job(job_id, result=payload, output_blob=output)
        except asyncio.CancelledError:
            raise
        except (OcrDependencyError, OcrProcessingError) as exc:
            await self.state.fail_job(job_id, str(exc))
        except Exception as exc:
            self.log.exception("OCR durable job %s failed", job_id)
            await self.state.fail_job(job_id, f"OCR failed: {exc}")
        finally:
            shutil.rmtree(session, ignore_errors=True)
