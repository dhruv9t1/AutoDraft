from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, UploadFile

from ..config import get_settings
from ..db import set_request_organization
from ..intake_file_security import IntakeFileRejected, inspect_upload, normalize_extensions, scan_for_malware
from ..intake_validation import (
    UnsafeIntakeRegex,
    is_visible,
    normalize_questions,
    validate_intake_answers,
    validate_safe_regex,
)
from ..models import QuestionnaireSaveRequest
from ..repositories.intake import IntakeRepository
from ..runtime import utc_iso
from ..storage import private_blob, safe_filename
from ..token_security import bearer_token_hash


class IntakeService:
    def __init__(self, repo: IntakeRepository):
        self.repo = repo
        self.settings = get_settings()

    @staticmethod
    def qid(value: str) -> uuid.UUID:
        try:
            return uuid.UUID(value)
        except ValueError as exc:
            raise HTTPException(400, "Invalid questionnaire ID") from exc

    async def definition(self, qid: uuid.UUID):
        template = await self.repo.get_template(qid)
        if not template:
            raise HTTPException(404, "Questionnaire not found")
        version = await self.repo.latest_version(qid)
        if not version:
            return {"id": str(qid), "title": template["title"], "matterType": template["matter_type"], "version": 0, "status": template["status"], "sections": [], "questions": []}
        sections = await self.repo.version_sections(version["id"])
        questions = await self.repo.version_questions(version["id"])
        return {
            "id": str(qid),
            "title": template["title"],
            "matterType": template["matter_type"],
            "version": version["version_number"],
            "status": version["status"],
            "sections": [{"id": str(s["id"]), "title": s["title"], "description": s["description"], "position": s["position"]} for s in sections],
            "questions": [{
                "id": str(q["id"]), "sectionId": str(q["section_id"]) if q["section_id"] else None,
                "position": q["position"], "label": q["label"], "helpText": q["help_text"],
                "type": q["question_type"], "required": q["required"], "mapsTo": q["fact_key"] or "",
                "options": q["options"] or [], "displayRule": q["display_rule"], "validation": q["validation"] or {},
                "approved": q["approved"],
            } for q in questions],
        }

    async def save(self, req: QuestionnaireSaveRequest):
        qid = self.qid(req.id) if req.id else None
        if not req.title.strip():
            raise HTTPException(400, "Questionnaire title is required")
        sections = [s.model_dump(by_alias=True) for s in req.sections]
        questions = [q.model_dump(by_alias=True) for q in req.questions]
        question_ids = [str(q.get("id") or "").strip() for q in questions]
        if any(not value for value in question_ids) or len(set(question_ids)) != len(question_ids):
            raise HTTPException(422, "Question IDs must be non-empty and unique")
        known = set(question_ids)
        supported_extensions = set(self.settings.intake_allowed_extension_list)
        for question in questions:
            if not str(question.get("label") or "").strip():
                raise HTTPException(422, "Every intake question needs a label")
            rule = question.get("displayRule")
            if isinstance(rule, dict) and rule.get("questionId") and str(rule["questionId"]) not in known:
                raise HTTPException(422, f"Conditional rule for {question['label']} references an unknown question")
            validation = dict(question.get("validation") or {})
            pattern = validation.get("pattern")
            if pattern:
                try:
                    validate_safe_regex(str(pattern))
                except UnsafeIntakeRegex as exc:
                    raise HTTPException(422, f"Unsafe validation pattern for {question['label']}: {exc}") from exc
            if validation.get("minLength") is not None and validation.get("maxLength") is not None and int(validation["minLength"]) > int(validation["maxLength"]):
                raise HTTPException(422, f"Minimum length exceeds maximum length for {question['label']}")
            if validation.get("minValue") is not None and validation.get("maxValue") is not None and float(validation["minValue"]) > float(validation["maxValue"]):
                raise HTTPException(422, f"Minimum value exceeds maximum value for {question['label']}")
            if question.get("type") == "file":
                allowed = normalize_extensions(validation.get("allowedExtensions") or [])
                if not allowed:
                    raise HTTPException(422, f"File question {question['label']} must declare allowedExtensions")
                unsupported = sorted(allowed - supported_extensions)
                if unsupported:
                    raise HTTPException(422, f"File question {question['label']} allows unsupported type(s): {', '.join(unsupported)}")
        result = await self.repo.save_definition(questionnaire_id=qid, title=req.title.strip(), matter_type=req.matter_type.strip(), sections=sections, questions=questions)
        if not result:
            raise HTTPException(404, "Questionnaire not found")
        return await self.definition(result[0])

    async def publish(self, qid: uuid.UUID):
        result = await self.repo.publish(qid)
        if not result:
            raise HTTPException(404, "Questionnaire not found")
        if result.get("unapproved"):
            raise HTTPException(409, f"{result['unapproved']} AI suggestion(s) still require lawyer approval")
        if result.get("empty"):
            raise HTTPException(409, "Add at least one question before publishing")
        return result

    async def create_session(self, qid: uuid.UUID, *, matter_id: str | None, expires_days: int, base_url: str):
        mid = None
        if matter_id:
            try:
                mid = uuid.UUID(matter_id)
            except ValueError as exc:
                raise HTTPException(400, "Invalid matter ID") from exc
        token = secrets.token_urlsafe(24)
        expires = datetime.now(timezone.utc) + timedelta(days=expires_days)
        result = await self.repo.create_session(qid, token=token, matter_id=mid, expires_at=expires)
        if not result:
            raise HTTPException(409, "Publish the questionnaire before creating a client link")
        _session, version = result
        return {"token": token, "shareUrl": f"{base_url.rstrip('/')}/intake/{token}", "version": version["version_number"], "expiresAt": utc_iso(expires)}

    @staticmethod
    def is_visible(question: dict[str, Any], answers: dict[str, Any]) -> bool:
        return is_visible(question, answers)

    async def public_data(self, token: str):
        session = await self.repo.public_session_by_token(token)
        if session:
            set_request_organization(str(session["organization_id"]))
        if not session:
            return None
        now = datetime.now(timezone.utc)
        status = session["status"]
        if session["revoked_at"]:
            status = "revoked"
        elif session["expires_at"] and session["expires_at"] < now and status == "open":
            status = "expired"
        questions = normalize_questions([dict(x["snapshot"]) for x in await self.repo.session_questions(session["id"])])
        return {
            "sessionId": str(session["id"]), "title": session["title"], "matterType": session["matter_type"],
            "version": session["version_number"], "status": status,
            "submittedAt": utc_iso(session["submitted_at"]) if session["submitted_at"] else None,
            "expiresAt": utc_iso(session["expires_at"]) if session["expires_at"] else None,
            "questions": questions,
        }

    async def legacy_public_data(self, token: str):
        organization_id = await self.repo.legacy_public_organization_by_token(token)
        if not organization_id:
            return None
        set_request_organization(str(organization_id))
        row = await self.repo.db.p().fetchrow(
            "SELECT id,title,matter_type,questions,answers,submitted_at,expires_at,revoked_at FROM intake_forms WHERE token_hash=$1",
            bearer_token_hash(token),
        )
        if not row:
            return None
        if row["revoked_at"] or (row["expires_at"] and row["expires_at"] < datetime.now(timezone.utc)):
            return {"status": "revoked" if row["revoked_at"] else "expired"}
        if row["submitted_at"]:
            return {
                "title": row["title"], "matterType": row["matter_type"],
                "questions": normalize_questions(list(row["questions"] or [])),
                "submitted": True, "status": "submitted",
            }

        # Compatibility forms are upgraded on first open to the immutable,
        # versioned questionnaire/session engine. A session-level advisory lock
        # prevents concurrent first-open requests from creating duplicate versions.
        lock_key = f"legacy-intake-migrate:{bearer_token_hash(token)}"
        async with self.repo.db.raw_pool().acquire() as lock_conn:
            await lock_conn.execute("SELECT pg_advisory_lock(hashtextextended($1,0))", lock_key)
            try:
                existing = await self.repo.public_session_by_token(token)
                if existing:
                    set_request_organization(str(existing["organization_id"]))
                    return await self.public_data(token)
                questions = normalize_questions(list(row["questions"] or []))
                supported = list(self.settings.intake_allowed_extension_list)
                for question in questions:
                    question["approved"] = True
                    question["sectionId"] = "legacy-main"
                    if question.get("type") == "file":
                        validation = dict(question.get("validation") or {})
                        validation.setdefault("allowedExtensions", supported)
                        question["validation"] = validation
                saved = await self.repo.save_definition(
                    questionnaire_id=None,
                    title=str(row["title"] or "Client Intake"),
                    matter_type=str(row["matter_type"] or ""),
                    sections=[{"id": "legacy-main", "title": "Questions", "description": "", "position": 0}],
                    questions=questions,
                )
                if not saved:
                    raise HTTPException(500, "Legacy intake migration failed")
                qid = saved[0]
                published = await self.repo.publish(qid)
                if not published or published.get("unapproved") or published.get("empty"):
                    raise HTTPException(500, "Legacy intake migration could not publish the questionnaire")
                expires_at = row["expires_at"] or (datetime.now(timezone.utc) + timedelta(days=7))
                created = await self.repo.create_session(qid, token=token, matter_id=None, expires_at=expires_at)
                if not created:
                    raise HTTPException(500, "Legacy intake migration could not create a client session")
            finally:
                await lock_conn.execute("SELECT pg_advisory_unlock(hashtextextended($1,0))", lock_key)
        return await self.public_data(token)

    async def _validated_submission(self, session_id: uuid.UUID, questions: list[dict[str, Any]], answers: dict[str, Any]):
        file_rows = await self.repo.session_files(session_id)
        uploaded = {str(row["question_id"]) for row in file_rows if str(row.get("scan_status") or "") in {"clean", "unavailable", "legacy_unscanned"}}
        result = validate_intake_answers(questions, answers, uploaded_file_question_ids=uploaded)
        if not result.ok:
            fields = list(dict.fromkeys(result.missing + result.invalid + result.unknown))
            message = "Some answers need attention."
            if result.unknown:
                message = "Submission contains undeclared intake fields."
            raise HTTPException(422, detail={"message": message, "fields": fields})
        return result.normalized

    async def submit(self, token: str, answers: dict[str, Any]):
        session = await self.repo.public_session_by_token(token)
        if session:
            set_request_organization(str(session["organization_id"]))
        if not session:
            raise HTTPException(404, "Intake form not found")
        data = await self.public_data(token)
        if data["status"] != "open":
            raise HTTPException(410, "This intake link is no longer accepting responses")
        questions = data["questions"]
        normalized = await self._validated_submission(session["id"], questions, answers)
        async with self.repo.db.p().transaction() as conn:
            for q in questions:
                qid = uuid.UUID(str(q["id"]))
                if str(q["id"]) not in normalized:
                    continue
                value = normalized[str(q["id"])]
                answer_json = value if isinstance(value, (list, dict)) else None
                answer_text = None if answer_json is not None else str(value)
                await conn.execute(
                    """INSERT INTO intake_answers(session_id,question_id,answer_text,answer_json) VALUES($1,$2,$3,$4::jsonb)
                       ON CONFLICT(session_id,question_id) DO UPDATE SET answer_text=EXCLUDED.answer_text,answer_json=EXCLUDED.answer_json,created_at=NOW(),review_status='pending'""",
                    session["id"], qid, answer_text, answer_json,
                )
            await conn.execute("UPDATE intake_sessions SET status='submitted',submitted_at=NOW() WHERE id=$1", session["id"])
        return {"submitted": True}

    async def submit_legacy(self, token: str, answers: dict[str, Any]):
        data = await self.legacy_public_data(token)
        if not data:
            raise HTTPException(404, "Intake form not found")
        if data.get("status") != "open":
            raise HTTPException(410, "This intake link is no longer accepting responses")
        # legacy_public_data upgrades open forms to a versioned session, so the
        # exact same validation + persistence path handles the submission.
        modern = await self.repo.public_session_by_token(token)
        if not modern:
            raise HTTPException(503, "Legacy intake migration is unavailable")
        return await self.submit(token, answers)

    async def review_payload(self, token: str):
        session = await self.repo.session_by_token(token)
        if not session:
            return None
        qs = {str(x["question_id"]): dict(x["snapshot"]) for x in await self.repo.session_questions(session["id"])}
        files = {str(row["question_id"]): row for row in await self.repo.session_files(session["id"])}
        answers = []
        for a in await self.repo.answers(session["id"]):
            qid = str(a["question_id"])
            q = qs.get(qid, {})
            attachment = files.get(qid)
            file_meta = None if not attachment else {
                "id": str(attachment["id"]), "filename": attachment["filename"], "mimeType": attachment["mime_type"],
                "detectedMimeType": attachment.get("detected_mime"), "scanStatus": attachment.get("scan_status"),
                "sizeBytes": attachment["size_bytes"], "sha256": attachment["sha256"],
            }
            answers.append({"questionId": qid, "label": q.get("label", qid), "mapsTo": q.get("mapsTo", ""), "answer": a["answer_text"] if a["answer_text"] is not None else a["answer_json"], "reviewStatus": a["review_status"], "file": file_meta})
        return {"submitted": bool(session["submitted_at"]), "submittedAt": utc_iso(session["submitted_at"]) if session["submitted_at"] else None, "answers": answers}

    async def download_file(self, token: str, question_id: str):
        session = await self.repo.session_by_token(token)
        if not session:
            raise HTTPException(404, "Intake session not found")
        try:
            qid = uuid.UUID(question_id)
        except ValueError as exc:
            raise HTTPException(400, "Invalid question ID") from exc
        row = await self.repo.session_file(session["id"], qid)
        if not row:
            raise HTTPException(404, "Intake file not found")
        if str(row.get("scan_status") or "") not in {"clean", "unavailable", "legacy_unscanned"}:
            raise HTTPException(423, "Intake file is quarantined")
        return row

    async def _purge_expired_quarantine(self, conn, *, organization_id: Any) -> None:
        retention = max(300, int(self.settings.intake_quarantine_retention_seconds))
        await conn.execute(
            "DELETE FROM intake_file_quarantine WHERE organization_id=$1 AND created_at < NOW() - ($2 * INTERVAL '1 second')",
            organization_id, retention,
        )

    async def _quota_check(self, conn, *, session: Any, question_id: uuid.UUID, incoming_bytes: int, replacing: bool) -> None:
        """Enforce quotas for accepted files only. Quarantine has separate limits."""
        lock_key = f"intake-upload:{session['organization_id']}:{session['id']}"
        await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", lock_key)
        await self._purge_expired_quarantine(conn, organization_id=session["organization_id"])
        existing = await conn.fetchrow("SELECT size_bytes,created_at FROM intake_files WHERE session_id=$1 AND question_id=$2", session["id"], question_id) if replacing else None
        existing_bytes = int(existing["size_bytes"]) if existing else 0
        accepted_total = int(await conn.fetchval("SELECT COALESCE(SUM(size_bytes),0) FROM intake_files WHERE session_id=$1", session["id"]) or 0)
        projected_session = accepted_total - existing_bytes + incoming_bytes
        if projected_session > self.settings.intake_session_storage_quota_bytes:
            raise HTTPException(413, "Intake session storage quota exceeded")

        accepted_count = int(await conn.fetchval("SELECT COUNT(*) FROM intake_files WHERE session_id=$1", session["id"]) or 0)
        projected_count = accepted_count + (0 if existing else 1)
        if projected_count > self.settings.intake_session_file_count_limit:
            raise HTTPException(429, "Intake session upload-count quota exceeded")

        daily_accepted = int(await conn.fetchval("SELECT COALESCE(SUM(size_bytes),0) FROM intake_files WHERE organization_id=$1 AND created_at >= date_trunc('day',NOW())", session["organization_id"]) or 0)
        daily_existing = existing_bytes if existing and existing["created_at"] >= datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) else 0
        if daily_accepted - daily_existing + incoming_bytes > self.settings.intake_org_daily_upload_quota_bytes:
            raise HTTPException(429, "Organization daily intake upload quota exceeded")

    async def _quarantine_quota_check(self, conn, *, session: Any, incoming_bytes: int) -> None:
        lock_key = f"intake-quarantine:{session['organization_id']}:{session['id']}"
        await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", lock_key)
        await self._purge_expired_quarantine(conn, organization_id=session["organization_id"])
        session_bytes = int(await conn.fetchval("SELECT COALESCE(SUM(size_bytes),0) FROM intake_file_quarantine WHERE session_id=$1", session["id"]) or 0)
        session_count = int(await conn.fetchval("SELECT COUNT(*) FROM intake_file_quarantine WHERE session_id=$1", session["id"]) or 0)
        if session_bytes + incoming_bytes > self.settings.intake_quarantine_session_storage_quota_bytes:
            raise HTTPException(429, "Intake quarantine storage quota exceeded")
        if session_count + 1 > self.settings.intake_quarantine_session_file_count_limit:
            raise HTTPException(429, "Intake quarantine upload-count quota exceeded")
        daily_quarantine = int(await conn.fetchval("SELECT COALESCE(SUM(size_bytes),0) FROM intake_file_quarantine WHERE organization_id=$1 AND created_at >= date_trunc('day',NOW())", session["organization_id"]) or 0)
        if daily_quarantine + incoming_bytes > self.settings.intake_quarantine_org_daily_upload_quota_bytes:
            raise HTTPException(429, "Organization daily intake quarantine quota exceeded")

    async def _quarantine(self, *, session: Any, question_id: uuid.UUID, filename: str, declared_mime: str, detected_mime: str | None, content: bytes, reason: str, scan_status: str, scan_engine: str = "") -> None:
        blob = private_blob(content, max_bytes=self.settings.intake_file_max_bytes)
        async with self.repo.db.p().transaction() as conn:
            await self._quarantine_quota_check(conn, session=session, incoming_bytes=blob.size_bytes)
            await conn.execute(
                """INSERT INTO intake_file_quarantine(
                       organization_id,session_id,question_id,filename,declared_mime,detected_mime,size_bytes,sha256,reason,scan_status,scan_engine,content
                   ) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)""",
                session["organization_id"], session["id"], question_id, filename, declared_mime or "application/octet-stream",
                detected_mime, blob.size_bytes, blob.sha256, reason, scan_status, scan_engine, blob.content,
            )

    async def store_file(self, token: str, question_id: str, file: UploadFile, max_bytes: int | None = None):
        session = await self.repo.public_session_by_token(token)
        if session:
            set_request_organization(str(session["organization_id"]))
        if not session:
            raise HTTPException(404, "Intake form not found")
        data = await self.public_data(token)
        if data["status"] != "open":
            raise HTTPException(410, "This intake link is no longer accepting files")
        q = next((x for x in data["questions"] if str(x.get("id")) == question_id), None)
        if not q or q.get("type") != "file":
            raise HTTPException(400, "Question does not accept a file")
        try:
            qid = uuid.UUID(question_id)
        except ValueError as exc:
            raise HTTPException(400, "Invalid file-question ID") from exc

        limit = min(int(max_bytes or self.settings.intake_file_max_bytes), self.settings.intake_file_max_bytes)
        content = await file.read(limit + 1)
        if len(content) > limit:
            raise HTTPException(413, "Uploaded file is too large")
        filename = safe_filename(file.filename or "upload", "upload")
        declared_mime = file.content_type or "application/octet-stream"
        allowed = (q.get("validation") or {}).get("allowedExtensions") or []
        detected_mime: str | None = None
        try:
            inspected = inspect_upload(content, filename=filename, declared_mime=declared_mime, allowed_extensions=allowed)
            detected_mime = inspected.detected_mime
        except IntakeFileRejected as exc:
            await self._quarantine(session=session, question_id=qid, filename=filename, declared_mime=declared_mime, detected_mime=detected_mime, content=content, reason=exc.reason, scan_status="rejected")
            raise HTTPException(exc.status_code, str(exc)) from exc

        scan = await scan_for_malware(content, filename=filename, settings=self.settings)
        require_scan = self.settings.security_mode.strip().lower() == "token" and self.settings.intake_require_malware_scan_in_production
        if scan.status == "infected":
            await self._quarantine(session=session, question_id=qid, filename=filename, declared_mime=declared_mime, detected_mime=inspected.detected_mime, content=content, reason="malware_detected", scan_status=scan.status, scan_engine=scan.engine)
            raise HTTPException(422, "Uploaded file failed malware scanning")
        if scan.status in {"unavailable", "error"} and require_scan:
            await self._quarantine(session=session, question_id=qid, filename=filename, declared_mime=declared_mime, detected_mime=inspected.detected_mime, content=content, reason="malware_scan_unavailable", scan_status=scan.status, scan_engine=scan.engine)
            raise HTTPException(503, "Malware scanner is unavailable; upload was quarantined")

        blob = private_blob(content, max_bytes=limit)
        async with self.repo.db.p().transaction() as conn:
            await self._quota_check(conn, session=session, question_id=qid, incoming_bytes=blob.size_bytes, replacing=True)
            row = await conn.fetchrow(
                """INSERT INTO intake_files(session_id,question_id,filename,mime_type,declared_mime,detected_mime,scan_status,scan_engine,size_bytes,sha256,content)
                   VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                   ON CONFLICT(session_id,question_id) DO UPDATE SET
                     filename=EXCLUDED.filename,mime_type=EXCLUDED.mime_type,declared_mime=EXCLUDED.declared_mime,
                     detected_mime=EXCLUDED.detected_mime,scan_status=EXCLUDED.scan_status,scan_engine=EXCLUDED.scan_engine,
                     size_bytes=EXCLUDED.size_bytes,sha256=EXCLUDED.sha256,content=EXCLUDED.content,created_at=NOW()
                   RETURNING id,filename,size_bytes,sha256,detected_mime,scan_status""",
                session["id"], qid, filename, inspected.detected_mime, declared_mime, inspected.detected_mime,
                scan.status, scan.engine, blob.size_bytes, blob.sha256, blob.content,
            )
        return {"id": str(row["id"]), "filename": row["filename"], "sizeBytes": row["size_bytes"], "sha256": row["sha256"], "detectedMimeType": row["detected_mime"], "scanStatus": row["scan_status"]}
