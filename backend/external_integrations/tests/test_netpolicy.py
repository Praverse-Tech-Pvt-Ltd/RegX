"""Destination policy: URLs, addresses, DNS and paths.

Unit tests with no database and no network. The resolver is monkeypatched, which
is the only honest way to test "a public name that answers with a private
address" -- and it is exactly the case a real DNS lookup could never be relied
on to produce.

Nothing here contacts a real metadata endpoint, a real private host, or anything
else. `169.254.169.254` appears as a string being refused, never as a socket.
"""

import ipaddress
import socket

import pytest

from external_integrations import netpolicy
from external_integrations.netpolicy import (
    DestinationRefused,
    ErrorCode,
    build_url,
    classify_address,
    resolve_destination,
    validate_url,
)


def _answer(*addresses):
    """A fake `getaddrinfo` returning exactly these addresses."""

    def fake(host, port, *args, **kwargs):
        out = []
        for address in addresses:
            family = (
                socket.AF_INET6
                if isinstance(ipaddress.ip_address(address), ipaddress.IPv6Address)
                else socket.AF_INET
            )
            out.append((family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, port)))
        return out

    return fake


# ---------------------------------------------------------------------------
# Address classification
# ---------------------------------------------------------------------------
class TestAddressClassification:
    @pytest.mark.parametrize(
        "address",
        [
            "127.0.0.1",
            "127.0.0.2",
            "0.0.0.0",
            "10.0.0.1",
            "172.16.0.1",
            "192.168.1.1",
            # The metadata endpoint every cloud provider exposes without
            # authentication. It is link-local, so the rule that refuses it is
            # the general one rather than a special case somebody remembered.
            "169.254.169.254",
            "169.254.1.1",
            "::1",
            "fe80::1",
            "fc00::1",
            "fd00::1",
            "ff02::1",
            "::",
            "::ffff:127.0.0.1",
            "::ffff:10.0.0.1",
            "100.64.0.1",
            "224.0.0.1",
            "240.0.0.1",
        ],
    )
    def test_non_public_addresses_are_refused(self, address):
        assert classify_address(address) is False

    @pytest.mark.parametrize(
        "address", ["93.184.216.34", "8.8.8.8", "2606:2800:220:1:248:1893:25c8:1946"]
    )
    def test_public_addresses_are_allowed(self, address):
        assert classify_address(address) is True

    def test_unparseable_text_is_not_public(self):
        """Fail closed. An address that cannot be understood is not one that
        has been shown to be safe."""
        assert classify_address("not-an-address") is False
        assert classify_address("") is False


# ---------------------------------------------------------------------------
# URL text
# ---------------------------------------------------------------------------
class TestUrlValidation:
    @pytest.mark.parametrize(
        "url",
        [
            "http://example.test/x",
            "file:///etc/passwd",
            "ftp://example.test/x",
            "gopher://example.test/x",
            "data:text/plain,hello",
            "javascript:alert(1)",
            "ws://example.test/x",
            "unix:///var/run/docker.sock",
        ],
    )
    def test_only_https_is_accepted(self, url):
        with pytest.raises(DestinationRefused) as excinfo:
            validate_url(url)
        assert excinfo.value.code in (ErrorCode.SCHEME_REJECTED, ErrorCode.URL_INVALID)

    def test_embedded_credentials_are_refused(self):
        """A credential in a URL ends up in every log line that records it."""
        with pytest.raises(DestinationRefused) as excinfo:
            validate_url("https://user:secret@example.test/x")
        assert excinfo.value.code == ErrorCode.CREDENTIALS_IN_URL

    def test_a_bare_at_sign_in_the_authority_is_refused(self):
        with pytest.raises(DestinationRefused) as excinfo:
            validate_url("https://user@example.test/x")
        assert excinfo.value.code == ErrorCode.CREDENTIALS_IN_URL

    @pytest.mark.parametrize("url", ["https://example.test:22/x", "https://example.test:8080/x"])
    def test_unexpected_ports_are_refused(self, url):
        with pytest.raises(DestinationRefused) as excinfo:
            validate_url(url)
        assert excinfo.value.code == ErrorCode.PORT_REJECTED

    def test_control_characters_are_refused(self):
        with pytest.raises(DestinationRefused) as excinfo:
            validate_url("https://example.test/x\r\nInjected: 1")
        assert excinfo.value.code == ErrorCode.URL_INVALID

    @pytest.mark.parametrize(
        "url",
        [
            "https://127.0.0.1/x",
            "https://127.0.0.2/x",
            "https://0.0.0.0/x",
            "https://10.0.0.1/x",
            "https://192.168.1.1/x",
            "https://169.254.169.254/latest/meta-data/",
            "https://[::1]/x",
            "https://[fe80::1]/x",
            # Integer and hex spellings of 127.0.0.1. No resolver returns these,
            # but plenty of parsers and operating systems interpret them.
            "https://2130706433/x",
            "https://0x7f000001/x",
            "https://0177.0.0.1/x",
        ],
    )
    def test_literal_private_addresses_never_reach_the_resolver(self, url, monkeypatch):
        def explode(*args, **kwargs):  # pragma: no cover - must not be called
            raise AssertionError("the resolver was consulted for a literal address")

        monkeypatch.setattr(socket, "getaddrinfo", explode)
        with pytest.raises(DestinationRefused) as excinfo:
            validate_url(url)
        assert excinfo.value.code == ErrorCode.DNS_BLOCKED

    def test_a_public_literal_address_is_accepted(self):
        scheme, host, port, path = validate_url("https://93.184.216.34/x")
        assert (scheme, host, port, path) == ("https", "93.184.216.34", 443, "/x")

    def test_case_and_trailing_dot_are_normalised(self, monkeypatch):
        """`EXAMPLE.test.` and `example.test` are the same host, so a check that
        treated them differently would be a check with a bypass."""
        monkeypatch.setattr(socket, "getaddrinfo", _answer("93.184.216.34"))
        _scheme, host, _port, _path = validate_url("https://EXAMPLE.Test./x")
        assert host == "example.test"


