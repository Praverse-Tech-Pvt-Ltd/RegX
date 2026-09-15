"""P6: the verification gaps, and only those.

The inbound and outbound flows are already proven end to end elsewhere in this
package, and none of that is repeated here. What already exists:

  * `test_operations.TestInboundImport.test_a_valid_pdf_becomes_a_normal_document_version`
    -- API -> task -> `documents.ingest` -> a real DocumentVersion
  * `test_operations.TestInboundImport.test_the_scan_is_queued_and_the_version_is_not_pre_cleared`
    -- imported content is not pre-cleared
  * `test_operations.TestOutboundPackageTransfer.test_a_frozen_package_transfers`
    and `...test_the_execution_binds_to_the_exact_snapshot`
  * `test_operations.TestRetryPolicy.test_semantic_failures_are_not_retried`
    and `...test_a_transient_failure_is_retried_and_bounded`
  * `test_execution_concurrency.test_two_workers_claim_one_execution_and_only_one_wins`
    and `...test_a_duplicate_request_never_becomes_two_executions`
  * `test_transport_socket` -- `perform_request` against a real loopback server

What those leave unproven, and what this module covers:

1. The FAILED audit event. Success and failure both emit, but only the success
   side was ever asserted -- `external_execution.failed` had no test reference
   anywhere, so a regression that stopped emitting it would have been silent.
2. Connector lifecycle audit: enabled, disabled, archived.
3. `localhost` as a *hostname*. 127.0.0.1 and ::1 are covered as literals, and
   localhost resolves to them, but the name path had no assertion.
4. Link-local reached by name rather than by literal.
5. Hostname normalization, asserted on the value `validate_url` returns.
6. That a refused redirect makes no second request, so a bearer token has no
   second request to travel on.

No production code is changed by this module, and nothing here contacts a real
host: DNS is stubbed and the transport is the existing double.
"""

from __future__ import annotations

import pytest

from external_integrations import services
from external_integrations.models import ConnectorStatus, ExecutionStatus
from external_integrations.tests.conftest import BASE_CONFIG, PDF_BYTES

#: The value `connector_secret` puts in the environment. Synthetic.
SECRET = "synthetic-token-value-not-a-real-credential"

EXECUTION_CREATED = "external_execution.created"
EXECUTION_SUCCEEDED = "external_execution.succeeded"
EXECUTION_FAILED = "external_execution.failed"


def _events(event_type=None):
    from audit.models import AuditEvent

    qs = AuditEvent.objects.all()
    return qs.filter(event_type=event_type) if event_type else qs


def _queued_import(tenant, actor, connector, *, key="p6"):
    """Queue an import through the service, which does not dispatch."""
    return services.create_execution(
        connector=connector,
        tenant=tenant,
        actor=actor,
        operation="import_document",
        idempotency_parts=[key],
        request_summary={
            "external_object_id": "remote-doc-1.pdf",
            "relative_path": "inbox/remote-doc-1.pdf",
            "title": "Imported synthetic document",
            "document_type": "pdf",
        },
    )


def _run(execution, tenant):
    from external_integrations.tasks import run_connector_execution

    run_connector_execution(execution.pk, tenant.pk)
    execution.refresh_from_db()
    return execution


def _fail_with(monkeypatch, code, *, retryable):
    from external_integrations import operations

    def fail(**kwargs):
        raise operations.OperationError(code, retryable=retryable)

    monkeypatch.setitem(operations.OPERATIONS, "import_document", fail)


