"""`generate()`: switch, configuration, tenant check, prompt versioning, failures."""

import pytest
from django.test import override_settings

from ai_gateway import providers, service
from ai_gateway.models import AICallRecord, AISwitch, CallOutcome
from ai_gateway.prompts import PromptFieldsInvalid, PromptNotFound
from ai_gateway.providers import ProviderError, ProviderErrorCode
from ai_gateway.tests.conftest import ai_settings, fake_e2e_settings

pytestmark = pytest.mark.django_db


def _last():
    return AICallRecord.objects.order_by("-id").first()


class TestDefaults:
    def test_ai_is_off_by_default(self, in_tenant):
        result = service.generate("gateway.health_check")
        assert result.status == "disabled"
        assert result.message == "AI is disabled."
        assert result.text is None
        assert _last().outcome == CallOutcome.DISABLED

    def test_default_settings_are_off_stub_and_empty(self, settings):
        assert settings.REGX_AI_ENABLED is False
        assert settings.REGX_AI_PROVIDER == "stub"
        for name in (
            "REGX_AI_E2E_BASE_URL",
            "REGX_AI_E2E_API_KEY",
            "REGX_AI_E2E_MODEL",
            "REGX_AI_OPENAI_API_KEY",
            "REGX_AI_OPENAI_MODEL",
        ):
            assert getattr(settings, name) == "", name

    def test_the_platform_switch_starts_off(self):
        assert AISwitch.is_on() is False


class TestOffSwitch:
    def test_setting_on_but_switch_off_is_disabled(self, in_tenant):
        with ai_settings(enabled=True):
            assert service.generate("gateway.health_check").status == "disabled"

    def test_switch_on_but_setting_off_is_disabled(self, in_tenant, switch_on):
        with ai_settings(enabled=False):
            assert service.generate("gateway.health_check").status == "disabled"

    def test_both_on_with_the_stub_answers(self, in_tenant, switch_on):
        with ai_settings(enabled=True):
            result = service.generate("gateway.health_check")
        assert result.ok
        assert result.text.startswith("[stub reply ")
        record = _last()
        assert record.outcome == CallOutcome.OK
        assert record.provider == "stub"
        assert record.model == "stub-1"
        assert record.attempts == 1

    def test_the_switch_is_read_on_every_call(self, in_tenant, switch_on):
        with ai_settings(enabled=True):
            assert service.generate("gateway.health_check").ok
            AISwitch.objects.filter(pk=1).update(enabled=False)
            assert service.generate("gateway.health_check").status == "disabled"

    def test_switching_off_stops_calls_to_the_provider(self, in_tenant, fake_server):
        with fake_e2e_settings(fake_server):
            service.generate("gateway.health_check")
        assert fake_server.requests == []


class TestNotConfigured:
    @pytest.mark.parametrize(
        ("missing", "code"),
        [
            ("e2e_base_url", "BASE_URL_MISSING"),
            ("e2e_api_key", "API_KEY_MISSING"),
            ("e2e_model", "MODEL_MISSING"),
        ],
    )
    def test_missing_value_is_not_configured(
        self, in_tenant, switch_on, fake_server, missing, code
    ):
        with fake_e2e_settings(fake_server, **{missing: ""}):
            result = service.generate("gateway.health_check")
        assert result.status == "not_configured"
        assert result.message == "AI is not configured."
        assert result.reason_code == code
        assert fake_server.requests == []

    def test_openai_without_a_key_is_not_configured(self, in_tenant, switch_on):
        with ai_settings(enabled=True, provider="openai", openai_model="m"):
            result = service.generate("gateway.health_check")
        assert (result.status, result.reason_code) == ("not_configured", "API_KEY_MISSING")

    def test_unknown_provider_is_not_configured(self, in_tenant, switch_on):
        with ai_settings(enabled=True, provider="somebody-else"):
            result = service.generate("gateway.health_check")
        assert (result.status, result.reason_code) == ("not_configured", "PROVIDER_UNKNOWN")

    def test_plain_http_to_a_remote_host_is_not_configured(self, in_tenant, switch_on):
        with ai_settings(
            enabled=True,
            provider="e2e",
            e2e_base_url="http://model.example.test/v1",
            e2e_api_key="k",
            e2e_model="m",
        ):
            result = service.generate("gateway.health_check")
        assert (result.status, result.reason_code) == ("not_configured", "ENDPOINT_INVALID")


