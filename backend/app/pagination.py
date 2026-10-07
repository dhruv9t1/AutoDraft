from __future__ import annotations
import base64,json,uuid
from datetime import datetime
from fastapi import HTTPException


def encode_cursor(updated_at:datetime, record_id:uuid.UUID|str)->str:
    raw=json.dumps({"t":updated_at.isoformat(),"id":str(record_id)},separators=(",",":" )).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(value:str|None):
    if not value:return None,None
    try:
        padded=value+"="*((4-len(value)%4)%4)
        data=json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        return datetime.fromisoformat(str(data["t"])),uuid.UUID(str(data["id"]))
    except Exception as exc:
        raise HTTPException(400,"Invalid pagination cursor") from exc


def page_rows(rows:list,limit:int, *, timestamp_field:str="updated_at"):
    limit=max(1,min(int(limit),200));items=list(rows[:limit]);next_cursor=None
    if len(rows)>limit and items:
        last=items[-1];next_cursor=encode_cursor(last[timestamp_field],last["id"])
    return items,next_cursor
