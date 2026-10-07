from __future__ import annotations

import base64
import hashlib
import json
import logging
import uuid
from typing import Any, Awaitable, Callable

from ..db import Database
from ..domain.template_automation import TemplateAutomationError, render_docx_base64
from ..domain.workflows import WorkflowAnswerValidationError, validate_workflow_answers
from ..repositories.automation import AutomationRepository
from ..binary_store import BinaryObjectStore
from .automation_data import AutomationDataService
from .domain_events import emit_domain_event


log = logging.getLogger(__name__)


class GenerationService:
    def __init__(self, db: Database, objects: BinaryObjectStore | None = None):
        self.db = db
        self.objects = objects
        self.automation = AutomationRepository(db, objects)
        self.data = AutomationDataService(db)

    @staticmethod
    def _fingerprint(**values: Any) -> str:
        payload = json.dumps(values, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    async def _targets(
        self,
        *,
        template_id: uuid.UUID | None,
        template_version: int | None,
        document_set_version_id: uuid.UUID | None,
        generation_run_id: uuid.UUID | None,
    ):
        if template_version is not None and template_id is None:
            raise ValueError("templateVersion requires templateId")
        if template_id and document_set_version_id:
            raise ValueError("Choose one template or one document set, not both")
        if document_set_version_id and template_version is not None:
            raise ValueError("templateVersion cannot be combined with a document set")

        selected: set[str] | None = None
        run = None
        if generation_run_id:
            run = await self.db.p().fetchrow("SELECT * FROM generation_runs WHERE id=$1", generation_run_id)
            if not run:
                raise ValueError("Generation run not found")
            if run["status"] != "population":
                raise ValueError("Authoritative document-set generation is allowed only while the run is in Population")
            if template_id is not None:
                raise ValueError("Generation run is pinned to a document set; do not supply templateId")
            if document_set_version_id is not None and document_set_version_id != run["document_set_version_id"]:
                raise ValueError("Generation run belongs to a different document set version")
            if run["selected_items"]:
                selected = {str(x) for x in run["selected_items"]}
            document_set_version_id = run["document_set_version_id"]

        if document_set_version_id:
            rows = await self.db.p().fetch(
                """SELECT dsi.id AS item_id,dsi.template_id,dsi.template_version_id,dsi.label,dsi.position,dsi.required,
                          t.name,tv.version_number
                   FROM document_set_items dsi
                   JOIN templates t ON t.id=dsi.template_id
                   JOIN template_versions tv ON tv.id=dsi.template_version_id
                   WHERE dsi.version_id=$1 ORDER BY dsi.position,dsi.id""",
                document_set_version_id,
            )
            if selected:
                missing_required = [
                    str(r["item_id"])
                    for r in rows
                    if r["required"] and str(r["item_id"]) not in selected and str(r["template_id"]) not in selected
                ]
                if missing_required:
                    raise ValueError("Generation run omits required document-set items: " + ", ".join(missing_required))
                rows = [r for r in rows if str(r["item_id"]) in selected or str(r["template_id"]) in selected]
            if not rows:
                raise ValueError("Document set version has no selected immutable templates")
            return rows, run

        if not template_id:
            raise ValueError("templateId or documentSetVersionId is required")
        if template_version is None:
            row = await self.db.p().fetchrow(
                """SELECT tv.id AS template_version_id,tv.template_id,tv.version_number,t.name,'' AS label,0 AS position,
                          NULL::uuid AS item_id,FALSE AS required
                   FROM template_versions tv JOIN templates t ON t.id=tv.template_id
                   JOIN templates current ON current.id=tv.template_id AND current.current_version=tv.version_number
                   WHERE tv.template_id=$1""",
                template_id,
            )
        else:
            row = await self.db.p().fetchrow(
                """SELECT tv.id AS template_version_id,tv.template_id,tv.version_number,t.name,'' AS label,0 AS position,
                          NULL::uuid AS item_id,FALSE AS required
                   FROM template_versions tv JOIN templates t ON t.id=tv.template_id
                   WHERE tv.template_id=$1 AND tv.version_number=$2""",
                template_id,
                template_version,
            )
        if not row:
            raise ValueError("Immutable template version not found")
        return [row], run

    async def _begin_attempt(self, key: str, fingerprint: str, generation_run_id: uuid.UUID | None):
        async with self.db.p().transaction() as conn:
            # Serialize all attempts for this tenant/idempotency key across API
            # workers without relying on a mutable singleton attempt row.
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(autodraft_current_organization_id()::text || ':' || $1, 0))",
                key,
            )
            history = await conn.fetch(
                """SELECT * FROM generation_attempts
                   WHERE idempotency_key=$1
                   ORDER BY attempt_number DESC,created_at DESC FOR UPDATE""",
                key,
            )
            if history:
                if any(row["request_fingerprint"] != fingerprint for row in history):
                    raise ValueError("Idempotency key was already used for a different generation request")
                latest = history[0]
                if latest["status"] == "completed":
                    return "replay", latest
                if latest["status"] == "processing":
                    stale = await conn.fetchval(
                        "SELECT updated_at < NOW() - INTERVAL '15 minutes' FROM generation_attempts WHERE id=$1",
                        latest["id"],
                    )
                    if not stale:
                        raise ValueError("An identical generation request is already in progress")
                    await conn.execute(
                        """UPDATE generation_attempts
                           SET status='failed',error='Processing lease expired before retry',finished_at=NOW(),updated_at=NOW()
                           WHERE id=$1""",
                        latest["id"],
                    )
                attempt_number = int(latest["attempt_number"] or 1) + 1
                created = await conn.fetchrow(
                    """INSERT INTO generation_attempts(
                           organization_id,idempotency_key,request_fingerprint,generation_run_id,
                           retry_of_attempt_id,attempt_number,status,started_at
                       ) VALUES(autodraft_current_organization_id(),$1,$2,$3,$4,$5,'processing',NOW())
                       RETURNING *""",
                    key,fingerprint,generation_run_id,latest["id"],attempt_number,
                )
                return "process", created
            created = await conn.fetchrow(
                """INSERT INTO generation_attempts(
                       organization_id,idempotency_key,request_fingerprint,generation_run_id,attempt_number,status,started_at
                   ) VALUES(autodraft_current_organization_id(),$1,$2,$3,1,'processing',NOW()) RETURNING *""",
                key,fingerprint,generation_run_id,
            )
            return "process", created

    async def _replay_attempt(self, attempt) -> dict[str, Any]:
        artifacts = []
        for raw_id in list(attempt["artifact_ids"] or []):
            try:
                artifact_id = uuid.UUID(str(raw_id))
            except ValueError:
                continue
            row = await self.db.p().fetchrow("SELECT * FROM generation_artifacts WHERE id=$1", artifact_id)
            if not row:
                raise ValueError("Completed generation attempt references a missing artifact")
            metadata = dict(row["metadata"] or {})
            encoded = row.get("docx_base64") if hasattr(row,"get") else row["docx_base64"]
            if row.get("object_key") if hasattr(row,"get") else row["object_key"]:
                if not self.objects:
                    raise ValueError("Generated artifact object store is unavailable")
                encoded = await self.objects.get_base64(str(row["object_key"]))
            artifacts.append(
                {
                    "id": str(row["id"]),
                    "matterDocumentId": metadata.get("matterDocumentId"),
                    "templateId": str(row["template_id"]),
                    "templateVersion": metadata.get("templateVersion"),
                    "filename": row["filename"],
                    "mimeType": row["mime_type"],
                    "docxBase64": encoded,
                    "sha256": row["sha256"],
                    "stats": metadata.get("stats") or {},
                    "warnings": metadata.get("warnings") or [],
                }
            )
        response_meta = dict(attempt["response_metadata"] or {})
        return {
            "artifacts": artifacts,
            "dataKeys": response_meta.get("dataKeys") or [],
            "dataConflicts": response_meta.get("dataConflicts") or [],
            "idempotentReplay": True,
            "generationAttemptId": str(attempt["id"]),
            "generationAttemptNumber": int(attempt.get("attempt_number", 1) if hasattr(attempt, "get") else attempt["attempt_number"]),
            "retryOfAttemptId": str(attempt["retry_of_attempt_id"]) if attempt["retry_of_attempt_id"] else None,
        }

    async def _mark_attempt_failed(self, attempt_id: uuid.UUID | None, error: Exception) -> None:
        if not attempt_id:
            return
        try:
            await self.db.p().execute(
                "UPDATE generation_attempts SET status='failed',error=$1,finished_at=NOW(),updated_at=NOW() WHERE id=$2",
                str(error)[:2000],
                attempt_id,
            )
        except Exception:
            log.exception("Failed to persist failed status for generation attempt %s", attempt_id)

    async def generate(
        self,
        *,
        matter_id: uuid.UUID | None,
        template_id: uuid.UUID | None,
        template_version: int | None,
        document_set_version_id: uuid.UUID | None,
        workflow_session_id: uuid.UUID | None,
        generation_run_id: uuid.UUID | None,
        overrides: dict[str, Any],
        save_to_matter: bool,
        idempotency_key: str | None = None,
        override_reason: str | None = None,
        override_actor_user_id: str | None = None,
        override_actor_role: str | None = None,
        progress_callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ):
        targets, run = await self._targets(
            template_id=template_id,
            template_version=template_version,
            document_set_version_id=document_set_version_id,
            generation_run_id=generation_run_id,
        )
        if run:
            if matter_id is not None and run["matter_id"] is not None and matter_id != run["matter_id"]:
                raise ValueError("Generation run belongs to a different matter")
            if matter_id is None:
                matter_id = run["matter_id"]

        if workflow_session_id is not None:
            workflow_session = await self.db.p().fetchrow(
                """SELECT s.matter_id,s.status,s.metadata,s.answers,v.definition,w.audience
                   FROM workflow_sessions s JOIN workflow_versions v ON v.id=s.workflow_version_id
                   JOIN workflows w ON w.id=v.workflow_id WHERE s.id=$1""",
                workflow_session_id,
            )
            if not workflow_session:
                raise ValueError("Workflow session not found")
            if workflow_session['status']!='completed':
                raise ValueError("Workflow session must be completed and schema-validated before authoritative generation")
            try:
                validate_workflow_answers(workflow_session['definition'], dict(workflow_session['answers'] or {}))
            except WorkflowAnswerValidationError as exc:
                fields = ", ".join(str(item.get("path") or item.get("semanticKey")) for item in exc.errors[:5])
                raise ValueError(f"Workflow session contains invalid/unvalidated answers: {fields}") from exc
            metadata = dict(workflow_session["metadata"] or {})
            if workflow_session['audience'] in {'client','both'} and not bool(metadata.get('authoritativeGenerationApproved')):
                raise ValueError("Client workflow session must be lawyer-approved before authoritative generation")
            if workflow_session["matter_id"] is not None:
                if matter_id is not None and matter_id != workflow_session["matter_id"]:
                    raise ValueError("Workflow session belongs to a different matter")
                if matter_id is None:
                    matter_id = workflow_session["matter_id"]

        key = (idempotency_key or "").strip()
        if not key:
            raise ValueError("idempotencyKey is required for every persisted headless generation request")
        fingerprint = self._fingerprint(
            matter_id=matter_id,
            template_id=template_id,
            template_version=template_version,
            document_set_version_id=document_set_version_id,
            workflow_session_id=workflow_session_id,
            generation_run_id=generation_run_id,
            overrides=overrides,
            override_reason=override_reason if overrides else None,
            override_actor_user_id=override_actor_user_id if overrides else None,
            save_to_matter=save_to_matter,
            target_versions=[str(x["template_version_id"]) for x in targets],
        )
        attempt_id: uuid.UUID | None = None
        attempt_number: int | None = None
        retry_of_attempt_id: uuid.UUID | None = None
        action, attempt = await self._begin_attempt(key, fingerprint, generation_run_id)
        attempt_id = attempt["id"]
        attempt_number = int(attempt["attempt_number"] or 1)
        retry_of_attempt_id = attempt["retry_of_attempt_id"]
        if action == "replay":
            return await self._replay_attempt(attempt)

        try:
            if progress_callback:
                await progress_callback({"stage":"data_snapshot","completed":0,"total":len(targets)})
            snapshot = await self.data.build_snapshot(
                matter_id=matter_id, workflow_session_id=workflow_session_id, overrides=overrides
            )
            data = snapshot.data

            # Render immutable snapshots outside the persistence transaction. This
            # prevents CPU/ZIP/XML work from holding DB connections/locks open.
            rendered_targets: list[dict[str, Any]] = []
            for target_index, target in enumerate(targets, start=1):
                if progress_callback:
                    await progress_callback({"stage":"rendering","completed":target_index-1,"total":len(targets),"templateId":str(target["template_id"])})
                automation = await self.db.p().fetchrow(
                    """SELECT tav.blueprint,tv.docx_base64,tv.docx_object_key
                       FROM template_automation_versions tav JOIN template_versions tv ON tv.id=tav.template_version_id
                       WHERE tav.template_version_id=$1""",
                    target["template_version_id"],
                )
                if not automation:
                    raise ValueError(f"Template {target['name']} version {target['version_number']} has no published automation blueprint")
                encoded_template=automation["docx_base64"]
                if automation.get("docx_object_key") if hasattr(automation,"get") else automation["docx_object_key"]:
                    if not self.objects: raise ValueError("Template object store is unavailable")
                    encoded_template=await self.objects.get_base64(str(automation["docx_object_key"]))
                if not encoded_template:
                    raise ValueError(f"Template {target['name']} version {target['version_number']} has no full DOCX snapshot")
                try:
                    rendered = render_docx_base64(encoded_template, automation["blueprint"], data)
                except TemplateAutomationError as exc:
                    raise ValueError(str(exc)) from exc
                encoded = base64.b64encode(rendered.content).decode("ascii")
                filename = (str(target["label"]).strip() or str(target["name"]).strip() or "Generated document") + ".docx"
                stored=None
                if self.objects:
                    stored=await self.objects.put_bytes(namespace=f"generation/{matter_id or 'unattached'}",data=rendered.content,suffix=".docx")
                rendered_targets.append({"target": target, "rendered": rendered, "encoded": encoded, "filename": filename, "stored": stored})
                if progress_callback:
                    await progress_callback({"stage":"rendering","completed":target_index,"total":len(targets),"templateId":str(target["template_id"])})

            if progress_callback:
                await progress_callback({"stage":"persisting","completed":len(targets),"total":len(targets)})
            artifacts = []
            async with self.db.p().transaction() as conn:
                if generation_run_id:
                    locked_run = await conn.fetchrow("SELECT status FROM generation_runs WHERE id=$1 FOR UPDATE", generation_run_id)
                    if not locked_run or locked_run["status"] != "population":
                        raise ValueError("Generation run left Population before artifacts could be committed")

                for item in rendered_targets:
                    target, rendered, encoded, filename = item["target"], item["rendered"], item["encoded"], item["filename"]
                    stored=item.get("stored")
                    object_key=stored.key if stored else None
                    db_b64=None if stored else encoded
                    artifact = await conn.fetchrow(
                        """INSERT INTO generation_artifacts(organization_id,matter_id,generation_run_id,workflow_session_id,template_id,template_version_id,filename,docx_base64,object_key,size_bytes,sha256,metadata)
                           VALUES(autodraft_current_organization_id(),$1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11::jsonb) RETURNING *""",
                        matter_id,generation_run_id,workflow_session_id,target["template_id"],target["template_version_id"],filename,
                        db_b64,object_key,len(rendered.content),rendered.sha256,
                        {"stats":rendered.stats,"warnings":list(rendered.warnings),'dataConflicts':snapshot.conflicts,
                         'overrideAudit': {'reason': override_reason, 'actorUserId': override_actor_user_id, 'actorRole': override_actor_role, 'keys': sorted(str(k) for k in overrides.keys())} if overrides else None,
                         "templateVersion":target["version_number"]},
                    )
                    matter_document_id=None
                    if save_to_matter and matter_id:
                        matter_document_id=await conn.fetchval(
                            """INSERT INTO matter_documents(organization_id,matter_id,name,docx_base64,object_key,sha256,size_bytes,source,metadata)
                               VALUES(autodraft_current_organization_id(),$1,$2,$3,$4,$5,$6,'automation',$7::jsonb) RETURNING id""",
                            matter_id,filename,db_b64,object_key,rendered.sha256,len(rendered.content),
                            {"generationArtifactId":str(artifact["id"]),"generationAttemptId":str(attempt_id) if attempt_id else None,
                             "templateVersionId":str(target["template_version_id"]),"sha256":rendered.sha256,'dataConflicts':snapshot.conflicts,
                             'overrideAudit': {'reason': override_reason, 'actorUserId': override_actor_user_id, 'actorRole': override_actor_role, 'keys': sorted(str(k) for k in overrides.keys())} if overrides else None},
                        )
                        await conn.execute("UPDATE generation_artifacts SET metadata=metadata||$1::jsonb WHERE id=$2",{"matterDocumentId":str(matter_document_id)},artifact["id"])
                    await emit_domain_event(conn,aggregate_type="generation_artifact",aggregate_id=artifact["id"],matter_id=matter_id,event_type="DocumentGenerated",payload={"templateId":str(target["template_id"]),"templateVersion":target["version_number"],"filename":filename})
                    artifacts.append({"id":str(artifact["id"]),"matterDocumentId":str(matter_document_id) if matter_document_id else None,
                                      "templateId":str(target["template_id"]),"templateVersion":target["version_number"],"filename":filename,
                                      "mimeType":artifact["mime_type"],"docxBase64":encoded,"downloadUrl":f"/api/generation/artifacts/{artifact['id']}/content",
                                      "sha256":rendered.sha256,"stats":rendered.stats,"warnings":list(rendered.warnings)})
                if generation_run_id:
                    await conn.execute("""UPDATE generation_runs SET
                           artifact_ids=COALESCE(artifact_ids,'[]'::jsonb) || $1::jsonb,
                           workflow_session_id=COALESCE($2,workflow_session_id),
                           metadata=metadata||$3::jsonb||jsonb_build_object(
                               'generationAttemptIds',COALESCE(metadata->'generationAttemptIds','[]'::jsonb)||jsonb_build_array($4::text)
                           ),updated_at=NOW() WHERE id=$5""",[a["id"] for a in artifacts],workflow_session_id,
                           {"headlessGenerated":True,"latestGenerationAttemptId":str(attempt_id) if attempt_id else None,"overrideAudit":{"reason":override_reason,"actorUserId":override_actor_user_id,"actorRole":override_actor_role,"keys":sorted(str(k) for k in overrides.keys())} if overrides else None},str(attempt_id),generation_run_id)
                if overrides:
                    await conn.execute("""INSERT INTO audit_events(organization_id,actor_user_id,matter_id,event_type,details)
                           VALUES(autodraft_current_organization_id(),$1::uuid,$2,'GenerationOverrideApplied',$3::jsonb)""",
                           uuid.UUID(str(override_actor_user_id)) if override_actor_user_id else None,matter_id,
                           {"reason":override_reason,"role":override_actor_role,"keys":sorted(str(k) for k in overrides.keys()),"generationAttemptId":str(attempt_id) if attempt_id else None})
                if attempt_id:
                    await conn.execute("""UPDATE generation_attempts SET status='completed',artifact_ids=$1::jsonb,response_metadata=$2::jsonb,error='',finished_at=NOW(),updated_at=NOW() WHERE id=$3""",
                                       [a["id"] for a in artifacts],{"dataKeys":sorted(str(k) for k in data.keys()),"dataConflicts":snapshot.conflicts,
                                       "attemptNumber":attempt_number,"retryOfAttemptId":str(retry_of_attempt_id) if retry_of_attempt_id else None},attempt_id)
            if progress_callback:
                await progress_callback({"stage":"completed","completed":len(targets),"total":len(targets),"artifactCount":len(artifacts)})
            return {
                "artifacts": artifacts,
                "dataKeys": sorted(str(k) for k in data.keys()),
                'dataConflicts':snapshot.conflicts,
                "idempotentReplay": False,
                "generationAttemptId": str(attempt_id) if attempt_id else None,
                "generationAttemptNumber": attempt_number,
                "retryOfAttemptId": str(retry_of_attempt_id) if retry_of_attempt_id else None,
            }
        except Exception as exc:
            for item in locals().get("rendered_targets",[]):
                stored=item.get("stored") if isinstance(item,dict) else None
                if stored is not None and self.objects:
                    try:
                        await self.objects.delete(stored.key)
                    except Exception:
                        log.exception("Failed to remove orphaned generation object %s", stored.key)
            await self._mark_attempt_failed(attempt_id, exc)
            raise
