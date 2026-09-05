import asyncio
from decimal import Decimal

import pytest

from sentinel.domain.integrity import TransactionRequest
from sentinel.infrastructure.persistence.database import _split_sql_statements, create_database
from sentinel.infrastructure.persistence.models import (
    IdempotencyRecord,
    TransactionRecord,
    TransactionStateRecord,
)


def make_request():
    return TransactionRequest(
        "txn-db-001", "idem-db-001", "source", "destination", Decimal("10"), "ETB"
    )


def test_models_contain_only_sentinel_metadata_and_constraints():
    assert TransactionRecord.__tablename__ == "sentinel_transactions"
    assert TransactionStateRecord.__tablename__ == "sentinel_transaction_state_history"
    assert IdempotencyRecord.__tablename__ == "sentinel_idempotency_records"
    assert any(
        "amount > 0" in str(constraint.sqltext)
        for constraint in TransactionRecord.__table__.constraints
        if hasattr(constraint, "sqltext")
    )
    assert "amount" not in {column.name for column in IdempotencyRecord.__table__.columns}


def test_database_requires_async_postgresql_and_configures_pool():
    with pytest.raises(ValueError):
        create_database("sqlite+aiosqlite://")

    try:
        engine, sessions = create_database(
            "postgresql+asyncpg://user:pass@localhost/sentinel", pool_size=3
        )
    except RuntimeError as error:
        assert "asyncpg" in str(error)
    else:
        assert engine.url.drivername == "postgresql+asyncpg"
        assert sessions.kw.get("expire_on_commit") is False
        asyncio.run(engine.dispose())


def test_migration_file_contains_required_tables_and_constraints(tmp_path):
    migration = tmp_path / "migration.sql"
    migration.write_text(
        "CREATE TABLE sentinel_transactions (amount NUMERIC NOT NULL CHECK (amount > 0));\n"
        "CREATE TABLE sentinel_idempotency_records (idempotency_key VARCHAR(256) PRIMARY KEY);\n",
        encoding="utf-8",
    )

    assert "sentinel_transactions" in migration.read_text(encoding="utf-8")
    assert "sentinel_idempotency_records" in migration.read_text(encoding="utf-8")


def test_migration_splitter_preserves_quoted_semicolons():
    statements = _split_sql_statements(
        "CREATE TABLE test_table (value TEXT DEFAULT 'a;b');\n"
        "-- comment;\n"
        "CREATE TABLE other_table (value TEXT);"
    )

    assert len(statements) == 2
    assert "'a;b'" in statements[0]
    assert "other_table" in statements[1]
