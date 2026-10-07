from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Runtime connections must use a dedicated non-owner/NOBYPASSRLS role.
    database_url: str = "postgresql://autodraft_app:autodraft_app@localhost:5432/wordaddin"
    # Optional owner/migrator connection. Production should keep DDL credentials
    # separate from DATABASE_URL; when empty, startup uses DATABASE_URL for
    # migrations for backwards-compatible local development.
    migration_database_url: str = ""
    # Unsafe database roles are rejected at startup unless this explicit local-only
    # escape hatch is enabled.
    allow_unsafe_database_role: bool = False
    # The historical default organization is allowed only in security_mode=local
    # and only when this development flag remains enabled. Token mode always fails closed.
    allow_local_default_organization: bool = True
    # Local/header-based identity is a development-only mode. By default it may
    # only bind to and accept direct requests from loopback. This escape hatch
    # exists solely for intentionally isolated development environments.
    allow_external_local_auth: bool = False
    host: str = "127.0.0.1"
    port: int = 3001
    api_auth_token: str = ""
    cors_origins: str = ""
    trusted_proxy_ips: str = ""
    rate_limit_requests: int = 180
    rate_limit_window_seconds: int = 60
    rate_limit_lease_size: int = 10
    # If PostgreSQL is temporarily unavailable, enforce a smaller per-process
    # fallback ceiling rather than making every API request depend on the DB.
    rate_limit_fallback_requests: int = 45
    rate_limit_db_retry_seconds: float = 5.0
    # Webhook/outbox delivery. Endpoint signing secrets are encrypted at rest.
    # Production must provide a high-entropy WEBHOOK_SECRET_ENCRYPTION_KEY and run
    # `python -m app.webhook_worker_process` as a dedicated dispatcher.
    webhook_secret_encryption_key: str = ""
    webhook_worker_poll_seconds: float = 0.5
    webhook_worker_concurrency: int = 4
    webhook_lease_seconds: int = 60
    webhook_timeout_seconds: float = 15.0
    webhook_max_attempts: int = 8
    webhook_backoff_base_seconds: int = 5
    webhook_backoff_max_seconds: int = 3600
    webhook_prepare_batch_size: int = 100
    webhook_allow_private_targets: bool = False
    security_hsts_seconds: int = 31536000
    security_enable_hsts: bool = True
    security_frame_ancestors: str = "'self' https://*.office.com https://*.officeapps.live.com"
    security_mode: str = "local"  # local | token
    auth_hmac_secret: str = ""
    # Production Word/Office SSO. When configured, the add-in exchanges an
    # Office/Entra access token for a short-lived AutoDraft token. The Entra
    # identity must already be mapped to an active app_user.
    entra_tenant_id: str = ""
    entra_client_id: str = ""
    entra_resource_uri: str = ""
    entra_required_scope: str = "access_as_user"
    auth_token_ttl_seconds: int = 3600
    default_organization_id: str = "00000000-0000-0000-0000-000000000001"
    default_user_id: str = "00000000-0000-0000-0000-000000000001"
    default_user_role: str = "owner"
    max_docx_snapshot_bytes: int = 100 * 1024 * 1024
    matter_document_max_bytes: int = 100 * 1024 * 1024
    # HTTP/body and render expansion guards. The ASGI middleware enforces these
    # before FastAPI/Pydantic materializes JSON/Base64 bodies.
    max_request_body_bytes: int = 160 * 1024 * 1024
    max_public_request_body_bytes: int = 2 * 1024 * 1024
    max_public_upload_body_bytes: int = 22 * 1024 * 1024
    max_rendered_docx_bytes: int = 150 * 1024 * 1024
    max_rendered_xml_part_bytes: int = 64 * 1024 * 1024
    # Final headless-render limits are checked after repeater expansion and before
    # the generated package is committed. They deliberately cover compressed
    # output, aggregate XML/uncompressed bytes, and surviving content controls.
    max_rendered_total_xml_bytes: int = 96 * 1024 * 1024
    max_rendered_uncompressed_docx_bytes: int = 240 * 1024 * 1024
    max_rendered_content_controls: int = 20000
    max_repeater_items: int = 250
    max_total_repeated_items: int = 2000

    # Public intake upload hardening. Production/token mode requires an AV
    # scanner to be enabled; signature/MIME/polyglot checks always run first.
    intake_file_max_bytes: int = 20 * 1024 * 1024
    intake_session_storage_quota_bytes: int = 50 * 1024 * 1024
    intake_org_daily_upload_quota_bytes: int = 500 * 1024 * 1024
    intake_session_file_count_limit: int = 20
    # Rejected/unverified uploads are isolated from legitimate upload quotas so a
    # public-link attacker cannot deny subsequent valid uploads by filling quarantine.
    intake_quarantine_retention_seconds: int = 24 * 3600
    intake_quarantine_cleanup_interval_seconds: int = 3600
    intake_quarantine_session_storage_quota_bytes: int = 25 * 1024 * 1024
    intake_quarantine_session_file_count_limit: int = 20
    intake_quarantine_org_daily_upload_quota_bytes: int = 250 * 1024 * 1024
    intake_malware_scanner_command: str = "clamscan"
    intake_malware_scan_timeout_seconds: float = 30.0
    intake_require_malware_scan_in_production: bool = True
    intake_allowed_file_extensions: str = ".pdf,.docx,.png,.jpg,.jpeg,.txt"
    # DOCX/OOXML hostile-package guards. Limits are checked from the ZIP
    # central directory before any member is decompressed.
    docx_max_zip_entries: int = 4096
    docx_max_zip_uncompressed_bytes: int = 256 * 1024 * 1024
    docx_max_zip_entry_uncompressed_bytes: int = 64 * 1024 * 1024
    docx_max_zip_compression_ratio: float = 200.0
    docx_zip_ratio_min_uncompressed_bytes: int = 1024 * 1024

    ollama_api_url: str = "http://127.0.0.1:11434"
    ollama_api_key: str = ""
    # vNext reliability default. Separate purpose-specific model settings keep
    # the gateway ready for future provider/model specialization.
    ollama_model: str = "qwen3:4b"
    field_model: str = "qwen3:4b"
    drafting_model: str = "qwen3:4b"
    review_model: str = "qwen3:4b"
    ollama_verifier_model: str = "qwen3:4b"
    ollama_enable_field_verifier: bool = True
    ollama_validate_on_startup: bool = True
    # When false (default), startup records/logs an Ollama problem but keeps the
    # deterministic extraction path available. Set true for locked-down servers.
    ollama_require_model_on_startup: bool = False
    ollama_api_path: str = "/api/chat"
    ollama_timeout_seconds: int = 300
    ollama_max_retries: int = 2
    ollama_chunk_size: int = 8000
    ollama_max_parallel_chunks: int = 2
    ollama_extraction_passes: int = 2
    # Large Word documents can expand to dozens of local model chunks. Above
    # this limit, Auto Detect returns the grounded deterministic candidates
    # immediately and leaves uncertain rows for lawyer review instead of making
    # the Word pane wait for a full System-2 pass.
    ollama_semantic_document_char_limit: int = 50_000
    # The Word task pane cannot reliably render thousands of review-only rows.
    # Large-document preview is therefore condensed before it reaches the UI.
    ollama_large_document_review_candidate_limit: int = 250
    ollama_think_level: str = "off"
    ollama_temperature: float = 0.0
    ollama_top_p: float = 1.0
    ollama_top_k: int = 1
    ollama_seed: int = 42
    # A 32k-context KV cache can exceed RAM on small hosts and Ollama then
    # answers every request with HTTP 500 ("llama-server process has
    # terminated"). _call halves num_ctx on such crashes down to
    # ollama_num_ctx_min; lower ollama_num_ctx upfront on constrained hosts.
    ollama_num_ctx: int = 32768
    ollama_num_ctx_min: int = 4096
    ollama_num_predict: int = 8192

    # Optional lawyer-firm-style System-1 candidate decider. This is deliberately
    # non-critical: if Jev is disabled or unavailable, ambiguous candidates flow
    # to the existing Qwen System-2 verifier / lawyer review.
    system1_provider: str = "off"  # off | jev
    jev_api_url: str = "https://api.typesafe.ai/v1/systemone"
    jev_api_key: str = ""
    jev_model: str = "jev-latest"
    jev_timeout_seconds: float = 20.0

    # Streaming/job transport. Direct SSE and job-event streams both emit a
    # comment heartbeat while idle; tests may override this with a small value.
    sse_heartbeat_seconds: float = 10.0
    extraction_job_ttl_seconds: int = 3600
    # Durable PostgreSQL-backed runtime queue/chunk state. Every API worker may
    # claim queued jobs; leases make jobs recoverable after process restarts.
    runtime_worker_poll_seconds: float = 0.5
    runtime_worker_lease_seconds: int = 90
    # Local concurrency inside one dedicated worker process. Cluster-wide
    # admission is separately capped in PostgreSQL.
    runtime_worker_concurrency: int = 2
    runtime_cluster_concurrency: int = 4
    # In production/token mode API processes do not start background workers.
    # Run ``python -m app.runtime_worker_process`` as a dedicated worker service.
    runtime_worker_mode: str = "auto"  # auto | embedded | external
    runtime_max_active_jobs_per_org: int = 8
    runtime_max_active_jobs_per_user: int = 4
    runtime_max_chunk_sessions_per_user: int = 4
    runtime_max_temp_bytes_per_org: int = 512 * 1024 * 1024
    runtime_object_store_path: str = str(BACKEND_ROOT / ".runtime-objects")
    # Immutable application binaries (template snapshots, generated artifacts,
    # Matter Documents) are kept outside PostgreSQL. Production should point
    # this at durable shared/object storage.
    binary_object_store_path: str = str(BACKEND_ROOT / ".binary-objects")
    # AES-256-GCM key shared by runtime and immutable binary object stores.
    # Required in token/production mode. Use 32 random bytes encoded as hex or
    # URL-safe Base64; never commit the value to source control.
    object_store_encryption_key: str = ""
    generation_job_ttl_seconds: int = 24 * 3600
    # Normal JSON requests are deliberately small; large DOCX uploads use
    # multipart UploadFile endpoints so Base64 cannot be materialized first.
    max_json_request_body_bytes: int = 16 * 1024 * 1024
    max_binary_upload_body_bytes: int = 110 * 1024 * 1024
    chunk_session_ttl_seconds: int = 3600

    # Local OCR. OCRmyPDF/Tesseract are OS-level executables; Python handles
    # upload/session orchestration, image-to-PDF conversion and text extraction.
    ocr_languages: str = "guj,eng"
    ocr_timeout_seconds: int = 1800
    ocr_job_ttl_seconds: int = 3600
    ocr_max_upload_bytes: int = 50 * 1024 * 1024
    # Decompression/rasterization guards. Byte limits alone do not bound decoded
    # image pixels, TIFF frame counts, or PDF page geometry.
    ocr_max_image_width: int = 12000
    ocr_max_image_height: int = 12000
    ocr_max_image_pixels_per_frame: int = 40_000_000
    ocr_max_image_frames: int = 50
    ocr_max_image_total_pixels: int = 100_000_000
    ocr_max_pdf_pages: int = 500
    ocr_max_pdf_page_width_points: float = 2160.0
    ocr_max_pdf_page_height_points: float = 2160.0
    ocr_max_pdf_page_area_points: float = 2_000_000.0
    ocr_max_output_pdf_bytes: int = 200 * 1024 * 1024
    ocr_max_extracted_text_chars: int = 10_000_000
    # OS-level OCR worker limits. POSIX workers apply RLIMIT_AS/CPU/FSIZE and
    # monitor the dedicated temporary directory while OCRmyPDF is running.
    ocr_subprocess_max_memory_bytes: int = 2 * 1024 * 1024 * 1024
    ocr_subprocess_max_cpu_seconds: int = 1200
    ocr_subprocess_max_file_bytes: int = 512 * 1024 * 1024
    ocr_max_temp_bytes: int = 1024 * 1024 * 1024
    ocr_smoke_cache_seconds: int = 300

    log_level: str = "INFO"

    max_document_length: int = 5 * 1024 * 1024
    max_ooxml_body_bytes: int = 50 * 1024 * 1024

    @property
    def cors_origin_list(self) -> list[str]:
        return [x.strip() for x in self.cors_origins.split(",") if x.strip()]

    @property
    def trusted_proxy_list(self) -> list[str]:
        return [x.strip() for x in self.trusted_proxy_ips.split(",") if x.strip()]

    @property
    def intake_allowed_extension_list(self) -> list[str]:
        values=[]
        for raw in self.intake_allowed_file_extensions.split(","):
            value=raw.strip().lower()
            if not value:
                continue
            if not value.startswith("."):
                value="."+value
            values.append(value)
        return values

    @property
    def ocr_language_list(self) -> list[str]:
        values = [x.strip() for x in self.ocr_languages.replace("+", ",").split(",") if x.strip()]
        return values or ["guj", "eng"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
