from app.config import Settings, get_settings


def test_settings_defaults_and_env(monkeypatch):
    # Default settings
    defaults = Settings()
    assert defaults.environment == "local"
    assert defaults.enable_hot_reload is False

    monkeypatch.setenv("ENABLE_HOT_RELOAD", "true")
    monkeypatch.setenv("PROVIDER_STRATEGY", "mock")
    monkeypatch.setenv("ENVIRONMENT", "dev")

    settings = Settings()
    assert settings.enable_hot_reload is True
    assert settings.environment == "dev"
    assert settings.default_provider_strategy == "mock"


def test_cached_settings_instance(monkeypatch):
    monkeypatch.setenv("ENABLE_HOT_RELOAD", "false")
    a = get_settings()
    b = get_settings()
    assert a is b

