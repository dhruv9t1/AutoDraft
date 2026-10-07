from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import time
import uuid
from dataclasses import dataclass
from functools import lru_cache

from fastapi import HTTPException, Request

from .config import Settings
from .db import set_request_organization
from .runtime_object_store import decode_object_store_encryption_key, RuntimeObjectStoreError


ROLE_ORDER = {"viewer": 0, "staff": 1, "lawyer": 2, "admin": 3, "owner": 4}
_LOCAL_HOSTNAMES = {"localhost", "localhost.localdomain"}
_PROXY_IDENTITY_HEADERS = ("forwarded", "x-forwarded-for", "x-real-ip")


@dataclass(frozen=True)
class SecurityContext:
    organization_id: str
    user_id: str
    role: str
    authenticated: bool
    auth_version: int = 0


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _is_loopback_host(value: str | None) -> bool:
    """Return True only for explicit loopback host/address values.

    Unknown hostnames deliberately fail closed: SECURITY_MODE=local is intended
    for direct, single-machine development, not reverse-proxied deployments.
    """
    host = (value or "").strip().lower()
    if not host:
        return False
    if host in _LOCAL_HOSTNAMES:
        return True
    # Handle bracketed IPv6 values if a caller supplies one.
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def validate_security_configuration(settings: Settings) -> None:
    """Fail startup for security modes that are unsafe outside local development."""
    mode = (settings.security_mode or "").strip().lower()
    if mode not in {"local", "token"}:
        raise RuntimeError("SECURITY_MODE must be either 'local' or 'token'")

    validate_entra_configuration(settings)

    if mode == "token":
        if not settings.auth_hmac_secret:
            raise RuntimeError("AUTH_HMAC_SECRET is required when SECURITY_MODE=token")
        if not settings.intake_require_malware_scan_in_production:
            raise RuntimeError("INTAKE_REQUIRE_MALWARE_SCAN_IN_PRODUCTION must remain enabled when SECURITY_MODE=token")
        # A 32-byte random secret encoded with URL-safe base64 is 43 characters.
        # Requiring this size prevents weak human-password HMAC keys in production.
        if len(settings.auth_hmac_secret.encode("utf-8")) < 43:
            raise RuntimeError(
                "AUTH_HMAC_SECRET is too weak; use at least 32 random bytes "
                "(for example: python -c \"import secrets; print(secrets.token_urlsafe(32))\")"
            )
        try:
            object_store_key = decode_object_store_encryption_key(settings.object_store_encryption_key)
        except RuntimeObjectStoreError as exc:
            raise RuntimeError(str(exc)) from exc
        if object_store_key is None:
            raise RuntimeError(
                "OBJECT_STORE_ENCRYPTION_KEY is required when SECURITY_MODE=token; "
                "use 32 random bytes encoded as hex or URL-safe Base64"
            )
        return

    # Client-supplied organization/user/role headers are intentionally supported
    # only in local development. An explicit override is required even to bind
    # this mode to a non-loopback interface.
    if not _is_loopback_host(settings.host) and not settings.allow_external_local_auth:
        raise RuntimeError(
            "SECURITY_MODE=local may only bind to loopback. "
            "Use SECURITY_MODE=token for multi-user/production deployments. "
            "For isolated development only, ALLOW_EXTERNAL_LOCAL_AUTH=true may override this guard."
        )


def create_hmac_token(*, secret: str, organization_id: str, user_id: str, role: str, auth_version: int = 1, ttl_seconds: int = 3600) -> str:
    if not secret:
        raise ValueError("AUTH_HMAC_SECRET is required")
    payload = {
        "org": str(uuid.UUID(organization_id)),
        "sub": str(uuid.UUID(user_id)),
        "role": role,
        "exp": int(time.time()) + max(60, int(ttl_seconds)),
        "av": max(1, int(auth_version)),
        "v": 2,
    }
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    sig = _b64(hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest())
    return f"ad1.{body}.{sig}"


