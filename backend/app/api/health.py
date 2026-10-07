from __future__ import annotations

from fastapi import APIRouter, Response, status

from ..ai.gateway import AIGateway
from ..db import Database


def build_health_router(db: Database, ai: AIGateway) -> APIRouter:
    router = APIRouter(prefix="/api/health", tags=["health"])

    @router.get("/live")
    async def live():
        return {"status": "ok", "runtime": "python"}

    @router.get("/ai")
    async def ai_health(response: Response):
        state = await ai.check_readiness(probe=True)
        ready = bool(state.get("ready"))
        if not ready:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return state

    @router.get("/ready")
    async def ready(response: Response):
        database_ready = False
        try:
            async with db.raw_pool().acquire() as conn:
                database_ready = bool(await conn.fetchval("SELECT 1"))
        except Exception:
            database_ready = False
        ai_state = await ai.check_readiness(probe=True)
        payload = {
            # Core readiness keeps matters/templates/manual workflows available
            # when AI is offline. AI has its own /api/health/ai readiness gate.
            "ready": bool(database_ready),
            "database": {"ready": database_ready},
            "aiFeaturesReady": bool(ai_state.get("ready")),
            "ai": ai_state,
        }
        if not database_ready:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return payload

    return router
