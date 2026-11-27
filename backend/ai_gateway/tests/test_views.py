"""Switch, metrics and health-check endpoints."""

import pytest
from django.test import override_settings

from ai_gateway.models import AICallRecord, AISwitch
from ai_gateway.tests.conftest import ai_settings, client_for, fake_e2e_settings

pytestmark = pytest.mark.django_db

API = "/api/regx/v1/ai"


class TestSwitch:
    def test_platform_admin_reads_the_state(self, platform_admin):
        response = client_for(platform_admin).get(f"{API}/switch/")
        assert response.status_code == 200
        assert response.json() == {
            "setting_enabled": False,
            "switch_enabled": False,
            "effective_enabled": False,
            "provider": "stub",
            "configuration_problem": None,
            "updated_at": None,
        }

    def test_platform_admin_turns_it_on_and_off(self, platform_admin):
        client = client_for(platform_admin)
        with ai_settings(enabled=True):
            on = client.put(f"{API}/switch/", {"switch_enabled": True}, format="json")
            assert on.status_code == 200
            assert on.json()["effective_enabled"] is True
            off = client.put(f"{API}/switch/", {"switch_enabled": False}, format="json")
        assert off.json()["effective_enabled"] is False
        row = AISwitch.objects.get()
        assert row.updated_by == platform_admin

    def test_the_problem_is_a_code_never_a_value(self, platform_admin, fake_server):
        with fake_e2e_settings(fake_server, e2e_api_key=""):
            body = client_for(platform_admin).get(f"{API}/switch/").json()
        assert body["configuration_problem"] == "API_KEY_MISSING"
        assert fake_server.url not in str(body)

    def test_a_tenant_admin_cannot_read_or_change_it(self, tenant_admin, ai_tenant):
        client = client_for(tenant_admin, ai_tenant)
        assert client.get(f"{API}/switch/").status_code == 403
        put = client.put(f"{API}/switch/", {"switch_enabled": True}, format="json")
        assert put.status_code == 403
        assert not AISwitch.is_on()

    def test_anonymous_is_refused(self, api_client):
        assert api_client.get(f"{API}/switch/").status_code in (401, 403)


class TestMetrics:
    def test_platform_admin_sees_latency_errors_and_tokens(
        self, platform_admin, in_tenant, switch_on, fake_server
    ):
        from ai_gateway import service

        fake_server.plan({"kind": "500"})
        with fake_e2e_settings(fake_server), override_settings(AI_MAX_RETRIES=0):
            service.generate("gateway.health_check")  # fails
            service.generate("gateway.health_check")  # answers
        service.generate("gateway.health_check")  # outside the settings block: disabled

        body = client_for(platform_admin).get(f"{API}/metrics/").json()
        assert body["calls"] == 3
        assert body["by_outcome"]["OK"] == 1
        assert body["by_outcome"]["PROVIDER_ERROR"] == 1
        assert body["by_outcome"]["DISABLED"] == 1
        assert body["provider_calls"] == 2
        assert body["provider_error_rate"] == 0.5
        assert body["provider_errors_by_reason"] == {"SERVER_ERROR": 1}
        assert body["latency_ms"]["sample"] == 2
        assert body["latency_ms"]["p50"] is not None
        assert body["tokens"]["output"] == 2
        assert body["by_prompt"] == [
            {"prompt_id": "gateway.health_check", "prompt_version": 1, "calls": 3}
        ]

    def test_metrics_carry_no_text(self, platform_admin, in_tenant, switch_on):
        from ai_gateway import service

        with ai_settings(enabled=True):
            result = service.generate("benchmark.answer", fields={"request": "SYNTH-METRIC-MARKER"})
        body = client_for(platform_admin).get(f"{API}/metrics/").content.decode()
        assert "SYNTH-METRIC-MARKER" not in body
        assert result.text not in body

    def test_a_tenant_admin_cannot_read_metrics(self, tenant_admin, ai_tenant):
        assert client_for(tenant_admin, ai_tenant).get(f"{API}/metrics/").status_code == 403


class TestHealthCheck:
    def test_off_answers_200_with_a_message_the_page_can_show(self, tenant_admin, ai_tenant):
        response = client_for(tenant_admin, ai_tenant).post(f"{API}/health-check/")
        assert response.status_code == 200
        assert response.json()["status"] == "disabled"
        assert response.json()["message"] == "AI is disabled."

    def test_provider_down_answers_200_ai_unavailable(
        self, tenant_admin, ai_tenant, switch_on, fake_server
    ):
        fake_server.default = {"kind": "500"}
        with fake_e2e_settings(fake_server), override_settings(AI_MAX_RETRIES=0):
            response = client_for(tenant_admin, ai_tenant).post(f"{API}/health-check/")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "unavailable"
        assert body["message"] == "AI unavailable. The rest of this page works as normal."
        assert body["text"] is None

    def test_working_provider_answers(self, tenant_admin, ai_tenant, switch_on, fake_server):
        with fake_e2e_settings(fake_server):
            body = client_for(tenant_admin, ai_tenant).post(f"{API}/health-check/").json()
        assert body["status"] == "ok"
        assert (body["prompt_id"], body["prompt_version"]) == ("gateway.health_check", 1)
        record = AICallRecord.objects.get(public_id=body["call_id"])
        assert record.tenant == ai_tenant
        assert record.user == tenant_admin

    def test_a_doer_may_not_run_it(self, member, ai_tenant):
        assert client_for(member, ai_tenant).post(f"{API}/health-check/").status_code == 403

    def test_without_a_tenant_header_it_is_refused(self, tenant_admin):
        assert client_for(tenant_admin).post(f"{API}/health-check/").status_code == 403

    def test_an_admin_of_another_tenant_is_refused(self, tenant_admin, other_tenant):
        response = client_for(tenant_admin, other_tenant).post(f"{API}/health-check/")
        assert response.status_code in (403, 404)
        assert not AICallRecord.objects.exists()