# ---------------------------------------------------------------------------
# DNS
# ---------------------------------------------------------------------------
class TestDnsPolicy:
    def test_a_public_name_resolving_privately_is_refused(self, monkeypatch):
        """THE rebinding test. The text is impeccable; the answer is not."""
        monkeypatch.setattr(socket, "getaddrinfo", _answer("169.254.169.254"))
        with pytest.raises(DestinationRefused) as excinfo:
            resolve_destination("https://totally-public.test/x")
        assert excinfo.value.code == ErrorCode.DNS_BLOCKED

    def test_one_bad_answer_refuses_the_whole_destination(self, monkeypatch):
        """A mixed answer set is a rebinding attempt, not a choice.

        Taking the public address and connecting to it would be agreeing to run
        a race whose other outcome is a request to a private host.
        """
        monkeypatch.setattr(socket, "getaddrinfo", _answer("93.184.216.34", "10.0.0.5"))
        with pytest.raises(DestinationRefused) as excinfo:
            resolve_destination("https://mixed.test/x")
        assert excinfo.value.code == ErrorCode.DNS_BLOCKED

    def test_order_does_not_matter(self, monkeypatch):
        monkeypatch.setattr(socket, "getaddrinfo", _answer("10.0.0.5", "93.184.216.34"))
        with pytest.raises(DestinationRefused):
            resolve_destination("https://mixed.test/x")

    def test_an_all_public_answer_is_accepted_and_pinned(self, monkeypatch):
        monkeypatch.setattr(socket, "getaddrinfo", _answer("93.184.216.34"))
        destination = resolve_destination("https://public.test/x")
        # The address is what the socket will use; the hostname is what TLS
        # will check. Both survive, which is the whole point.
        assert destination.address == "93.184.216.34"
        assert destination.hostname == "public.test"
        assert destination.port == 443

    def test_an_unresolvable_name_is_refused(self, monkeypatch):
        def fail(*args, **kwargs):
            raise socket.gaierror("nope")

        monkeypatch.setattr(socket, "getaddrinfo", fail)
        with pytest.raises(DestinationRefused) as excinfo:
            resolve_destination("https://missing.test/x")
        assert excinfo.value.code == ErrorCode.DNS_UNRESOLVED

    def test_an_empty_answer_is_refused(self, monkeypatch):
        monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [])
        with pytest.raises(DestinationRefused) as excinfo:
            resolve_destination("https://empty.test/x")
        assert excinfo.value.code == ErrorCode.DNS_UNRESOLVED

    def test_the_refusal_never_names_the_resolved_address(self, monkeypatch):
        """The error message is a side channel. "Which private address did it
        resolve to" is precisely what this module exists to stop anyone
        learning."""
        monkeypatch.setattr(socket, "getaddrinfo", _answer("169.254.169.254"))
        with pytest.raises(DestinationRefused) as excinfo:
            resolve_destination("https://rebinding.test/x")
        assert "169.254" not in str(excinfo.value)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
