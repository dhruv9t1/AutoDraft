from __future__ import annotations

from typing import Any


async def emit_domain_event(
    conn,
    *,
    aggregate_type: str,
    aggregate_id,
    event_type: str,
    payload: dict[str, Any] | None = None,
    matter_id=None,
) -> None:
    """Persist a tenant-scoped domain event inside the caller's transaction.

    The legal-data write never depends on an external webhook. The dedicated webhook dispatcher expands pending rows into endpoint deliveries
    and publishes them with leasing, retries, signatures and idempotency keys.
    """
    await conn.execute(
        """
        INSERT INTO outbox_events(
          organization_id,aggregate_type,aggregate_id,matter_id,event_type,payload
        )
        VALUES(
          autodraft_current_organization_id(),
          $1,$2,$3,$4,$5::jsonb
        )
        """,
        aggregate_type,
        aggregate_id,
        matter_id,
        event_type,
        payload or {},
    )
