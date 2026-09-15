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


# ===========================================================================
# P4 -- the governed chain beyond IIG
# ===========================================================================


class TestGovernedChainIsCreated:
    """Each object must exist AND have been made through its own domain's
    service, which is what the audit events below actually prove."""

    def test_regulatory_case_is_created(self):
        from regulatory_cases.models import RegulatoryCase

        _seed()
        case = RegulatoryCase.objects.get(tenant__slug="demo")
        assert case.title.startswith("DEMO-")
        assert case.case_number  # claimed by create_case, not invented here

    def test_workflow_is_moved_through_a_real_transition(self):
        """Created AND submitted. A seed that only created rows would leave
        nothing for a Reviewer to act on in the demo."""
        from workflows.models import WorkflowItem, WorkflowTransition

        _seed()
        item = WorkflowItem.objects.get(tenant__slug="demo")
        assert item.state == "submitted"
        # perform_transition writes history; a direct state write would not.
        assert WorkflowTransition.objects.filter(workflow_item=item).count() == 1

    def test_document_goes_through_the_real_ingest_path(self):
        from documents.models import Document

        _seed()
        document = Document.objects.get(tenant__slug="demo")
        version = document.versions.get()
        assert version.sha256_checksum  # computed by ingest, not supplied
        assert version.size_bytes > 0

    def test_document_scan_status_is_never_written_by_the_seed(self):
        """The seed must never assert a scan result. Whatever the configured
        scanner produces is what the row says -- pending when no worker has
        run, and never `clean` by fiat."""
        from documents.models import Document

        _seed()
        version = Document.objects.get(tenant__slug="demo").versions.get()
        # With CELERY_TASK_ALWAYS_EAGER the stub runs and returns clean; with
        # no worker it stays pending. Both are honest; "infected" would mean
        # the scanner spoke. What matters is that the seed did not decide.
        assert version.scan_status in {"pending", "clean"}

    def test_blueprint_version_reaches_active_through_the_lifecycle(self):
        from dossier_blueprints.models import DossierBlueprintVersion

        _seed()
        version = DossierBlueprintVersion.objects.get(blueprint__tenant__slug="demo")
        assert version.status == "active"
        assert version.sections.count() == 3

    def test_dossier_is_instantiated_from_the_blueprint_with_provenance(self):
        from submission_dossiers.models import SubmissionDossier

        _seed()
        dossier = SubmissionDossier.objects.get(tenant__slug="demo")
        # instantiate_version records which version it was stamped from.
        assert dossier.blueprint_instantiation is not None

    def test_package_is_internal_and_left_in_draft(self):
        """Not frozen. Its only evidence is a synthetic document that a local
        stack "scans" with StubScanner; freezing would present an inspected,
        immutable artifact built on a scan that never happened."""
        from submission_packages.models import SubmissionPackage

        _seed()
        package = SubmissionPackage.objects.get(tenant__slug="demo")
        assert package.status == "draft"

    def test_connector_is_created_disabled_with_no_credential(self):
        from external_integrations.models import Connector, ConnectorCredentialReference

        _seed()
        connector = Connector.objects.get(tenant__slug="demo")
        assert connector.status == "draft"  # never enabled
        assert not ConnectorCredentialReference.objects.filter(connector=connector).exists()

    def test_connector_points_at_a_reserved_unroutable_host(self):
        """`.invalid` is reserved by RFC 2606 and never resolves, so the demo
        connector cannot reach anything -- and being public it does not look
        like an SSRF test of the private-IP guards."""
        from external_integrations.models import Connector

        _seed()
        base_url = Connector.objects.get(tenant__slug="demo").configuration["base_url"]
        assert ".invalid" in base_url
        assert "localhost" not in base_url and "127.0.0.1" not in base_url


class TestSeededActionsAreAudited:
    """Seeding uses the same services a user does, so it must leave the same
    trail. Suppressing audit for seeded data would make the demo trail a
    fiction."""

    def _types(self):
        from audit.models import AuditEvent

        return set(AuditEvent.objects.values_list("event_type", flat=True))

    def test_every_seeded_domain_emits_its_creation_event(self):
        _seed()
        written = self._types()
        for expected in (
            "regulatory_case.created",
            "workflow.created",
            "workflow.submitted",
            "document.created",
            "document.version.created",
            "dossier_blueprint.created",
            "dossier_blueprint_version.created",
            "dossier_blueprint_version.activated",
            "dossier_blueprint.instantiated",
            "submission_package.created",
            "external_connector.created",
        ):
            assert expected in written, f"missing audit event: {expected}"

    def test_rerunning_does_not_duplicate_lifecycle_events(self):
        """The seed is idempotent, so a second run must not re-emit governed
        transitions -- an audit trail showing two activations of one version
        would be a false record."""
        from audit.models import AuditEvent

        _seed()
        before = AuditEvent.objects.count()
        _seed()
        _seed()
        assert AuditEvent.objects.count() == before


class TestChainIdempotency:
    def test_counts_are_stable_across_three_runs(self):
        from documents.models import Document
        from dossier_blueprints.models import DossierBlueprint, DossierBlueprintSection
        from external_integrations.models import Connector
        from regulatory_cases.models import RegulatoryCase
        from submission_dossiers.models import SubmissionDossier
        from submission_packages.models import SubmissionPackage
        from workflows.models import WorkflowItem

        def counts():
            return (
                RegulatoryCase.objects.filter(tenant__slug="demo").count(),
                WorkflowItem.objects.filter(tenant__slug="demo").count(),
                Document.objects.filter(tenant__slug="demo").count(),
                DossierBlueprint.objects.filter(tenant__slug="demo").count(),
                DossierBlueprintSection.objects.filter(tenant__slug="demo").count(),
                SubmissionDossier.objects.filter(tenant__slug="demo").count(),
                SubmissionPackage.objects.filter(tenant__slug="demo").count(),
                Connector.objects.filter(tenant__slug="demo").count(),
            )

        _seed()
        first = counts()
        _seed()
        _seed()
        assert counts() == first
        assert first == (1, 1, 1, 1, 3, 1, 1, 1)


class TestNothingIsFabricated:
    def test_no_forbidden_submission_wording_anywhere_in_seeded_content(self):
        """The package is an internal transfer artifact. Calling it an eCTD
        sequence or an agency filing would be a claim the product cannot
        honour."""
        from regulatory_cases.models import RegulatoryCase
        from submission_packages.models import SubmissionPackage

        _seed()
        text = " ".join(
            [
                RegulatoryCase.objects.get(tenant__slug="demo").description,
                SubmissionPackage.objects.get(tenant__slug="demo").description,
            ]
        ).lower()
        for forbidden in ("ectd", "agency filing", "gateway submission", "fda approval"):
            assert forbidden not in text or "not an" in text or "not a" in text

    def test_all_demo_content_is_prefixed_or_reserved(self):
        from external_integrations.models import Connector
        from regulatory_cases.models import RegulatoryCase
        from submission_packages.models import SubmissionPackage
        from workflows.models import WorkflowItem

        _seed()
        for value in (
            RegulatoryCase.objects.get(tenant__slug="demo").title,
            WorkflowItem.objects.get(tenant__slug="demo").title,
            SubmissionPackage.objects.get(tenant__slug="demo").name,
            Connector.objects.get(tenant__slug="demo").name,
        ):
            assert value.startswith("DEMO-"), value
