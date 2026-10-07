from __future__ import annotations

import os
import uuid

import pytest

from app.db import Database, run_migrations
from app.token_security import bearer_token_hash


async def _migrate_with_owner(fallback_db: Database) -> None:
    """Run migrations as the owner/migrator when provided; the runtime role cannot do DDL."""
    migration_url = os.getenv("AUTODRAFT_TEST_MIGRATION_DATABASE_URL")
    if not migration_url:
        await run_migrations(fallback_db)
        return
    owner = Database(migration_url)
    await owner.connect()
    try:
        await run_migrations(owner)
    finally:
        await owner.close()


@pytest.mark.asyncio
async def test_real_postgres_jsonb_round_trip_is_python_list():
    """Opt-in integration gate: AUTODRAFT_TEST_DATABASE_URL must point to a disposable DB."""
    url = os.getenv("AUTODRAFT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set AUTODRAFT_TEST_DATABASE_URL to run the real PostgreSQL contract gate")

    from app.db import reset_request_organization, set_request_organization

    db = Database(os.getenv("AUTODRAFT_TEST_MIGRATION_DATABASE_URL") or url)
    await db.connect()
    org_token = set_request_organization("00000000-0000-0000-0000-000000000001")
    try:
        await _migrate_with_owner(db)
        async with db.p().acquire() as conn:
            tx = conn.transaction()
            await tx.start()
            try:
                await conn.execute("SELECT set_config('autodraft.organization_id',$1,true)", "00000000-0000-0000-0000-000000000001")
                token = "contract-" + uuid.uuid4().hex
                questions = [
                    {
                        "id": "agreement_date",
                        "label": "Agreement date",
                        "type": "date",
                        "required": True,
                        "options": [],
                        "mapsTo": "agreement.execution_date",
                        "helpText": "",
                        "approved": True,
                    }
                ]
                await conn.execute(
                    "INSERT INTO intake_forms(token_hash,title,matter_type,questions) VALUES($1,$2,$3,$4::jsonb)",
                    bearer_token_hash(token),
                    "Contract Test",
                    "Test",
                    questions,
                )
                row = await conn.fetchrow("SELECT questions FROM intake_forms WHERE token_hash=$1", bearer_token_hash(token))
                assert isinstance(row["questions"], list)
                assert row["questions"][0]["label"] == "Agreement date"
            finally:
                await tx.rollback()
    finally:
        reset_request_organization(org_token)
        await db.close()


@pytest.mark.asyncio
async def test_real_postgres_public_intake_resolves_non_default_tenant():
    """Opt-in: a bearer intake token must bootstrap its own tenant before RLS reads."""
    url = os.getenv("AUTODRAFT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set AUTODRAFT_TEST_DATABASE_URL to run the real PostgreSQL tenant gate")

    from app.db import set_request_organization
    from app.repositories.intake import IntakeRepository

    db = Database(url)
    await db.connect()
    admin = Database(os.getenv("AUTODRAFT_TEST_MIGRATION_DATABASE_URL") or url)
    await admin.connect()
    org_id = uuid.uuid4()
    template_id = uuid.uuid4()
    version_id = uuid.uuid4()
    session_id = uuid.uuid4()
    token = "tenant-" + uuid.uuid4().hex
    try:
        await _migrate_with_owner(db)
        # Bootstrap test rows through the raw migration connection. Production
        # creates these through scoped repositories; this setup keeps the test
        # focused on anonymous token -> tenant resolution.
        async with admin.raw_pool().acquire() as conn:
            await conn.execute("INSERT INTO organizations(id,name) VALUES($1,'Tenant Test')", org_id)
            await conn.execute("SELECT set_config('autodraft.organization_id',$1,false)", str(org_id))
            await conn.execute("INSERT INTO questionnaire_templates(organization_id,id,title,matter_type,status) VALUES($1,$2,'Tenant Intake','Test','published')", org_id, template_id)
            await conn.execute("INSERT INTO questionnaire_versions(id,template_id,version_number,status,published_at) VALUES($1,$2,1,'published',NOW())", version_id, template_id)
            await conn.execute("INSERT INTO intake_sessions(organization_id,id,questionnaire_version_id,token_hash,status) VALUES($1,$2,$3,$4,'open')", org_id, session_id, version_id, bearer_token_hash(token))
            await conn.execute("INSERT INTO public_intake_token_hashes(token_hash,organization_id,session_id) VALUES($1,$2,$3)", bearer_token_hash(token), org_id, session_id)

        # Simulate a public request that begins under the default tenant. The
        # lookup must still discover and set the token's non-default tenant.
        set_request_organization("00000000-0000-0000-0000-000000000001")
        row = await IntakeRepository(db).public_session_by_token(token)
        assert row is not None
        assert str(row["organization_id"]) == str(org_id)
        assert str(row["id"]) == str(session_id)
    finally:
        async with admin.raw_pool().acquire() as conn:
            async with conn.transaction():
                await conn.execute("SET LOCAL session_replication_role = replica")
                await conn.execute("DELETE FROM organizations WHERE id=$1", org_id)
        await admin.close()
        await db.close()


