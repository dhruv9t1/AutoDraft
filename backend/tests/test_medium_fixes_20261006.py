from __future__ import annotations

import ast
import base64
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.domain.expressions import ExpressionError, evaluate, validate_expression
from app.domain.template_automation import TemplateAutomationError, _format_value, validate_blueprint
from app.runtime_object_store import RuntimeObjectStore, RuntimeObjectStoreError
from app.security import PostgresRateLimiter, RequestBodyLimitMiddleware

ROOT = Path(__file__).resolve().parents[1]


def test_expression_operator_arity_is_validated_at_publication_time():
    for expression in (
        {"eq": [1, 1, 1]},
        {"not": [True, False]},
        {"if": [True, 1, 2, 3]},
        {"divide": [10]},
        {"and": []},
    ):
        with pytest.raises(ExpressionError):
            validate_expression(expression)
    validate_expression({"if": [True, 1, 2]})
    validate_expression({"eq": [1, 1]})


def test_contains_fails_closed_for_incompatible_types():
    assert evaluate({"contains": [[1, 2], 2]}, {}).value is True
    assert evaluate({"contains": ["legal draft", "draft"]}, {}).value is True
    with pytest.raises(ExpressionError, match="text member"):
        evaluate({"contains": ["123", 2]}, {})
    with pytest.raises(ExpressionError, match="requires a text"):
        evaluate({"contains": [12345, "23"]}, {})


def test_blueprint_number_formatting_is_validated_and_render_errors_do_not_fall_back():
    with pytest.raises(TemplateAutomationError, match="numberDecimals"):
        validate_blueprint({"bindings": [{"controlTag": "amount", "semanticKey": "matter.amount", "formatting": {"numberDecimals": 99}}]})
    with pytest.raises(TemplateAutomationError, match="number formatting"):
        _format_value("not-a-number", {"numberDecimals": 2})
    assert _format_value("1234.5", {"numberDecimals": 2, "grouping": True}) == "1,234.50"


@pytest.mark.asyncio
async def test_request_body_limit_never_emits_second_response_start_after_downstream_started():
    sent = []
    receive_calls = 0

    async def receive():
        nonlocal receive_calls
        receive_calls += 1
        return {"type": "http.request", "body": b"0123456789", "more_body": False}

    async def send(message):
        sent.append(message)

    async def app(scope, limited_receive, tracked_send):
        await tracked_send({"type": "http.response.start", "status": 200, "headers": []})
        await limited_receive()

    middleware = RequestBodyLimitMiddleware(app, max_bytes=5, public_max_bytes=5)
    scope = {"type": "http", "path": "/api/example", "headers": []}
    await middleware(scope, receive, send)
    assert [m["type"] for m in sent].count("http.response.start") == 1
    assert sent[-1]["type"] == "http.response.body"


@pytest.mark.asyncio
async def test_object_store_encrypts_bytes_at_rest_and_authenticates_ciphertext(tmp_path):
    key = base64.urlsafe_b64encode(b"k" * 32).decode().rstrip("=")
    store = RuntimeObjectStore(str(tmp_path / "objects"), encryption_key=key)
    item = await store.put("org/job/input.bin", b"confidential legal material")
    raw = (tmp_path / "objects" / item.key).read_bytes()
    assert b"confidential legal material" not in raw
    assert await store.get(item.key) == b"confidential legal material"
    tampered = bytearray(raw); tampered[-1] ^= 1
    (tmp_path / "objects" / item.key).write_bytes(tampered)
    with pytest.raises(RuntimeObjectStoreError, match="failed authentication"):
        await store.get(item.key)


class _BrokenPool:
    def acquire(self):
        raise RuntimeError("database unavailable")


class _BrokenDb:
    def raw_pool(self):
        return _BrokenPool()


@pytest.mark.asyncio
async def test_rate_limiter_uses_bounded_local_fallback_when_database_is_unavailable():
    limiter = PostgresRateLimiter(_BrokenDb(), limit=100, lease_size=10, fallback_limit=2, db_retry_seconds=60)
    assert await limiter.allow("client") is True
    assert await limiter.allow("client") is True
    assert await limiter.allow("client") is False


def test_permission_matrix_is_enforced_by_route_dependency_not_http_middleware():
    runtime = (ROOT / "app/runtime.py").read_text()
    main = (ROOT / "app/main.py").read_text()
    assert "require_permission(ctx, permission_for_request(request.method, request.url.path))" in runtime
    middleware_block = main.split('async def request_observability', 1)[1]
    assert "permission_for_request(" not in middleware_block
    assert "require_permission(" not in middleware_block

    # Every non-public API mutation must explicitly depend on api_auth or a
    # stronger dependency that itself depends on api_auth.
    accepted = {"api_auth", "admin_auth", "lawyer_auth"}
    missing = []
    for path in (ROOT / "app/api").glob("*.py"):
        source = path.read_text()
        tree = ast.parse(source)
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            mutation = False
            route_path = None
            decorator_auth = False
            for dec in node.decorator_list:
                if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)):
                    continue
                if dec.func.attr.lower() not in {"post", "put", "patch", "delete"}:
                    continue
                mutation = True
                if dec.args and isinstance(dec.args[0], ast.Constant):
                    route_path = str(dec.args[0].value)
                dec_text = ast.get_source_segment(source, dec) or ""
                decorator_auth = any(f"Depends({name})" in dec_text for name in accepted)
            if not mutation or not route_path or not route_path.startswith("/api/"):
                continue
            if "/public/" in route_path or route_path == "/api/auth/office-exchange":
                continue
            function_text = ast.get_source_segment(source, node) or ""
            signature = function_text.split("\n", 1)[0]
            param_auth = any(f"Depends({name})" in signature for name in accepted)
            if not decorator_auth and not param_auth:
                missing.append(f"{path.name}:{node.name}:{route_path}")
    assert not missing, missing


def test_medium_fixes_remove_webhook_body_retention_and_add_quarantine_lifecycle():
    webhook = (ROOT / "app/webhook_worker.py").read_text()
    config = (ROOT / "app/config.py").read_text()
    janitor = (ROOT / "app/quarantine_cleanup.py").read_text()
    main = (ROOT / "app/main.py").read_text()
    assert "response.text" not in webhook
    assert "response_excerpt=None" in webhook
    assert "intake_quarantine_cleanup_interval_seconds" in config
    assert "public_intake_token_hashes" in janitor
    assert "DELETE FROM intake_file_quarantine" in janitor
    assert "quarantine_janitor.start()" in main and "quarantine_janitor.stop()" in main


def test_jwks_clients_are_cached_per_tenant_and_object_encryption_is_required_in_token_mode():
    auth = (ROOT / "app/auth.py").read_text()
    config = (ROOT / "app/config.py").read_text()
    assert "@lru_cache(maxsize=32)" in auth
    assert "_entra_jwks_client(tenant).get_signing_key_from_jwt(token)" in auth
    assert "OBJECT_STORE_ENCRYPTION_KEY is required when SECURITY_MODE=token" in auth
    assert "object_store_encryption_key" in config
