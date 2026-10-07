from __future__ import annotations

import base64
import hashlib
import uuid
from dataclasses import dataclass

from .runtime_object_store import RuntimeObjectStore


@dataclass(frozen=True)
class BinaryObject:
    key: str
    byte_length: int
    sha256: str


def estimated_base64_decoded_size(encoded: str) -> int:
    value=(encoded or "").strip()
    if not value:
        return 0
    padding=2 if value.endswith("==") else 1 if value.endswith("=") else 0
    return max(0,(len(value)*3)//4-padding)


class BinaryObjectStore:
    """Immutable application-binary store.

    PostgreSQL stores only object keys, sizes and hashes. The filesystem backend
    is suitable for a shared mounted volume; deployments can replace this class
    with S3/Azure/GCS while preserving the repository contract.
    """
    def __init__(self, root: str, *, encryption_key: str | None = None):
        self.store=RuntimeObjectStore(root, encryption_key=encryption_key)

    async def put_bytes(self, *, namespace: str, data: bytes, suffix: str = ".bin") -> BinaryObject:
        raw=bytes(data)
        digest=hashlib.sha256(raw).hexdigest()
        key=f"{namespace.strip('/')}/{uuid.uuid4().hex}-{digest[:16]}{suffix}"
        stored=await self.store.put(key,raw)
        return BinaryObject(stored.key,stored.byte_length,stored.sha256)

    async def put_base64(self, *, namespace: str, encoded: str, max_bytes: int, suffix: str = ".docx") -> BinaryObject:
        if estimated_base64_decoded_size(encoded)>int(max_bytes):
            raise ValueError("Binary payload exceeds configured size limit")
        try:
            raw=base64.b64decode(encoded,validate=True)
        except Exception as exc:
            raise ValueError("Binary payload is not valid Base64") from exc
        if len(raw)>int(max_bytes):
            raise ValueError("Binary payload exceeds configured size limit")
        return await self.put_bytes(namespace=namespace,data=raw,suffix=suffix)

    async def get_bytes(self,key:str)->bytes:
        return await self.store.get(key)

    async def get_base64(self,key:str)->str:
        return base64.b64encode(await self.get_bytes(key)).decode("ascii")

    async def delete(self,key:str|None)->None:
        await self.store.delete(key)
