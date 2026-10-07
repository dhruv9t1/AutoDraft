from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator

from ..runtime import api_auth, db, settings, utc_iso
from ..auth import require_role
from ..repositories.webhooks import WebhookRepository
from ..webhook_security import WebhookSecretBox, WebhookSecurityError, generate_webhook_secret, validate_webhook_url

router = APIRouter(prefix="/api/integrations", tags=["integrations"])
repo = WebhookRepository(db)


class WebhookEndpointCreate(BaseModel):
    url: str
    description: str = Field(default="", max_length=500)
    event_types: list[str] = Field(default_factory=list, alias="eventTypes", max_length=100)

    @field_validator("event_types")
    @classmethod
    def validate_event_types(cls, values: list[str]) -> list[str]:
        cleaned=[]
        for value in values:
            v=value.strip()
            if not v or len(v)>160:
                raise ValueError("Webhook event types must be non-empty and at most 160 characters")
            if v not in cleaned:
                cleaned.append(v)
        return cleaned


class WebhookEndpointUpdate(BaseModel):
    url: str | None = None
    description: str | None = Field(default=None, max_length=500)
    event_types: list[str] | None = Field(default=None, alias="eventTypes", max_length=100)
    active: bool | None = None


class WebhookRetryResponse(BaseModel):
    queued: bool


def _endpoint(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id":str(row["id"]),"url":row["url"],"description":row.get("description") or "",
        "eventTypes":row.get("event_types") or [],"active":bool(row.get("active")),
        "createdByUserId":str(row["created_by_user_id"]) if row.get("created_by_user_id") else None,
        "createdAt":utc_iso(row.get("created_at")),"updatedAt":utc_iso(row.get("updated_at")),
    }


def _delivery(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id":str(row["id"]),"eventId":str(row["event_id"]),"endpointId":str(row["endpoint_id"]),
        "eventType":row.get("event_type"),"endpointUrl":row.get("endpoint_url"),
        "idempotencyKey":row.get("idempotency_key"),"status":row.get("status"),
        "attemptCount":int(row.get("attempt_count") or 0),"availableAt":utc_iso(row.get("available_at")),
        "lastHttpStatus":row.get("last_http_status"),"lastError":row.get("last_error"),
        "deliveredAt":utc_iso(row.get("delivered_at")) if row.get("delivered_at") else None,
        "createdAt":utc_iso(row.get("created_at")),"updatedAt":utc_iso(row.get("updated_at")),
    }


def _admin(ctx):
    require_role(ctx,"admin")
    return ctx


def _box() -> WebhookSecretBox:
    try:
        return WebhookSecretBox(settings.webhook_secret_encryption_key)
    except WebhookSecurityError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.get("/webhooks")
async def list_webhooks(ctx=Depends(api_auth)):
    _admin(ctx)
    return [_endpoint(row) for row in await repo.list_endpoints()]


@router.post("/webhooks", status_code=201)
async def create_webhook(req: WebhookEndpointCreate, ctx=Depends(api_auth)):
    _admin(ctx)
    try:
        url=validate_webhook_url(req.url,production=settings.security_mode.strip().lower()=="token")
    except WebhookSecurityError as exc:
        raise HTTPException(422,str(exc)) from exc
    endpoint_id=str(uuid.uuid4())
    secret=generate_webhook_secret()
    row=await repo.create_endpoint(
        endpoint_id=endpoint_id,url=url,description=req.description.strip(),event_types=req.event_types,
        secret_ciphertext=_box().encrypt(endpoint_id,secret),created_by_user_id=ctx.user_id,
    )
    result=_endpoint(row)
    result["signingSecret"]=secret  # returned exactly once
    return result


@router.patch("/webhooks/{endpoint_id}")
async def update_webhook(endpoint_id: str, req: WebhookEndpointUpdate, ctx=Depends(api_auth)):
    _admin(ctx)
    url=req.url
    if url is not None:
        try:
            url=validate_webhook_url(url,production=settings.security_mode.strip().lower()=="token")
        except WebhookSecurityError as exc:
            raise HTTPException(422,str(exc)) from exc
    event_types=req.event_types
    if event_types is not None:
        event_types=WebhookEndpointCreate(url=url or "https://placeholder.invalid",eventTypes=event_types).event_types
    row=await repo.update_endpoint(endpoint_id,url=url,description=req.description,event_types=event_types,active=req.active)
    if not row: raise HTTPException(404,"Webhook endpoint not found")
    return _endpoint(row)


@router.post("/webhooks/{endpoint_id}/rotate-secret")
async def rotate_webhook_secret(endpoint_id: str, ctx=Depends(api_auth)):
    _admin(ctx)
    secret=generate_webhook_secret()
    if not await repo.rotate_secret(endpoint_id,_box().encrypt(endpoint_id,secret)):
        raise HTTPException(404,"Webhook endpoint not found")
    return {"id":endpoint_id,"signingSecret":secret}


@router.delete("/webhooks/{endpoint_id}", status_code=204)
async def deactivate_webhook(endpoint_id: str, ctx=Depends(api_auth)):
    _admin(ctx)
    if not await repo.deactivate_endpoint(endpoint_id): raise HTTPException(404,"Webhook endpoint not found")
    return Response(status_code=204)


@router.get("/webhook-deliveries")
async def list_webhook_deliveries(status: str | None=None, limit: int=100, ctx=Depends(api_auth)):
    _admin(ctx)
    if status not in {None,"pending","leased","delivered","dead"}: raise HTTPException(422,"Invalid delivery status")
    return [_delivery(row) for row in await repo.list_deliveries(limit=limit,status=status)]


@router.get("/webhook-deliveries/{delivery_id}/attempts")
async def list_webhook_attempts(delivery_id: str, ctx=Depends(api_auth)):
    _admin(ctx)
    rows=await repo.attempts(delivery_id)
    return [{
        "attemptNumber":int(r["attempt_number"]),"requestedAt":utc_iso(r["requested_at"]),
        "completedAt":utc_iso(r["completed_at"]),"httpStatus":r.get("http_status"),
        "error":r.get("error"),"responseExcerpt":r.get("response_excerpt"),
    } for r in rows]


@router.post("/webhook-deliveries/{delivery_id}/retry", response_model=WebhookRetryResponse)
async def retry_webhook_delivery(delivery_id: str, ctx=Depends(api_auth)):
    _admin(ctx)
    if not await repo.retry_delivery(delivery_id): raise HTTPException(409,"Delivery is not dead or does not exist")
    return WebhookRetryResponse(queued=True)