class TestTenantCheck:
    def test_no_tenant_is_refused(self, db, switch_on):
        with ai_settings(enabled=True):
            result = service.generate("gateway.health_check")
        assert result.status == "refused"
        assert result.reason_code == "TENANT_REQUIRED"
        record = _last()
        assert record.outcome == CallOutcome.TENANT_REFUSED
        assert record.tenant is None

    def test_tenant_is_checked_before_the_switch(self, db):
        # Off and no tenant: the answer is the tenant refusal, not "disabled".
        assert service.generate("gateway.health_check").reason_code == "TENANT_REQUIRED"

    def test_a_member_may_call(self, in_tenant, switch_on, member):
        with ai_settings(enabled=True):
            assert service.generate("gateway.health_check", user=member).ok
        assert _last().user == member

    def test_a_user_from_another_tenant_is_refused(self, in_tenant, switch_on, other_tenant):
        from ai_gateway.tests.conftest import _make_user, _member

        outsider = _make_user("ai-outsider@example.test")
        _member(other_tenant, outsider, ["doer"])
        with ai_settings(enabled=True):
            result = service.generate("gateway.health_check", user=outsider)
        assert (result.status, result.reason_code) == ("refused", "NOT_A_MEMBER")

    def test_an_inactive_member_is_refused(self, in_tenant, switch_on, ai_tenant):
        from ai_gateway.tests.conftest import _make_user, _member

        user = _make_user("ai-inactive@example.test")
        _member(ai_tenant, user, ["doer"], active=False)
        with ai_settings(enabled=True):
            assert service.generate("gateway.health_check", user=user).reason_code == "NOT_A_MEMBER"


class TestPromptVersioning:
    def test_every_record_carries_prompt_id_and_version(self, in_tenant, switch_on):
        with ai_settings(enabled=True):
            result = service.generate("benchmark.answer", fields={"request": "synthetic"})
        assert (result.prompt_id, result.prompt_version) == ("benchmark.answer", 1)
        record = _last()
        assert (record.prompt_id, record.prompt_version) == ("benchmark.answer", 1)

    def test_refusals_carry_the_prompt_version_too(self, db):
        service.generate("gateway.health_check")
        assert (_last().prompt_id, _last().prompt_version) == ("gateway.health_check", 1)

    def test_an_unknown_prompt_is_a_programming_error(self, in_tenant):
        with pytest.raises(PromptNotFound):
            service.generate("no.such.prompt")

    def test_wrong_fields_are_a_programming_error_and_name_no_value(self, in_tenant):
        with pytest.raises(PromptFieldsInvalid) as exc:
            service.generate("benchmark.answer", fields={"wrong": "SECRET-FIELD-VALUE"})
        assert "SECRET-FIELD-VALUE" not in str(exc.value)


class _Exploding:
    name = "exploding"

    def complete(self, request):
        raise RuntimeError("provider bug")


class _AlwaysFails:
    name = "always-fails"

    def __init__(self, code):
        self.code = code
        self.calls = 0

    def complete(self, request):
        self.calls += 1
        raise ProviderError(self.code)


@pytest.fixture
def custom_provider():
    registered = []

    def use(name, instance):
        providers.register_provider(name, lambda config: instance)
        registered.append(name)

    yield use
    for name in registered:
        providers._FACTORIES.pop(name, None)


