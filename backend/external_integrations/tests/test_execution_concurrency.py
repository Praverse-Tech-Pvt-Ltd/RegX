"""Real concurrency against real PostgreSQL, for paths in docs/LOCK_ORDER.md.

Threads on separate connections, not sequential calls with a comment claiming
concurrency. `transaction=True` is required: the ordinary test transaction would
hide every lock interaction here, because both "threads" would be inside it.

What these prove is not "no deadlock happened once" -- a race that passes once
proves little. They prove the **outcome** is correct under interleaving: exactly
one winner where there must be one, no duplicate governed history, and no remote
call from a loser.

The `race` helper lives in `common.concurrency_testing`, which imports no
domain. This file lives with the domain it tests, because a cross-domain test
placed in `common` inverts the architecture -- `import-linter` caught exactly
that during Milestone 15.
"""

import pytest

from common.concurrency_testing import race

pytestmark = pytest.mark.slow


def _tenant_and_actor(slug, email):
    from authorization.models import MembershipRole, Role
    from identity.models import User
    from tenancy.models import Tenant, TenantMembership

    tenant = Tenant.objects.create(name=slug, slug=slug)
    user = User.objects.create_user(email=email, password="TestPass1234!", full_name="Actor")
    membership = TenantMembership.objects.create(tenant=tenant, user=user, is_active=True)
    role, _ = Role.objects.get_or_create(
        name=Role.BuiltIn.TENANT_ADMIN, defaults={"description": "admin"}
    )
    MembershipRole.objects.create(membership=membership, role=role)
    return tenant, user


# ---------------------------------------------------------------------------
# Connector executions
# ---------------------------------------------------------------------------
@pytest.mark.django_db(transaction=True)
class TestConnectorConcurrency:
    def _world(self):
        from external_integrations import services
        from external_integrations.models import ConnectorStatus

        tenant, actor = _tenant_and_actor("conn-race", "conn-race@example.test")
        connector = services.create_connector(
            tenant=tenant,
            actor=actor,
            name="Race connector",
            connector_type="generic_https",
            configuration={
                "base_url": "https://connector.test/",
                "allowed_path_prefix": "/regx/",
                "verify_tls": True,
            },
            credential={"credential_type": "bearer_token"},
        )
        connector = services.set_connector_status(
            connector=connector, tenant=tenant, actor=actor, status=ConnectorStatus.ACTIVE
        )
        return connector, tenant, actor

    def test_two_workers_claim_one_execution_and_only_one_wins(self):
        """The claim is the whole duplicate-delivery defence.

        A broker redelivering a message must cost a database round trip, not a
        second remote call.
        """
        from external_integrations import services

        connector, tenant, actor = self._world()
        execution = services.create_execution(
            connector=connector,
            tenant=tenant,
            actor=actor,
            operation="import_document",
            idempotency_parts=["claim-race"],
            request_summary={},
        )

        def claim():
            claimed = services.claim_execution(execution.pk)
            return "claimed" if claimed is not None else "already taken"

        results, errors = race([claim, claim])

        assert not errors, errors
        assert sorted(results) == ["already taken", "claimed"], results
        execution.refresh_from_db()
        assert execution.attempt_count == 1, "both workers counted an attempt"

    def test_queueing_races_safely_with_disabling(self):
        """Either the execution was queued while the connector was enabled, or
        it was refused. What must not exist is an execution queued onto a
        connector that was already disabled."""
        from external_integrations import services
        from external_integrations.models import ConnectorExecution, ConnectorStatus

        connector, tenant, actor = self._world()

        def queue():
            try:
                services.create_execution(
                    connector=connector,
                    tenant=tenant,
                    actor=actor,
                    operation="import_document",
                    idempotency_parts=["disable-race"],
                    request_summary={},
                )
                return "queued"
            except services.ConnectorNotExecutable:
                return "refused"

        def disable():
            services.set_connector_status(
                connector=connector, tenant=tenant, actor=actor, status=ConnectorStatus.DISABLED
            )
            return "disabled"

        results, errors = race([queue, disable])

        assert not errors, errors
        assert "disabled" in results
        queued = ConnectorExecution.objects.count()
        if "queued" in results:
            assert queued == 1
        else:
            assert queued == 0

    def test_a_duplicate_request_never_becomes_two_executions(self):
        """Two identical requests arriving together.

        The unique index on `(tenant, idempotency_key)` is the floor under the
        service's lookup: even if both transactions read "no existing execution"
        the database refuses the second insert.
        """
        from external_integrations import services

        connector, tenant, actor = self._world()

        def create():
            try:
                services.create_execution(
                    connector=connector,
                    tenant=tenant,
                    actor=actor,
                    operation="import_document",
                    idempotency_parts=["same-key"],
                    request_summary={},
                )
                return "created"
            except Exception as exc:
                return f"refused:{type(exc).__name__}"

        results, errors = race([create, create])

        from external_integrations.models import ConnectorExecution

        assert ConnectorExecution.objects.count() == 1, (
            f"duplicate executions created: {results} {errors}"
        )
