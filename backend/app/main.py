from __future__ import annotations
import asyncio, logging, uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from .runtime import settings, log, db, ai, ocr, runtime_state, authenticated_context, binary_object_store
from .db import Database, clear_request_organization, ensure_local_default_identity, reset_request_organization, run_migrations
from .api.health import build_health_router, build_status_router
from .api.documents import router as documents_router
from .api.templates import router as templates_router
from .api.ocr import router as ocr_router
from .api.drafting import router as drafting_router
from .api.intake import router as intake_router
from .api.matters import router as matters_router
from .api.organization import router as organization_router
from .api.document_sets import router as document_sets_router
from .api.practice import router as practice_router
from .api.fields import router as fields_router
from .api.contacts import router as contacts_router
from .api.workflows import router as workflows_router
from .api.automation import router as automation_router
from .api.authentication import router as authentication_router
from .api.integrations import router as integrations_router
from .errors import AutoDraftError
from .security import RequestBodyLimitMiddleware, SecurityHeadersMiddleware, PostgresRateLimiter, client_ip, install_sensitive_access_log_filter, normalize_correlation_id, redact_sensitive_path
from .auth import validate_security_configuration
from .runtime_worker import DurableRuntimeWorker
from .quarantine_cleanup import IntakeQuarantineJanitor
logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
install_sensitive_access_log_filter()
runtime_worker=DurableRuntimeWorker(state=runtime_state,db=db,ai=ai,ocr=ocr,settings=settings,log=log,binary_store=binary_object_store)
quarantine_janitor=IntakeQuarantineJanitor(db,retention_seconds=settings.intake_quarantine_retention_seconds,interval_seconds=settings.intake_quarantine_cleanup_interval_seconds,log=log)
@asynccontextmanager
async def lifespan(app:FastAPI):
    validate_security_configuration(settings)
    ocr.cleanup_expired(settings.ocr_job_ttl_seconds)
    migration_db = None
    try:
        if settings.migration_database_url.strip():
            migration_db = Database(settings.migration_database_url.strip())
            await migration_db.connect()
            await run_migrations(migration_db)
            if settings.security_mode.strip().lower() == "local" and settings.allow_local_default_organization:
                await ensure_local_default_identity(
                    migration_db,
                    organization_id=settings.default_organization_id,
                    user_id=settings.default_user_id,
                    role=settings.default_user_role,
                )
            await migration_db.close()
            migration_db = None
            log.info("PostgreSQL migrations applied with the dedicated migration role")
        await db.connect()
        role = await db.assert_safe_runtime_role(allow_unsafe=settings.allow_unsafe_database_role)
        if not settings.migration_database_url.strip() and role.get("unsafe_reasons"):
            await run_migrations(db)
            if settings.security_mode.strip().lower() == "local" and settings.allow_local_default_organization:
                await ensure_local_default_identity(
                    db,
                    organization_id=settings.default_organization_id,
                    user_id=settings.default_user_id,
                    role=settings.default_user_role,
                )
            log.info("PostgreSQL migrations applied using the explicitly allowed local development role")
        await db.assert_rls_hardening_migrated()
        if role.get("unsafe_reasons"):
            log.warning("PostgreSQL runtime role %s is unsafe but explicitly allowed for local development: %s", role.get("role_name"), ", ".join(role.get("unsafe_reasons") or []))
        else: log.info("PostgreSQL runtime role %s passed RLS safety checks", role.get("role_name"))
    except Exception:
        if migration_db is not None:
            await migration_db.close()
        await db.close()
        raise
    if settings.ollama_validate_on_startup:
        readiness = await ai.check_readiness()
        if not readiness.get("ready"):
            message = readiness.get("error") or "Configured Ollama model is unavailable."
            if settings.ollama_require_model_on_startup:
                await db.close()
                raise RuntimeError(message)
            log.warning("Ollama readiness check: %s", message)
        else:
            log.info("Ollama ready with model %s", settings.ollama_model)
    worker_mode=(settings.runtime_worker_mode or "auto").strip().lower()
    if worker_mode not in {"auto","embedded","external"}:
        await db.close(); raise RuntimeError("RUNTIME_WORKER_MODE must be auto, embedded, or external")
    embedded = worker_mode == "embedded" or (worker_mode == "auto" and settings.security_mode.strip().lower() == "local")
    if embedded:
        await runtime_worker.start(); log.info("Embedded runtime worker started as %s (cluster cap=%s)", runtime_worker.worker_id, settings.runtime_cluster_concurrency)
    else: log.info("API process will not execute runtime jobs; use `python -m app.runtime_worker_process` for dedicated workers")
    await quarantine_janitor.start()
    try:
        yield
    finally:
        await quarantine_janitor.stop()
        if embedded:
            await runtime_worker.stop()
        await ai.close(); await db.close()
