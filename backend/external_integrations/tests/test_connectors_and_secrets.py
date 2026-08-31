"""Connector configuration, credential references and the connection test.

The recurring question in this file is "can a secret get out": through a
serialiser, through audit, through a log, through an error message, or through
the OpenAPI schema. Each of those is asked directly rather than assumed.
"""

import json

import pytest

from external_integrations import services
from external_integrations.config_schema import (
    ConfigErrorCode,
    ConfigurationError,
    validate_configuration,
)
from external_integrations.models import Connector, ConnectorStatus, TestStatus
from external_integrations.secrets import (
    SecretUnavailable,
    auth_headers,
    environment_variable_name,
    resolve_connector_secret,
)
from external_integrations.tests.conftest import (
    BASE_CONFIG,
    INTEGRATIONS_API,
    enable,
    make_connector,
)

SYNTHETIC_SECRET = "synthetic-token-value-not-a-real-credential"


# ---------------------------------------------------------------------------
# Configuration schema
# ---------------------------------------------------------------------------
class TestConfigurationSchema:
    def test_a_valid_configuration_is_normalised_with_defaults(self):
        config = validate_configuration("generic_https", {"base_url": "https://x.test/"})
        assert config["allowed_path_prefix"] == "/"
        assert config["verify_tls"] is True
        assert config["connect_timeout_seconds"] >= 1
        assert config["read_timeout_seconds"] >= 1
        assert config["max_response_bytes"] > 0

    def test_an_unknown_field_is_refused(self):
        """Not ignored. A field that is carried along without meaning is a field
        somebody will later assume was honoured."""
        with pytest.raises(ConfigurationError) as excinfo:
            validate_configuration(
                "generic_https", {**BASE_CONFIG, "proxy_command": "ssh -W %h:%p bastion"}
            )
        assert excinfo.value.code == ConfigErrorCode.UNKNOWN_FIELD

    @pytest.mark.parametrize(
        "field",
        ["command", "script", "template", "python_path", "filesystem_root", "proxy", "ssh_config"],
    )
    def test_nothing_that_turns_configuration_into_code_is_accepted(self, field):
        with pytest.raises(ConfigurationError) as excinfo:
            validate_configuration("generic_https", {**BASE_CONFIG, field: "anything"})
        assert excinfo.value.code == ConfigErrorCode.UNKNOWN_FIELD

    def test_tls_verification_cannot_be_disabled(self):
        """There is no environment flag for this, and no test-only exception."""
        with pytest.raises(ConfigurationError) as excinfo:
            validate_configuration("generic_https", {**BASE_CONFIG, "verify_tls": False})
        assert excinfo.value.code == ConfigErrorCode.TLS_REQUIRED

    def test_a_missing_base_url_is_refused(self):
        with pytest.raises(ConfigurationError) as excinfo:
            validate_configuration("generic_https", {"allowed_path_prefix": "/x/"})
        assert excinfo.value.code == ConfigErrorCode.MISSING_FIELD

    @pytest.mark.parametrize(
        "url",
        [
            "http://insecure.test/",
            "https://169.254.169.254/",
            "https://127.0.0.1/",
            "https://user:pw@host.test/",
            "https://host.test:22/",
        ],
    )
    def test_an_unsafe_base_url_is_refused_at_configuration_time(self, url):
        with pytest.raises(ConfigurationError):
            validate_configuration("generic_https", {**BASE_CONFIG, "base_url": url})

    @pytest.mark.parametrize(
        "header",
        [
            "Authorization",
            "authorization",
            "Cookie",
            "Host",
            "Content-Length",
            "Transfer-Encoding",
            "Connection",
            "Proxy-Authorization",
            "X-Anything-Else",
        ],
    )
    def test_headers_outside_the_allow_list_are_refused(self, header):
        """`Authorization` in particular: a configurable auth header is a
        plaintext secret in a JSON column with extra steps."""
        with pytest.raises(ConfigurationError) as excinfo:
            validate_configuration(
                "generic_https", {**BASE_CONFIG, "static_headers": {header: "value"}}
            )
        assert excinfo.value.code == ConfigErrorCode.HEADER_REJECTED

    def test_allow_listed_headers_are_accepted_and_lowercased(self):
        config = validate_configuration(
            "generic_https", {**BASE_CONFIG, "static_headers": {"Accept": "application/json"}}
        )
        assert config["static_headers"] == {"accept": "application/json"}

    def test_a_header_value_with_a_newline_is_refused(self):
        with pytest.raises(ConfigurationError) as excinfo:
            validate_configuration(
                "generic_https", {**BASE_CONFIG, "static_headers": {"Accept": "a\r\nX-Evil: 1"}}
            )
        assert excinfo.value.code == ConfigErrorCode.HEADER_REJECTED

    @pytest.mark.parametrize(
        "key,value",
        [
            ("connect_timeout_seconds", 0),
            ("connect_timeout_seconds", 999),
            ("read_timeout_seconds", 0),
            ("read_timeout_seconds", 10000),
            ("connect_timeout_seconds", "5"),
            ("connect_timeout_seconds", True),
        ],
    )
    def test_timeouts_are_bounded_and_typed(self, key, value):
        """Never infinite, never absent, never a bool wearing an int's clothes."""
        with pytest.raises(ConfigurationError) as excinfo:
            validate_configuration("generic_https", {**BASE_CONFIG, key: value})
        assert excinfo.value.code == ConfigErrorCode.INVALID_VALUE

    def test_the_response_limit_is_bounded(self):
        with pytest.raises(ConfigurationError):
            validate_configuration(
                "generic_https", {**BASE_CONFIG, "max_response_bytes": 10 * 1024**4}
            )

    def test_an_unsupported_connector_type_is_refused(self):
        with pytest.raises(ConfigurationError) as excinfo:
            validate_configuration("sftp", BASE_CONFIG)
        assert excinfo.value.code == ConfigErrorCode.UNSUPPORTED_TYPE


