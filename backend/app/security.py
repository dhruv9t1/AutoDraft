from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import logging
import re
import secrets
import time
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


_TOKEN_PATH_PATTERNS = (
    re.compile(r"^(/api/intake/public/)[^/]+"),
    re.compile(r"^(/api/intake/)[^/]+"),
    re.compile(r"^(/intake/)[^/]+"),
    re.compile(r"^(/api/workflows/public/)[^/]+"),
    re.compile(r"^(/workflow/)[^/]+"),
)

_CORRELATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def normalize_correlation_id(value: str | None, *, fallback: str | None = None) -> str:
    """Return a bounded, log/header-safe correlation ID.

    Callers may supply IDs for end-to-end tracing, but arbitrary header bytes,
    whitespace/control characters, or unbounded values must never flow into
    logs, audit rows, or response headers. Invalid input is replaced with a
    server-generated/fallback identifier.
    """
    raw = str(value or "")
    candidate = raw.strip()
    if candidate and raw == candidate and _CORRELATION_ID_PATTERN.fullmatch(candidate):
        return candidate
    generated = str(fallback or secrets.token_hex(16)).strip()
    if _CORRELATION_ID_PATTERN.fullmatch(generated):
        return generated
    return secrets.token_hex(16)


def redact_sensitive_path(path: str) -> str:
    value = str(path or "")
    for pattern in _TOKEN_PATH_PATTERNS:
        redacted, count = pattern.subn(r"\1[REDACTED]", value, count=1)
        if count:
            return redacted
    return value


class SensitivePathLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            mutable = list(args); mutable[2] = redact_sensitive_path(mutable[2]); record.args = tuple(mutable)
        elif isinstance(record.msg, str):
            record.msg = redact_sensitive_path(record.msg)
        return True


def install_sensitive_access_log_filter() -> None:
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(existing, SensitivePathLogFilter) for existing in logger.filters):
        logger.addFilter(SensitivePathLogFilter())


class RequestBodyTooLarge(Exception):
    pass


class RequestBodyLimitMiddleware:
    def __init__(self, app, *, max_bytes: int, public_max_bytes: int, public_upload_max_bytes: int | None = None, json_max_bytes:int|None=None, binary_upload_max_bytes:int|None=None):
        self.app = app; self.max_bytes=max(1,int(max_bytes)); self.public_max_bytes=max(1,int(public_max_bytes)); self.public_upload_max_bytes=max(1,int(public_upload_max_bytes or public_max_bytes)); self.json_max_bytes=max(1,int(json_max_bytes or max_bytes)); self.binary_upload_max_bytes=max(1,int(binary_upload_max_bytes or max_bytes))

    @staticmethod
    def _is_public_submission(path: str) -> bool:
        return path.startswith("/api/intake/public/") or path.startswith("/api/workflows/public/")

    @staticmethod
    def _is_public_file_upload(path: str) -> bool:
        return path.startswith("/api/intake/public/") and "/files/" in path

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http": return await self.app(scope, receive, send)
        path=str(scope.get("path") or "")
        headers={k.lower():v for k,v in scope.get("headers") or []}
        content_type=headers.get(b"content-type",b"").decode("latin1").lower()
        if self._is_public_file_upload(path): limit=self.public_upload_max_bytes
        elif content_type.startswith("multipart/form-data") or content_type.startswith("application/octet-stream"):
            limit=self.binary_upload_max_bytes
        elif "application/json" in content_type:
            limit=min(self.max_bytes,self.json_max_bytes)
        else: limit=self.public_max_bytes if self._is_public_submission(path) else self.max_bytes
        raw_length=headers.get(b"content-length",b"")
        if raw_length:
            try:
                if int(raw_length)>limit:
                    return await JSONResponse(status_code=413,content={"detail":"Request body is too large"})(scope,receive,send)
            except ValueError: pass
        total=0
        response_started=False
        response_complete=False
        async def limited_receive():
            nonlocal total
            message=await receive()
            if message.get("type")=="http.request":
                total += len(message.get("body") or b"")
                if total>limit: raise RequestBodyTooLarge
            return message
        async def tracked_send(message):
            nonlocal response_started,response_complete
            if message.get("type")=="http.response.start":
                response_started=True
            elif message.get("type")=="http.response.body" and not message.get("more_body",False):
                response_complete=True
            await send(message)
        try:
            await self.app(scope,limited_receive,tracked_send)
        except RequestBodyTooLarge:
            if response_started:
                # ASGI forbids emitting a second response start. End an already
                # started partial response instead of attempting an invalid 413.
                if not response_complete:
                    await send({"type":"http.response.body","body":b"","more_body":False})
                return
            await JSONResponse(status_code=413,content={"detail":"Request body is too large"})(scope,receive,send)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, production: bool, hsts_seconds: int, enable_hsts: bool, frame_ancestors: str):
        super().__init__(app); self.production=production; self.hsts_seconds=max(0,int(hsts_seconds)); self.enable_hsts=enable_hsts; self.frame_ancestors=frame_ancestors.strip() or "'none'"

    async def dispatch(self, request: Request, call_next):
        nonce=secrets.token_urlsafe(18); request.state.csp_nonce=nonce
        response=await call_next(request)
        response.headers.setdefault("X-Content-Type-Options","nosniff")
        response.headers.setdefault("Referrer-Policy","no-referrer")
        response.headers.setdefault("Permissions-Policy","camera=(), microphone=(), geolocation=(), usb=()")
        response.headers.setdefault("Cross-Origin-Resource-Policy","same-site")
        response.headers.setdefault("Content-Security-Policy", f"default-src 'self'; base-uri 'self'; object-src 'none'; form-action 'self'; frame-ancestors {self.frame_ancestors}; script-src 'self' 'nonce-{nonce}'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'")
        if self.production and self.enable_hsts:
            response.headers.setdefault("Strict-Transport-Security",f"max-age={self.hsts_seconds}; includeSubDomains")
        return response