# ===========================================================================
# 1. The failed-execution audit event
# ===========================================================================
@pytest.mark.django_db
class TestFailedExecutionIsAudited:
    def test_a_non_retryable_failure_emits_failed(
        self, tenant_a, admin_a, active_connector, connector_secret, monkeypatch
    ):
        _fail_with(monkeypatch, "REMOTE_4XX", retryable=False)
        execution = _run(_queued_import(tenant_a, admin_a, active_connector), tenant_a)

        assert execution.status == ExecutionStatus.FAILED
        assert _events(EXECUTION_FAILED).count() == 1

    def test_an_exhausted_transient_failure_emits_failed_exactly_once(
        self, tenant_a, admin_a, active_connector, connector_secret, monkeypatch
    ):
        """A retryable failure that runs out of attempts is still terminal, and
        the terminal event is the one the trail needs.

        The retries are driven here rather than left to Celery. Under
        `task_always_eager` a `self.retry()` re-raises instead of re-entering
        the task, so one call leaves the execution back in QUEUED at attempt 1
        -- which is why `TestRetryPolicy.test_a_transient_failure_is_retried_
        and_bounded` passes without ever reaching the bound it names: its
        `attempt_count <= MAX_ATTEMPTS` holds at 1. Re-invoking the task is
        what a broker redelivering the message does, and it is the only way to
        observe what actually happens at the bound.
        """
        from external_integrations import tasks

        _fail_with(monkeypatch, "TIMEOUT", retryable=True)
        execution = _queued_import(tenant_a, admin_a, active_connector)

        # Bounded by more than MAX_ATTEMPTS, so a task that stopped terminating
        # would fail the assertions below rather than spin here.
        for _ in range(tasks.MAX_ATTEMPTS + 2):
            execution.refresh_from_db()
            if execution.status in {ExecutionStatus.FAILED, ExecutionStatus.SUCCEEDED}:
                break
            try:
                tasks.run_connector_execution(execution.pk, tenant_a.pk)
            except Exception:
                # Eager mode re-raises the failure in place of scheduling a
                # retry. The execution is already back in QUEUED by then.
                pass
        execution.refresh_from_db()

        assert execution.status == ExecutionStatus.FAILED
        assert execution.error_code == tasks.ExecutionErrorCode.ATTEMPTS_EXHAUSTED
        # The bound is real: a permanently broken endpoint costs three tries.
        assert execution.attempt_count == tasks.MAX_ATTEMPTS
        # Three attempts, one terminal row. Each attempt emits `started`.
        assert _events(EXECUTION_FAILED).count() == 1
        assert _events("external_execution.started").count() == tasks.MAX_ATTEMPTS

    def test_the_failed_event_names_the_tenant_and_the_execution(
        self, tenant_a, admin_a, active_connector, connector_secret, monkeypatch
    ):
        _fail_with(monkeypatch, "REMOTE_4XX", retryable=False)
        execution = _run(_queued_import(tenant_a, admin_a, active_connector), tenant_a)

        event = _events(EXECUTION_FAILED).get()
        assert event.tenant_id == tenant_a.pk
        assert event.resource_id == str(execution.public_id)
        assert event.resource_type == "external_integration"

    def test_the_actor_is_recoverable_even_though_the_worker_has_none(
        self, tenant_a, admin_a, active_connector, connector_secret, monkeypatch
    ):
        """A worker runs with no authenticated user, so `finish_execution`
        emits with no actor -- attributing the row to a person who was not
        there would be the wrong fix. Attribution is still recoverable: the
        `created` event carries the actor, and both events name the same
        execution.
        """
        _fail_with(monkeypatch, "REMOTE_4XX", retryable=False)
        execution = _run(_queued_import(tenant_a, admin_a, active_connector), tenant_a)

        created = _events(EXECUTION_CREATED).get()
        failed = _events(EXECUTION_FAILED).get()
        assert created.actor_id == admin_a.pk
        assert created.actor_email == admin_a.email
        assert failed.actor_id is None
        assert failed.resource_id == created.resource_id == str(execution.public_id)
        assert execution.requested_by_id == admin_a.pk

    def test_the_failed_payload_is_allow_listed_and_carries_no_secret(
        self, tenant_a, admin_a, active_connector, connector_secret, monkeypatch
    ):
        from external_integrations.audit_events import _ALLOWED_PAYLOAD_KEYS

        _fail_with(monkeypatch, "REMOTE_4XX", retryable=False)
        _run(_queued_import(tenant_a, admin_a, active_connector), tenant_a)

        payload = _events(EXECUTION_FAILED).get().payload
        assert set(payload) <= _ALLOWED_PAYLOAD_KEYS
        assert payload["status"] == ExecutionStatus.FAILED
        assert payload["error_code"] == "REMOTE_4XX"

        serialised = str(payload)
        assert SECRET not in serialised
        assert "authorization" not in serialised.lower()
        assert "bearer" not in serialised.lower()

    def test_no_remote_response_body_reaches_the_failed_event(
        self, tenant_a, admin_a, active_connector, connector_secret, fake_remote
    ):
        """The remote answers with a body and then the transfer fails. That
        body is attacker-influenced text and must not be in the audit row.
        """
        from external_integrations.transport import TransportError, TransportErrorCode

        fake_remote.body = b"<html>internal-hostname leaked here</html>"
        fake_remote.raises = TransportError(TransportErrorCode.REMOTE_4XX, http_status=404)
        _run(_queued_import(tenant_a, admin_a, active_connector), tenant_a)

        blob = str(_events(EXECUTION_FAILED).get().payload)
        assert "internal-hostname" not in blob
        assert "html" not in blob.lower()

    def test_a_failure_never_emits_succeeded(
        self, tenant_a, admin_a, active_connector, connector_secret, monkeypatch
    ):
        _fail_with(monkeypatch, "REMOTE_4XX", retryable=False)
        _run(_queued_import(tenant_a, admin_a, active_connector), tenant_a)

        assert _events(EXECUTION_SUCCEEDED).count() == 0

    def test_a_success_never_emits_failed(
        self, tenant_a, admin_a, active_connector, connector_secret, fake_remote
    ):
        fake_remote.body = PDF_BYTES
        execution = _run(_queued_import(tenant_a, admin_a, active_connector), tenant_a)

        assert execution.status == ExecutionStatus.SUCCEEDED
        assert _events(EXECUTION_SUCCEEDED).count() == 1
        assert _events(EXECUTION_FAILED).count() == 0

    def test_a_failure_in_one_tenant_writes_no_event_for_the_other(
        self, tenant_a, tenant_b, admin_a, active_connector, connector_secret, monkeypatch
    ):
        _fail_with(monkeypatch, "REMOTE_4XX", retryable=False)
        _run(_queued_import(tenant_a, admin_a, active_connector), tenant_a)

        assert _events(EXECUTION_FAILED).filter(tenant_id=tenant_b.pk).count() == 0


