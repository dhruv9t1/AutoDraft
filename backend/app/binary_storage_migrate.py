from __future__ import annotations

import argparse
import asyncio
import base64
import logging

import asyncpg

from .binary_store import BinaryObjectStore, estimated_base64_decoded_size
from .config import Settings

log=logging.getLogger("autodraft.binary_storage_migrate")

TABLES=(
    ("templates","docx_sha256","docx_size_bytes","templates"),
    ("template_versions","docx_sha256","docx_size_bytes","template-versions"),
    ("matter_documents","sha256","size_bytes","matter-documents"),
    ("generation_artifacts","sha256","size_bytes","generation-artifacts"),
)

async def migrate(*,batch_size:int=50,dry_run:bool=False)->dict[str,int]:
    settings=Settings()
    dsn=settings.migration_database_url or settings.database_url
    conn=await asyncpg.connect(dsn)
    store=BinaryObjectStore(settings.binary_object_store_path, encryption_key=settings.object_store_encryption_key)
    counts:dict[str,int]={}
    try:
        for table,hash_col,size_col,namespace in TABLES:
            migrated=0
            while True:
                rows=await conn.fetch(
                    f"SELECT id,organization_id,docx_base64 FROM {table} WHERE docx_base64 IS NOT NULL AND object_key IS NULL ORDER BY id LIMIT $1",
                    batch_size,
                )
                if not rows:break
                if dry_run:
                    migrated+=len(rows);break
                for row in rows:
                    encoded=str(row["docx_base64"] or "")
                    if estimated_base64_decoded_size(encoded)>settings.max_binary_upload_body_bytes:
                        raise RuntimeError(f"{table}:{row['id']} exceeds configured binary migration size limit")
                    try:raw=base64.b64decode(encoded,validate=True)
                    except Exception as exc:raise RuntimeError(f"{table}:{row['id']} contains invalid Base64") from exc
                    obj=await store.put_bytes(namespace=f"{row['organization_id']}/{namespace}/{row['id']}",data=raw,suffix=".docx")
                    tag=await conn.execute(
                        f"UPDATE {table} SET object_key=$1,{hash_col}=$2,{size_col}=$3,docx_base64=NULL WHERE id=$4 AND object_key IS NULL AND docx_base64 IS NOT NULL",
                        obj.key,obj.sha256,obj.byte_length,row["id"],
                    )
                    if tag.endswith("0"):
                        await store.delete(obj.key)
                    else:migrated+=1
            counts[table]=migrated
            log.info("%s: %s legacy Base64 row(s) %s",table,migrated,"found" if dry_run else "migrated")
    finally:await conn.close()
    return counts

async def _main()->None:
    parser=argparse.ArgumentParser(description="Move legacy AutoDraft DOCX Base64 rows from PostgreSQL into the configured immutable binary object store")
    parser.add_argument("--batch-size",type=int,default=50)
    parser.add_argument("--dry-run",action="store_true")
    args=parser.parse_args()
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    counts=await migrate(batch_size=max(1,min(args.batch_size,500)),dry_run=args.dry_run)
    print(counts)

if __name__=="__main__":asyncio.run(_main())