def _real_postgres_urls():
    runtime = os.getenv("AUTODRAFT_TEST_DATABASE_URL")
    migration = os.getenv("AUTODRAFT_TEST_MIGRATION_DATABASE_URL")
    if not runtime or not migration:
        pytest.skip("Set AUTODRAFT_TEST_DATABASE_URL and AUTODRAFT_TEST_MIGRATION_DATABASE_URL for adversarial RLS/FK gates")
    return runtime, migration


@pytest.mark.asyncio
async def test_real_postgres_all_tenant_tables_force_rls_and_have_policy():
    """Every normal organization-owned table must fail closed at the database layer."""
    _, migration_url = _real_postgres_urls()
    admin = Database(migration_url)
    await admin.connect()
    try:
        await run_migrations(admin)
        rows = await admin.raw_pool().fetch(
            """SELECT c.relname,c.relrowsecurity,c.relforcerowsecurity,
                      EXISTS(SELECT 1 FROM pg_policy p WHERE p.polrelid=c.oid AND p.polname='autodraft_tenant_isolation') AS has_policy
                 FROM pg_class c
                 JOIN pg_namespace n ON n.oid=c.relnamespace
                 JOIN pg_attribute a ON a.attrelid=c.oid AND a.attname='organization_id' AND a.attnum>0 AND NOT a.attisdropped
                WHERE n.nspname='public' AND c.relkind='r' ORDER BY c.relname"""
        )
        bootstrap={"public_intake_token_hashes","public_legacy_intake_token_hashes","public_user_identities","public_workflow_tokens"}
        runtime_infra={"runtime_jobs","runtime_job_events","runtime_chunk_sessions","runtime_chunks"}
        bad=[]
        for row in rows:
            if row["relname"] in bootstrap or row["relname"] in runtime_infra:
                continue
            if not (row["relrowsecurity"] and row["relforcerowsecurity"] and row["has_policy"]):
                bad.append(row["relname"])
        assert not bad, f"Tenant tables missing forced RLS/policy: {bad}"

        # Every FK relationship between two tenant-owned tables must have a
        # tenant-aware composite companion constraint. Bare historical FKs may
        # remain for compatibility, but they cannot be the only DB invariant.
        fk_rows=await admin.raw_pool().fetch(
            """SELECT child.relname AS child,parent.relname AS parent,pg_get_constraintdef(c.oid) AS definition
                 FROM pg_constraint c
                 JOIN pg_class child ON child.oid=c.conrelid
                 JOIN pg_class parent ON parent.oid=c.confrelid
                 JOIN pg_namespace n ON n.oid=child.relnamespace
                WHERE c.contype='f' AND n.nspname='public'
                  AND EXISTS(SELECT 1 FROM pg_attribute a WHERE a.attrelid=child.oid AND a.attname='organization_id' AND a.attnum>0 AND NOT a.attisdropped)
                  AND EXISTS(SELECT 1 FROM pg_attribute a WHERE a.attrelid=parent.oid AND a.attname='organization_id' AND a.attnum>0 AND NOT a.attisdropped)"""
        )
        by_pair={}
        for row in fk_rows: by_pair.setdefault((row["child"],row["parent"]),[]).append(row["definition"].replace(' ',''))
        missing=[]
        for (child,parent),defs in by_pair.items():
            if parent in {"organizations"}: continue
            composite=any("FOREIGNKEY(organization_id," in d and f"REFERENCES{parent}(organization_id," in d for d in defs)
            if not composite: missing.append(f"{child}->{parent}")
        assert not missing, f"Tenant relationships missing composite tenant FK: {sorted(missing)}"
    finally:
        await admin.close()