class TestPathControl:
    BASE = "https://public.test/"

    def test_a_relative_path_extends_the_prefix(self):
        url = build_url(base_url=self.BASE, allowed_path_prefix="/regx/", relative_path="a/b.pdf")
        assert url == "https://public.test/regx/a/b.pdf"

    def test_a_missing_trailing_slash_on_the_prefix_is_normalised(self):
        url = build_url(base_url=self.BASE, allowed_path_prefix="/regx", relative_path="a.pdf")
        assert url == "https://public.test/regx/a.pdf"

    @pytest.mark.parametrize(
        "relative",
        [
            "../etc/passwd",
            "a/../../b",
            "..",
            "%2e%2e/x",
            "%2E%2E/x",
            "%252e%252e/x",
            "a%2fb",
            "a%5cb",
            "a\\b",
            "a\x00b",
            "a\nb",
        ],
    )
    def test_traversal_and_encoded_traversal_are_refused(self, relative):
        with pytest.raises(DestinationRefused) as excinfo:
            build_url(base_url=self.BASE, allowed_path_prefix="/regx/", relative_path=relative)
        assert excinfo.value.code == ErrorCode.PATH_REJECTED

    @pytest.mark.parametrize(
        "relative",
        [
            "/absolute",
            "//evil.test/x",
            "https://evil.test/x",
            "http://evil.test/x",
        ],
    )
    def test_a_payload_can_never_replace_the_destination(self, relative):
        """`urljoin` would honour every one of these and send tenant data to a
        host nobody configured. This does not use `urljoin`."""
        with pytest.raises(DestinationRefused) as excinfo:
            build_url(base_url=self.BASE, allowed_path_prefix="/regx/", relative_path=relative)
        assert excinfo.value.code == ErrorCode.PATH_REJECTED

    def test_the_result_always_stays_under_the_prefix(self):
        url = build_url(base_url=self.BASE, allowed_path_prefix="/regx/", relative_path="")
        assert url == "https://public.test/regx/"

    def test_a_prefix_must_be_absolute(self):
        with pytest.raises(DestinationRefused) as excinfo:
            build_url(base_url=self.BASE, allowed_path_prefix="regx/", relative_path="a")
        assert excinfo.value.code == ErrorCode.PATH_REJECTED

    def test_a_non_default_allowed_port_survives_the_join(self):
        url = build_url(
            base_url="https://public.test:8443/",
            allowed_path_prefix="/regx/",
            relative_path="a.pdf",
        )
        assert url == "https://public.test:8443/regx/a.pdf"


class TestModuleShape:
    def test_http_is_not_in_the_allow_list(self):
        """There is no development-only escape hatch. An escape hatch that
        exists in the code exists in production."""
        assert netpolicy.ALLOWED_SCHEMES == frozenset({"https"})

    def test_no_environment_variable_relaxes_the_policy(self):
        source = netpolicy.__file__ or ""
        with open(source, encoding="utf-8") as handle:
            text = handle.read()
        assert "os.environ" not in text
        assert "getenv" not in text


class TestPrefixContainment:
    """The containment check, isolated from the traversal rejection.

    These two guards protect the same property from different directions:
    `_assert_path_is_safe` refuses traversal *syntax*, and the containment check
    refuses a *resolved* path that escapes the prefix. Testing containment while
    the syntax check is disabled is the only way to show it is load-bearing --
    with both active, no input reaches it, which is how it went from a guard to
    a tautology in the first place.
    """

    BASE = "https://public.test/"

    @pytest.mark.parametrize(
        "relative",
        ["../outside", "a/../../outside", "a/b/../../../outside", "./../outside"],
    )
    def test_a_resolved_path_that_escapes_the_prefix_is_refused(self, relative, monkeypatch):
        # The syntax check is neutered on purpose, so the only thing that can
        # refuse these is containment on the resolved path.
        monkeypatch.setattr(netpolicy, "_assert_path_is_safe", lambda path: None)
        with pytest.raises(DestinationRefused) as excinfo:
            build_url(base_url=self.BASE, allowed_path_prefix="/regx/", relative_path=relative)
        assert excinfo.value.code == ErrorCode.PATH_REJECTED

    @pytest.mark.parametrize("relative", ["a/b.pdf", "a/./b.pdf", "deep/nested/thing.pdf", ""])
    def test_a_resolved_path_inside_the_prefix_is_allowed(self, relative, monkeypatch):
        monkeypatch.setattr(netpolicy, "_assert_path_is_safe", lambda path: None)
        url = build_url(base_url=self.BASE, allowed_path_prefix="/regx/", relative_path=relative)
        assert url.startswith("https://public.test/regx")

    def test_a_sibling_prefix_does_not_count_as_containment(self, monkeypatch):
        """`/regx-other/x` must not pass a `/regx/` prefix on a string match."""
        monkeypatch.setattr(netpolicy, "_assert_path_is_safe", lambda path: None)
        with pytest.raises(DestinationRefused):
            build_url(
                base_url=self.BASE,
                allowed_path_prefix="/regx/",
                relative_path="../regx-other/x",
            )
