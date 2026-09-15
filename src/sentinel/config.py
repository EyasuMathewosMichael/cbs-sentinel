"""Environment-backed application configuration."""

import os
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Settings:
    """Application configuration with explicit CBS provider controls."""

    environment: str = "development"
    cbs_provider: str = "simulation"
    cbs_endpoint: str | None = field(default=None, repr=False)
    log_level: str = "INFO"
    database_url: str | None = field(default=None, repr=False)
    db_pool_size: int = 5
    db_max_overflow: int = 10
    redis_url: str | None = field(default=None, repr=False)
    redis_max_connections: int = 20
    mtls_required: bool = True
    min_tls_version: str = "TLSv1.3"
    secrets_backend: str = "external"
    kms_provider: str = "external-kms"
    hsm_required: bool = True
    iam_backend: str = "external-iam"

    @classmethod
    def from_environment(cls) -> "Settings":
        """Build settings from environment variables with safe local defaults."""
        return cls(
            environment=os.getenv("SENTINEL_ENVIRONMENT", "development"),
            cbs_provider=os.getenv("SENTINEL_CBS_PROVIDER", "simulation").lower(),
            cbs_endpoint=os.getenv("SENTINEL_CBS_ENDPOINT"),
            log_level=os.getenv("SENTINEL_LOG_LEVEL", "INFO").upper(),
            database_url=os.getenv("SENTINEL_DATABASE_URL"),
            db_pool_size=_positive_int_from_environment("SENTINEL_DB_POOL_SIZE", 5),
            db_max_overflow=_nonnegative_int_from_environment("SENTINEL_DB_MAX_OVERFLOW", 10),
            redis_url=os.getenv("SENTINEL_REDIS_URL"),
            redis_max_connections=_positive_int_from_environment(
                "SENTINEL_REDIS_MAX_CONNECTIONS", 20
            ),
            mtls_required=_boolean_from_environment("SENTINEL_MTLS_REQUIRED", True),
            min_tls_version=os.getenv("SENTINEL_MIN_TLS_VERSION", "TLSv1.3"),
            secrets_backend=os.getenv("SENTINEL_SECRETS_BACKEND", "external"),
            kms_provider=os.getenv("SENTINEL_KMS_PROVIDER", "external-kms"),
            hsm_required=_boolean_from_environment("SENTINEL_HSM_REQUIRED", True),
            iam_backend=os.getenv("SENTINEL_IAM_BACKEND", "external-iam"),
        )

    def validate_security(self) -> None:
        from sentinel.security import EnterpriseSecurityPolicy

        EnterpriseSecurityPolicy(
            environment=self.environment,
            mtls_required=self.mtls_required,
            min_tls_version=self.min_tls_version,
            secrets_backend=self.secrets_backend,
            kms_provider=self.kms_provider,
            hsm_required=self.hsm_required,
            iam_backend=self.iam_backend,
        ).validate()
        if self.cbs_provider not in {"simulation", "placeholder"}:
            if self.cbs_endpoint:
                raise ValueError(
                    "real bank connectivity requires an explicitly implemented and approved adapter"
                )
        elif self.cbs_endpoint:
            raise ValueError(
                "endpoint configuration is rejected for simulation and placeholder providers; "
                "real bank connectivity requires an explicit bank adapter"
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


def _boolean_from_environment(name: str, default: bool) -> bool:
    value = os.getenv(name, str(default)).strip().lower()
    if value not in {"true", "false"}:
        raise ValueError(f"{name} must be true or false")
    return value == "true"
