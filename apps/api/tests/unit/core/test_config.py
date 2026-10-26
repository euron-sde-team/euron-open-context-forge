import pytest

from contextforge.core.config import Settings

STRONG = "x" * 40


def prod(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "production",
        "session_secret": STRONG,
        "api_key_pepper": "y" * 40,
        "local_master_key": "z" * 40,
        "cookie_secure": True,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_development_defaults_boot() -> None:
    Settings().guard()


def test_production_with_strong_secrets_boots() -> None:
    prod().guard()


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"session_secret": "dev-session-secret-not-for-production"}, "SESSION_SECRET"),
        ({"api_key_pepper": "short"}, "API_KEY_PEPPER"),
        ({"local_master_key": "dev-local-master-key-not-for-production"}, "LOCAL_MASTER_KEY"),
        ({"api_key_pepper": STRONG}, "must differ"),
        (
            {"CONTEXTFORGE_CLOUD": "aws", "aws_endpoint_url": "http://floci:4566"},
            "AWS_ENDPOINT_URL",
        ),
        ({"auth_required": False}, "AUTH_REQUIRED"),
        ({"cookie_secure": False}, "COOKIE_SECURE"),
    ],
)
def test_production_guards(overrides: dict[str, object], fragment: str) -> None:
    with pytest.raises(RuntimeError, match=fragment):
        prod(**overrides).guard()


def test_kms_mode_does_not_need_local_master_key() -> None:
    prod(key_mode="kms", local_master_key="dev-local-master-key-not-for-production").guard()


def test_cors_origins_accept_comma_string() -> None:
    s = Settings(cors_origins="http://a.test, http://b.test")  # type: ignore[arg-type]
    assert s.cors_origins == ["http://a.test", "http://b.test"]


def test_cors_origins_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:4310,http://127.0.0.1:4310")
    assert Settings().cors_origins == ["http://localhost:4310", "http://127.0.0.1:4310"]


def test_tracing_is_a_no_op_until_enabled() -> None:
    from opentelemetry import trace

    from contextforge.core import tracing

    # Checked by identity, not by span recording: another test in the same process may
    # have installed an SDK provider, which this must neither need nor replace.
    before = trace.get_tracer_provider()
    tracing.configure_tracing(Settings())
    assert tracing._configured is False
    assert trace.get_tracer_provider() is before


def test_redis_is_optional() -> None:
    assert Settings().cache_backend == "memory"
    assert Settings(redis_url="redis://localhost:4379/0").cache_backend == "redis"


def test_aliases_and_prices_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOKENIZER_ALIASES", "chat-small=gpt-4o-mini, chat-large=gpt-4o")
    monkeypatch.setenv("MODEL_PRICES", "my-model=1.25")
    s = Settings()
    assert s.tokenizer_aliases == {"chat-small": "gpt-4o-mini", "chat-large": "gpt-4o"}
    assert str(s.model_prices["my-model"]) == "1.25"
    assert "gpt-4o" in s.model_prices  # defaults are kept
