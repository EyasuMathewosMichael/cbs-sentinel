"""Environment-backed application configuration."""

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    """Configuration required by the Phase 0 application foundation."""

    environment: str = "development"
    log_level: str = "INFO"
    database_url: str | None = None
    db_pool_size: int = 5
    db_max_overflow: int = 10
    redis_url: str | None = None
    redis_max_connections: int = 20

    @classmethod
    def from_environment(cls) -> "Settings":
        """Build settings from environment variables with safe local defaults."""
        return cls(
            environment=os.getenv("SENTINEL_ENVIRONMENT", "development"),
            log_level=os.getenv("SENTINEL_LOG_LEVEL", "INFO").upper(),
            database_url=os.getenv("SENTINEL_DATABASE_URL"),
            db_pool_size=_positive_int_from_environment("SENTINEL_DB_POOL_SIZE", 5),
            db_max_overflow=_nonnegative_int_from_environment("SENTINEL_DB_MAX_OVERFLOW", 10),
            redis_url=os.getenv("SENTINEL_REDIS_URL"),
            redis_max_connections=_positive_int_from_environment(
                "SENTINEL_REDIS_MAX_CONNECTIONS", 20
            ),
        )


def _positive_int_from_environment(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value < 1:
        raise ValueError(f"{name} must be positive")
    return value


def _nonnegative_int_from_environment(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value < 0:
        raise ValueError(f"{name} must not be negative")
    return value
