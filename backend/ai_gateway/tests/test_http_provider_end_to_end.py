"""The real HTTP adapter, end to end through `generate()`, against the local fake server.

Covers the request format, parsing, timeouts, retries, error mapping and the
response-size cap -- and that no log line or record carries the prompt, the
response or the key.
"""

import json
import logging

import pytest
from django.test import override_settings

from ai_gateway import service
from ai_gateway.models import AICallRecord, CallOutcome
from ai_gateway.tests.conftest import fake_e2e_settings
from ai_gateway.tests.fake_openai_server import FAKE_API_KEY, FAKE_MODEL, REPLY_MARKER
from common.structured_logging import JSONFormatter

pytestmark = pytest.mark.django_db

PROMPT_MARKER = "SYNTHETIC-PROMPT-MARKER-7f3a"


def _ask(fields=None):
    return service.generate(
        "benchmark.answer", fields=fields or {"request": f"{PROMPT_MARKER} what is a batch record?"}
    )


class TestRequestFormat:
    def test_post_to_chat_completions_with_model_messages_and_limit(
        self, in_tenant, switch_on, fake_server
    ):
        with fake_e2e_settings(fake_server):
            result = _ask()
        assert result.ok
        [req] = fake_server.requests
        assert req["method"] == "POST"
        assert req["path"] == "/v1/chat/completions"
        body = req["json"]
        assert body["model"] == FAKE_MODEL
        assert body["max_tokens"] == 400
        assert body["messages"][0]["role"] == "user"
        assert PROMPT_MARKER in body["messages"][0]["content"]

    def test_headers_carry_bearer_key_json_and_a_generic_user_agent(
        self, in_tenant, switch_on, fake_server
    ):
        with fake_e2e_settings(fake_server):
            _ask()
        headers = {k.lower(): v for k, v in fake_server.requests[0]["headers"].items()}
        assert headers["authorization"] == f"Bearer {FAKE_API_KEY}"
        assert headers["content-type"] == "application/json"
        assert headers["user-agent"] == "RegX-AI/1"
        # The key is in the header only, never in the URL.
        assert FAKE_API_KEY not in fake_server.requests[0]["path"]

    def test_reply_text_model_and_tokens_are_parsed(self, in_tenant, switch_on, fake_server):
        with fake_e2e_settings(fake_server):
            result = _ask()
        assert result.text.startswith(REPLY_MARKER)
        record = AICallRecord.objects.get(public_id=result.call_id)
        assert record.model == FAKE_MODEL
        assert record.input_tokens > 0
        assert record.output_tokens == 2
        assert record.latency_ms is not None


class TestErrors:
    def _run(self, server, *plan, **settings_extra):
        server.plan(*plan)
        with fake_e2e_settings(server):
            with override_settings(**settings_extra):
                return _ask()

    def test_a_hanging_server_times_out(self, in_tenant, switch_on, fake_server):
        result = self._run(
            fake_server,
            {"kind": "hang", "delay": 3},
            AI_CALL_TIMEOUT_SECONDS=0.5,
            AI_MAX_RETRIES=0,
        )
        assert (result.status, result.reason_code) == ("unavailable", "TIMEOUT")
        assert AICallRecord.objects.get(public_id=result.call_id).latency_ms < 2500

    def test_a_drip_feeding_server_hits_the_overall_deadline(
        self, in_tenant, switch_on, fake_server
    ):
        result = self._run(
            fake_server,
            {"kind": "drip", "delay": 0.2},
            AI_CALL_TIMEOUT_SECONDS=0.6,
            AI_MAX_RETRIES=0,
        )
        assert result.reason_code == "TIMEOUT"

    def test_429_then_success_is_retried(self, in_tenant, switch_on, fake_server):
        result = self._run(fake_server, {"kind": "429"})
        assert result.ok
        assert len(fake_server.requests) == 2
        assert AICallRecord.objects.get(public_id=result.call_id).attempts == 2

    def test_500_every_time_gives_up_after_the_retry_limit(self, in_tenant, switch_on, fake_server):
        fake_server.default = {"kind": "500"}
        result = self._run(fake_server, AI_MAX_RETRIES=2)
        assert (result.status, result.reason_code) == ("unavailable", "SERVER_ERROR")
        assert len(fake_server.requests) == 3

    def test_401_is_not_retried(self, in_tenant, switch_on, fake_server):
        result = self._run(fake_server, {"kind": "401"})
        assert result.reason_code == "AUTH_FAILED"
        assert len(fake_server.requests) == 1

    def test_400_is_a_client_error_and_not_retried(self, in_tenant, switch_on, fake_server):
        result = self._run(fake_server, {"kind": "400"})
        assert result.reason_code == "CLIENT_ERROR"
        assert len(fake_server.requests) == 1

    def test_malformed_json_is_a_bad_response(self, in_tenant, switch_on, fake_server):
        assert self._run(fake_server, {"kind": "malformed"}).reason_code == "BAD_RESPONSE"

    def test_json_without_choices_is_a_bad_response(self, in_tenant, switch_on, fake_server):
        assert self._run(fake_server, {"kind": "bad_shape"}).reason_code == "BAD_RESPONSE"

    def test_an_oversized_response_is_refused_while_reading(
        self, in_tenant, switch_on, fake_server
    ):
        result = self._run(
            fake_server, {"kind": "long", "size": 300_000}, AI_MAX_RESPONSE_BYTES=100_000
        )
        assert result.reason_code == "RESPONSE_TOO_LARGE"

    def test_a_long_answer_within_the_cap_is_returned(self, in_tenant, switch_on, fake_server):
        result = self._run(fake_server, {"kind": "long", "size": 50_000})
        assert result.ok
        assert len(result.text) == 50_000

    def test_nothing_listening_is_a_connection_failure(self, in_tenant, switch_on, fake_server):
        url = fake_server.url
        fake_server.stop()
        with fake_e2e_settings(fake_server, e2e_base_url=url), override_settings(AI_MAX_RETRIES=0):
            result = _ask()
        assert (result.status, result.reason_code) == ("unavailable", "CONNECTION_FAILED")

    def test_repeated_failures_open_the_breaker_and_stop_traffic(
        self, in_tenant, switch_on, fake_server
    ):
        fake_server.default = {"kind": "500"}
        with (
            fake_e2e_settings(fake_server),
            override_settings(AI_MAX_RETRIES=0, AI_BREAKER_FAILURE_THRESHOLD=2),
        ):
            _ask()
            _ask()
            sent = len(fake_server.requests)
            result = _ask()
        assert len(fake_server.requests) == sent == 2
        assert result.reason_code == "CIRCUIT_OPEN"


