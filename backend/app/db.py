from __future__ import annotations

import hashlib
import hmac
import json
import re
import uuid
from pathlib import Path
from contextvars import ContextVar, Token
from contextlib import asynccontextmanager
from typing import Any
from dataclasses import dataclass

import asyncpg


DEFAULT_LOCAL_ORGANIZATION_ID = "00000000-0000-0000-0000-000000000001"
_request_organization: ContextVar[str | None] = ContextVar(
    "autodraft_request_organization", default=None
)
_request_connection: ContextVar[tuple[int, Any] | None] = ContextVar(
    "autodraft_request_connection", default=None
)


@dataclass
class RequestTransactionScope:
    connection: Any
    rollback_only: bool = False

    def rollback(self) -> None:
        self.rollback_only = True


class MissingTenantContextError(RuntimeError):
    """Raised when tenant-scoped data access is attempted without an organization."""


def clear_request_connection() -> Token[tuple[int, Any] | None]:
    """Detach the bound request-transaction connection from this context.

    Async work that outlives the request handler (SSE generators, spawned
    tasks) inherits the bound connection through contextvars. The middleware
    releases and rolls back that connection when call_next returns, so any
    task still holding it crashes with "another operation is in progress"
    and its writes are discarded. Stream bodies must call this before doing
    database work so their queries use normal scoped connections instead.
    """
    return _request_connection.set(None)


def reset_request_connection(token: Token[tuple[int, Any] | None]) -> None:
    _request_connection.reset(token)


def set_request_organization(organization_id: str) -> Token[str | None]:
    normalized = str(uuid.UUID(str(organization_id)))
    return _request_organization.set(normalized)


def clear_request_organization() -> Token[str | None]:
    return _request_organization.set(None)


def reset_request_organization(token: Token[str | None]) -> None:
    _request_organization.reset(token)


def get_request_organization() -> str | None:
    return _request_organization.get()


class ScopedPool:
    """Tenant-scoped pool facade for normal application repositories.

    Every repository query runs in a transaction with ``autodraft.organization_id``
    set locally. In production/token mode a missing tenant context is a hard error.
    A default organization may be enabled only for the explicit local-development
    runtime path.
    """

    def __init__(
        self,
        pool: asyncpg.Pool,
        *,
        allow_default_organization: bool = False,
        default_organization_id: str | None = None,
    ):
        self._pool = pool
        self._allow_default_organization = allow_default_organization
        self._default_organization_id = (
            str(uuid.UUID(default_organization_id)) if default_organization_id else None
        )

    def acquire(self):
        # Raw acquire is retained for migrations/bootstrap/token-to-tenant lookup.
        # Application repositories should use transaction() or one-shot helpers.
        return self._pool.acquire()

    def _bound_connection(self):
        bound = _request_connection.get()
        if bound and bound[0] == id(self):
            return bound[1]
        return None

    def _organization(self) -> str:
        org = _request_organization.get()
        if org:
            return org
        if self._allow_default_organization and self._default_organization_id:
            return self._default_organization_id
        raise MissingTenantContextError(
            "Tenant context is required for database access; "
            "autodraft.organization_id was not established for this operation."
        )

    @asynccontextmanager
    async def request_transaction(self):
        """Bind one outer tenant transaction to the current request context.

        Repository one-shot calls and nested ``transaction()`` blocks reuse this
        connection, allowing the HTTP mutation and its audit record to commit or
        roll back together.
        """
        if self._bound_connection() is not None:
            raise RuntimeError("A request transaction is already active")
        org = self._organization()
        async with self._pool.acquire() as conn:
            tx = conn.transaction()
            await tx.start()
            token = _request_connection.set((id(self), conn))
            scope = RequestTransactionScope(conn)
            try:
                await conn.execute("SELECT set_config('autodraft.organization_id', $1, true)", org)
                yield scope
            except BaseException:
                await tx.rollback()
                raise
            else:
                if scope.rollback_only:
                    await tx.rollback()
                else:
                    await tx.commit()
            finally:
                _request_connection.reset(token)

    @asynccontextmanager
    async def transaction(self):
        bound = self._bound_connection()
        if bound is not None:
            async with bound.transaction():
                yield bound
            return
        org = self._organization()
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SELECT set_config('autodraft.organization_id', $1, true)", org)
                yield conn

    async def _call(self, method: str, query: str, *args):
        bound = self._bound_connection()
        if bound is not None:
            return await getattr(bound, method)(query, *args)
        org = self._organization()
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SELECT set_config('autodraft.organization_id', $1, true)", org)
                return await getattr(conn, method)(query, *args)

    async def fetch(self, query: str, *args): return await self._call("fetch", query, *args)
    async def fetchrow(self, query: str, *args): return await self._call("fetchrow", query, *args)
    async def fetchval(self, query: str, *args): return await self._call("fetchval", query, *args)
    async def execute(self, query: str, *args): return await self._call("execute", query, *args)


