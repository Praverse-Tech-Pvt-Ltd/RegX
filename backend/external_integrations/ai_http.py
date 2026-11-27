"""The HTTP adapter for OpenAI-compatible chat endpoints (E2E and OpenAI).

One class serves both: E2E's endpoint is expected to speak the OpenAI chat
completions format [assumption until E2E's details arrive; see
docs/AI_INTEGRATION_RUNBOOK.md]. Registered into `ai_gateway` at start-up, so
the gateway never imports this app.

WHY THIS DOES NOT USE `netpolicy`
---------------------------------
`netpolicy` guards destinations a *tenant user* chooses. This destination is
chosen by the operator, in the deployment's environment, and no request can
change it. The rules here are smaller but still strict:

* `https://` for any host; `http://` only to a loopback host (the local fake
  server used by tests and the benchmark proof). Anything else is refused as
  not configured.
* No redirects (`http.client` never follows them), no proxies (environment
  proxy variables are not consulted).
* Bounded: an overall deadline for the call, and a cap on the response size,
  enforced while reading.
* Nothing the remote says is passed on except the parsed answer. Error bodies
  are dropped and mapped to an enumerated code: they can echo the prompt.
* The key goes in the `Authorization` header only, never in the URL, and never
  in an exception or log line.
"""

from __future__ import annotations

import http.client
import json
import ssl
import time
from urllib.parse import urlsplit

from ai_gateway.providers import ProviderError, ProviderErrorCode, ProviderReply, ProviderRequest

USER_AGENT = "RegX-AI/1"
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_CHUNK = 64 * 1024


class EndpointRefused(ValueError):
    """The configured base URL breaks the rules above. Carries no URL text."""


def parse_base_url(base_url: str) -> tuple[str, str, int, str]:
    """(scheme, host, port, path prefix) or EndpointRefused."""
    parts = urlsplit(base_url)
    scheme = (parts.scheme or "").lower()
    host = parts.hostname or ""
    if parts.username or parts.password or parts.query or parts.fragment:
        raise EndpointRefused("base URL must not carry credentials, a query or a fragment")
    if scheme == "https" and host:
        pass
    elif scheme == "http" and host in LOOPBACK_HOSTS:
        pass
    else:
        raise EndpointRefused("base URL must be https, or http to a loopback host")
    try:
        port = parts.port or (443 if scheme == "https" else 80)
    except ValueError:
        raise EndpointRefused("base URL port is invalid") from None
    return scheme, host, port, parts.path.rstrip("/")


class OpenAICompatibleProvider:
    def __init__(
        self, *, name: str, base_url: str, api_key: str, model: str, max_response_bytes: int
    ):
        self.name = name
        self._scheme, self._host, self._port, self._prefix = parse_base_url(base_url)
        self._api_key = api_key
        self.model = model
        self._max_bytes = max_response_bytes

    def __repr__(self) -> str:  # keep the key out of tracebacks and debuggers
        return f"OpenAICompatibleProvider(name={self.name!r}, model={self.model!r})"

    @property
    def path(self) -> str:
        return f"{self._prefix}/chat/completions"

    def _connection(self, timeout: float) -> http.client.HTTPConnection:
        if self._scheme == "https":
            return http.client.HTTPSConnection(
                self._host, self._port, timeout=timeout, context=ssl.create_default_context()
            )
        return http.client.HTTPConnection(self._host, self._port, timeout=timeout)

    def complete(self, request: ProviderRequest) -> ProviderReply:
        deadline = time.monotonic() + request.timeout_seconds
        body = json.dumps(
            {
                "model": self.model,
                "messages": [{"role": "user", "content": request.prompt}],
                "max_tokens": request.max_output_tokens,
            }
        ).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self._api_key}",
            "User-Agent": USER_AGENT,
        }
        conn = self._connection(timeout=max(request.timeout_seconds, 0.001))
        try:
            try:
                conn.request("POST", self.path, body=body, headers=headers)
                response = conn.getresponse()
                status = response.status
                raw = self._read_bounded(response, deadline)
            except TimeoutError:
                raise ProviderError(ProviderErrorCode.TIMEOUT) from None
            except (OSError, http.client.HTTPException):
                raise ProviderError(ProviderErrorCode.CONNECTION_FAILED) from None
        finally:
            conn.close()

        if status == 429:
            raise ProviderError(ProviderErrorCode.RATE_LIMITED)
        if status >= 500:
            raise ProviderError(ProviderErrorCode.SERVER_ERROR)
        if status in (401, 403):
            raise ProviderError(ProviderErrorCode.AUTH_FAILED)
        if status != 200:
            raise ProviderError(ProviderErrorCode.CLIENT_ERROR)
        return self._parse(raw)

    def _read_bounded(self, response, deadline: float) -> bytes:
        chunks, size = [], 0
        while True:
            if time.monotonic() > deadline:
                raise ProviderError(ProviderErrorCode.TIMEOUT)
            chunk = response.read1(_CHUNK) if hasattr(response, "read1") else response.read(_CHUNK)
            if not chunk:
                return b"".join(chunks)
            size += len(chunk)
            if size > self._max_bytes:
                raise ProviderError(ProviderErrorCode.RESPONSE_TOO_LARGE)
            chunks.append(chunk)

    def _parse(self, raw: bytes) -> ProviderReply:
        try:
            data = json.loads(raw)
            text = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError):
            raise ProviderError(ProviderErrorCode.BAD_RESPONSE) from None
        if not isinstance(text, str):
            raise ProviderError(ProviderErrorCode.BAD_RESPONSE)
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}

        def count(key):
            value = usage.get(key)
            return value if isinstance(value, int) and value >= 0 else None

        model = data.get("model") if isinstance(data.get("model"), str) else self.model
        return ProviderReply(
            text=text,
            model=model[:128],
            input_tokens=count("prompt_tokens"),
            output_tokens=count("completion_tokens"),
        )


def build_provider(config) -> OpenAICompatibleProvider:
    """Factory registered with `ai_gateway` for the "e2e" and "openai" names."""
    return OpenAICompatibleProvider(
        name=config.provider,
        base_url=config.base_url,
        api_key=config.api_key,
        model=config.model,
        max_response_bytes=config.max_response_bytes,
    )


def register() -> None:
    from ai_gateway.providers import register_provider

    register_provider("e2e", build_provider)
    register_provider("openai", build_provider)