# ---------------------------------------------------------------------------
# Credential references
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCredentialReference:
    def test_the_model_has_no_column_that_could_hold_a_secret(self):
        """A structural guarantee, not a convention: a column that does not
        exist cannot be written by a raw cursor or leaked by a serialiser."""
        from external_integrations.models import ConnectorCredentialReference

        names = {f.name for f in ConnectorCredentialReference._meta.get_fields()}
        for forbidden in ("value", "secret", "token", "password", "api_key", "credential_value"):
            assert forbidden not in names

    def test_the_variable_name_is_derived_from_the_connector(self, tenant_a, admin_a):
        connector = make_connector(tenant_a, admin_a)
        name = environment_variable_name(connector, connector.credential_reference)
        assert name.startswith("REGX_CONNECTOR_")
        assert name.endswith("_TOKEN")

    def test_an_explicit_reference_name_is_used_verbatim(self, tenant_a, admin_a):
        from external_integrations import services as svc

        connector = make_connector(tenant_a, admin_a, credential=False)
        reference = svc.set_credential_reference(
            connector=connector,
            tenant=tenant_a,
            actor=admin_a,
            credential_type="api_key",
            reference_name="MY_DEPLOYMENT_KEY",
        )
        assert environment_variable_name(connector, reference) == "MY_DEPLOYMENT_KEY"

    def test_a_missing_secret_is_a_loud_failure_not_an_empty_string(
        self, tenant_a, admin_a, monkeypatch
    ):
        """No default, no development fallback. An empty string would produce an
        unauthenticated request that nobody notices."""
        connector = make_connector(tenant_a, admin_a)
        name = environment_variable_name(connector, connector.credential_reference)
        monkeypatch.delenv(name, raising=False)
        with pytest.raises(SecretUnavailable):
            resolve_connector_secret(connector, connector.credential_reference)

    def test_an_empty_environment_value_is_also_a_failure(self, tenant_a, admin_a, monkeypatch):
        connector = make_connector(tenant_a, admin_a)
        name = environment_variable_name(connector, connector.credential_reference)
        monkeypatch.setenv(name, "")
        with pytest.raises(SecretUnavailable):
            resolve_connector_secret(connector, connector.credential_reference)

    def test_the_failure_names_the_variable_and_never_a_value(self, tenant_a, admin_a, monkeypatch):
        connector = make_connector(tenant_a, admin_a)
        name = environment_variable_name(connector, connector.credential_reference)
        monkeypatch.delenv(name, raising=False)
        with pytest.raises(SecretUnavailable) as excinfo:
            resolve_connector_secret(connector, connector.credential_reference)
        # The name is what an operator needs; it is not itself a secret.
        assert name in str(excinfo.value)

    def test_the_auth_header_is_built_by_the_adapter(self, tenant_a, admin_a, monkeypatch):
        connector = make_connector(tenant_a, admin_a)
        name = environment_variable_name(connector, connector.credential_reference)
        monkeypatch.setenv(name, SYNTHETIC_SECRET)
        assert auth_headers(connector, connector.credential_reference) == {
            "Authorization": f"Bearer {SYNTHETIC_SECRET}"
        }

    def test_no_secret_reaches_the_api(self, client_admin_a, tenant_a, admin_a, monkeypatch):
        """The whole response body is searched, not just the fields somebody
        remembered to check."""
        connector = make_connector(tenant_a, admin_a)
        name = environment_variable_name(connector, connector.credential_reference)
        monkeypatch.setenv(name, SYNTHETIC_SECRET)

        response = client_admin_a.get(f"{INTEGRATIONS_API}/{connector.public_id}/")
        assert response.status_code == 200
        body = json.dumps(response.data, default=str)
        assert SYNTHETIC_SECRET not in body
        # The variable name and the resolvability flag are fine, and useful.
        assert response.data["credential"]["environment_variable"] == name
        assert response.data["credential"]["is_resolvable"] is True

    def test_resolvability_is_false_when_the_variable_is_absent(
        self, client_admin_a, tenant_a, admin_a, monkeypatch
    ):
        connector = make_connector(tenant_a, admin_a)
        name = environment_variable_name(connector, connector.credential_reference)
        monkeypatch.delenv(name, raising=False)
        response = client_admin_a.get(f"{INTEGRATIONS_API}/{connector.public_id}/")
        assert response.data["credential"]["is_resolvable"] is False

    def test_no_secret_reaches_audit(self, tenant_a, admin_a, monkeypatch):
        from audit.models import AuditEvent

        connector = make_connector(tenant_a, admin_a)
        name = environment_variable_name(connector, connector.credential_reference)
        monkeypatch.setenv(name, SYNTHETIC_SECRET)
        enable(connector, tenant_a, admin_a)

        rows = json.dumps(list(AuditEvent.objects.values("event_type", "payload")), default=str)
        assert SYNTHETIC_SECRET not in rows
        # Nor the base URL, which is not secret but is also not audit's business.
        assert "connector.test" not in rows


