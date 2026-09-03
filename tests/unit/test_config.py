from sentinel.config import Settings


def test_settings_use_safe_defaults(monkeypatch):
    monkeypatch.delenv("SENTINEL_ENVIRONMENT", raising=False)
    monkeypatch.delenv("SENTINEL_LOG_LEVEL", raising=False)

    assert Settings.from_environment() == Settings()


def test_settings_read_environment(monkeypatch):
    monkeypatch.setenv("SENTINEL_ENVIRONMENT", "test")
    monkeypatch.setenv("SENTINEL_LOG_LEVEL", "debug")

    assert Settings.from_environment() == Settings(environment="test", log_level="DEBUG")


def test_settings_normalize_log_level(monkeypatch):
    monkeypatch.setenv("SENTINEL_LOG_LEVEL", "warning")

    assert Settings.from_environment().log_level == "WARNING"
