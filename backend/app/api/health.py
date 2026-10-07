from __future__ import annotations

from fastapi import APIRouter, Response, status

from ..ai.gateway import AIGateway
from ..db import Database
from ..ocr_service import dependency_status


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


def build_status_router(db: Database, ai: AIGateway, settings) -> APIRouter:
    router = APIRouter(tags=["status"])

    @router.get("/")
    async def root():
        return {"name": "AutoDraft Backend", "runtime": "Python/FastAPI", "version": "1.3.0"}

    @router.get("/health")
    async def health():
        database_ok = False
        try:
            async with db.raw_pool().acquire() as conn:
                database_ok = bool(await conn.fetchval("SELECT 1"))
        except Exception:
            database_ok = False
        try:
            state = await dependency_status(tuple(settings.ocr_language_list))
            ocr_payload = {"ready": state.ready, "ocrmypdf": state.ocrmypdf, "tesseract": state.tesseract, "missingLanguages": list(state.missing_languages)}
        except Exception as exc:
            ocr_payload = {"ready": False, "error": str(exc)}
        return {"status": "ok" if database_ok else "degraded", "runtime": "python", "database": {"ready": database_ok}, "ollama": ai.readiness, "ocr": ocr_payload}

    return router
