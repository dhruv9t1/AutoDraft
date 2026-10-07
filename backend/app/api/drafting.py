from __future__ import annotations
from fastapi import APIRouter, Depends
from ..runtime import *
from ..models import *
from ..drafting_pipeline import run_drafting_pipeline

router=APIRouter(tags=["drafting"])
@router.post("/api/drafting/chat",response_model=DraftResult,dependencies=[Depends(api_auth)])
async def drafting_chat(req:DraftingChatRequest):
 return await run_drafting_pipeline(ai,req)