# ===========================================================================
# 2. Connector lifecycle audit
# ===========================================================================
@pytest.mark.django_db
class TestConnectorLifecycleIsAudited:
    """Only the transitions `set_connector_status` actually emits. No lifecycle
    event is invented here that the service does not produce."""

    @pytest.mark.parametrize(
        ("status", "event_type"),
        [
            (ConnectorStatus.DISABLED, "external_connector.disabled"),
            (ConnectorStatus.ARCHIVED, "external_connector.archived"),
        ],
    )
    def test_each_transition_emits_its_own_event(
        self, tenant_a, admin_a, active_connector, status, event_type
    ):
        assert _events(event_type).count() == 0
        services.set_connector_status(
            connector=active_connector, tenant=tenant_a, actor=admin_a, status=status
        )
        assert _events(event_type).count() == 1

    def test_enabling_emits_enabled(self, tenant_a, admin_a):
        """`active_connector` is deliberately not used here: it enables during
        setup, which would make a count assertion meaningless."""
        from external_integrations.tests.conftest import make_connector

        connector = make_connector(tenant_a, admin_a, name="P6 connector")
        assert _events("external_connector.enabled").count() == 0

        services.set_connector_status(
            connector=connector, tenant=tenant_a, actor=admin_a, status=ConnectorStatus.ACTIVE
        )
        assert _events("external_connector.enabled").count() == 1

    def test_creating_and_editing_are_audited(self, tenant_a, admin_a):
        connector = services.create_connector(
            tenant=tenant_a,
            actor=admin_a,
            name="P6 audit connector",
            connector_type="generic_https",
            configuration=dict(BASE_CONFIG),
        )
        assert _events("external_connector.created").count() == 1

        services.update_connector(
            connector=connector, tenant=tenant_a, actor=admin_a, description="edited"
        )
        assert _events("external_connector.updated").count() == 1

    def test_a_no_op_edit_writes_no_event(self, tenant_a, admin_a, active_connector):
        """A trail that records edits which did not happen is a false record,
        and `update_connector` only emits when a field actually moved."""
        services.update_connector(
            connector=active_connector,
            tenant=tenant_a,
            actor=admin_a,
            name=active_connector.name,
        )
        assert _events("external_connector.updated").count() == 0

    def test_a_lifecycle_event_names_the_tenant_the_actor_and_the_connector(
        self, tenant_a, admin_a, active_connector
    ):
        services.set_connector_status(
            connector=active_connector,
            tenant=tenant_a,
            actor=admin_a,
            status=ConnectorStatus.DISABLED,
        )
        event = _events("external_connector.disabled").get()
        assert event.tenant_id == tenant_a.pk
        assert event.actor_id == admin_a.pk
        assert event.resource_id == str(active_connector.public_id)
        assert event.payload["status"] == ConnectorStatus.DISABLED

    def test_no_lifecycle_payload_carries_a_secret_a_name_or_a_url(
        self, tenant_a, admin_a, active_connector, connector_secret
    ):
        """The connector's name is tenant free text and its base URL describes
        the deployment's network. Both are deliberately absent from the
        allow-list; the public id identifies the connector without describing
        it."""
        from external_integrations.audit_events import _ALLOWED_PAYLOAD_KEYS

        services.set_connector_status(
            connector=active_connector,
            tenant=tenant_a,
            actor=admin_a,
            status=ConnectorStatus.DISABLED,
        )
        for event in _events().filter(event_type__startswith="external_connector."):
            assert set(event.payload) <= _ALLOWED_PAYLOAD_KEYS
            blob = str(event.payload)
            assert SECRET not in blob
            assert active_connector.name not in blob
            assert BASE_CONFIG["base_url"] not in blob


