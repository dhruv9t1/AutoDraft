from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _compact(text: str) -> str:
    """Collapse all whitespace so assertions check code intent, not formatting."""
    return re.sub(r"\s+", "", text)


def test_public_intake_has_tenant_bootstrap_mapping():
    migration = (ROOT / "backend/migrations/20261004000013_runtime_hardening.sql").read_text()
    repo = (ROOT / "backend/app/repositories/intake.py").read_text()
    service = (ROOT / "backend/app/services/intake_service.py").read_text()
    assert "CREATE TABLE IF NOT EXISTS public_intake_tokens" in migration
    assert "public_session_by_token" in repo
    assert "set_config('autodraft.organization_id'" in repo
    assert "set_request_organization" in service


def test_audit_log_does_not_require_precreated_user_row():
    main = (ROOT / "backend/app/main.py").read_text()
    assert "SELECT id FROM app_users WHERE id=$2::uuid AND organization_id=$1::uuid" in main


def test_release_contains_only_word_manifest_identity():
    extension = ROOT / "word-extension"
    assert not (extension / "manifest.json").exists()
    xml = (extension / "manifest.xml").read_text()
    commands = (extension / "src/commands/commands.ts").read_text()
    taskpane = (extension / "src/taskpane/taskpane.html").read_text()
    assert '<Host Name="Document"' in xml
    assert "Mailbox.ReadWrite" not in xml
    assert "MailboxEnums" not in commands
    assert "Contoso" not in xml + commands + taskpane


def test_no_dead_background_job_route_or_stale_runtime_defaults():
    template_service = (ROOT / "word-extension/src/services/templateService.ts").read_text()
    eval_script = (ROOT / "word-extension/scripts/eval-variable-identification.ts").read_text()
    config = (ROOT / "backend/app/config.py").read_text()
    assert "/api/jobs/" not in template_service
    assert "localhost:8080" not in eval_script
    assert 'ollama_model: str = "qwen3:4b"' in config


def test_word_event_lifecycle_uses_tracking_and_original_context():
    event_service = (ROOT / "word-extension/src/services/word/eventService.ts").read_text()
    queue = (ROOT / "word-extension/src/services/word/operationQueue.ts").read_text()
    assert ".track()" in event_service
    assert ".untrack()" in event_service
    assert "runWordOperationWithContext" in event_service
    assert "Word.run(context, callback)" not in queue
    assert "callback(context)" in queue


def test_binding_planner_verifies_existing_binding_text_and_trim_map():
    planner = (ROOT / "word-extension/src/services/word/bindingPlanner.ts").read_text()
    # Whitespace-insensitive: the planner must map the trimmed range through the
    # same left/rightTrimmed slice for both text and the source-position map.
    assert "map:map.slice(left,rightTrimmed)" in _compact(planner)
    assert "an existing control has this binding ID but no longer contains the expected source text" in planner


def test_intake_submission_contract_accepts_multiselect_arrays():
    from app.models import IntakeSubmission
    parsed = IntakeSubmission(answers={"services": ["Drafting", "Review"]})
    assert parsed.answers["services"] == ["Drafting", "Review"]


def test_public_intake_error_renderer_does_not_inject_message_html():
    source = (ROOT / "backend/app/api/intake.py").read_text()
    assert "strong.textContent=String(message" in source
    assert "err.innerHTML='<b>'+message" not in source


def test_intake_file_workflow_has_authenticated_download_and_single_current_file():
    api = (ROOT / "backend/app/api/intake.py").read_text()
    service = (ROOT / "backend/app/services/intake_service.py").read_text()
    migration = (ROOT / "backend/migrations/20261004000013_runtime_hardening.sql").read_text()
    assert '@router.get("/api/intake/{token}/files/{question_id}",dependencies=[Depends(api_auth)])' in api
    assert "download_file" in service
    assert "uq_intake_files_session_question" in migration
    assert "ON CONFLICT(session_id,question_id) DO UPDATE" in service


def test_core_readiness_does_not_make_ai_outage_take_manual_app_offline():
    source = (ROOT / "backend/app/api/health.py").read_text()
    assert '"ready": bool(database_ready)' in source
    assert '"aiFeaturesReady": bool(ai_state.get("ready"))' in source
    assert 'bool(database_ready and ai_state.get("ready"))' not in source


def test_ocr_uses_current_skip_mode_syntax():
    source = (ROOT / "backend/app/ocr_service.py").read_text()
    assert '"--mode",\n            "skip"' in source


def test_intake_visibility_handles_multi_select_values():
    from app.services.intake_service import IntakeService
    q = {"displayRule": {"questionId": "services", "operator": "equals", "value": "Review"}}
    assert IntakeService.is_visible(q, {"services": ["Drafting", "Review"]}) is True
    q["displayRule"]["value"] = "Other"
    assert IntakeService.is_visible(q, {"services": ["Drafting", "Review"]}) is False
