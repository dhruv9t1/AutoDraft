from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class RuntimeObjectStoreError(RuntimeError):
    pass


_ENCRYPTED_MAGIC = b"ADOBJ1\x00"
_NONCE_BYTES = 12


def decode_object_store_encryption_key(value: str | None) -> bytes | None:
    """Decode a 256-bit object-store encryption key.

    Accepted forms are 64 hexadecimal characters or URL-safe Base64 that
    decodes to exactly 32 bytes. Empty input intentionally means plaintext
    local-development mode; token/production mode rejects empty input at
    startup in ``validate_security_configuration``.
    """
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if len(text) == 64:
            raw = bytes.fromhex(text)
        else:
            raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (ValueError, binascii.Error) as exc:
        raise RuntimeObjectStoreError(
            "OBJECT_STORE_ENCRYPTION_KEY must be 32 random bytes encoded as hex or URL-safe Base64"
        ) from exc
    if len(raw) != 32:
        raise RuntimeObjectStoreError(
            "OBJECT_STORE_ENCRYPTION_KEY must decode to exactly 32 random bytes"
        )
    return raw


@dataclass(frozen=True)
class StoredRuntimeObject:
    key: str
    byte_length: int
    sha256: str


class RuntimeObjectStore:
    """Small object/blob abstraction for durable runtime payloads.

    The filesystem backend encrypts new objects with AES-256-GCM whenever an
    encryption key is configured. The object key is authenticated as AAD so a
    ciphertext cannot be silently moved to a different logical object. Legacy
    plaintext objects remain readable to support safe in-place upgrades; run
    ``python -m app.object_store_encrypt`` after enabling encryption to rewrite
    existing objects at rest.
    """

    def __init__(self, root: str, *, encryption_key: str | None = None):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        key = decode_object_store_encryption_key(encryption_key)
        self._cipher = AESGCM(key) if key is not None else None

    @property
    def encryption_enabled(self) -> bool:
        return self._cipher is not None

    def _path(self, key: str) -> Path:
        normalized = key.replace("\\", "/").lstrip("/")
        if not normalized or ".." in normalized.split("/"):
            raise RuntimeObjectStoreError("Invalid runtime object key")
        path = (self.root / normalized).resolve()
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise RuntimeObjectStoreError("Runtime object key escapes configured store") from exc
        return path

    def _encode(self, key: str, raw: bytes) -> bytes:
        if self._cipher is None:
            return raw
        nonce = os.urandom(_NONCE_BYTES)
        ciphertext = self._cipher.encrypt(nonce, raw, key.encode("utf-8"))
        return _ENCRYPTED_MAGIC + nonce + ciphertext

    def _decode(self, key: str, stored: bytes) -> bytes:
        if not stored.startswith(_ENCRYPTED_MAGIC):
            return stored
        if self._cipher is None:
            raise RuntimeObjectStoreError(
                f"Runtime object is encrypted but OBJECT_STORE_ENCRYPTION_KEY is not configured: {key}"
            )
        minimum = len(_ENCRYPTED_MAGIC) + _NONCE_BYTES + 16
        if len(stored) < minimum:
            raise RuntimeObjectStoreError(f"Encrypted runtime object is truncated: {key}")
        nonce_start = len(_ENCRYPTED_MAGIC)
        nonce = stored[nonce_start : nonce_start + _NONCE_BYTES]
        ciphertext = stored[nonce_start + _NONCE_BYTES :]
        try:
            return self._cipher.decrypt(nonce, ciphertext, key.encode("utf-8"))
        except Exception as exc:
            raise RuntimeObjectStoreError(f"Encrypted runtime object failed authentication: {key}") from exc

    async def put(self, key: str, data: bytes) -> StoredRuntimeObject:
        raw = bytes(data)
        path = self._path(key)
        digest = hashlib.sha256(raw).hexdigest()
        stored_bytes = self._encode(key, raw)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(prefix=".autodraft-", dir=str(path.parent))
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(stored_bytes)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp_name, path)
            except Exception:
                try:
                    os.unlink(tmp_name)
                except FileNotFoundError:
                    pass
                raise

        await asyncio.to_thread(_write)
        return StoredRuntimeObject(key=key, byte_length=len(raw), sha256=digest)

    async def get(self, key: str) -> bytes:
        path = self._path(key)
        try:
            stored = await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError as exc:
            raise RuntimeObjectStoreError(f"Runtime object is missing: {key}") from exc
        return self._decode(key, stored)

    async def rewrite_encrypted(self, key: str) -> bool:
        """Rewrite one legacy plaintext object in encrypted form.

        Returns True when a rewrite occurred, False when the object was already
        encrypted. Encryption must be configured.
        """
        if self._cipher is None:
            raise RuntimeObjectStoreError("Object-store encryption is not configured")
        path = self._path(key)
        try:
            stored = await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError as exc:
            raise RuntimeObjectStoreError(f"Runtime object is missing: {key}") from exc
        if stored.startswith(_ENCRYPTED_MAGIC):
            self._decode(key, stored)  # authenticate existing ciphertext
            return False
        await self.put(key, stored)
        return True

    async def delete(self, key: str | None) -> None:
        if not key:
            return
        path = self._path(key)
        try:
            await asyncio.to_thread(path.unlink)
        except FileNotFoundError:
            return
        parent = path.parent
        while parent != self.root:
            try:
                await asyncio.to_thread(parent.rmdir)
            except OSError:
                break
            parent = parent.parent

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._path(key).is_file)
