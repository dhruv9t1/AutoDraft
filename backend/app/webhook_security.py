from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import ipaddress
import json
import secrets
import socket
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class WebhookSecurityError(ValueError):
    pass


@dataclass(frozen=True)
class WebhookSignature:
    timestamp: str
    value: str


@dataclass(frozen=True)
class ResolvedWebhookTarget:
    """A webhook destination pinned to an address validated for this attempt.

    ``url`` uses the resolved IP so the HTTP stack cannot perform a second DNS
    lookup after the SSRF check. ``host_header`` and ``sni_hostname`` preserve
    the original authority for HTTP routing and TLS certificate verification.
    """

    url: str
    host_header: str
    sni_hostname: str
    resolved_ip: str


class WebhookSecretBox:
    """Encrypt endpoint signing secrets at rest.

    The setting is hashed to an AES-256 key so operators can provide a normal
    high-entropy secret instead of raw binary key material. Endpoint ID is bound
    as associated data so ciphertext cannot be moved between endpoints.
    """

    def __init__(self, master_secret: str):
        secret = (master_secret or "").encode("utf-8")
        if len(secret) < 32:
            raise WebhookSecurityError("WEBHOOK_SECRET_ENCRYPTION_KEY must contain at least 32 characters")
        self._key = hashlib.sha256(secret).digest()

    def encrypt(self, endpoint_id: str, secret: str) -> str:
        nonce = secrets.token_bytes(12)
        ciphertext = AESGCM(self._key).encrypt(nonce, secret.encode("utf-8"), endpoint_id.encode("ascii"))
        return base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")

    def decrypt(self, endpoint_id: str, ciphertext: str) -> str:
        try:
            raw = base64.urlsafe_b64decode(ciphertext.encode("ascii"))
            if len(raw) < 29:
                raise ValueError("ciphertext too short")
            return AESGCM(self._key).decrypt(raw[:12], raw[12:], endpoint_id.encode("ascii")).decode("utf-8")
        except Exception as exc:  # cryptographic failures must not leak details
            raise WebhookSecurityError("Webhook signing secret could not be decrypted") from exc


def generate_webhook_secret() -> str:
    return secrets.token_urlsafe(40)


def canonical_webhook_body(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_webhook(secret: str, timestamp: str, delivery_id: str, body: bytes) -> WebhookSignature:
    material = timestamp.encode("ascii") + b"." + delivery_id.encode("ascii") + b"." + body
    digest = hmac.new(secret.encode("utf-8"), material, hashlib.sha256).hexdigest()
    return WebhookSignature(timestamp=timestamp, value=f"v1={digest}")


def validate_webhook_url(url: str, *, production: bool) -> str:
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ({"https"} if production else {"http", "https"}):
        raise WebhookSecurityError("Production webhooks require https:// URLs")
    if not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise WebhookSecurityError("Webhook URL must be an absolute URL without credentials or fragments")
    if len(url) > 2048:
        raise WebhookSecurityError("Webhook URL is too long")
    return parsed.geturl()


def _unsafe_ip(value: str) -> bool:
    ip = ipaddress.ip_address(value)
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _host_header(parsed) -> str:
    host = parsed.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    default_port = 443 if parsed.scheme == "https" else 80
    return f"{host}:{parsed.port}" if parsed.port and parsed.port != default_port else host


def _pinned_url(parsed, address: str) -> str:
    host = f"[{address}]" if ":" in address else address
    default_port = 443 if parsed.scheme == "https" else 80
    netloc = f"{host}:{parsed.port}" if parsed.port and parsed.port != default_port else host
    return urlunparse((parsed.scheme, netloc, parsed.path or "/", parsed.params, parsed.query, ""))


async def resolve_safe_webhook_target(url: str, *, allow_private: bool) -> ResolvedWebhookTarget:
    """Resolve and validate a webhook target once, then pin delivery to that IP.

    This closes the DNS-rebinding/TOCTOU gap that exists when a hostname is
    validated with one lookup and the HTTP client performs another lookup later.
    """
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if not host:
        raise WebhookSecurityError("Webhook URL is missing a hostname")
    if host.lower() == "localhost" and not allow_private:
        raise WebhookSecurityError("Private/loopback webhook targets are disabled")

    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None

    if literal is not None:
        addresses = [str(literal)]
    else:
        try:
            infos = await asyncio.to_thread(
                socket.getaddrinfo,
                host,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        except OSError as exc:
            raise WebhookSecurityError("Webhook hostname could not be resolved") from exc
        addresses = sorted({item[4][0] for item in infos if item and item[4]}, key=lambda value: (ipaddress.ip_address(value).version, int(ipaddress.ip_address(value))))

    if not addresses:
        raise WebhookSecurityError("Webhook hostname did not resolve to an address")
    if not allow_private and any(_unsafe_ip(address) for address in addresses):
        raise WebhookSecurityError("Webhook hostname resolves to a private/reserved address")

    # A single validated address is used for this attempt. Retries resolve again,
    # which supports legitimate DNS changes without reopening the TOCTOU window.
    address = addresses[0]
    return ResolvedWebhookTarget(
        url=_pinned_url(parsed, address),
        host_header=_host_header(parsed),
        sni_hostname=host,
        resolved_ip=address,
    )


async def assert_safe_webhook_target(url: str, *, allow_private: bool) -> None:
    """Compatibility wrapper for callers that only need target validation."""
    await resolve_safe_webhook_target(url, allow_private=allow_private)