def verify_hmac_token(token: str, secret: str) -> SecurityContext:
    try:
        prefix, body, signature = token.split(".", 2)
        if prefix != "ad1":
            raise ValueError("unsupported token")
        expected = _b64(hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            raise ValueError("invalid signature")
        payload = json.loads(_unb64(body).decode("utf-8"))
        if int(payload.get("exp", 0)) < int(time.time()):
            raise ValueError("expired")
        organization_id = str(uuid.UUID(str(payload["org"])))
        user_id = str(uuid.UUID(str(payload["sub"])))
        role = str(payload.get("role", "viewer"))
        if role not in ROLE_ORDER:
            raise ValueError("invalid role")
        auth_version = int(payload.get("av", 0))
        if auth_version < 1:
            raise ValueError("revocation version missing")
        return SecurityContext(organization_id, user_id, role, True, auth_version)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired AutoDraft access token") from exc


def _assert_local_request_is_safe(request: Request, settings: Settings) -> None:
    if settings.allow_external_local_auth:
        return
    client_host = request.client.host if request.client else None
    if not _is_loopback_host(client_host):
        raise HTTPException(
            status_code=403,
            detail="Local security mode only accepts direct loopback requests",
        )
    # Do not trust local identity headers through a proxy by default. A reverse
    # proxy can otherwise make an internet client appear to originate on loopback.
    if any(request.headers.get(name) for name in _PROXY_IDENTITY_HEADERS):
        raise HTTPException(
            status_code=403,
            detail="Local security mode does not accept proxied identity requests",
        )



def validate_entra_configuration(settings: Settings) -> None:
    if bool(settings.entra_tenant_id) != bool(settings.entra_client_id):
        raise RuntimeError("ENTRA_TENANT_ID and ENTRA_CLIENT_ID must be configured together")


@lru_cache(maxsize=32)
def _entra_jwks_client(tenant: str):
    # PyJWKClient maintains an in-memory JWKS/signing-key cache. Reusing one
    # client per Entra tenant avoids a network dependency on every token exchange.
    import jwt
    return jwt.PyJWKClient(f"https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys")


def verify_entra_access_token(token: str, settings: Settings) -> dict:
    """Verify an Office/Entra JWT using Microsoft's published signing keys.

    No Office token is persisted. Identity routing is performed separately via
    ``public_user_identities`` after signature/audience/issuer validation.
    """
    if not settings.entra_tenant_id or not settings.entra_client_id:
        raise HTTPException(status_code=503, detail="Office SSO is not configured")
    try:
        import jwt
        tenant = settings.entra_tenant_id.strip()
        client_id = settings.entra_client_id.strip()
        audiences = [client_id]
        if settings.entra_resource_uri.strip():
            audiences.append(settings.entra_resource_uri.strip())
        signing_key = _entra_jwks_client(tenant).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=audiences,
            issuer=f"https://login.microsoftonline.com/{tenant}/v2.0",
            options={"require": ["exp", "iat", "oid", "tid"]},
        )
        if str(claims.get("tid") or "").lower() != tenant.lower():
            raise ValueError("tenant mismatch")
        required_scope = settings.entra_required_scope.strip()
        if required_scope:
            scopes = {part for part in str(claims.get("scp") or "").split() if part}
            if required_scope not in scopes:
                raise ValueError("required Office API scope is missing")
        return dict(claims)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid Office/Entra access token") from exc

def resolve_security_context(request: Request, settings: Settings) -> SecurityContext:
    mode = (settings.security_mode or "").strip().lower()
    auth = request.headers.get("Authorization", "")

    validate_entra_configuration(settings)

    if mode == "token":
        if not settings.auth_hmac_secret:
            raise HTTPException(status_code=503, detail="Token security mode is not configured")
        if not auth.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Authentication required")
        ctx = verify_hmac_token(auth[7:].strip(), settings.auth_hmac_secret)
    elif mode == "local":
        _assert_local_request_is_safe(request, settings)
        # Development-only header identity. Production/multi-user deployments
        # must use signed per-user token claims instead of these headers.
        org = request.headers.get("X-Organization-ID") or settings.default_organization_id
        user = request.headers.get("X-User-ID") or settings.default_user_id
        role = request.headers.get("X-User-Role") or settings.default_user_role
        try:
            org = str(uuid.UUID(org)); user = str(uuid.UUID(user))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid organization/user ID") from exc
        if role not in ROLE_ORDER:
            raise HTTPException(status_code=400, detail="Invalid AutoDraft role")
        ctx = SecurityContext(org, user, role, bool(settings.api_auth_token and auth), 0)
        # API_AUTH_TOKEN remains a local-development convenience only. It is not
        # consulted in token mode and is not a multi-user production credential.
        if settings.api_auth_token and auth != f"Bearer {settings.api_auth_token}":
            raise HTTPException(status_code=401, detail="Unauthorized")
    else:
        raise HTTPException(status_code=503, detail="Invalid AutoDraft security configuration")

    request.state.security = ctx
    set_request_organization(ctx.organization_id)
    return ctx


def require_role(ctx: SecurityContext, *roles: str) -> None:
    if not roles:
        return
    required = max((ROLE_ORDER.get(role, 99) for role in roles), default=99)
    if ROLE_ORDER.get(ctx.role, -1) < required:
        raise HTTPException(status_code=403, detail="Insufficient AutoDraft permissions")
