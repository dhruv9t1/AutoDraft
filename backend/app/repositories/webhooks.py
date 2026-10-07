from __future__ import annotations

import uuid
from typing import Any

from ..db import Database


class WebhookRepository:
    def __init__(self, db: Database):
        self.db = db

    async def list_endpoints(self) -> list[dict[str, Any]]:
        rows = await self.db.p().fetch(
            """SELECT id,url,description,event_types,active,created_by_user_id,created_at,updated_at
                 FROM webhook_endpoints
                WHERE organization_id=autodraft_current_organization_id()
                ORDER BY created_at,id"""
        )
        return [dict(row) for row in rows]

    async def create_endpoint(
        self,
        *,
        endpoint_id: str,
        url: str,
        description: str,
        event_types: list[str],
        secret_ciphertext: str,
        created_by_user_id: str,
    ) -> dict[str, Any]:
        row = await self.db.p().fetchrow(
            """INSERT INTO webhook_endpoints(
                    id,organization_id,url,description,event_types,secret_ciphertext,created_by_user_id
                 ) VALUES($1::uuid,autodraft_current_organization_id(),$2,$3,$4::jsonb,$5,$6::uuid)
                 RETURNING id,url,description,event_types,active,created_by_user_id,created_at,updated_at""",
            endpoint_id,
            url,
            description,
            event_types,
            secret_ciphertext,
            created_by_user_id,
        )
        return dict(row)

    async def update_endpoint(
        self,
        endpoint_id: str,
        *,
        url: str | None = None,
        description: str | None = None,
        event_types: list[str] | None = None,
        active: bool | None = None,
    ) -> dict[str, Any] | None:
        row = await self.db.p().fetchrow(
            """UPDATE webhook_endpoints
                  SET url=COALESCE($2,url),
                      description=COALESCE($3,description),
                      event_types=COALESCE($4::jsonb,event_types),
                      active=COALESCE($5,active),
                      updated_at=NOW()
                WHERE organization_id=autodraft_current_organization_id() AND id=$1::uuid
                RETURNING id,url,description,event_types,active,created_by_user_id,created_at,updated_at""",
            endpoint_id,
            url,
            description,
            event_types,
            active,
        )
        return dict(row) if row else None

    async def rotate_secret(self, endpoint_id: str, ciphertext: str) -> bool:
        result = await self.db.p().execute(
            """UPDATE webhook_endpoints SET secret_ciphertext=$2,updated_at=NOW()
                WHERE organization_id=autodraft_current_organization_id() AND id=$1::uuid""",
            endpoint_id,
            ciphertext,
        )
        return result.endswith("1")

    async def deactivate_endpoint(self, endpoint_id: str) -> bool:
        async with self.db.p().acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """UPDATE webhook_endpoints SET active=FALSE,updated_at=NOW()
                        WHERE organization_id=autodraft_current_organization_id() AND id=$1::uuid
                        RETURNING id""",
                    endpoint_id,
                )
                if not row:
                    return False
                await conn.execute(
                    """UPDATE webhook_deliveries
                          SET status='dead',lease_owner=NULL,lease_expires_at=NULL,
                              last_error='Webhook endpoint disabled',updated_at=NOW()
                        WHERE organization_id=autodraft_current_organization_id()
                          AND endpoint_id=$1::uuid AND status IN ('pending','leased')""",
                    endpoint_id,
                )
                return True

    async def list_deliveries(self, *, limit: int = 100, status: str | None = None) -> list[dict[str, Any]]:
        rows = await self.db.p().fetch(
            """SELECT d.id,d.event_id,d.endpoint_id,d.idempotency_key,d.status,d.attempt_count,
                      d.available_at,d.last_http_status,d.last_error,d.delivered_at,d.created_at,d.updated_at,
                      e.event_type,w.url AS endpoint_url
                 FROM webhook_deliveries d
                 JOIN outbox_events e ON e.organization_id=d.organization_id AND e.id=d.event_id
                 JOIN webhook_endpoints w ON w.organization_id=d.organization_id AND w.id=d.endpoint_id
                WHERE d.organization_id=autodraft_current_organization_id()
                  AND ($1::text IS NULL OR d.status=$1)
                ORDER BY d.created_at DESC,d.id DESC
                LIMIT $2""",
            status,
            max(1, min(int(limit), 500)),
        )
        return [dict(row) for row in rows]

    async def retry_delivery(self, delivery_id: str) -> bool:
        exists = await self.db.p().fetchval(
            """SELECT EXISTS(SELECT 1 FROM webhook_deliveries
                 WHERE organization_id=autodraft_current_organization_id() AND id=$1::uuid AND status='dead')""",
            delivery_id,
        )
        if not exists:
            return False
        await self.db.p().execute("SELECT autodraft_retry_webhook_delivery($1::uuid)", delivery_id)
        return True

    async def attempts(self, delivery_id: str) -> list[dict[str, Any]]:
        rows = await self.db.p().fetch(
            """SELECT a.attempt_number,a.requested_at,a.completed_at,a.http_status,a.error,a.response_excerpt
                 FROM webhook_delivery_attempts a
                 JOIN webhook_deliveries d ON d.organization_id=a.organization_id AND d.id=a.delivery_id
                WHERE a.organization_id=autodraft_current_organization_id() AND a.delivery_id=$1::uuid
                ORDER BY a.attempt_number""",
            delivery_id,
        )
        return [dict(row) for row in rows]


class WebhookWorkerRepository:
    """Cross-tenant worker access is limited to SECURITY DEFINER queue functions."""

    def __init__(self, db: Database):
        self.db = db

    async def prepare(self, limit: int) -> int:
        async with self.db.raw_pool().acquire() as conn:
            return int(await conn.fetchval("SELECT autodraft_prepare_webhook_deliveries($1)", int(limit)) or 0)

    async def claim(self, worker_id: str, lease_seconds: int) -> dict[str, Any] | None:
        async with self.db.raw_pool().acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM autodraft_claim_webhook_delivery($1,$2)", worker_id, int(lease_seconds))
        return dict(row) if row else None

    async def finish(
        self,
        delivery_id: str,
        worker_id: str,
        *,
        success: bool,
        retryable: bool,
        http_status: int | None,
        error: str | None,
        response_excerpt: str | None,
        max_attempts: int,
        backoff_base_seconds: int,
        backoff_max_seconds: int,
    ) -> str:
        async with self.db.raw_pool().acquire() as conn:
            return str(
                await conn.fetchval(
                    """SELECT autodraft_finish_webhook_delivery(
                           $1::uuid,$2,$3,$4,$5,$6,$7,$8,$9,$10
                       )""",
                    delivery_id,
                    worker_id,
                    success,
                    retryable,
                    http_status,
                    error,
                    response_excerpt,
                    int(max_attempts),
                    int(backoff_base_seconds),
                    int(backoff_max_seconds),
                )
            )
