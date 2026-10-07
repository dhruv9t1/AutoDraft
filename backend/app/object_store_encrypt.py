from __future__ import annotations

import asyncio
from pathlib import Path

from .config import get_settings
from .runtime_object_store import RuntimeObjectStore


async def _rewrite(root: str, key: str) -> tuple[int, int]:
    store = RuntimeObjectStore(root, encryption_key=key)
    rewritten = 0
    existing = 0
    for path in Path(root).expanduser().resolve().rglob("*"):
        if not path.is_file() or path.name.startswith(".autodraft-"):
            continue
        logical = path.relative_to(store.root).as_posix()
        if await store.rewrite_encrypted(logical):
            rewritten += 1
        else:
            existing += 1
    return rewritten, existing


async def main() -> None:
    settings = get_settings()
    if not settings.object_store_encryption_key.strip():
        raise RuntimeError("OBJECT_STORE_ENCRYPTION_KEY must be configured before migration")
    runtime = await _rewrite(settings.runtime_object_store_path, settings.object_store_encryption_key)
    binary = await _rewrite(settings.binary_object_store_path, settings.object_store_encryption_key)
    print(
        f"Object-store encryption migration complete: runtime rewritten={runtime[0]} already_encrypted={runtime[1]}; "
        f"binary rewritten={binary[0]} already_encrypted={binary[1]}"
    )


if __name__ == "__main__":
    asyncio.run(main())
