from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..auth import create_hmac_token, require_role, verify_entra_access_token
from ..runtime import api_auth, db, settings

router = APIRouter(tags=["authentication"])


class IdentityBindingRequest(BaseModel):
    tenant_id: str = Field(alias="tenantId")
    object_id: str = Field(alias="objectId")
    user_id: str = Field(alias="userId")
    provider: Literal["entra"] = "entra"

    model_config = {"populate_by_name": True}


def _subject(tenant_id: str, object_id: str) -> str:
    try:
        return f"{uuid.UUID(tenant_id)}:{uuid.UUID(object_id)}".lower()
    except ValueError as exc:
        raise HTTPException(400, "Invalid Entra tenant/object ID") from exc


@router.post("/api/auth/office-exchange")
async def office_exchange(request: Request):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "Office authentication token required")
    office_token = auth[7:].strip()
    claims = await asyncio.to_thread(verify_entra_access_token, office_token, settings)
    subject = _subject(str(claims.get("tid") or ""), str(claims.get("oid") or ""))

    async with db.raw_pool().acquire() as conn:
        mapping = await conn.fetchrow(
            "SELECT organization_id,user_id FROM public_user_identities WHERE provider='entra' AND subject=$1",
            subject,
        )
        if not mapping:
            raise HTTPException(403, "This Microsoft account is not provisioned for AutoDraft")
        async with conn.transaction():
            await conn.execute("SELECT set_config('autodraft.organization_id',$1,true)", str(mapping["organization_id"]))
            user = await conn.fetchrow(
                "SELECT id,organization_id,email,display_name,role,active,auth_version FROM app_users WHERE id=$1 AND organization_id=$2",
                mapping["user_id"], mapping["organization_id"],
            )
    if not user or not user["active"]:
        raise HTTPException(403, "AutoDraft user is inactive")

    token = create_hmac_token(
        secret=settings.auth_hmac_secret,
        organization_id=str(user["organization_id"]),
        user_id=str(user["id"]),
        role=str(user["role"]),
        auth_version=int(user["auth_version"] or 1),
        ttl_seconds=settings.auth_token_ttl_seconds,
    )
    expires_at = int(datetime.now(timezone.utc).timestamp()) + int(settings.auth_token_ttl_seconds)
    return {
        "accessToken": token,
        "expiresAt": expires_at,
        "user": {
            "id": str(user["id"]), "organizationId": str(user["organization_id"]),
            "email": user["email"], "displayName": user["display_name"], "role": user["role"],
        },
    }


@router.post("/api/auth/identity-bindings")
async def bind_office_identity(req: IdentityBindingRequest, ctx=Depends(api_auth)):
    require_role(ctx, "admin")
    if str(uuid.UUID(req.tenant_id)).lower() != str(settings.entra_tenant_id).lower():
        raise HTTPException(400, "Identity tenant does not match configured ENTRA_TENANT_ID")
    user_id = uuid.UUID(req.user_id)
    subject = _subject(req.tenant_id, req.object_id)
    user = await db.p().fetchrow("SELECT id,organization_id,active FROM app_users WHERE id=$1", user_id)
    if not user:
        raise HTTPException(404, "AutoDraft user not found")
    await db.p().execute(
        """INSERT INTO public_user_identities(provider,subject,organization_id,user_id)
           VALUES('entra',$1,$2,$3)
           ON CONFLICT(provider,subject) DO UPDATE
           SET organization_id=EXCLUDED.organization_id,user_id=EXCLUDED.user_id""",
        subject, user["organization_id"], user_id,
    )
    return {"provider": "entra", "subject": subject, "userId": str(user_id)}


@router.post("/api/auth/users/{user_id}/revoke-sessions")
async def revoke_user_sessions(user_id: str, ctx=Depends(api_auth)):
    require_role(ctx, "admin")
    try:
        target = uuid.UUID(user_id)
    except ValueError as exc:
        raise HTTPException(400, "Invalid AutoDraft user ID") from exc
    row = await db.p().fetchrow(
        "UPDATE app_users SET auth_version=auth_version+1,updated_at=NOW() WHERE id=$1 RETURNING id,auth_version",
        target,
    )
    if not row:
        raise HTTPException(404, "AutoDraft user not found")
    return {"userId": str(row["id"]), "revoked": True, "authVersion": int(row["auth_version"])}