# ---------------------------------------------------------------------------
# Connector lifecycle
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestConnectorLifecycle:
    def test_a_new_connector_starts_as_a_draft(self, tenant_a, admin_a):
        """DRAFT, not ACTIVE. Enabling is a separate deliberate act."""
        connector = make_connector(tenant_a, admin_a)
        assert connector.status == ConnectorStatus.DRAFT
        assert connector.configuration_version == 1

    def test_enabling_and_disabling_move_the_status(self, tenant_a, admin_a):
        connector = enable(make_connector(tenant_a, admin_a), tenant_a, admin_a)
        assert connector.status == ConnectorStatus.ACTIVE
        connector = services.set_connector_status(
            connector=connector,
            tenant=tenant_a,
            actor=admin_a,
            status=ConnectorStatus.DISABLED,
        )
        assert connector.status == ConnectorStatus.DISABLED

    def test_active_is_not_approval(self, tenant_a, admin_a):
        """There is no APPROVED state to be confused with."""
        assert "approved" not in {value for value, _label in ConnectorStatus.choices}

    def test_editing_the_configuration_bumps_the_version(self, tenant_a, admin_a):
        connector = make_connector(tenant_a, admin_a)
        updated = services.update_connector(
            connector=connector,
            tenant=tenant_a,
            actor=admin_a,
            configuration={**BASE_CONFIG, "read_timeout_seconds": 45},
        )
        assert updated.configuration_version == 2

    def test_an_unchanged_configuration_does_not_bump_the_version(self, tenant_a, admin_a):
        """A version that moved on every save would be meaningless, and it is
        the number executions compare themselves against."""
        connector = make_connector(tenant_a, admin_a)
        updated = services.update_connector(
            connector=connector, tenant=tenant_a, actor=admin_a, configuration=dict(BASE_CONFIG)
        )
        assert updated.configuration_version == 1

    def test_renaming_does_not_bump_the_version(self, tenant_a, admin_a):
        connector = make_connector(tenant_a, admin_a)
        updated = services.update_connector(
            connector=connector, tenant=tenant_a, actor=admin_a, name="Renamed"
        )
        assert updated.configuration_version == 1
        assert updated.name == "Renamed"

    def test_enabling_revalidates_the_stored_configuration(self, tenant_a, admin_a):
        """A connector configured under different rules must not become
        executable just because somebody pressed a button."""
        connector = make_connector(tenant_a, admin_a)
        Connector.objects.filter(pk=connector.pk).update(
            configuration={"base_url": "http://insecure.test/"}, configuration_version=2
        )
        connector.refresh_from_db()
        with pytest.raises(services.ConnectorNotExecutable):
            enable(connector, tenant_a, admin_a)

    def test_an_archived_connector_cannot_be_changed(self, tenant_a, admin_a):
        connector = make_connector(tenant_a, admin_a)
        services.set_connector_status(
            connector=connector,
            tenant=tenant_a,
            actor=admin_a,
            status=ConnectorStatus.ARCHIVED,
        )
        connector.refresh_from_db()
        with pytest.raises(services.ConnectorNotExecutable):
            services.update_connector(
                connector=connector, tenant=tenant_a, actor=admin_a, name="Nope"
            )

    def test_there_is_no_delete_endpoint(self, client_admin_a, tenant_a, admin_a):
        """Connectors are archived. Executions reference them, and that history
        is evidence of what was transferred."""
        connector = make_connector(tenant_a, admin_a)
        response = client_admin_a.delete(f"{INTEGRATIONS_API}/{connector.public_id}/")
        assert response.status_code in (404, 405)


