"""Which provider to use and whether it is configured, read fresh on every call.

Reading settings per call (not once at import) is what lets the off switch and
a configuration change take effect without a restart, and what lets tests use
`override_settings`.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings

from .providers import known_providers

#: The public OpenAI API. Used only when the provider is "openai", which is for
#: development; production uses the E2E endpoint.
OPENAI_BASE_URL = "https://api.openai.com/v1"

#: Providers served by the HTTP adapter, which need a URL, a key and a model.
HTTP_PROVIDERS = frozenset({"e2e", "openai"})


class ConfigProblem:
    PROVIDER_UNKNOWN = "PROVIDER_UNKNOWN"
    BASE_URL_MISSING = "BASE_URL_MISSING"
    API_KEY_MISSING = "API_KEY_MISSING"
    MODEL_MISSING = "MODEL_MISSING"


@dataclass(frozen=True)
class AIConfig:
    provider: str
    base_url: str
    api_key: str
    model: str
    timeout_seconds: float
    max_retries: int
    retry_backoff_seconds: float
    max_response_bytes: int

    def __repr__(self) -> str:  # never let the key reach a log line or a traceback
        return f"AIConfig(provider={self.provider!r}, model={self.model!r})"

    __str__ = __repr__


def load_config() -> AIConfig:
    provider = (settings.REGX_AI_PROVIDER or "").strip().lower()
    if provider == "e2e":
        base_url = settings.REGX_AI_E2E_BASE_URL
        api_key = settings.REGX_AI_E2E_API_KEY
        model = settings.REGX_AI_E2E_MODEL
    elif provider == "openai":
        base_url = OPENAI_BASE_URL
        api_key = settings.REGX_AI_OPENAI_API_KEY
        model = settings.REGX_AI_OPENAI_MODEL
    else:
        base_url, api_key, model = "", "", ""
    return AIConfig(
        provider=provider,
        base_url=(base_url or "").strip(),
        api_key=(api_key or "").strip(),
        model=(model or "").strip(),
        timeout_seconds=float(settings.AI_CALL_TIMEOUT_SECONDS),
        max_retries=int(settings.AI_MAX_RETRIES),
        retry_backoff_seconds=float(settings.AI_RETRY_BACKOFF_SECONDS),
        max_response_bytes=int(settings.AI_MAX_RESPONSE_BYTES),
    )


def config_problem(config: AIConfig) -> str | None:
    """None when the configuration can make a call, else an enumerated reason."""
    if config.provider not in known_providers():
        return ConfigProblem.PROVIDER_UNKNOWN
    if config.provider not in HTTP_PROVIDERS:
        # The stub needs nothing; a provider plugged in later checks its own setup.
        return None
    if not config.base_url:
        return ConfigProblem.BASE_URL_MISSING
    if not config.api_key:
        return ConfigProblem.API_KEY_MISSING
    if not config.model:
        return ConfigProblem.MODEL_MISSING
    return None