class Database:
    def __init__(
        self,
        url: str,
        *,
        allow_default_organization: bool = False,
        default_organization_id: str | None = None,
    ):
        self.url = url
        self.pool: asyncpg.Pool | None = None
        self._scoped: ScopedPool | None = None
        self._allow_default_organization = allow_default_organization
        self._default_organization_id = default_organization_id

    @staticmethod
    async def _configure_connection(conn: asyncpg.Connection) -> None:
        # asyncpg maps json/jsonb to str by default. AutoDraft treats these
        # columns as typed Python data, so install codecs once at pool creation.
        for pg_type in ("json", "jsonb"):
            await conn.set_type_codec(
                pg_type,
                schema="pg_catalog",
                encoder=json.dumps,
                decoder=json.loads,
                format="text",
            )

    async def connect(self):
        self.pool = await asyncpg.create_pool(
            self.url,
            min_size=1,
            max_size=10,
            command_timeout=60,
            init=self._configure_connection,
        )
        self._scoped = ScopedPool(
            self.pool,
            allow_default_organization=self._allow_default_organization,
            default_organization_id=self._default_organization_id,
        )

    async def close(self):
        if self.pool:
            await self.pool.close()

    def p(self) -> ScopedPool:
        if not self.pool or not self._scoped:
            raise RuntimeError("Database is not connected")
        return self._scoped

    def raw_pool(self) -> asyncpg.Pool:
        if not self.pool:
            raise RuntimeError("Database is not connected")
        return self.pool

    async def runtime_role_diagnostics(self) -> dict[str, Any]:
        """Return the PostgreSQL properties that determine whether RLS can be bypassed."""
        async with self.raw_pool().acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT r.rolname AS role_name,
                       r.rolsuper AS is_superuser,
                       r.rolbypassrls AS bypass_rls,
                       EXISTS (
                         SELECT 1
                         FROM pg_class c
                         JOIN pg_namespace n ON n.oid=c.relnamespace
                         JOIN pg_attribute a ON a.attrelid=c.oid
                           AND a.attname='organization_id'
                           AND a.attnum > 0
                           AND NOT a.attisdropped
                         WHERE c.relowner=r.oid
                           AND c.relkind IN ('r','p')
                           AND n.nspname NOT IN ('pg_catalog','information_schema')
                       ) AS owns_tenant_tables
                FROM pg_roles r
                WHERE r.rolname=current_user
                """
            )
        if not row:
            raise RuntimeError("Unable to inspect PostgreSQL runtime role")
        return dict(row)

    async def assert_rls_hardening_migrated(self) -> None:
        bootstrap_tables = {
            "public_intake_token_hashes",
            "public_legacy_intake_token_hashes",
            "public_user_identities",
            "public_workflow_tokens",
        }
        runtime_infrastructure_tables = {
            "runtime_jobs",
            "runtime_job_events",
            "runtime_chunk_sessions",
            "runtime_chunks",
        }
        async with self.raw_pool().acquire() as conn:
            present = await conn.fetchval(
                "SELECT to_regprocedure('autodraft_current_organization_id()') IS NOT NULL"
            )
            rows = await conn.fetch(
                """
                SELECT c.relname,
                       c.relrowsecurity AS rls_enabled,
                       c.relforcerowsecurity AS rls_forced,
                       EXISTS (
                         SELECT 1 FROM pg_policy p
                         WHERE p.polrelid=c.oid AND p.polname='autodraft_tenant_isolation'
                       ) AS tenant_policy
                FROM pg_class c
                JOIN pg_namespace n ON n.oid=c.relnamespace
                JOIN pg_attribute a ON a.attrelid=c.oid
                  AND a.attname='organization_id'
                  AND a.attnum > 0
                  AND NOT a.attisdropped
                WHERE n.nspname='public' AND c.relkind IN ('r','p')
                ORDER BY c.relname
                """
            )
            tenant_fk_present = await conn.fetchval(
                """SELECT EXISTS(
                       SELECT 1 FROM pg_constraint
                       WHERE conname='fk_matter_participants_matter_tenant'
                     )"""
            )
            canonical_guard_present = await conn.fetchval(
                "SELECT to_regprocedure('autodraft_guard_legacy_canonical_fact_write()') IS NOT NULL"
            )
            durable_runtime_present = await conn.fetchval(
                "SELECT to_regprocedure('autodraft_claim_runtime_job(text,integer,integer)') IS NOT NULL"
            )
            canonical_completion_present = await conn.fetchval(
                """SELECT EXISTS(SELECT 1 FROM pg_constraint WHERE conname='fk_matters_practice_stage_compatible')
                          AND to_regclass('matter_field_value_items') IS NOT NULL
                          AND to_regclass('contact_field_value_items') IS NOT NULL
                          AND to_regclass('field_value_migration_errors') IS NOT NULL"""
            )
        if not present:
            raise RuntimeError(
                "Required RLS hardening migration is not applied. "
                "Run migrations with MIGRATION_DATABASE_URL (recommended) or apply them before starting the runtime role."
            )
        unprotected = []
        for row in rows:
            name = row["relname"]
            if name in bootstrap_tables:
                continue
            if name in runtime_infrastructure_tables:
                # Durable queue tables intentionally do not FORCE RLS so the
                # table-owner SECURITY DEFINER claim/prune functions can recover
                # work across tenants. Direct runtime-role access must still be
                # protected by normal RLS and the tenant policy.
                if not (row["rls_enabled"] and row["tenant_policy"]):
                    unprotected.append(name)
                continue
            if not all(row[key] for key in ("rls_enabled", "rls_forced", "tenant_policy")):
                unprotected.append(name)
        if unprotected:
            raise RuntimeError(
                "Tenant isolation is incomplete for: " + ", ".join(unprotected) + ". "
                "Apply migration 20261005000019_tenant_relational_integrity.sql."
            )
        if not tenant_fk_present:
            raise RuntimeError(
                "Tenant-consistent foreign keys are not fully migrated. "
                "Apply migration 20261005000019_tenant_relational_integrity.sql."
            )
        if not canonical_guard_present:
            raise RuntimeError(
                "Canonical legal-value authority migration is not applied. "
                "Apply migration 20261005000020_canonical_legal_value_authority.sql."
            )
        if not durable_runtime_present:
            raise RuntimeError(
                "Durable runtime-state migration is not applied. "
                "Apply migrations through 20261006000026_runtime_queue_completion.sql."
            )
        if not canonical_completion_present:
            raise RuntimeError(
                "Canonical data completion migration is not applied. "
                "Apply migration 20261006000023_canonical_data_completion.sql."
            )

    async def assert_safe_runtime_role(self, *, allow_unsafe: bool = False) -> dict[str, Any]:
        diagnostics = await self.runtime_role_diagnostics()
        unsafe = []
        if diagnostics["is_superuser"]:
            unsafe.append("SUPERUSER")
        if diagnostics["bypass_rls"]:
            unsafe.append("BYPASSRLS")
        if diagnostics["owns_tenant_tables"]:
            unsafe.append("tenant-table owner")
        diagnostics["unsafe_reasons"] = unsafe
        if unsafe and not allow_unsafe:
            raise RuntimeError(
                "Unsafe PostgreSQL runtime role "
                f"{diagnostics['role_name']!r}: {', '.join(unsafe)}. "
                "Use a dedicated non-owner, non-superuser, NOBYPASSRLS runtime role. "
                "For local development only, ALLOW_UNSAFE_DATABASE_ROLE=true may be set explicitly."
            )
        return diagnostics


_VERSION_RE = re.compile(r"^(\d+)")
_MIGRATION_LOCK_KEY = 0x4155544F44524146  # "AUTODRAF" as a stable advisory-lock key


def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sqlx_checksum(path: Path) -> bytes:
    """Return the checksum SQLx stores in `_sqlx_migrations`.

    SQLx hashes the migration SQL with SHA-384. Hash the exact UTF-8 file bytes
    so line endings/BOM are not silently normalized by Python text I/O.
    """
    return hashlib.sha384(path.read_bytes()).digest()


def _version(path: Path) -> int | None:
    match = _VERSION_RE.match(path.name)
    return int(match.group(1)) if match else None


async def run_migrations(db: Database, migrations_dir: str | Path = "migrations") -> None:
    """Apply Python migrations safely, including databases previously managed by SQLx.

    The first Python backend used only a filename table. This runner upgrades that
    table in place with checksums/source metadata, imports successful matching SQLx
    versions instead of replaying them, and serialises concurrent startup via a
    PostgreSQL advisory lock.
    """

    migrations_path = Path(migrations_dir)
    if str(migrations_dir) == "migrations":
        migrations_path = Path(__file__).resolve().parent.parent / "migrations"

    paths = sorted(migrations_path.glob("*.sql"))
    pool = db.raw_pool()

    async with pool.acquire() as conn:
        await conn.execute("SELECT pg_advisory_lock($1)", _MIGRATION_LOCK_KEY)
        try:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS autodraft_schema_migrations (
                    name TEXT PRIMARY KEY,
                    checksum TEXT,
                    source TEXT NOT NULL DEFAULT 'python',
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            # Upgrade the original tiny migration-history table without requiring
            # a separate migration that itself depends on the runner.
            await conn.execute("ALTER TABLE autodraft_schema_migrations ADD COLUMN IF NOT EXISTS checksum TEXT")
            await conn.execute("ALTER TABLE autodraft_schema_migrations ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'python'")

            applied_rows = await conn.fetch(
                "SELECT name, checksum, source FROM autodraft_schema_migrations"
            )
            applied = {row["name"]: row for row in applied_rows}

            sqlx_migrations: dict[int, bytes] = {}
            sqlx_exists = await conn.fetchval("SELECT to_regclass('_sqlx_migrations') IS NOT NULL")
            if sqlx_exists:
                # SQLx's history contract includes a SHA-384 checksum. Importing
                # by version alone can silently bless a locally modified file, so
                # checksum availability/equality is mandatory.
                try:
                    rows = await conn.fetch("SELECT version,checksum FROM _sqlx_migrations WHERE success = TRUE")
                except asyncpg.UndefinedColumnError as exc:
                    raise RuntimeError(
                        "Existing _sqlx_migrations table has no checksum column; "
                        "AutoDraft cannot prove migration equivalence safely."
                    ) from exc
                for row in rows:
                    stored = row["checksum"]
                    if stored is None:
                        raise RuntimeError(f"SQLx migration {row['version']} has no checksum")
                    sqlx_migrations[int(row["version"])] = bytes(stored)

            for path in paths:
                digest = _checksum(path)
                existing = applied.get(path.name)
                if existing:
                    previous = existing["checksum"]
                    if previous and previous != digest:
                        raise RuntimeError(
                            f"Migration checksum mismatch for {path.name}. "
                            "Do not edit an already-applied migration; add a new migration instead."
                        )
                    if not previous:
                        await conn.execute(
                            "UPDATE autodraft_schema_migrations SET checksum=$1 WHERE name=$2",
                            digest,
                            path.name,
                        )
                    continue

                version = _version(path)
                if version is not None and version in sqlx_migrations:
                    expected_sqlx = _sqlx_checksum(path)
                    stored_sqlx = sqlx_migrations[version]
                    if not hmac.compare_digest(expected_sqlx, stored_sqlx):
                        raise RuntimeError(
                            f"SQLx migration checksum mismatch for version {version} ({path.name}). "
                            "The local SQL is not byte-equivalent to the migration recorded by SQLx."
                        )
                    await conn.execute(
                        """
                        INSERT INTO autodraft_schema_migrations(name, checksum, source)
                        VALUES($1, $2, 'sqlx-import')
                        ON CONFLICT(name) DO NOTHING
                        """,
                        path.name,
                        digest,
                    )
                    continue

                sql = path.read_text(encoding="utf-8")
                async with conn.transaction():
                    await conn.execute(sql)
                    await conn.execute(
                        "INSERT INTO autodraft_schema_migrations(name, checksum, source) VALUES($1,$2,'python')",
                        path.name,
                        digest,
                    )
        finally:
            await conn.execute("SELECT pg_advisory_unlock($1)", _MIGRATION_LOCK_KEY)


async def ensure_local_default_identity(
    db: Database,
    *,
    organization_id: str,
    user_id: str,
    role: str,
) -> None:
    """Ensure the explicit local-development tenant/user exists.

    Runtime queue rows have tenant-consistent foreign keys to ``app_users``.
    Older local databases may contain the historical default organization but no
    default user, which makes local Word flows fail at job creation time. This
    helper is intentionally called only from the ``SECURITY_MODE=local`` startup
    path.
    """

    org = str(uuid.UUID(str(organization_id)))
    user = str(uuid.UUID(str(user_id)))
    normalized_role = role if role in {"owner", "admin", "lawyer", "staff", "viewer"} else "owner"
    async with db.raw_pool().acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT set_config('autodraft.organization_id', $1, true)", org)
            await conn.execute(
                """
                INSERT INTO organizations(id, name)
                VALUES($1::uuid, 'Local AutoDraft')
                ON CONFLICT (id) DO NOTHING
                """,
                org,
            )
            await conn.execute(
                """
                INSERT INTO app_users(id, organization_id, email, display_name, role, active)
                VALUES($1::uuid, $2::uuid, NULL, 'Local AutoDraft User', $3, TRUE)
                ON CONFLICT (id) DO UPDATE
                   SET organization_id=EXCLUDED.organization_id,
                       display_name=COALESCE(NULLIF(app_users.display_name, ''), EXCLUDED.display_name),
                       role=EXCLUDED.role,
                       active=TRUE,
                       updated_at=NOW()
                """,
                user,
                org,
                normalized_role,
            )