@pytest.mark.asyncio
async def test_real_postgres_runtime_role_blocks_cross_tenant_crud_and_fk_spoofing():
    """Direct SQL adversarial gate across matters/contacts/workflows/templates/sets and tenant FKs."""
    runtime_url, migration_url = _real_postgres_urls()
    from app.db import set_request_organization, reset_request_organization

    admin=Database(migration_url); runtime=Database(runtime_url)
    await admin.connect()
    org_a,org_b=uuid.uuid4(),uuid.uuid4(); user_a,user_b=uuid.uuid4(),uuid.uuid4()
    matter_a,matter_b=uuid.uuid4(),uuid.uuid4(); contact_a,contact_b=uuid.uuid4(),uuid.uuid4()
    workflow_b,wv_b=uuid.uuid4(),uuid.uuid4(); template_b=uuid.uuid4(); set_b,setv_b=uuid.uuid4(),uuid.uuid4()
    field_b=uuid.uuid4()
    try:
        await run_migrations(admin)
        async with admin.raw_pool().acquire() as conn:
            for oid,name in ((org_a,"RLS A"),(org_b,"RLS B")):
                await conn.execute("INSERT INTO organizations(id,name) VALUES($1,$2) ON CONFLICT(id) DO NOTHING",oid,name)
            await conn.execute("INSERT INTO app_users(id,organization_id,role,active) VALUES($1,$2,'admin',TRUE),($3,$4,'admin',TRUE)",user_a,org_a,user_b,org_b)
            await conn.execute("INSERT INTO matters(id,organization_id,title,matter_type) VALUES($1,$2,'A','test'),($3,$4,'B','test')",matter_a,org_a,matter_b,org_b)
            await conn.execute("INSERT INTO contacts(id,organization_id,display_name) VALUES($1,$2,'A contact'),($3,$4,'B contact')",contact_a,org_a,contact_b,org_b)
            await conn.execute("INSERT INTO workflows(id,organization_id,name) VALUES($1,$2,'B workflow')",workflow_b,org_b)
            await conn.execute("INSERT INTO workflow_versions(id,organization_id,workflow_id,version_number,status) VALUES($1,$2,$3,1,'published')",wv_b,org_b,workflow_b)
            await conn.execute("INSERT INTO templates(id,organization_id,name,type) VALUES($1,$2,$3,'test')",template_b,org_b,"rls-template-"+uuid.uuid4().hex)
            await conn.execute("INSERT INTO document_sets(id,organization_id,name) VALUES($1,$2,'B set')",set_b,org_b)
            await conn.execute("INSERT INTO document_set_versions(id,organization_id,document_set_id,version_number) VALUES($1,$2,$3,1)",setv_b,org_b,set_b)
            await conn.execute("INSERT INTO field_definitions(id,organization_id,semantic_key,display_label) VALUES($1,$2,$3,'B field')",field_b,org_b,"rls.field."+uuid.uuid4().hex)
        await runtime.connect()
        token=set_request_organization(str(org_a))
        try:
            # SELECT/UPDATE/DELETE cannot see tenant B rows across several major subsystems.
            for table,row_id in (("matters",matter_b),("contacts",contact_b),("workflows",workflow_b),("templates",template_b),("document_sets",set_b)):
                assert await runtime.p().fetchval(f"SELECT COUNT(*) FROM {table} WHERE id=$1",row_id)==0
                assert (await runtime.p().execute(f"UPDATE {table} SET updated_at=NOW() WHERE id=$1",row_id)).endswith("0")
                assert (await runtime.p().execute(f"DELETE FROM {table} WHERE id=$1",row_id)).endswith("0")
            # Cross-tenant INSERT is rejected by RLS.
            with pytest.raises(Exception):
                await runtime.p().execute("INSERT INTO matters(organization_id,title,matter_type) VALUES($1,'spoof','test')",org_b)
            # Composite tenant FKs reject cross-tenant parent references even though RI checks bypass RLS.
            with pytest.raises(Exception):
                await runtime.p().execute("INSERT INTO matter_participants(organization_id,matter_id,contact_id,role_key,display_role) VALUES($1,$2,$3,'client','Client')",org_a,matter_b,contact_a)
            with pytest.raises(Exception):
                await runtime.p().execute("INSERT INTO matter_field_values(organization_id,matter_id,field_definition_id,source,status) VALUES($1,$2,$3,'test','confirmed')",org_a,matter_a,field_b)
            with pytest.raises(Exception):
                await runtime.p().execute("INSERT INTO workflow_sessions(organization_id,workflow_version_id,matter_id) VALUES($1,$2,$3)",org_a,wv_b,matter_a)
            with pytest.raises(Exception):
                await runtime.p().execute("INSERT INTO generation_runs(organization_id,matter_id,document_set_version_id) VALUES($1,$2,$3)",org_a,matter_a,setv_b)
        finally:
            reset_request_organization(token)
        async with runtime.raw_pool().acquire() as conn:
            await conn.execute("RESET autodraft.organization_id")
            with pytest.raises(Exception):
                await conn.fetchval("SELECT COUNT(*) FROM matters")
    finally:
        await runtime.close()
        async with admin.raw_pool().acquire() as conn:
            async with conn.transaction():
                await conn.execute("SET LOCAL session_replication_role = replica")
                await conn.execute("DELETE FROM organizations WHERE id=ANY($1::uuid[])",[org_a,org_b])
        await admin.close()


