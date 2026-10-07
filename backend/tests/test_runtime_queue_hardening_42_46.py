from __future__ import annotations

from pathlib import Path

import pytest

from app.runtime_object_store import RuntimeObjectStore, RuntimeObjectStoreError

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_runtime_object_store_is_atomic_and_path_safe(tmp_path):
    store = RuntimeObjectStore(str(tmp_path / "objects"))
    item = await store.put("runtime/org/jobs/one/input.bin", b"legal-bytes")
    assert item.byte_length == 11
    assert await store.get(item.key) == b"legal-bytes"
    assert await store.exists(item.key)
    await store.delete(item.key)
    assert not await store.exists(item.key)
    with pytest.raises(RuntimeObjectStoreError):
        await store.put("../escape", b"no")


def test_runtime_42_user_ownership_is_persisted_and_enforced():
    migration = (ROOT / "migrations/20261006000026_runtime_queue_completion.sql").read_text()
    state = (ROOT / "app/runtime_state.py").read_text()
    documents = (ROOT / "app/api/documents.py").read_text()
    ocr = (ROOT / "app/api/ocr.py").read_text()
    templates = (ROOT / "app/api/templates.py").read_text()
    assert "owner_user_id UUID" in migration
    assert "fk_runtime_jobs_owner_tenant" in migration
    assert "fk_runtime_chunk_sessions_owner_tenant" in migration
    assert "owner_user_id is required for user-facing runtime job access" in state
    assert "owner_user_id=request.state.security.user_id" in documents
    assert "owner_user_id=request.state.security.user_id" in ocr
    assert "owner_user_id=request.state.security.user_id" in templates


def test_runtime_43_44_incremental_bytes_and_quotas_are_enforced_before_write():
    state = (ROOT / "app/runtime_state.py").read_text()
    config = (ROOT / "app/config.py").read_text()
    for setting in (
        "runtime_max_active_jobs_per_org",
        "runtime_max_active_jobs_per_user",
        "runtime_max_chunk_sessions_per_user",
        "runtime_max_temp_bytes_per_org",
    ):
        assert setting in config
        assert f"self.settings.{setting}" in state
    assert "projected_session" in state
    assert "Chunk upload exceeds declared total size" in state
    assert "pg_advisory_xact_lock" in state


def test_runtime_45_cluster_worker_admission_and_external_worker_service():
    migration = (ROOT / "migrations/20261006000026_runtime_queue_completion.sql").read_text()
    main = (ROOT / "app/main.py").read_text()
    worker_process = (ROOT / "app/runtime_worker_process.py").read_text()
    config = (ROOT / "app/config.py").read_text()
    assert "p_cluster_concurrency" in migration
    assert "pg_advisory_xact_lock(hashtext('autodraft:runtime:claim'))" in migration
    assert "runtime_cluster_concurrency" in config
    assert "runtime_worker_mode" in config
    assert 'settings.security_mode.strip().lower() == "local"' in main
    assert "Dedicated AutoDraft runtime worker started" in worker_process


def test_runtime_46_large_runtime_bytes_live_outside_postgres():
    migration = (ROOT / "migrations/20261006000026_runtime_queue_completion.sql").read_text()
    state = (ROOT / "app/runtime_state.py").read_text()
    runtime = (ROOT / "app/runtime.py").read_text()
    assert "payload_object_key" in migration
    assert "input_object_key" in migration
    assert "output_object_key" in migration
    assert "object_key TEXT" in migration
    assert "content=NULL" in state
    assert "RuntimeObjectStore" in runtime
    assert "self.objects.put" in state