def _networks(values: list[str]):
    result=[]
    for value in values:
        try: result.append(ipaddress.ip_network(value,strict=False))
        except ValueError: continue
    return result


def client_ip(request: Request, trusted_proxy_values: list[str]) -> str:
    direct=request.client.host if request.client else "unknown"
    try: direct_ip=ipaddress.ip_address(direct)
    except ValueError: return direct
    networks=_networks(trusted_proxy_values)
    if not any(direct_ip in network for network in networks): return direct
    forwarded=[]
    for value in request.headers.get("x-forwarded-for","").split(","):
        value=value.strip()
        if value:
            try: forwarded.append(ipaddress.ip_address(value))
            except ValueError: continue
    # Walk from the trusted peer backwards and discard only configured proxy hops.
    # This prevents a client-supplied leftmost X-Forwarded-For value from winning
    # when a trusted reverse proxy appends to an existing header.
    chain=forwarded+[direct_ip]
    for candidate in reversed(chain):
        if any(candidate in network for network in networks):
            continue
        return str(candidate)
    if forwarded: return str(forwarded[0])
    real=request.headers.get("x-real-ip","").strip()
    try: return str(ipaddress.ip_address(real)) if real else direct
    except ValueError: return direct


class PostgresRateLimiter:
    """Shared fixed-window limiter using small PostgreSQL-backed permit leases.

    Workers reserve a bounded block of permits atomically, then consume that block
    in memory. This preserves a cluster-wide hard ceiling while avoiding a database
    write for every request. Unused leased permits can make a window slightly more
    restrictive, but they can never cause the configured global limit to be exceeded.
    """
    def __init__(self, db, *, limit: int=180, window_seconds: int=60, lease_size: int=10, fallback_limit: int | None=None, db_retry_seconds: float=5.0):
        self.db=db
        self.limit=max(1,int(limit))
        self.window_seconds=max(1,int(window_seconds))
        self.lease_size=max(1,min(int(lease_size),self.limit))
        self.fallback_limit=max(1,min(int(fallback_limit if fallback_limit is not None else max(1,self.limit//4)),self.limit))
        self.db_retry_seconds=max(0.1,float(db_retry_seconds))
        self._leases: dict[tuple[str, int], int] = {}
        self._fallback_counts: dict[tuple[str, int], int] = {}
        self._db_unavailable_until=0.0
        self._lease_lock=asyncio.Lock()
        self._log=logging.getLogger("autodraft.rate_limit")

    async def _reserve(self, digest: str, window_start: datetime, expires: datetime) -> int:
        requested=self.lease_size
        async with self.db.raw_pool().acquire() as conn:
            async with conn.transaction():
                status=await conn.execute(
                    """INSERT INTO security_rate_limit_buckets(key_hash,window_start,request_count,expires_at)
                       VALUES($1,$2,$3,$4)
                       ON CONFLICT(key_hash,window_start) DO NOTHING""",
                    digest, window_start, min(requested,self.limit), expires,
                )
                if status.endswith("1"):
                    granted=min(requested,self.limit)
                else:
                    row=await conn.fetchrow(
                        "SELECT request_count FROM security_rate_limit_buckets WHERE key_hash=$1 AND window_start=$2 FOR UPDATE",
                        digest, window_start,
                    )
                    current=int(row["request_count"]) if row else self.limit
                    granted=max(0,min(requested,self.limit-current))
                    if granted:
                        await conn.execute(
                            """UPDATE security_rate_limit_buckets
                               SET request_count=request_count+$3, expires_at=$4
                               WHERE key_hash=$1 AND window_start=$2""",
                            digest, window_start, granted, expires,
                        )
            if int(digest[:2],16)==0:
                await conn.execute("DELETE FROM security_rate_limit_buckets WHERE expires_at < NOW()")
        return granted

    async def allow(self, key: str) -> bool:
        now=datetime.now(timezone.utc)
        epoch=int(now.timestamp())
        start_epoch=epoch-(epoch%self.window_seconds)
        window_start=datetime.fromtimestamp(start_epoch,tz=timezone.utc)
        expires=datetime.fromtimestamp(start_epoch+self.window_seconds*2,tz=timezone.utc)
        digest=hashlib.sha256(key.encode("utf-8")).hexdigest()
        cache_key=(digest,start_epoch)

        remaining=self._leases.get(cache_key,0)
        if remaining > 0:
            self._leases[cache_key]=remaining-1
            return True

        async with self._lease_lock:
            remaining=self._leases.get(cache_key,0)
            if remaining > 0:
                self._leases[cache_key]=remaining-1
                return True
            # Keep only the current window in local memory.
            self._leases={k:v for k,v in self._leases.items() if k[1] == start_epoch and v > 0}
            self._fallback_counts={k:v for k,v in self._fallback_counts.items() if k[1] == start_epoch and v > 0}
            granted=None
            if time.monotonic() >= self._db_unavailable_until:
                try:
                    granted=await self._reserve(digest,window_start,expires)
                    self._db_unavailable_until=0.0
                except Exception:
                    self._db_unavailable_until=time.monotonic()+self.db_retry_seconds
                    self._log.warning("PostgreSQL rate-limit backend unavailable; using bounded local fallback",exc_info=True)
            if granted is not None:
                if granted <= 0:
                    return False
                self._leases[cache_key]=granted-1
                return True
            used=self._fallback_counts.get(cache_key,0)
            if used >= self.fallback_limit:
                return False
            self._fallback_counts[cache_key]=used+1
            return True

# Backward-compatible development/test helper. Production middleware uses
# PostgresRateLimiter above so enforcement is shared across all workers.
class SlidingWindowLimiter:
    def __init__(self, limit: int = 180, window_seconds: int = 60):
        import time
        from collections import defaultdict, deque
        from threading import Lock
        self.limit=max(1,int(limit)); self.window_seconds=max(1,int(window_seconds)); self._events=defaultdict(deque); self._lock=Lock(); self._time=time

    def allow(self, key: str) -> bool:
        now=self._time.monotonic(); cutoff=now-self.window_seconds
        with self._lock:
            events=self._events[key]
            while events and events[0] <= cutoff: events.popleft()
            if len(events) >= self.limit: return False
            events.append(now); return True