# ===========================================================================
# 3 & 4. Hostnames that resolve somewhere they must not
# ===========================================================================
def _resolving_to(monkeypatch, answers: list[tuple[int, str]]):
    """Pin DNS for the duration of one test.

    `_resolve` is stubbed and the classifier is left alone: the point is that
    the real classifier refuses what a resolver returns, so stubbing the
    classifier would make the test prove nothing. Stubbing DNS is also what
    keeps this self-contained -- no name here is ever looked up for real.
    """
    from external_integrations import netpolicy

    monkeypatch.setattr(netpolicy, "_resolve", lambda hostname, port: answers)


class TestLocalhostByName:
    """127.0.0.1 and ::1 are already covered as literals. This is the name.

    No production special case is needed for `localhost` and none is asserted:
    the generic address classification already refuses whatever it resolves to,
    which is the stronger property -- it holds for every name, not one.
    """

    @pytest.mark.parametrize(
        ("family", "address"), [(2, "127.0.0.1"), (10, "::1"), (2, "127.0.0.53")]
    )
    def test_localhost_is_refused_however_it_resolves(self, monkeypatch, family, address):
        from external_integrations.netpolicy import (
            DestinationRefused,
            ErrorCode,
            resolve_destination,
        )

        _resolving_to(monkeypatch, [(family, address)])
        with pytest.raises(DestinationRefused) as excinfo:
            resolve_destination("https://localhost/")
        assert excinfo.value.code == ErrorCode.DNS_BLOCKED

    def test_a_public_name_that_also_answers_loopback_is_refused(self, monkeypatch):
        """One prohibited answer refuses the destination. Picking the public
        answer out of a mixed set would be agreeing to run the rebinding
        race."""
        from external_integrations.netpolicy import DestinationRefused, resolve_destination

        _resolving_to(monkeypatch, [(2, "93.184.216.34"), (2, "127.0.0.1")])
        with pytest.raises(DestinationRefused):
            resolve_destination("https://rebind.invalid/")

    def test_the_refusal_never_names_the_address_it_resolved_to(self, monkeypatch):
        """An error string is a side channel, and "which internal address does
        this name point at" is the question the module exists to stop the
        caller answering."""
        from external_integrations.netpolicy import DestinationRefused, resolve_destination

        _resolving_to(monkeypatch, [(2, "10.11.12.13")])
        with pytest.raises(DestinationRefused) as excinfo:
            resolve_destination("https://internal.invalid/")
        assert "10.11.12.13" not in str(excinfo.value)

    def test_a_public_answer_is_still_allowed(self, monkeypatch):
        """The complement. Without it, every test above would also pass on a
        module that refused everything."""
        from external_integrations.netpolicy import resolve_destination

        _resolving_to(monkeypatch, [(2, "93.184.216.34")])
        destination = resolve_destination("https://example.invalid/x")
        assert destination.address == "93.184.216.34"
        assert destination.hostname == "example.invalid"
        assert destination.port == 443


