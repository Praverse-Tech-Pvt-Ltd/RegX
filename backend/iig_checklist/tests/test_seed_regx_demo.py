"""Tests for the seed_regx_demo management command.

The command exists to make the IIG checklist engine executable from a clean
install, so these tests assert the two gates in `create_execution` are actually
open afterwards -- not merely that rows were written.

Every test starts from pytest's empty database, which is the clean-install case
the command is written for.
"""

import io

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

pytestmark = pytest.mark.django_db


def _seed(**kwargs):
    out = io.StringIO()
    call_command("seed_regx_demo", stdout=out, **kwargs)
    return out.getvalue()


class TestSeedOnCleanDatabase:
    def test_seed_succeeds_on_empty_database(self):
        output = _seed()
        assert "Demo environment ready." in output

    def test_creates_demo_tenant(self):
        from tenancy.models import Tenant

        _seed()
        tenant = Tenant.objects.get(slug="demo")
        assert "DEMO-" in tenant.name

    def test_creates_the_four_role_accounts(self):
        from authorization.models import MembershipRole
        from identity.models import User

        _seed()
        emails = set(
            User.objects.filter(email__endswith="demo.regx.invalid").values_list("email", flat=True)
        )
        assert emails == {
            "doer@demo.regx.invalid",
            "reviewer@demo.regx.invalid",
            "vp@demo.regx.invalid",
            "tenant_admin@demo.regx.invalid",
        }
        roles = set(
            MembershipRole.objects.filter(
                membership__user__email__endswith="demo.regx.invalid"
            ).values_list("role__name", flat=True)
        )
        assert roles == {"doer", "reviewer", "vp", "tenant_admin"}

    def test_demo_accounts_are_not_given_a_production_domain(self):
        """`.invalid` is reserved and never resolves, so a demo account cannot
        be mistaken for, or mailed as, a real one."""
        from identity.models import User

        _seed()
        for email in User.objects.filter(email__endswith="demo.regx.invalid").values_list(
            "email", flat=True
        ):
            assert email.endswith(".invalid")


class TestGatesAreOpened:
    """The point of the command: both `create_execution` gates must be open."""

    def test_checklist_version_reaches_active(self):
        from iig_checklist.models import ChecklistVersion

        _seed()
        version = ChecklistVersion.objects.get(definition__code="DEMO-EXCIPIENT-REVIEW")
        assert version.status == "active"

    def test_activation_went_through_the_real_lifecycle(self):
        """Each transition emits an audit event. Their presence is what
        distinguishes a governed activation from writing `status` directly."""
        from audit.models import AuditEvent

        _seed()
        written = set(AuditEvent.objects.values_list("event_type", flat=True))
        assert "iig_checklist.version.submitted_for_review" in written
        assert "iig_checklist.version.approved" in written
        assert "iig_checklist.version.activated" in written

    def test_formulation_version_is_approved(self):
        from formulations.models import FormulationVersion

        _seed()
        fv = FormulationVersion.objects.get(product__product_code="DEMO-TAB-100")
        assert fv.status == "approved"

    def test_sample_execution_exists_with_response_slots(self):
        from iig_checklist.models import ChecklistExecution

        _seed()
        execution = ChecklistExecution.objects.get(
            checklist_version__definition__code="DEMO-EXCIPIENT-REVIEW"
        )
        assert execution.responses.count() == 3

    def test_a_further_execution_can_be_created_through_the_service(self):
        """The seeded execution proves the gates opened once. This proves they
        stay open for work a user does afterwards."""
        from formulations.models import FormulationVersion
        from identity.models import User
        from iig_checklist.models import ChecklistExecution, ChecklistVersion
        from iig_checklist.services import create_execution
        from tenancy.models import Tenant

        _seed()
        tenant = Tenant.objects.get(slug="demo")
        version = ChecklistVersion.objects.get(definition__code="DEMO-EXCIPIENT-REVIEW")
        fv = FormulationVersion.objects.get(product__product_code="DEMO-TAB-100")
        doer = User.objects.get(email="doer@demo.regx.invalid")

        # The domain forbids two active executions for one combination, so the
        # seeded one is cancelled first -- through the real transition.
        from iig_checklist.services import transition_execution

        seeded = ChecklistExecution.objects.get(checklist_version=version)
        transition_execution(
            execution=seeded, action="cancel", actor=doer, tenant=tenant, reason="test"
        )

        fresh = create_execution(
            tenant=tenant,
            checklist_version_public_id=str(version.public_id),
            formulation_version_public_id=str(fv.public_id),
            actor=doer,
        )
        assert fresh.status == "draft"