@pytest.mark.asyncio
async def test_real_postgres_public_workflow_token_bootstraps_only_its_tenant():
    runtime_url,migration_url=_real_postgres_urls()
    from app.repositories.workflows import WorkflowRepository
    from app.db import set_request_organization
    from app.token_security import bearer_token_hash as hash_public_token

    admin=Database(migration_url); runtime=Database(runtime_url)
    await admin.connect(); await run_migrations(admin)
    org=uuid.uuid4(); workflow=uuid.uuid4(); version=uuid.uuid4(); session=uuid.uuid4(); raw="wf-"+uuid.uuid4().hex
    try:
        async with admin.raw_pool().acquire() as conn:
            await conn.execute("INSERT INTO organizations(id,name) VALUES($1,'Workflow bootstrap')",org)
            await conn.execute("INSERT INTO workflows(id,organization_id,name,status,current_version) VALUES($1,$2,'Public','published',1)",workflow,org)
            await conn.execute("INSERT INTO workflow_versions(id,organization_id,workflow_id,version_number,status,published_at) VALUES($1,$2,$3,1,'published',NOW())",version,org,workflow)
            await conn.execute("INSERT INTO workflow_sessions(id,organization_id,workflow_version_id,status) VALUES($1,$2,$3,'in_progress')",session,org,version)
            await conn.execute("INSERT INTO public_workflow_tokens(token_hash,organization_id,session_id) VALUES($1,$2,$3)",hash_public_token(raw),org,session)
        await runtime.connect()
        set_request_organization("00000000-0000-0000-0000-000000000001")
        row=await WorkflowRepository(runtime).public_session(raw)
        assert row and str(row["organization_id"])==str(org) and str(row["id"])==str(session)
    finally:
        await runtime.close()
        async with admin.raw_pool().acquire() as conn:
            await conn.execute("DELETE FROM organizations WHERE id=$1",org)
        await admin.close()
