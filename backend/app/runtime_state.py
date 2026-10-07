from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from .config import Settings
from .db import Database, get_request_organization
from .runtime_object_store import RuntimeObjectStore
from .errors import AutoDraftError


class RuntimeQuotaExceeded(AutoDraftError):
    def __init__(self, message: str):
        super().__init__("RUNTIME_QUOTA_EXCEEDED", message, 429, True)


@dataclass(frozen=True)
class ClaimedRuntimeJob:
    job_id: str
    organization_id: str
    job_type: str


class DurableRuntimeState:
    """Tenant/user-owned durable queue metadata backed by PostgreSQL.

    Large payloads, OCR binaries/results and chunk bodies are stored through the
    runtime object-store abstraction. PostgreSQL keeps only ownership, state,
    byte counts, hashes/keys and small event metadata.
    """

    def __init__(self, db: Database, settings: Settings, objects: RuntimeObjectStore):
        self.db = db
        self.settings = settings
        self.objects = objects

    @staticmethod
    def _uuid(value: str) -> uuid.UUID:
        return uuid.UUID(str(value))

    def _organization(self) -> str:
        organization_id = get_request_organization()
        if not organization_id:
            raise RuntimeError("Runtime state requires tenant context")
        return organization_id

    @staticmethod
    def _json_bytes(value: dict[str, Any]) -> bytes:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")

    async def _org_temp_bytes(self, conn) -> int:
        value = await conn.fetchval(
            """
            SELECT COALESCE((SELECT SUM(payload_bytes+input_bytes+result_bytes+output_bytes)
                               FROM runtime_jobs WHERE organization_id=autodraft_current_organization_id()
                                AND expires_at>NOW()),0)
                 + COALESCE((SELECT SUM(e.byte_length)
                               FROM runtime_job_events e
                               JOIN runtime_jobs j ON j.organization_id=e.organization_id AND j.id=e.job_id
                              WHERE e.organization_id=autodraft_current_organization_id()
                                AND j.expires_at>NOW()),0)
                 + COALESCE((SELECT SUM(c.byte_length)
                               FROM runtime_chunks c
                               JOIN runtime_chunk_sessions s
                                 ON s.organization_id=c.organization_id AND s.id=c.session_id
                              WHERE c.organization_id=autodraft_current_organization_id()
                                AND s.expires_at>NOW()),0)
            """
        )
        return int(value or 0)

    async def create_job(
        self,
        job_type: str,
        *,
        owner_user_id: str,
        payload: dict[str, Any] | None = None,
        input_blob: bytes | None = None,
        input_filename: str | None = None,
        input_suffix: str | None = None,
        ttl_seconds: int | None = None,
    ) -> dict[str, Any]:
        ttl = max(60, int(ttl_seconds or self.settings.extraction_job_ttl_seconds))
        organization_id = self._organization()
        owner = str(self._uuid(owner_user_id))
        job_id = str(uuid.uuid4())
        payload_raw = self._json_bytes(payload or {})
        input_raw = bytes(input_blob) if input_blob is not None else b""
        projected = len(payload_raw) + len(input_raw)
        payload_key = f"runtime/{organization_id}/jobs/{job_id}/payload.json"
        input_key = f"runtime/{organization_id}/jobs/{job_id}/input.bin" if input_blob is not None else None

        stored_keys: list[str] = []
        try:
            async with self.db.p().transaction() as conn:
                await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", f"autodraft:runtime:quota:{organization_id}")
                org_active = await conn.fetchval(
                    "SELECT COUNT(*) FROM runtime_jobs WHERE organization_id=autodraft_current_organization_id() AND status IN ('queued','running') AND expires_at>NOW()"
                )
                user_active = await conn.fetchval(
                    "SELECT COUNT(*) FROM runtime_jobs WHERE organization_id=autodraft_current_organization_id() AND owner_user_id=$1::uuid AND status IN ('queued','running') AND expires_at>NOW()",
                    owner,
                )
                if int(org_active or 0) >= max(1, int(self.settings.runtime_max_active_jobs_per_org)):
                    raise RuntimeQuotaExceeded("Organization runtime-job quota reached")
                if int(user_active or 0) >= max(1, int(self.settings.runtime_max_active_jobs_per_user)):
                    raise RuntimeQuotaExceeded("User runtime-job quota reached")
                if await self._org_temp_bytes(conn) + projected > int(self.settings.runtime_max_temp_bytes_per_org):
                    raise RuntimeQuotaExceeded("Organization runtime temporary-storage quota reached")

                await self.objects.put(payload_key, payload_raw); stored_keys.append(payload_key)
                if input_key:
                    await self.objects.put(input_key, input_raw); stored_keys.append(input_key)

                row = await conn.fetchrow(
                    """
                    INSERT INTO runtime_jobs(
                      id,organization_id,owner_user_id,job_type,status,payload,
                      payload_object_key,payload_bytes,input_object_key,input_bytes,
                      input_filename,input_suffix,expires_at
                    ) VALUES(
                      $1::uuid,autodraft_current_organization_id(),$2::uuid,$3,'queued','{}'::jsonb,
                      $4,$5,$6,$7,$8,$9,NOW()+make_interval(secs=>$10)
                    )
                    RETURNING id,organization_id,owner_user_id,job_type,status,error,input_filename,input_suffix,
                              cancel_requested,created_at,updated_at,expires_at,attempt_count
                    """,
                    job_id, owner, job_type, payload_key, len(payload_raw), input_key,
                    len(input_raw), input_filename, input_suffix, ttl,
                )
            return dict(row)
        except Exception:
            for key in stored_keys:
                await self.objects.delete(key)
            raise

    async def get_job(
        self,
        job_id: str,
        *,
        owner_user_id: str | None = None,
        include_blob: bool = False,
        hydrate: bool = True,
        internal: bool = False,
    ) -> dict[str, Any] | None:
        if not internal and not owner_user_id:
            raise ValueError("owner_user_id is required for user-facing runtime job access")
        columns = (
            "id,organization_id,owner_user_id,job_type,status,error,input_filename,input_suffix,"
            "cancel_requested,lease_owner,lease_expires_at,created_at,updated_at,expires_at,attempt_count,"
            "payload_object_key,payload_bytes,result_object_key,result_bytes,input_object_key,input_bytes,"
            "output_object_key,output_bytes,payload,result"
        )
        owner = str(self._uuid(owner_user_id)) if owner_user_id else None
        row = await self.db.p().fetchrow(
            f"SELECT {columns} FROM runtime_jobs WHERE id=$1 AND ($2::uuid IS NULL OR owner_user_id=$2::uuid)",
            self._uuid(job_id), owner,
        )
        if not row:
            return None
        out = dict(row)
        if hydrate:
            if out.get("payload_object_key"):
                out["payload"] = json.loads((await self.objects.get(out["payload_object_key"])).decode("utf-8"))
            if out.get("result_object_key"):
                out["result"] = json.loads((await self.objects.get(out["result_object_key"])).decode("utf-8"))
        if include_blob:
            out["input_blob"] = await self.objects.get(out["input_object_key"]) if out.get("input_object_key") else None
            out["output_blob"] = await self.objects.get(out["output_object_key"]) if out.get("output_object_key") else None
        return out

    async def append_event(self, job_id: str, event_type: str, data: dict[str, Any]) -> int:
        organization_id = self._organization()
        raw = self._json_bytes(data)
        key = f"runtime/{organization_id}/jobs/{job_id}/events/{uuid.uuid4().hex}.json"
        async with self.db.p().transaction() as conn:
            await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", f"autodraft:runtime:quota:{organization_id}")
            if await self._org_temp_bytes(conn) + len(raw) > int(self.settings.runtime_max_temp_bytes_per_org):
                raise RuntimeQuotaExceeded("Organization runtime temporary-storage quota reached while recording job events")
            await self.objects.put(key, raw)
            try:
                event_id = await conn.fetchval(
                    """INSERT INTO runtime_job_events(organization_id,job_id,event_type,data,object_key,byte_length)
                       VALUES(autodraft_current_organization_id(),$1,$2,'{}'::jsonb,$3,$4) RETURNING id""",
                    self._uuid(job_id), event_type, key, len(raw),
                )
            except Exception:
                await self.objects.delete(key)
                raise
        return int(event_id)

    async def events_after(self, job_id: str, after_id: int = 0, *, owner_user_id: str | None = None, internal: bool = False) -> list[dict[str, Any]]:
        if not internal and not owner_user_id:
            raise ValueError("owner_user_id is required for user-facing runtime event access")
        owner = str(self._uuid(owner_user_id)) if owner_user_id else None
        rows = await self.db.p().fetch(
            """
            SELECT e.id,e.event_type,e.data,e.object_key,e.created_at
              FROM runtime_job_events e
              JOIN runtime_jobs j ON j.organization_id=e.organization_id AND j.id=e.job_id
             WHERE e.job_id=$1 AND e.id>$2 AND ($3::uuid IS NULL OR j.owner_user_id=$3::uuid)
             ORDER BY e.id
            """,
            self._uuid(job_id), int(after_id), owner,
        )
        result=[]
        for row in rows:
            item=dict(row)
            if item.get("object_key"):
                item["data"] = json.loads((await self.objects.get(str(item["object_key"]))).decode("utf-8"))
            result.append(item)
        return result

    async def complete_job(self, job_id: str, *, result: dict[str, Any], output_blob: bytes | None = None) -> None:
        organization_id = self._organization()
        result_raw = self._json_bytes(result)
        result_key = f"runtime/{organization_id}/jobs/{job_id}/result.json"
        output_raw = bytes(output_blob) if output_blob is not None else b""
        output_key = f"runtime/{organization_id}/jobs/{job_id}/output.bin" if output_blob is not None else None
        stored: list[str] = []
        try:
            async with self.db.p().transaction() as conn:
                await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", f"autodraft:runtime:quota:{organization_id}")
                job = await conn.fetchrow("SELECT result_bytes,output_bytes,result_object_key,output_object_key FROM runtime_jobs WHERE id=$1 FOR UPDATE", self._uuid(job_id))
                if not job:
                    return
                current = await self._org_temp_bytes(conn)
                delta = len(result_raw) + len(output_raw) - int(job["result_bytes"] or 0) - int(job["output_bytes"] or 0)
                if current + delta > int(self.settings.runtime_max_temp_bytes_per_org):
                    raise RuntimeQuotaExceeded("Organization runtime temporary-storage quota reached while completing job")
                await self.objects.put(result_key, result_raw); stored.append(result_key)
                if output_key:
                    await self.objects.put(output_key, output_raw); stored.append(output_key)
                await conn.execute(
                    """UPDATE runtime_jobs
                          SET status='completed',result='{}'::jsonb,result_object_key=$2,result_bytes=$3,
                              output_object_key=$4,output_bytes=$5,error=NULL,
                              lease_owner=NULL,lease_expires_at=NULL,updated_at=NOW()
                        WHERE id=$1""",
                    self._uuid(job_id), result_key, len(result_raw), output_key, len(output_raw),
                )
            for old in (job["result_object_key"], job["output_object_key"]):
                if old and old not in stored:
                    await self.objects.delete(old)
        except Exception:
            for key in stored:
                await self.objects.delete(key)
            raise

    async def fail_job(self, job_id: str, error: str) -> None:
        await self.db.p().execute(
            "UPDATE runtime_jobs SET status='failed',error=$2,lease_owner=NULL,lease_expires_at=NULL,updated_at=NOW() WHERE id=$1",
            self._uuid(job_id), error[:8000],
        )

    async def mark_cancelled(self, job_id: str) -> None:
        await self.db.p().execute(
            "UPDATE runtime_jobs SET status='cancelled',cancel_requested=TRUE,lease_owner=NULL,lease_expires_at=NULL,updated_at=NOW() WHERE id=$1",
            self._uuid(job_id),
        )

    async def request_cancel(self, job_id: str, *, owner_user_id: str | None = None, internal: bool = False) -> bool:
        if not internal and not owner_user_id:
            raise ValueError("owner_user_id is required for user-facing runtime cancellation")
        owner = str(self._uuid(owner_user_id)) if owner_user_id else None
        row = await self.db.p().fetchrow(
            """UPDATE runtime_jobs SET cancel_requested=TRUE,
                       status=CASE WHEN status='queued' THEN 'cancelled' ELSE status END,updated_at=NOW()
                 WHERE id=$1 AND ($2::uuid IS NULL OR owner_user_id=$2::uuid) RETURNING id""",
            self._uuid(job_id), owner,
        )
        return bool(row)

    async def heartbeat(self, job_id: str, worker_id: str) -> bool:
        row = await self.db.p().fetchrow(
            """UPDATE runtime_jobs SET lease_expires_at=NOW()+make_interval(secs=>$3),updated_at=NOW()
                 WHERE id=$1 AND status='running' AND lease_owner=$2 RETURNING cancel_requested""",
            self._uuid(job_id), worker_id, max(10, int(self.settings.runtime_worker_lease_seconds)),
        )
        return bool(row and row["cancel_requested"])

    async def release_for_retry(self, job_id: str, worker_id: str) -> None:
        await self.db.p().execute(
            """UPDATE runtime_jobs SET status=CASE WHEN cancel_requested THEN 'cancelled' ELSE 'queued' END,
                       lease_owner=NULL,lease_expires_at=NULL,updated_at=NOW()
                 WHERE id=$1 AND lease_owner=$2 AND status='running'""",
            self._uuid(job_id), worker_id,
        )

    async def claim_job(self, worker_id: str) -> ClaimedRuntimeJob | None:
        async with self.db.raw_pool().acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM autodraft_claim_runtime_job($1,$2,$3)",
                worker_id,
                max(10, int(self.settings.runtime_worker_lease_seconds)),
                max(1, int(self.settings.runtime_cluster_concurrency)),
            )
        if not row:
            return None
        return ClaimedRuntimeJob(str(row["job_id"]), str(row["organization_id"]), str(row["job_type"]))

    async def prune_global(self) -> None:
        async with self.db.raw_pool().acquire() as conn:
            keys = [str(row[0]) for row in await conn.fetch("SELECT * FROM autodraft_expired_runtime_object_keys()")]
            await conn.execute("SELECT autodraft_prune_runtime_state()")
        for key in keys:
            await self.objects.delete(key)

    async def create_chunk_session(
        self,
        *,
        owner_user_id: str,
        kind: str,
        total_chunks: int,
        resource_id: str | None = None,
        expected_total_size: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ttl = max(60, int(self.settings.chunk_session_ttl_seconds))
        organization_id = self._organization()
        owner = str(self._uuid(owner_user_id))
        if expected_total_size is not None and int(expected_total_size) > int(self.settings.runtime_max_temp_bytes_per_org):
            raise RuntimeQuotaExceeded("Declared upload exceeds organization temporary-storage quota")
        async with self.db.p().transaction() as conn:
            await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", f"autodraft:runtime:quota:{organization_id}")
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM runtime_chunk_sessions WHERE owner_user_id=$1::uuid AND expires_at>NOW()",
                owner,
            )
            if int(count or 0) >= max(1, int(self.settings.runtime_max_chunk_sessions_per_user)):
                raise RuntimeQuotaExceeded("User chunk-session quota reached")
            row = await conn.fetchrow(
                """INSERT INTO runtime_chunk_sessions(
                       organization_id,owner_user_id,session_kind,resource_id,total_chunks,expected_total_size,metadata,expires_at
                     ) VALUES(autodraft_current_organization_id(),$1::uuid,$2,$3,$4,$5,$6::jsonb,NOW()+make_interval(secs=>$7))
                     RETURNING id,owner_user_id,session_kind,resource_id,total_chunks,expected_total_size,metadata,created_at,expires_at""",
                owner, kind, resource_id, int(total_chunks), expected_total_size, metadata or {}, ttl,
            )
        return dict(row)

    async def put_chunk(
        self,
        session_id: str,
        chunk_index: int,
        content: str,
        *,
        owner_user_id: str,
        kind: str | None = None,
        resource_id: str | None = None,
    ) -> dict[str, Any] | None:
        sid = self._uuid(session_id)
        owner = str(self._uuid(owner_user_id))
        organization_id = self._organization()
        encoded = content.encode("utf-8")
        object_key = f"runtime/{organization_id}/chunks/{sid}/{int(chunk_index)}-{uuid.uuid4().hex}.bin"
        old_key: str | None = None
        wrote = False
        try:
            async with self.db.p().transaction() as conn:
                await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", f"autodraft:runtime:quota:{organization_id}")
                session = await conn.fetchrow(
                    """SELECT id,total_chunks,expected_total_size,session_kind,resource_id,metadata
                         FROM runtime_chunk_sessions
                        WHERE id=$1 AND owner_user_id=$2::uuid AND expires_at>NOW()
                          AND ($3::text IS NULL OR session_kind=$3)
                          AND ($4::text IS NULL OR resource_id=$4) FOR UPDATE""",
                    sid, owner, kind, resource_id,
                )
                if not session:
                    return None
                if not 0 <= int(chunk_index) < int(session["total_chunks"]):
                    raise IndexError("Invalid chunk index")
                existing = await conn.fetchrow(
                    "SELECT byte_length,object_key FROM runtime_chunks WHERE session_id=$1 AND chunk_index=$2",
                    sid, int(chunk_index),
                )
                current_session = await conn.fetchval("SELECT COALESCE(SUM(byte_length),0) FROM runtime_chunks WHERE session_id=$1", sid)
                old_bytes = int(existing["byte_length"] or 0) if existing else 0
                projected_session = int(current_session or 0) - old_bytes + len(encoded)
                expected_size = session["expected_total_size"]
                if expected_size is not None and projected_session > int(expected_size):
                    raise RuntimeQuotaExceeded("Chunk upload exceeds declared total size")
                current_org = await self._org_temp_bytes(conn)
                if current_org - old_bytes + len(encoded) > int(self.settings.runtime_max_temp_bytes_per_org):
                    raise RuntimeQuotaExceeded("Organization runtime temporary-storage quota reached")
                await self.objects.put(object_key, encoded); wrote = True
                await conn.execute(
                    """INSERT INTO runtime_chunks(organization_id,session_id,chunk_index,content,object_key,byte_length)
                         VALUES(autodraft_current_organization_id(),$1,$2,NULL,$3,$4)
                         ON CONFLICT(organization_id,session_id,chunk_index)
                         DO UPDATE SET content=NULL,object_key=EXCLUDED.object_key,byte_length=EXCLUDED.byte_length,created_at=NOW()""",
                    sid, int(chunk_index), object_key, len(encoded),
                )
                stats = await conn.fetchrow(
                    "SELECT COUNT(*)::int AS received,COALESCE(SUM(byte_length),0)::bigint AS received_bytes FROM runtime_chunks WHERE session_id=$1",
                    sid,
                )
                await conn.execute("UPDATE runtime_chunk_sessions SET updated_at=NOW() WHERE id=$1", sid)
                old_key = str(existing["object_key"]) if existing and existing["object_key"] else None
            if old_key and old_key != object_key:
                await self.objects.delete(old_key)
            result = dict(session); result.update(dict(stats)); return result
        except Exception:
            if wrote:
                await self.objects.delete(object_key)
            raise

    async def finalize_chunk_session(
        self,
        session_id: str,
        *,
        owner_user_id: str,
        kind: str | None = None,
        resource_id: str | None = None,
    ) -> tuple[dict[str, Any], list[str]] | None:
        sid = self._uuid(session_id)
        owner = str(self._uuid(owner_user_id))
        async with self.db.p().transaction() as conn:
            session = await conn.fetchrow(
                """SELECT id,session_kind,resource_id,total_chunks,expected_total_size,metadata
                     FROM runtime_chunk_sessions
                    WHERE id=$1 AND owner_user_id=$2::uuid AND expires_at>NOW()
                      AND ($3::text IS NULL OR session_kind=$3)
                      AND ($4::text IS NULL OR resource_id=$4) FOR UPDATE""",
                sid, owner, kind, resource_id,
            )
            if not session:
                return None
            chunks = await conn.fetch(
                "SELECT chunk_index,content,object_key,byte_length FROM runtime_chunks WHERE session_id=$1 ORDER BY chunk_index",
                sid,
            )
            if len(chunks) != int(session["total_chunks"]):
                raise ValueError("Not all chunks were uploaded")
            if [int(row["chunk_index"]) for row in chunks] != list(range(int(session["total_chunks"]))):
                raise ValueError("Chunk sequence is incomplete")
            total_bytes = sum(int(row["byte_length"] or 0) for row in chunks)
            if session["expected_total_size"] is not None and total_bytes > int(session["expected_total_size"]):
                raise RuntimeQuotaExceeded("Chunk upload exceeds declared total size")
            values: list[str] = []
            keys: list[str] = []
            for row in chunks:
                if row["object_key"]:
                    key = str(row["object_key"]); keys.append(key)
                    raw = await self.objects.get(key)
                    values.append(raw.decode("utf-8"))
                else:
                    values.append(str(row["content"] or ""))
            await conn.execute("DELETE FROM runtime_chunk_sessions WHERE id=$1", sid)
        for key in keys:
            await self.objects.delete(key)
        return dict(session), values
