from sentinel.config import Settings


def test_settings_use_safe_defaults(monkeypatch):
    monkeypatch.delenv("SENTINEL_ENVIRONMENT", raising=False)
    monkeypatch.delenv("SENTINEL_LOG_LEVEL", raising=False)
    monkeypatch.delenv("SENTINEL_DATABASE_URL", raising=False)
    monkeypatch.delenv("SENTINEL_DB_POOL_SIZE", raising=False)
    monkeypatch.delenv("SENTINEL_DB_MAX_OVERFLOW", raising=False)

    assert Settings.from_environment() == Settings()


def test_settings_read_environment(monkeypatch):
    monkeypatch.setenv("SENTINEL_ENVIRONMENT", "test")
    monkeypatch.setenv("SENTINEL_LOG_LEVEL", "debug")
    monkeypatch.delenv("SENTINEL_DATABASE_URL", raising=False)
    monkeypatch.delenv("SENTINEL_DB_POOL_SIZE", raising=False)
    monkeypatch.delenv("SENTINEL_DB_MAX_OVERFLOW", raising=False)

    assert Settings.from_environment() == Settings(environment="test", log_level="DEBUG")


def test_settings_normalize_log_level(monkeypatch):
    monkeypatch.setenv("SENTINEL_LOG_LEVEL", "warning")

    assert Settings.from_environment().log_level == "WARNING"


def test_settings_load_database_configuration(monkeypatch):
    monkeypatch.setenv("SENTINEL_DATABASE_URL", "postgresql+asyncpg://app:pass@localhost:5433/sentinel")
    monkeypatch.setenv("SENTINEL_DB_POOL_SIZE", "8")
    monkeypatch.setenv("SENTINEL_DB_MAX_OVERFLOW", "2")

    settings = Settings.from_environment()

    assert settings.database_url.endswith("/sentinel")
    assert settings.db_pool_size == 8
    assert settings.db_max_overflow == 2


def test_settings_load_redis_configuration(monkeypatch):
    monkeypatch.setenv("SENTINEL_REDIS_URL", "rediss://cache.example.test:6380/0")
    monkeypatch.setenv("SENTINEL_REDIS_MAX_CONNECTIONS", "12")

    settings = Settings.from_environment()

    assert settings.redis_url == "rediss://cache.example.test:6380/0"
    assert settings.redis_max_connections == 12