class TestLinkLocalByName:
    @pytest.mark.parametrize(
        ("family", "address"),
        [
            (2, "169.254.0.1"),
            (2, "169.254.169.254"),  # the cloud metadata endpoint
            (10, "fe80::1"),
        ],
    )
    def test_a_name_resolving_to_link_local_is_refused(self, monkeypatch, family, address):
        from external_integrations.netpolicy import (
            DestinationRefused,
            ErrorCode,
            resolve_destination,
        )

        _resolving_to(monkeypatch, [(family, address)])
        with pytest.raises(DestinationRefused) as excinfo:
            resolve_destination("https://metadata.invalid/latest/meta-data/")
        assert excinfo.value.code == ErrorCode.DNS_BLOCKED


# ===========================================================================
# 5. Hostname normalization
# ===========================================================================
class TestHostnameNormalization:
    """Asserted on the hostname `validate_url` returns, because that value is
    what gets resolved and what the `Host` header later carries."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://EXAMPLE.INVALID/x",
            "https://Example.Invalid/x",
            "https://example.invalid./x",
            "https://EXAMPLE.INVALID./x",
        ],
    )
    def test_spellings_of_one_name_normalize_to_that_name(self, url):
        from external_integrations.netpolicy import validate_url

        _scheme, hostname, _port, _path = validate_url(url)
        assert hostname == "example.invalid"

    def test_normalization_does_not_widen_what_is_accepted(self):
        """The trailing dot is stripped from a loopback name too, so the
        stripping itself cannot be used to dodge a later check."""
        from external_integrations.netpolicy import validate_url

        _scheme, hostname, _port, _path = validate_url("https://LOCALHOST./")
        assert hostname == "localhost"

    def test_credentials_in_the_url_are_refused(self):
        from external_integrations.netpolicy import DestinationRefused, ErrorCode, validate_url

        with pytest.raises(DestinationRefused) as excinfo:
            validate_url("https://user:pass@example.invalid/")
        assert excinfo.value.code == ErrorCode.CREDENTIALS_IN_URL

    @pytest.mark.parametrize(
        "url",
        [
            "https://2130706433/",  # 127.0.0.1 written as an integer
            "https://0x7f000001/",  # ... as hex
            "https://0177.0.0.1/",  # ... as dotted octal
            "https://[::ffff:127.0.0.1]/",  # ... as an IPv4-mapped IPv6 literal
        ],
    )
    def test_numeric_spellings_of_loopback_are_refused_before_dns(self, url):
        from external_integrations.netpolicy import DestinationRefused, ErrorCode, validate_url

        with pytest.raises(DestinationRefused) as excinfo:
            validate_url(url)
        assert excinfo.value.code == ErrorCode.DNS_BLOCKED

    @pytest.mark.parametrize(
        "url",
        [
            "https://exa mple.invalid/",
            "https://example.invalid\n/",
            "https://example.invalid\r\nHost: evil.invalid/",
            "https://example.invalid\t/",
        ],
    )
    def test_whitespace_and_control_characters_are_refused(self, url):
        from external_integrations.netpolicy import DestinationRefused, ErrorCode, validate_url

        with pytest.raises(DestinationRefused) as excinfo:
            validate_url(url)
        assert excinfo.value.code == ErrorCode.URL_INVALID


# ===========================================================================
# 6. A refused redirect makes no second request
# ===========================================================================
@pytest.mark.django_db
class TestARefusedRedirectCarriesNothingOnward:
    """Redirects are refused, not followed. That is what makes credential
    leakage across a redirect impossible rather than merely unobserved: there
    is no second request for the `Authorization` header to travel on, and the
    redirect target is never resolved or contacted.

    These assert the consequence at the operation level.
    `test_transport_socket.test_a_redirect_is_not_followed` already covers the
    socket-level refusal against a real loopback server, so that is not
    repeated. Nothing here implements or asks for redirect following.
    """

    def _redirect(self, fake_remote, status):
        from external_integrations.transport import TransportError, TransportErrorCode

        fake_remote.raises = TransportError(TransportErrorCode.REDIRECT_REFUSED, http_status=status)

    @pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
    def test_a_redirect_produces_exactly_one_request(
        self, tenant_a, admin_a, active_connector, connector_secret, fake_remote, status
    ):
        self._redirect(fake_remote, status)
        execution = _run(_queued_import(tenant_a, admin_a, active_connector), tenant_a)

        assert len(fake_remote.calls) == 1
        assert execution.status == ExecutionStatus.FAILED
        assert execution.error_code == "REDIRECT_REFUSED"

    def test_the_credential_went_to_the_configured_host_and_nowhere_else(
        self, tenant_a, admin_a, active_connector, connector_secret, fake_remote
    ):
        """The one request must actually have carried the credential --
        otherwise "no second request carried it" would also be true of a test
        that never authenticated at all."""
        self._redirect(fake_remote, 302)
        _run(_queued_import(tenant_a, admin_a, active_connector), tenant_a)

        (call,) = fake_remote.calls
        assert call.headers["Authorization"] == f"Bearer {SECRET}"
        assert call.url.startswith(BASE_CONFIG["base_url"].rstrip("/") + "/regx/")

    def test_the_refusal_is_not_retried(
        self, tenant_a, admin_a, active_connector, connector_secret, fake_remote
    ):
        """A redirect is a deterministic answer, so repeating the request would
        only repeat the redirect."""
        self._redirect(fake_remote, 301)
        execution = _run(_queued_import(tenant_a, admin_a, active_connector), tenant_a)

        assert execution.attempt_count == 1

    def test_nothing_about_the_redirect_target_is_stored_or_audited(
        self, tenant_a, admin_a, active_connector, connector_secret, fake_remote
    ):
        """A `Location` header is remote input naming a destination policy never
        approved. It is not stored, so it cannot later be read back as though
        somebody had approved it."""
        self._redirect(fake_remote, 302)
        execution = _run(_queued_import(tenant_a, admin_a, active_connector), tenant_a)

        blob = str(
            {
                "request": execution.request_summary,
                "response": execution.response_summary,
                "error": execution.error_code,
                "reference": execution.external_reference,
                "audit": [event.payload for event in _events(EXECUTION_FAILED)],
            }
        )
        assert "location" not in blob.lower()
        assert SECRET not in blob
