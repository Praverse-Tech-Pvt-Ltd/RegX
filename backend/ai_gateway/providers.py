"""The provider interface: prompt in, text out, plus metadata.

Kept deliberately small so another implementation (for example one taken from
the separate 483 codebase) can be plugged in by writing one class with one
method and registering a factory for it.

No module here opens a network connection. The stub is pure computation; the
HTTP adapter is registered from `external_integrations` at start-up.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ProviderRequest:
    """What a provider is asked to do. `prompt` is client content: never log it."""

    prompt: str
    max_output_tokens: int
    timeout_seconds: float


@dataclass(frozen=True)
class ProviderReply:
    """What a provider returns. `text` is model output: never log it."""

    text: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None


class ProviderErrorCode:
    TIMEOUT = "TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"
    SERVER_ERROR = "SERVER_ERROR"
    CONNECTION_FAILED = "CONNECTION_FAILED"
    AUTH_FAILED = "AUTH_FAILED"
    CLIENT_ERROR = "CLIENT_ERROR"
    BAD_RESPONSE = "BAD_RESPONSE"
    RESPONSE_TOO_LARGE = "RESPONSE_TOO_LARGE"


#: Worth another attempt: the same request may succeed a moment later.
RETRYABLE = frozenset(
    {
        ProviderErrorCode.TIMEOUT,
        ProviderErrorCode.RATE_LIMITED,
        ProviderErrorCode.SERVER_ERROR,
        ProviderErrorCode.CONNECTION_FAILED,
    }
)


class ProviderError(Exception):
    """A provider failure with an enumerated code.

    The message is the code. Nothing the remote said is carried: a remote error
    body is untrusted text and may echo the prompt back.
    """

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)

    @property
    def retryable(self) -> bool:
        return self.code in RETRYABLE


class Provider(Protocol):
    name: str

    def complete(self, request: ProviderRequest) -> ProviderReply: ...


class StubProvider:
    """Deterministic and offline. The default provider.

    The reply depends only on the prompt, so tests and the consistency check get
    the same answer every time. It does not pretend to be a model: the text says
    it is a stub.
    """

    name = "stub"
    model = "stub-1"

    def complete(self, request: ProviderRequest) -> ProviderReply:
        digest = hashlib.sha256(request.prompt.encode("utf-8")).hexdigest()[:12]
        text = f"[stub reply {digest}] AI is running on the offline stub provider."
        return ProviderReply(
            text=text,
            model=self.model,
            input_tokens=len(request.prompt.split()),
            output_tokens=len(text.split()),
        )


ProviderFactory = Callable[["object"], Provider]

_FACTORIES: dict[str, ProviderFactory] = {"stub": lambda config: StubProvider()}


def register_provider(name: str, factory: ProviderFactory) -> None:
    """Called by `external_integrations` at start-up for the HTTP providers."""
    _FACTORIES[name] = factory


def provider_factory(name: str) -> ProviderFactory | None:
    return _FACTORIES.get(name)


def known_providers() -> frozenset[str]:
    return frozenset(_FACTORIES)
