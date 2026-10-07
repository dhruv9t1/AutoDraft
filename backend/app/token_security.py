from __future__ import annotations

import hashlib


def bearer_token_hash(token: str) -> str:
    value = (token or "").strip()
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
