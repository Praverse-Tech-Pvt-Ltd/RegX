"""The OpenAI-compatible adapter on its own: URL rules, registration, timeout use."""

import pytest

from ai_gateway.providers import ProviderError, ProviderRequest, provider_factory
from ai_gateway.tests.fake_openai_server import FAKE_API_KEY, FAKE_MODEL, FakeOpenAIServer
from external_integrations.ai_http import (
    EndpointRefused,
    OpenAICompatibleProvider,
    build_provider,
    parse_base_url,
)


@pytest.fixture
def server():
    s = FakeOpenAIServer().start()
    yield s
    s.stop()


def _provider(url, key=FAKE_API_KEY):
    return OpenAICompatibleProvider(
        name="e2e", base_url=url, api_key=key, model=FAKE_MODEL, max_response_bytes=1_000_000
    )


class TestBaseUrlRules:
    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://models.example.test/v1", ("https", "models.example.test", 443, "/v1")),
            ("https://models.example.test:8443/v1/", ("https", "models.example.test", 8443, "/v1")),
            ("http://127.0.0.1:9000/v1", ("http", "127.0.0.1", 9000, "/v1")),
            ("http://localhost:9000", ("http", "localhost", 9000, "")),
        ],
    )
    def test_accepted(self, url, expected):
        assert parse_base_url(url) == expected

    @pytest.mark.parametrize(
        "url",
        [
            "http://models.example.test/v1",  # plain http to a remote host
            "http://10.0.0.5/v1",  # plain http, even on a private network
            "ftp://models.example.test/",
            "https://user:pass@models.example.test/v1",
            "https://models.example.test/v1?key=abc",
            "https:///v1",
            "",
        ],
    )
    def test_refused(self, url):
        with pytest.raises(EndpointRefused) as exc:
            parse_base_url(url)
        assert "pass" not in str(exc.value) and "abc" not in str(exc.value)


class TestAdapter:
    def test_both_names_are_registered_at_start_up(self):
        assert provider_factory("e2e") is build_provider
        assert provider_factory("openai") is build_provider

    def test_repr_hides_the_key(self, server):
        assert FAKE_API_KEY not in repr(_provider(server.url))

    def test_the_timeout_given_is_the_timeout_used(self, server):
        server.plan({"kind": "hang", "delay": 2})
        with pytest.raises(ProviderError) as exc:
            _provider(server.url).complete(
                ProviderRequest(prompt="p", max_output_tokens=5, timeout_seconds=0.3)
            )
        assert exc.value.code == "TIMEOUT"
        assert exc.value.retryable

    def test_a_remote_error_body_is_dropped(self, server):
        server.plan({"kind": "500"})
        with pytest.raises(ProviderError) as exc:
            _provider(server.url).complete(
                ProviderRequest(prompt="ECHO-ME-BACK", max_output_tokens=5, timeout_seconds=2)
            )
        assert str(exc.value) == "SERVER_ERROR"
        assert "ECHO-ME-BACK" not in repr(exc.value)

    def test_missing_usage_gives_unknown_tokens_not_an_error(self, server, monkeypatch):
        provider = _provider(server.url)
        reply = provider._parse(b'{"choices": [{"message": {"content": "hi"}}]}')
        assert (reply.text, reply.input_tokens, reply.output_tokens) == ("hi", None, None)
        assert reply.model == FAKE_MODEL

    @pytest.mark.parametrize(
        "raw",
        [b"[]", b'{"choices": []}', b'{"choices": [{"message": {"content": 5}}]}', b"\xff"],
    )
    def test_unexpected_shapes_are_bad_responses(self, server, raw):
        with pytest.raises(ProviderError) as exc:
            _provider(server.url)._parse(raw)
        assert exc.value.code == "BAD_RESPONSE"
        assert not exc.value.retryable
