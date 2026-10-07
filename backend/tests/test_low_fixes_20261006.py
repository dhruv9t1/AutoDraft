from __future__ import annotations

import ast
from pathlib import Path

from app.security import normalize_correlation_id

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent


def test_correlation_ids_are_bounded_and_header_log_safe():
    valid = "550e8400-e29b-41d4-a716-446655440000"
    assert normalize_correlation_id(valid, fallback="fallback") == valid
    for invalid in ("", " has-space ", "bad\nheader", "x" * 129, "🔥"):
        assert normalize_correlation_id(invalid, fallback="safe-fallback") == "safe-fallback"
    main = (ROOT / "app/main.py").read_text()
    assert 'normalize_correlation_id(request.headers.get("X-Correlation-ID")' in main
    assert 'normalize_correlation_id(getattr(request.state, "request_id", None)' in main


def test_persistence_cleanup_paths_log_failures_and_command_tags_fail_loudly():
    generation = (ROOT / "app/services/generation_service.py").read_text()
    templates_repo = (ROOT / "app/repositories/templates.py").read_text()
    automation_repo = (ROOT / "app/repositories/automation.py").read_text()
    templates_api = (ROOT / "app/api/templates.py").read_text()
    assert "Failed to persist failed status for generation attempt" in generation
    assert "Failed to remove orphaned generation object" in generation
    assert "Failed to remove orphaned template snapshot object" in templates_repo
    assert "TEMPLATE_SNAPSHOT_UNREADABLE" in automation_repo
    assert "except Exception: docx=None" not in automation_repo
    assert "except Exception:docx=None" not in automation_repo
    assert "def _affected_rows" in templates_api
    assert "except Exception:pass" not in templates_api


def test_release_tooling_excludes_python_bytecode_and_common_caches():
    packager = (PROJECT / "scripts/make-release-zip.sh").read_text()
    auditor = (PROJECT / "scripts/audit-release.py").read_text()
    assert "*.pyc" in packager and "*.pyo" in packager
    assert ".mypy_cache" in packager and ".ruff_cache" in packager
    assert 'BAD_SUFFIXES={".pyc",".pyo"}' in auditor
    assert '".mypy_cache"' in auditor and '".ruff_cache"' in auditor


def test_implementation_status_matches_webhook_worker_reality():
    status = (PROJECT / "IMPLEMENTATION_STATUS.md").read_text()
    assert "production webhook delivery workers/retries on top of the transactional outbox" not in status
    assert "dedicated production webhook dispatcher" in status
    assert (ROOT / "app/webhook_worker.py").exists()
    assert (ROOT / "app/webhook_worker_process.py").exists()


def test_low_fix_files_parse_cleanly():
    for relative in (
        "app/main.py",
        "app/security.py",
        "app/services/generation_service.py",
        "app/repositories/templates.py",
        "app/repositories/automation.py",
        "app/api/templates.py",
    ):
        ast.parse((ROOT / relative).read_text())
