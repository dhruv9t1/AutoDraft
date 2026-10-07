import asyncpg

import run


def test_database_startup_error_is_actionable_and_does_not_echo_password():
    message = run._format_database_startup_error(
        "postgresql://autodraft_app:super-secret@localhost:5432/wordaddin",
        asyncpg.InvalidPasswordError('password authentication failed for user "autodraft_app"'),
    )

    assert "PostgreSQL rejected the configured DATABASE_URL password" in message
    assert "backend/.env.example" in message
    assert "ALTER ROLE autodraft_app" in message
    assert "super-secret" not in message
