"""`manage.py ai_benchmark`: refuses when not configured, works end to end on the fake server."""

import json
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from ai_gateway.benchmark_prompts import BENCHMARK_PROMPTS
from ai_gateway.models import AISwitch
from ai_gateway.tests.conftest import ai_settings, fake_e2e_settings


def _run(*args):
    out = StringIO()
    call_command("ai_benchmark", *args, stdout=out)
    return out.getvalue()


@pytest.mark.django_db
class TestRefusesWithoutConfiguration:
    def test_default_empty_settings_stop_with_not_configured(self, ai_tenant, fake_server):
        with pytest.raises(CommandError, match=r"not configured.*Nothing was sent"):
            _run("--tenant", ai_tenant.slug)
        assert fake_server.requests == []

    def test_missing_key_stops_and_sends_nothing(self, ai_tenant, switch_on, fake_server):
        with fake_e2e_settings(fake_server, e2e_api_key=""):
            with pytest.raises(CommandError, match="API_KEY_MISSING"):
                _run("--tenant", ai_tenant.slug)
        assert fake_server.requests == []

    def test_the_offline_stub_is_not_benchmarked(self, ai_tenant, switch_on):
        with ai_settings(enabled=True), pytest.raises(CommandError, match="STUB"):
            _run("--tenant", ai_tenant.slug)

    def test_configured_but_switched_off_stops_and_sends_nothing(self, ai_tenant, fake_server):
        with fake_e2e_settings(fake_server), pytest.raises(CommandError, match="disabled"):
            _run("--tenant", ai_tenant.slug)
        assert fake_server.requests == []

    def test_unknown_tenant_stops(self, db, switch_on, fake_server):
        with fake_e2e_settings(fake_server), pytest.raises(CommandError, match="tenant"):
            _run("--tenant", "nobody")
        assert fake_server.requests == []


@pytest.mark.django_db(transaction=True)
class TestEndToEndOnTheFakeServer:
    """Worker threads use their own database connections, so these tests commit."""

    @pytest.fixture
    def on(self, ai_tenant):
        AISwitch.objects.update_or_create(pk=1, defaults={"enabled": True})

    def test_fast_server_meets_both_targets(self, ai_tenant, on, fake_server, tmp_path):
        report_path = tmp_path / "report.json"
        with fake_e2e_settings(fake_server):
            out = _run(
                "--tenant",
                ai_tenant.slug,
                "--concurrency",
                "1,5,10",
                "--json-out",
                str(report_path),
            )
        n = len(BENCHMARK_PROMPTS)
        # 1+5+10 rounds of the prompt set, then 3 consistency runs per prompt.
        assert len(fake_server.requests) == n * 16 + n * 3
        report = json.loads(report_path.read_text())
        assert [lvl["concurrency"] for lvl in report["levels"]] == [1, 5, 10]
        for level in report["levels"]:
            for mode in ("fast", "think"):
                m = level["modes"][mode]
                assert m["errors"] == 0
                assert m["meets_target"] is True
                assert m["p95_ms"] >= m["p50_ms"] >= 0
                assert m["output_tokens"] > 0
        assert report["consistency"] == {
            "prompts": n,
            "repeats": 3,
            "identical": n,
            "failed_runs": 0,
        }
        assert "MISSES" not in out
        assert "FAKE-REPLY-MARKER" not in out + report_path.read_text()

    def test_slow_server_misses_the_target_and_says_so(self, ai_tenant, on, fake_server, tmp_path):
        fake_server.default = {"kind": "slow", "delay": 0.4}
        report_path = tmp_path / "report.json"
        with fake_e2e_settings(fake_server):
            out = _run(
                "--tenant",
                ai_tenant.slug,
                "--concurrency",
                "1",
                "--repeats",
                "2",
                "--fast-target",
                "0.2",
                "--think-target",
                "0.2",
                "--json-out",
                str(report_path),
            )
        level = json.loads(report_path.read_text())["levels"][0]
        assert level["modes"]["fast"]["meets_target"] is False
        assert level["modes"]["fast"]["p95_ms"] >= 400
        assert "MISSES" in out

    def test_errors_are_counted_and_fail_the_target(self, ai_tenant, on, fake_server, tmp_path):
        fake_server.default = {"kind": "500"}
        report_path = tmp_path / "report.json"
        with fake_e2e_settings(fake_server):
            _run(
                "--tenant",
                ai_tenant.slug,
                "--concurrency",
                "1",
                "--repeats",
                "2",
                "--json-out",
                str(report_path),
            )
        report = json.loads(report_path.read_text())
        fast = report["levels"][0]["modes"]["fast"]
        assert fast["errors"] == fast["requests"]
        assert fast["error_rate"] == 1.0
        assert fast["meets_target"] is False
        assert report["consistency"]["identical"] == 0
