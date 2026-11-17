"""Prompt versioning rules and the test-suite network guard."""

import socket

import pytest

from ai_gateway.benchmark_prompts import BENCHMARK_PROMPTS, TARGET_P95_SECONDS
from ai_gateway.prompts import PROMPTS, PromptNotFound, get_prompt
from common import network_guard

#: Published (id, version) -> sha256 of the text. Editing a published template's
#: text fails here: add a new version instead, and pin it.
PINNED = {
    ("gateway.health_check", 1): "280af80a2acc273959856bde3c6e04bbf014a258b0a6a8e7307199da115de057",
    ("benchmark.answer", 1): "560d2a1d17ac165c80ddf83fc7a645628d40530fb0626fbc64b92f64628dc832",
}


class TestPromptVersions:
    def test_every_published_template_is_pinned_and_unchanged(self):
        assert set(PROMPTS) == set(PINNED)
        for key, template in PROMPTS.items():
            assert template.fingerprint() == PINNED[key], f"{key} changed: add a new version"

    def test_ids_and_versions_are_well_formed(self):
        for (template_id, version), template in PROMPTS.items():
            assert template.id == template_id and template.version == version
            assert version >= 1
            assert template.max_output_tokens > 0

    def test_latest_version_is_chosen_when_none_is_given(self):
        assert get_prompt("benchmark.answer").version == max(
            v for (i, v) in PROMPTS if i == "benchmark.answer"
        )

    def test_unknown_version_is_refused(self):
        with pytest.raises(PromptNotFound):
            get_prompt("benchmark.answer", 99)


class TestBenchmarkPromptSet:
    def test_it_has_short_long_and_long_context_prompts_in_both_modes(self):
        modes = {p.mode for p in BENCHMARK_PROMPTS}
        assert modes == set(TARGET_P95_SECONDS) == {"fast", "think"}
        sizes = sorted(len(p.request) for p in BENCHMARK_PROMPTS)
        assert sizes[0] < 200
        assert sizes[-1] > 20_000  # long context

    def test_the_sow_targets(self):
        assert TARGET_P95_SECONDS == {"fast": 5.0, "think": 10.0}

    def test_every_prompt_is_marked_synthetic_or_is_a_generic_question(self):
        for prompt in BENCHMARK_PROMPTS:
            if len(prompt.request) > 200:
                assert "invented for testing" in prompt.request, prompt.name


class TestNetworkGuard:
    def test_the_guard_is_installed_for_the_whole_session(self):
        assert network_guard.installed()

    @pytest.mark.parametrize(
        "address",
        [("8.8.8.8", 443), ("1.1.1.1", 80), ("169.254.169.254", 80), ("2001:4860:4860::8888", 443)],
    )
    def test_a_connection_to_a_non_local_address_fails_before_sending(self, address):
        family = socket.AF_INET6 if ":" in address[0] else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_STREAM)
        try:
            with pytest.raises(network_guard.NonLocalConnectionBlocked):
                sock.connect(address)
            with pytest.raises(network_guard.NonLocalConnectionBlocked):
                sock.connect_ex(address)
        finally:
            sock.close()

    def test_loopback_is_allowed(self, fake_server):
        host, port = fake_server.server_address[:2]
        with socket.create_connection((host, port), timeout=2):
            pass

    @pytest.mark.parametrize(
        ("raw", "local"),
        [
            ("127.0.0.1", True),
            ("::1", True),
            ("10.1.2.3", True),
            ("172.18.0.2", True),
            ("192.168.1.10", True),
            ("::ffff:127.0.0.1", True),
            ("169.254.169.254", False),
            ("8.8.8.8", False),
            ("172.32.0.1", False),
            ("not-an-ip", False),
        ],
    )
    def test_classification(self, raw, local):
        assert network_guard.is_local_ip(raw) is local
