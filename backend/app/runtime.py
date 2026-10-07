from __future__ import annotations

import base64
import gzip
import json
import logging
from typing import Any

from fastapi import Request

from .ai import AIGateway
from .auth import SecurityContext, resolve_security_context
from .config import get_settings
from .db import Database
from .ocr_service import OcrService
from .permissions import permission_for_request, require_permission
from .ollama_service import OllamaService
from .runtime_state import DurableRuntimeState
from .runtime_object_store import RuntimeObjectStore
from .binary_store import BinaryObjectStore

settings = get_settings()
log = logging.getLogger("autodraft")
db = Database(
    settings.database_url,
    allow_default_organization=(
        settings.security_mode.strip().lower() == "local" and settings.allow_local_default_organization
    ),
    default_organization_id=settings.default_organization_id,
)
ollama_provider = OllamaService(settings)
ai = AIGateway(ollama_provider, db)
ocr = OcrService(settings.ocr_language_list, settings.ocr_timeout_seconds)
# Durable queue metadata lives in PostgreSQL; large payload/blob/chunk bytes live
# in the configured object store so WAL/backups do not scale with OCR/doc size.
runtime_object_store = RuntimeObjectStore(settings.runtime_object_store_path, encryption_key=settings.object_store_encryption_key)
# Immutable application binaries use a separate durable store from ephemeral runtime payloads.
binary_object_store = BinaryObjectStore(settings.binary_object_store_path, encryption_key=settings.object_store_encryption_key)
runtime_state = DurableRuntimeState(db, settings, runtime_object_store)


def utc_iso(v: Any) -> str:
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return str(v)


def compress_ooxml(s: str) -> str:
    return base64.b64encode(gzip.compress(s.encode("utf-8"))).decode("ascii")


def decompress_ooxml(s: str) -> str:
    try:
        return gzip.decompress(base64.b64decode(s)).decode("utf-8")
    except Exception:
        return s


def dump(model: Any) -> Any:
    if hasattr(model, "model_dump"):
        return model.model_dump(by_alias=True, exclude_none=True)
    return model


def sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def authenticated_context(request: Request):
    ctx = resolve_security_context(request, settings)
    if settings.security_mode.strip().lower() == "token":
        user = await db.p().fetchrow("SELECT role,active,auth_version FROM app_users WHERE id=$1::uuid", ctx.user_id)
        if not user or not user["active"]:
            from fastapi import HTTPException
            raise HTTPException(status_code=401, detail="AutoDraft user is inactive or unavailable")
        if int(user["auth_version"] or 1) != int(ctx.auth_version):
            from fastapi import HTTPException
            raise HTTPException(status_code=401, detail="AutoDraft access token has been revoked")
        ctx = SecurityContext(ctx.organization_id, ctx.user_id, str(user["role"]), True, int(user["auth_version"] or 1))
        request.state.security = ctx
    return ctx


async def api_auth(request: Request):
    existing = getattr(request.state, "security", None)
    ctx = existing if existing is not None else await authenticated_context(request)
    if request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
        require_permission(ctx, permission_for_request(request.method, request.url.path))
    return ctx
