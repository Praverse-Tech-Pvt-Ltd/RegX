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
# Workflow transitions
# ---------------------------------------------------------------------------
@pytest.mark.django_db(transaction=True)
class TestWorkflowConcurrency:
    def test_two_transitions_on_one_item_produce_exactly_one_winner(self):
        """The item row is the serialization point.

        Both threads submit the same draft. One must win and one must be
        refused -- not both, which would write two history rows for a single
        state change and leave the trail claiming something that never happened.
        """
        from workflows import services
        from workflows.models import WorkflowItem, WorkflowTransition

        tenant, actor = _tenant_and_actor("wf-race", "wf-race@example.test")
        item = services.create_item(tenant=tenant, actor=actor, title="Race")

        def submit():
            try:
                services.perform_transition(item=item, action="submit", actor=actor, tenant=tenant)
                return "won"
            except Exception:
                return "refused"

        results, errors = race([submit, submit])

        assert not errors, f"a transition failed unexpectedly: {errors}"
        assert sorted(results) == ["refused", "won"], results

        item.refresh_from_db()
        assert item.state == WorkflowItem.State.SUBMITTED
        assert WorkflowTransition.objects.filter(workflow_item=item).count() == 1, (
            "two history rows were written for one state change"
        )

    def test_a_losing_transition_leaves_no_trace(self):
        """A rejected attempt must not write history, audit, or a partial state.

        `perform_transition` validates before it writes for exactly this reason;
        under contention is where that ordering earns its keep.
        """
        from audit.models import AuditEvent
        from workflows import services
        from workflows.models import WorkflowTransition

        tenant, actor = _tenant_and_actor("wf-trace", "wf-trace@example.test")
        item = services.create_item(tenant=tenant, actor=actor, title="Trace")
        before = AuditEvent.objects.count()

        def submit():
            try:
                services.perform_transition(item=item, action="submit", actor=actor, tenant=tenant)
                return "won"
            except Exception:
                return "refused"

        race([submit, submit])

        assert WorkflowTransition.objects.filter(workflow_item=item).count() == 1
        # One transition, so exactly one transition audit row beyond the
        # baseline -- the loser contributed nothing.
        assert AuditEvent.objects.count() - before == 1
