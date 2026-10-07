from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass

from app.config import Settings, get_settings
from app.db import Database, run_migrations
from app.ollama_service import OllamaService

@dataclass
class Check:
    name: str
    passed: bool
    detail: str

async def ollama_checks() -> list[Check]:
    base=get_settings(); checks=[]
    # Real configured provider/model readiness, including structured-output probe.
    service=OllamaService(base)
    try:
        state=await service.check_readiness(probe=True)
        checks.append(Check("configured Ollama readiness",bool(state.get("ready")),json.dumps(state,ensure_ascii=False)))
    finally: await service.close()

    missing=Settings(_env_file=None,ollama_api_url=base.ollama_api_url,ollama_model="__autodraft_model_must_not_exist__",ollama_validate_on_startup=False)
    service=OllamaService(missing)
    try:
        state=await service.check_readiness(probe=False)
        checks.append(Check("missing model fails closed",state.get("reachable") is True and state.get("modelAvailable") is False,json.dumps(state,ensure_ascii=False)))
    finally: await service.close()

    unreachable=Settings(_env_file=None,ollama_api_url="http://127.0.0.1:9",ollama_model=base.ollama_model,ollama_timeout_seconds=2,ollama_max_retries=0,ollama_validate_on_startup=False)
    service=OllamaService(unreachable)
    try:
        state=await service.check_readiness(probe=False)
        checks.append(Check("Ollama unavailable is controlled",state.get("reachable") is False,json.dumps(state,ensure_ascii=False)))
    finally: await service.close()
    return checks

async def postgres_checks() -> list[Check]:
    url=os.getenv("AUTODRAFT_TEST_DATABASE_URL")
    if not url: return [Check("real PostgreSQL integration",False,"AUTODRAFT_TEST_DATABASE_URL is not set")]
    db=Database(url)
    try:
        await db.connect();await run_migrations(db)
        value=await db.p().fetchval("SELECT 1")
        return [Check("real PostgreSQL integration",value==1,"migrations + SELECT 1 succeeded")]
    except Exception as exc:
        return [Check("real PostgreSQL integration",False,str(exc))]
    finally:
        try: await db.close()
        except Exception: pass

async def database_failure_check() -> Check:
    db=Database("postgresql://postgres:postgres@127.0.0.1:9/autodraft_fault")
    try:
        await asyncio.wait_for(db.connect(),timeout=3)
    except Exception as exc:
        return Check("database unavailable is detectable",True,type(exc).__name__)
    else:
        await db.close();return Check("database unavailable is detectable",False,"unexpectedly connected")

async def main() -> int:
    checks=[];checks.extend(await ollama_checks());checks.extend(await postgres_checks());checks.append(await database_failure_check())
    for c in checks: print(("PASS" if c.passed else "FAIL"),"-",c.name,"-",c.detail)
    return 0 if all(c.passed for c in checks) else 1

if __name__=="__main__": raise SystemExit(asyncio.run(main()))