app=FastAPI(title="AutoDraft Backend",version="1.3.0",lifespan=lifespan)
app.include_router(build_health_router(db, ai))
app.include_router(documents_router)
app.include_router(templates_router)
app.include_router(ocr_router)
app.include_router(drafting_router)
app.include_router(intake_router)
app.include_router(matters_router)
app.include_router(organization_router)
app.include_router(document_sets_router)
app.include_router(practice_router)
app.include_router(fields_router)
app.include_router(contacts_router)
app.include_router(workflows_router)
app.include_router(automation_router)
app.include_router(authentication_router)
app.include_router(integrations_router)
app.include_router(build_status_router(db, ai, settings))
@app.exception_handler(AutoDraftError)
async def autodraft_error_handler(request: Request, exc: AutoDraftError):
    request_id = normalize_correlation_id(getattr(request.state, "request_id", None) or request.headers.get("X-Correlation-ID"), fallback=uuid.uuid4().hex)
    return JSONResponse(status_code=exc.status_code,content={"error":{"code":exc.code,"message":exc.message,"recoverable":exc.recoverable,"requestId":request_id}},headers={"X-Correlation-ID":request_id})
app.add_middleware(SecurityHeadersMiddleware, production=settings.security_mode.strip().lower()=="token", hsts_seconds=settings.security_hsts_seconds, enable_hsts=settings.security_enable_hsts, frame_ancestors=settings.security_frame_ancestors)
app.add_middleware(RequestBodyLimitMiddleware,max_bytes=settings.max_request_body_bytes,public_max_bytes=settings.max_public_request_body_bytes,public_upload_max_bytes=settings.max_public_upload_body_bytes,json_max_bytes=settings.max_json_request_body_bytes,binary_upload_max_bytes=settings.max_binary_upload_body_bytes)
rate_limiter=PostgresRateLimiter(db,limit=settings.rate_limit_requests,window_seconds=settings.rate_limit_window_seconds,lease_size=settings.rate_limit_lease_size,fallback_limit=settings.rate_limit_fallback_requests,db_retry_seconds=settings.rate_limit_db_retry_seconds)
origins=settings.cors_origin_list
if settings.security_mode.strip().lower()=="local" and not origins:
    origins=["https://localhost:3000","http://localhost:3000","https://127.0.0.1:3000","http://127.0.0.1:3000"]
app.add_middleware(CORSMiddleware,allow_origins=origins,allow_credentials=bool(origins),allow_methods=["GET","POST","PUT","PATCH","DELETE","OPTIONS"],allow_headers=["Content-Type","Authorization","X-Correlation-ID","X-Organization-ID","X-User-ID","X-User-Role"])
@app.middleware("http")
async def request_observability(request:Request,call_next):
    tenant_token=clear_request_organization()
    correlation=normalize_correlation_id(request.headers.get("X-Correlation-ID"), fallback=uuid.uuid4().hex)
    request.state.request_id=correlation
    client=client_ip(request, settings.trusted_proxy_list)
    path=request.url.path
    safe_path=redact_sensitive_path(path)
    protected = path.startswith("/api/") and not (path.startswith("/api/health") or path.startswith("/api/auth/office-exchange") or path.startswith("/api/intake/public/") or path.startswith("/api/workflows/public/"))
    try:
        if protected:
            await authenticated_context(request)
        rate_limited = path.startswith("/api/") and not path.startswith("/api/health")
        if rate_limited and not await rate_limiter.allow(f"{client}:{request.method.upper()}:{safe_path.split('?',1)[0]}"):
            return JSONResponse(status_code=429,content={"error":{"code":"RATE_LIMITED","message":"Too many requests","recoverable":True,"requestId":correlation}},headers={"X-Correlation-ID":correlation})
        started=datetime.now(timezone.utc)
        mutation = protected and request.method.upper() in {"POST","PUT","PATCH","DELETE"}
        try:
            if mutation:
                async with db.p().request_transaction() as request_tx:
                    response=await call_next(request)
                    if response.status_code < 400:
                        ctx=getattr(request.state,"security",None)
                        organization_id = ctx.organization_id if ctx else settings.default_organization_id; user_id = ctx.user_id if ctx else settings.default_user_id
                        await request_tx.connection.execute(
                            """INSERT INTO audit_events(organization_id,actor_user_id,event_type,request_id,ip_address,details)
                               VALUES($1::uuid,(SELECT id FROM app_users WHERE id=$2::uuid AND organization_id=$1::uuid),$3,$4,$5::inet,$6::jsonb)""",
                            organization_id,
                            user_id,
                            f"HTTP_{request.method.upper()}",correlation,client,
                            {"path":safe_path,"status":response.status_code},
                        )
                    else:
                        request_tx.rollback()  # never commit partial DB changes from a failed mutation
            else:
                response=await call_next(request)
        except Exception as exc:
            log.exception("[%s] request failed: %s %s",correlation,request.method,safe_path)
            if exc.__class__.__module__.startswith("asyncpg"):
                return JSONResponse(status_code=503,content={"error":{"code":"DATABASE_UNAVAILABLE","message":"The database is unavailable.","recoverable":True,"requestId":correlation}},headers={"X-Correlation-ID":correlation})
            raise
        elapsed=(datetime.now(timezone.utc)-started).total_seconds()*1000
        response.headers["X-Correlation-ID"]=correlation
        log.info("[%s] %s %s -> %s %.1fms",correlation,request.method,safe_path,response.status_code,elapsed)
        return response
    finally:
        reset_request_organization(tenant_token)
