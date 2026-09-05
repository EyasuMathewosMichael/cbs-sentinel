import asyncio
import os
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from sentinel.domain.integrity import TransactionRequest
from sentinel.domain.transactions import Transaction, TransactionState
from sentinel.infrastructure.persistence.database import (
    create_database,
    run_migration,
    session_scope,
)
from sentinel.infrastructure.persistence.repositories import (
    ConcurrentStateUpdateError,
    IdempotencyConflictError,
    IdempotencyRepository,
    TransactionRepository,
)

DATABASE_URL = os.getenv("SENTINEL_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="SENTINEL_DATABASE_URL is not configured")


def request(transaction_id="integration-txn"):
    return TransactionRequest(
        transaction_id,
        f"idem-{transaction_id}",
        "source-account",
        "destination-account",
        Decimal("10.00"),
        "ETB",
    )


def test_real_postgresql_persistence_constraints_transactions_and_rollback():
    async def scenario():
        run_id = uuid4().hex
        transaction_id = f"integration-{run_id}"
        engine, sessions = create_database(DATABASE_URL, pool_size=2, max_overflow=1)
        await run_migration(engine, "migrations/001_initial_postgresql.sql")
        transaction_repository = TransactionRepository()
        idempotency_repository = IdempotencyRepository()
        transaction = Transaction(transaction_id)
        async with session_scope(sessions) as session:
            assert await idempotency_repository.reserve(session, request(transaction_id))
            await transaction_repository.create(session, request(transaction_id), transaction)
        async with session_scope(sessions) as session:
            assert not await idempotency_repository.reserve(session, request(transaction_id))
            persisted = await transaction_repository.get(session, transaction_id)
            assert persisted is not None
            assert persisted.state == TransactionState.RECEIVED.value
            assert len(persisted.state_history) == 1
        transaction.transition(TransactionState.VALIDATING)
        async with session_scope(sessions) as session:
            await transaction_repository.append_state(session, transaction, "integration-test")
        async with session_scope(sessions) as session:
            persisted = await transaction_repository.get(session, transaction_id)
            assert persisted is not None
            assert persisted.state == TransactionState.VALIDATING.value
            assert len(persisted.state_history) == 2
        with pytest.raises(IntegrityError):
            async with session_scope(sessions) as session:
                await session.execute(
                    text(
                        "INSERT INTO sentinel_transactions ("
                        "transaction_id, request_id, idempotency_key, source_account, "
                        "destination_account, amount, currency, transaction_type, state, "
                        "created_at, updated_at) VALUES ("
                        "'rollback', 'rollback', 'rollback-idem', 'source', "
                        "'destination', 0, 'ETB', 'TRANSFER', 'RECEIVED', NOW(), NOW())"
                    )
                )
        async with session_scope(sessions) as session:
            result = await session.execute(
                text(
                    "SELECT COUNT(*) FROM sentinel_transactions "
                    "WHERE transaction_id = 'rollback'"
                )
            )
            assert result.scalar_one() == 0
        await engine.dispose()

    asyncio.run(scenario())


def test_real_postgresql_foreign_key_and_concurrent_unique_constraints():
    async def scenario():
        run_id = uuid4().hex
        transaction_id = f"concurrent-{run_id}"
        shared_request = request(transaction_id)
        engine, sessions = create_database(DATABASE_URL, pool_size=8, max_overflow=0)
        await run_migration(engine, "migrations/001_initial_postgresql.sql")
        async with session_scope(sessions) as session:
            with pytest.raises(IntegrityError):
                async with session.begin_nested():
                    await session.execute(
                        text(
                            "INSERT INTO sentinel_transaction_state_history ("
                            "transaction_id, new_state, actor, occurred_at) VALUES ("
                            "'missing', 'RECEIVED', 'test', NOW())"
                        )
                    )

        barrier = asyncio.Barrier(8)
        repository = IdempotencyRepository()

        async def reserve_once() -> bool:
            await barrier.wait()
            async with session_scope(sessions) as session:
                return await repository.reserve(session, shared_request)

        results = await asyncio.gather(*(reserve_once() for _ in range(8)))
        assert sum(results) == 1

        async with session_scope(sessions) as session:
            result = await session.execute(
                text(
                    "SELECT COUNT(*) FROM sentinel_idempotency_records "
                    "WHERE idempotency_key = :idempotency_key"
                ),
                {"idempotency_key": shared_request.idempotency_key},
            )
            assert result.scalar_one() == 1
            await session.execute(
                text(
                    "DELETE FROM sentinel_idempotency_records "
                    "WHERE idempotency_key = :idempotency_key"
                ),
                {"idempotency_key": shared_request.idempotency_key},
            )
        await engine.dispose()

    asyncio.run(scenario())


def test_real_postgresql_rejects_idempotency_payload_conflicts():
    async def scenario():
        run_id = uuid4().hex
        transaction_id = f"conflict-{run_id}"
        engine, sessions = create_database(DATABASE_URL)
        await run_migration(engine, "migrations/001_initial_postgresql.sql")
        repository = IdempotencyRepository()
        original = request(transaction_id)
        conflicting = TransactionRequest(
            transaction_id,
            original.idempotency_key,
            original.source_account,
            original.destination_account,
            Decimal("11.00"),
            original.currency,
        )
        async with session_scope(sessions) as session:
            assert await repository.reserve(session, original)
            assert not await repository.reserve(session, original)
            with pytest.raises(IdempotencyConflictError):
                await repository.reserve(session, conflicting)
        await engine.dispose()

    asyncio.run(scenario())


def test_real_postgresql_serializes_state_writes_and_rejects_stale_update():
    async def scenario():
        run_id = uuid4().hex
        transaction_id = f"state-race-{run_id}"
        engine, sessions = create_database(DATABASE_URL, pool_size=2, max_overflow=0)
        await run_migration(engine, "migrations/001_initial_postgresql.sql")
        transaction_repository = TransactionRepository()
        idempotency_repository = IdempotencyRepository()
        original = request(transaction_id)
        async with session_scope(sessions) as session:
            assert await idempotency_repository.reserve(session, original)
            await transaction_repository.create(session, original, Transaction(transaction_id))

        barrier = asyncio.Barrier(2)

        async def append_once() -> str:
            transaction = Transaction(transaction_id)
            transaction.transition(TransactionState.VALIDATING, actor="race-test")
            await barrier.wait()
            try:
                async with session_scope(sessions) as session:
                    await transaction_repository.append_state(session, transaction, "race-test")
            except ConcurrentStateUpdateError:
                return "stale"
            return "updated"

        results = await asyncio.gather(append_once(), append_once())
        assert sorted(results) == ["stale", "updated"]
        async with session_scope(sessions) as session:
            persisted = await transaction_repository.get(session, transaction_id)
            assert persisted is not None
            assert persisted.state == TransactionState.VALIDATING.value
            assert len(persisted.state_history) == 2
        await engine.dispose()

    asyncio.run(scenario())


def test_real_postgresql_indexes_and_connection_failure_are_explicit():
    async def scenario():
        engine, sessions = create_database(DATABASE_URL)
        await run_migration(engine, "migrations/001_initial_postgresql.sql")
        async with session_scope(sessions) as session:
            result = await session.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE schemaname = current_schema() "
                    "AND tablename IN ('sentinel_transactions', "
                    "'sentinel_transaction_state_history', 'sentinel_idempotency_records')"
                )
            )
            indexes = {row[0] for row in result}
        await engine.dispose()
        assert {
            "ix_sentinel_transactions_state",
            "ix_sentinel_transactions_created_at",
            "ix_sentinel_state_history_transaction",
            "ix_sentinel_idempotency_expires_at",
        } <= indexes

        failed_engine, failed_sessions = create_database(
            "postgresql+asyncpg://sentinel_user:invalid@127.0.0.1:1/sentinel",
            pool_size=1,
            max_overflow=0,
        )
        try:
            with pytest.raises((DBAPIError, OSError)):
                async with session_scope(failed_sessions) as session:
                    await session.execute(text("SELECT 1"))
        finally:
            await failed_engine.dispose()

    asyncio.run(scenario())