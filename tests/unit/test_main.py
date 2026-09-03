from sentinel.main import create_application


def test_create_application_loads_settings(monkeypatch):
    monkeypatch.setenv("SENTINEL_ENVIRONMENT", "test")

    settings = create_application()

    assert settings.environment == "test"