"""Async PostgreSQL engine and session factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from sentinel.infrastructure.persistence.models import Base


def create_database(
    database_url: str,
    *,
    pool_size: int = 5,
    max_overflow: int = 10,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Create a pooled async engine and session factory for SENTINEL state."""
    if not database_url.startswith("postgresql+asyncpg://"):
        raise ValueError("database_url must use the postgresql+asyncpg scheme")
    if pool_size < 1 or max_overflow < 0:
        raise ValueError("pool_size must be positive and max_overflow must not be negative")
    try:
        engine = create_async_engine(
            database_url,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_pre_ping=True,
            pool_recycle=1800,
        )
    except ModuleNotFoundError as error:
        raise RuntimeError("asyncpg is required for PostgreSQL persistence") from error
    return engine, async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def session_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Commit successful work and roll back failed database transactions."""
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def create_schema(engine: AsyncEngine) -> None:
    """Create the SENTINEL schema for local development and tests."""
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def run_migration(engine: AsyncEngine, migration_path: str | Path) -> None:
    """Apply a local SQL migration using the PostgreSQL connection."""
    statements = _split_sql_statements(Path(migration_path).read_text(encoding="utf-8"))
    async with engine.begin() as connection:
        for statement in statements:
            if statement.strip():
                await connection.exec_driver_sql(statement)


def _split_sql_statements(script: str) -> list[str]:
    """Split SQL without treating quoted semicolons as statement delimiters."""
    statements: list[str] = []
    statement_start = 0
    index = 0
    quote: str | None = None
    dollar_tag: str | None = None
    while index < len(script):
        if dollar_tag is not None:
            if script.startswith(dollar_tag, index):
                index += len(dollar_tag)
                dollar_tag = None
            else:
                index += 1
            continue
        if quote is not None:
            if script[index] == quote:
                if index + 1 < len(script) and script[index + 1] == quote:
                    index += 2
                else:
                    quote = None
                    index += 1
            else:
                index += 1
            continue
        if script.startswith("--", index):
            newline = script.find("\n", index + 2)
            index = len(script) if newline == -1 else newline + 1
            continue
        if script.startswith("/*", index):
            comment_end = script.find("*/", index + 2)
            if comment_end == -1:
                raise ValueError("unterminated SQL block comment")
            index = comment_end + 2
            continue
        if script[index] in {"'", '"'}:
            quote = script[index]
            index += 1
            continue
        if script[index] == "$":
            tag_end = script.find("$", index + 1)
            if tag_end != -1:
                candidate = script[index : tag_end + 1]
                if candidate[1:-1].replace("_", "").isalnum():
                    dollar_tag = candidate
                    index = tag_end + 1
                    continue
        if script[index] == ";":
            statements.append(script[statement_start:index])
            statement_start = index + 1
        index += 1
    if quote is not None or dollar_tag is not None:
        raise ValueError("unterminated quoted SQL expression")
    trailing_statement = script[statement_start:]
    if trailing_statement.strip():
        statements.append(trailing_statement)
    return statements