class TestIdempotency:
    def test_second_run_creates_nothing(self):
        second = _seed()
        second = _seed()
        assert "Already seeded; nothing to create." in second

    def test_object_counts_are_stable_across_runs(self):
        from formulations.models import FormulationVersion
        from identity.models import User
        from iig_checklist.models import (
            ChecklistDefinition,
            ChecklistExecution,
            ChecklistQuestion,
            ChecklistVersion,
        )
        from tenancy.models import Tenant, TenantMembership

        def counts():
            return (
                Tenant.objects.filter(slug="demo").count(),
                User.objects.filter(email__endswith="demo.regx.invalid").count(),
                TenantMembership.objects.filter(tenant__slug="demo").count(),
                ChecklistDefinition.objects.filter(tenant__slug="demo").count(),
                ChecklistVersion.objects.filter(definition__tenant__slug="demo").count(),
                ChecklistQuestion.objects.filter(
                    section__checklist_version__definition__tenant__slug="demo"
                ).count(),
                FormulationVersion.objects.filter(product__tenant__slug="demo").count(),
                ChecklistExecution.objects.filter(
                    checklist_version__definition__tenant__slug="demo"
                ).count(),
            )

        _seed()
        first = counts()
        _seed()
        _seed()
        assert counts() == first
        assert first == (1, 4, 4, 1, 1, 3, 1, 1)

    def test_rerun_does_not_re_activate_an_active_version(self):
        """A second run must not push the already-active version back through
        the lifecycle, which would emit duplicate governed audit events."""
        from audit.models import AuditEvent

        _seed()
        first = AuditEvent.objects.filter(event_type="iig_checklist.version.activated").count()
        _seed()
        assert (
            AuditEvent.objects.filter(event_type="iig_checklist.version.activated").count() == first
        )


class TestDryRun:
    def test_dry_run_writes_nothing(self):
        from tenancy.models import Tenant

        output = _seed(dry_run=True)
        assert "Nothing was written." in output
        assert not Tenant.objects.filter(slug="demo").exists()


class TestCredentialHandling:
    def test_password_can_come_from_an_environment_variable(self, monkeypatch):
        from identity.models import User

        monkeypatch.setenv("SEED_DEMO_PW", "FromTheEnvironment#1")
        _seed(password_env="SEED_DEMO_PW")
        user = User.objects.get(email="doer@demo.regx.invalid")
        assert user.check_password("FromTheEnvironment#1")

    def test_missing_environment_variable_is_an_error(self, monkeypatch):
        monkeypatch.delenv("SEED_DEMO_PW", raising=False)
        with pytest.raises(CommandError, match="unset or empty"):
            _seed(password_env="SEED_DEMO_PW")

    def test_password_and_password_env_are_mutually_exclusive(self):
        with pytest.raises(CommandError, match="not both"):
            _seed(password="x", password_env="SEED_DEMO_PW")


class TestDoesNotTouchPlatformContent:
    def test_only_the_demo_definition_is_created(self):
        """The six platform checklist definitions are regulatory content.
        Activating them here would silently promote unreviewed material."""
        from iig_checklist.models import ChecklistDefinition

        _seed()
        created = ChecklistDefinition.objects.all()
        assert created.count() == 1
        assert created.first().code.startswith("DEMO-")

    def test_seeded_definition_is_tenant_scoped_not_platform_master(self):
        from iig_checklist.models import ChecklistDefinition

        _seed()
        definition = ChecklistDefinition.objects.get(code="DEMO-EXCIPIENT-REVIEW")
        assert definition.scope_type == "tenant"
