from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response

from ..models import BoilerplateCreateRequest, BoilerplateEntry, OrganizationAIPolicyUpdateRequest
from ..runtime import api_auth, db, settings, utc_iso
from ..auth import require_role
from ..repositories.ai_governance import AIGovernanceRepository
from ..services.organization_service import get_boilerplate_entries, remove_boilerplate_entry, save_boilerplate_entry

router = APIRouter(tags=["organization"])
ai_governance = AIGovernanceRepository(db)


@router.get("/api/organization/boilerplate", dependencies=[Depends(api_auth)])
async def list_organization_boilerplate():
    return [BoilerplateEntry.model_validate(row) for row in await get_boilerplate_entries(db)]


@router.post("/api/organization/boilerplate", dependencies=[Depends(api_auth)])
async def create_organization_boilerplate(req: BoilerplateCreateRequest):
    try:
        row = await save_boilerplate_entry(db, value=req.value, label=req.label, kind=req.kind)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return BoilerplateEntry.model_validate(row)


@router.delete("/api/organization/boilerplate/{entry_id}", status_code=204, dependencies=[Depends(api_auth)])
async def delete_organization_boilerplate(entry_id: str):
    await remove_boilerplate_entry(db, entry_id)
    return Response(status_code=204)


@router.get("/api/organization/ai-policy")
async def get_ai_policy(ctx=Depends(api_auth)):
    require_role(ctx, "admin")
    row=await ai_governance.policy()
    return {
        "externalSystem1Enabled":bool(row.get("external_system1_enabled")),
        "provider":row.get("provider") or "off",
        "providerModel":row.get("provider_model") or "",
        "consentNote":row.get("consent_note") or "",
        "consentedByUserId":str(row.get("consented_by_user_id")) if row.get("consented_by_user_id") else None,
        "consentedAt":utc_iso(row.get("consented_at")) if row.get("consented_at") else None,
        "metadata":row.get("metadata") or {},
        "configuredProviderAvailable":bool(settings.system1_provider.strip().lower()=="jev" and settings.jev_api_key),
        "configuredModel":settings.jev_model,
    }

@router.put("/api/organization/ai-policy")
async def update_ai_policy(req:OrganizationAIPolicyUpdateRequest,ctx=Depends(api_auth)):
    require_role(ctx,"admin")
    if req.external_system1_enabled:
        if settings.system1_provider.strip().lower()!="jev" or not settings.jev_api_key:
            raise HTTPException(409,"External Jev provider is not configured on this deployment")
        if req.provider!="jev":
            raise HTTPException(422,"Enabled external System-1 policy must select jev")
        if req.provider_model and req.provider_model!=settings.jev_model:
            raise HTTPException(422,"Tenant policy cannot select an unconfigured external model")
    try:
        row=await ai_governance.update_policy(
            enabled=req.external_system1_enabled,provider=req.provider,provider_model=req.provider_model or settings.jev_model if req.external_system1_enabled else "",
            consent_note=req.consent_note,user_id=ctx.user_id,metadata=req.metadata,
        )
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc
    return {"externalSystem1Enabled":bool(row["external_system1_enabled"]),"provider":row["provider"],"providerModel":row["provider_model"],"consentNote":row["consent_note"],"consentedByUserId":str(row["consented_by_user_id"]) if row["consented_by_user_id"] else None,"consentedAt":utc_iso(row["consented_at"]) if row["consented_at"] else None,"metadata":row["metadata"] or {}}