class TestFailureBehaviour:
    def test_a_provider_bug_returns_unavailable_not_a_crash(
        self, in_tenant, switch_on, custom_provider
    ):
        custom_provider("exploding", _Exploding())
        with ai_settings(enabled=True, provider="exploding"):
            result = service.generate("gateway.health_check")
        assert result.status == "unavailable"
        assert result.message.startswith("AI unavailable")
        assert result.reason_code == "PROVIDER_FAILED"

    def test_retryable_errors_are_retried_up_to_the_limit(
        self, in_tenant, switch_on, custom_provider
    ):
        failing = _AlwaysFails(ProviderErrorCode.SERVER_ERROR)
        custom_provider("always-fails", failing)
        with (
            ai_settings(enabled=True, provider="always-fails"),
            override_settings(AI_MAX_RETRIES=2),
        ):
            result = service.generate("gateway.health_check")
        assert failing.calls == 3
        assert result.reason_code == "SERVER_ERROR"
        assert _last().attempts == 3

    def test_non_retryable_errors_are_not_retried(self, in_tenant, switch_on, custom_provider):
        failing = _AlwaysFails(ProviderErrorCode.AUTH_FAILED)
        custom_provider("always-fails", failing)
        with ai_settings(enabled=True, provider="always-fails"):
            result = service.generate("gateway.health_check")
        assert failing.calls == 1
        assert result.reason_code == "AUTH_FAILED"

    def test_the_breaker_opens_and_then_refuses_without_calling(
        self, in_tenant, switch_on, custom_provider
    ):
        failing = _AlwaysFails(ProviderErrorCode.AUTH_FAILED)
        custom_provider("always-fails", failing)
        with (
            ai_settings(enabled=True, provider="always-fails"),
            override_settings(AI_BREAKER_FAILURE_THRESHOLD=3),
        ):
            for _ in range(3):
                service.generate("gateway.health_check")
            assert failing.calls == 3
            result = service.generate("gateway.health_check")
        assert failing.calls == 3  # not called again
        assert (result.status, result.reason_code) == ("unavailable", "CIRCUIT_OPEN")
        assert _last().outcome == CallOutcome.CIRCUIT_OPEN

    def test_after_the_cooldown_one_trial_call_goes_through(
        self, in_tenant, switch_on, custom_provider, monkeypatch
    ):
        import time as real_time

        from ai_gateway import breaker

        failing = _AlwaysFails(ProviderErrorCode.AUTH_FAILED)
        custom_provider("always-fails", failing)
        now = [real_time.time()]
        monkeypatch.setattr(breaker.time, "time", lambda: now[0])
        with (
            ai_settings(enabled=True, provider="always-fails"),
            override_settings(AI_BREAKER_FAILURE_THRESHOLD=2, AI_BREAKER_COOLDOWN_SECONDS=60),
        ):
            service.generate("gateway.health_check")
            service.generate("gateway.health_check")
            assert service.generate("gateway.health_check").reason_code == "CIRCUIT_OPEN"
            now[0] += 61
            assert service.generate("gateway.health_check").reason_code == "AUTH_FAILED"
            assert failing.calls == 3
            # The trial failed, so the breaker is open again at once.
            assert service.generate("gateway.health_check").reason_code == "CIRCUIT_OPEN"

    def test_a_success_closes_the_breaker(self, in_tenant, switch_on):
        from ai_gateway import breaker

        with ai_settings(enabled=True), override_settings(AI_BREAKER_FAILURE_THRESHOLD=5):
            for _ in range(4):
                breaker.record_failure("stub")
            assert service.generate("gateway.health_check").ok
            breaker.record_failure("stub")
            assert not breaker.is_open("stub")


class TestRecordHoldsNoText:
    def test_the_call_record_has_no_text_column(self):
        text_types = {"TextField", "JSONField", "BinaryField"}
        for field in AICallRecord._meta.get_fields():
            assert field.get_internal_type() not in text_types, field.name
        names = {f.name for f in AICallRecord._meta.get_fields()}
        assert not names & {"prompt", "prompt_text", "response", "text", "fields", "error"}