# ---------------------------------------------------------------------------
# Connection test
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestConnectionTest:
    def test_a_reachable_endpoint_is_reported_reachable(
        self, client_admin_a, active_connector, connector_secret, fake_remote
    ):
        response = client_admin_a.post(f"{INTEGRATIONS_API}/{active_connector.public_id}/test/")
        assert response.status_code == 200
        assert response.data["reachable"] is True
        assert response.data["authenticated"] is True
        assert response.data["error_code"] == ""
        assert isinstance(response.data["latency_ms"], int)

    def test_the_test_never_writes(
        self, client_admin_a, active_connector, connector_secret, fake_remote
    ):
        """A button labelled "test" must not perform a transfer nobody asked
        for."""
        client_admin_a.post(f"{INTEGRATIONS_API}/{active_connector.public_id}/test/")
        assert [call.method for call in fake_remote.calls] == ["GET"]

    def test_the_result_is_recorded_on_the_connector(
        self, client_admin_a, active_connector, connector_secret, fake_remote
    ):
        client_admin_a.post(f"{INTEGRATIONS_API}/{active_connector.public_id}/test/")
        active_connector.refresh_from_db()
        assert active_connector.last_test_status == TestStatus.REACHABLE
        assert active_connector.last_tested_at is not None

    def test_an_auth_failure_is_reported_as_unauthorised(
        self, client_admin_a, active_connector, connector_secret, fake_remote
    ):
        from external_integrations.transport import TransportError, TransportErrorCode

        fake_remote.raises = TransportError(TransportErrorCode.AUTH_FAILED, http_status=401)
        response = client_admin_a.post(f"{INTEGRATIONS_API}/{active_connector.public_id}/test/")
        assert response.data["reachable"] is False
        assert response.data["status"] == TestStatus.UNAUTHORISED
        assert response.data["error_code"] == TransportErrorCode.AUTH_FAILED

    def test_a_missing_secret_is_reported_without_attempting_a_request(
        self, client_admin_a, active_connector, fake_remote, monkeypatch
    ):
        from external_integrations.secrets import environment_variable_name

        name = environment_variable_name(active_connector, active_connector.credential_reference)
        monkeypatch.delenv(name, raising=False)
        response = client_admin_a.post(f"{INTEGRATIONS_API}/{active_connector.public_id}/test/")
        assert response.data["status"] == TestStatus.UNAUTHORISED
        assert fake_remote.calls == []

    def test_the_result_carries_no_remote_body_or_headers(
        self, client_admin_a, active_connector, connector_secret, fake_remote
    ):
        """Only reachability. A remote body can contain another tenant's data,
        an internal hostname, or markup."""
        fake_remote.body = b"<html>internal.corp.example says hello</html>"
        response = client_admin_a.post(f"{INTEGRATIONS_API}/{active_connector.public_id}/test/")
        body = json.dumps(response.data, default=str)
        assert "internal.corp" not in body
        assert set(response.data) == {
            "reachable",
            "authenticated",
            "status",
            "latency_ms",
            "error_code",
        }