class TestNothingSensitiveIsLogged:
    def _formatted(self, caplog):
        formatter = JSONFormatter()
        return [formatter.format(r) for r in caplog.records]

    @pytest.mark.parametrize("plan", [None, {"kind": "500"}, {"kind": "malformed"}])
    def test_logs_and_records_carry_no_prompt_response_or_key(
        self, in_tenant, switch_on, fake_server, member, caplog, plan
    ):
        if plan:
            fake_server.default = plan
        caplog.set_level(logging.DEBUG)
        with fake_e2e_settings(fake_server), override_settings(AI_MAX_RETRIES=1):
            result = service.generate(
                "benchmark.answer",
                fields={"request": f"{PROMPT_MARKER} synthetic"},
                user=member,
            )
        lines = self._formatted(caplog)
        raw_attrs = [json.dumps(vars(r), default=str) for r in caplog.records]
        for text in lines + raw_attrs:
            assert PROMPT_MARKER not in text
            assert REPLY_MARKER not in text
            assert FAKE_API_KEY not in text
        record = AICallRecord.objects.get(public_id=result.call_id)
        row = json.dumps(
            {f.attname: getattr(record, f.attname) for f in record._meta.fields}, default=str
        )
        for marker in (PROMPT_MARKER, REPLY_MARKER, FAKE_API_KEY):
            assert marker not in row

    def test_the_log_line_has_the_agreed_fields(
        self, in_tenant, switch_on, fake_server, member, caplog
    ):
        caplog.set_level(logging.INFO, logger="regx.ai_gateway")
        with fake_e2e_settings(fake_server):
            result = service.generate("gateway.health_check", user=member)
        [line] = [json.loads(x) for x in self._formatted(caplog) if "ai call finished" in x]
        assert line["outcome"] == CallOutcome.OK
        assert line["tenant"] == "ai-tenant"
        assert line["user"] == str(member.public_id)
        assert line["ai_provider"] == "e2e"
        assert line["ai_model"] == FAKE_MODEL
        assert (line["prompt_id"], line["prompt_version"]) == ("gateway.health_check", 1)
        assert isinstance(line["duration_ms"], int)
        assert line["input_tokens"] >= 1
        assert line["output_tokens"] == 2
        assert line["ai_call_id"] == result.call_id
        assert "email" not in json.dumps(line)
        assert member.email not in json.dumps(line)

    def test_the_config_repr_hides_the_key(self, fake_server):
        from ai_gateway.config import load_config

        with fake_e2e_settings(fake_server):
            config = load_config()
        assert FAKE_API_KEY not in repr(config)
        assert FAKE_API_KEY not in str(config)
