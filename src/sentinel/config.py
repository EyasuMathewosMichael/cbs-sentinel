"""Environment-backed application configuration."""

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    """Configuration required by the Phase 0 application foundation."""

    environment: str = "development"
    log_level: str = "INFO"

    @classmethod
    def from_environment(cls) -> "Settings":
        """Build settings from environment variables with safe local defaults."""
        return cls(
            environment=os.getenv("SENTINEL_ENVIRONMENT", "development"),
            log_level=os.getenv("SENTINEL_LOG_LEVEL", "INFO").upper(),
        )
