"""The two MAJOR findings from independent review of PR #36.

MAJOR 1 -- linking required only `regulatory_cases.manage_links`, so the
endpoint was an existence oracle: link a same-tenant UUID the caller may not
see, and success said it exists while an error said it does not.

MAJOR 2 -- the manager blocked queryset paths and `Model.delete()`, but a plain
`instance.save()` never passes through the manager, so a governed link could be
repointed, moved between cases or tenants, or have its provenance rewritten
outside the service layer and without audit.

Both are release-blocking. Synthetic data only.
"""

import uuid

import pytest
from django.db import InternalError, ProgrammingError, connection, transaction
from django.utils import timezone

from regulatory_cases import services
from regulatory_cases.models import (
    RegulatoryCaseChecklist,
    RegulatoryCaseDocument,
    RegulatoryCaseWorkflow,
)

BASE = "/api/regx/v1/regulatory-cases/"


def _url(case, suffix=""):
    return f"{BASE}{case.public_id}/{suffix}"


# ---------------------------------------------------------------------------
# MAJOR 1 -- target module authorization
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestTargetModuleAuthorization:
    """`manage_links` alone must not be enough to link anything."""

    # -- documents ---------------------------------------------------------
    def test_document_link_requires_document_permission(
        self, case_a, document_a, support_a, tenant_a
    ):
        """PLATFORM_SUPPORT has documents [] -- linking must fail closed even
        though the document exists in the same tenant."""
        from regulatory_cases.projection import can_view_documents

        assert can_view_documents(support_a, tenant_a) is False
        with pytest.raises(services.InvalidLinkTarget):
            services.link_target(
                kind="document",
                case=case_a,
                target_public_id=document_a.public_id,
                actor=support_a,
                tenant=tenant_a,
            )
        assert RegulatoryCaseDocument.objects.count() == 0

    def test_document_link_succeeds_with_permission(self, case_a, document_a, doer_a, tenant_a):
        link = services.link_target(
            kind="document",
            case=case_a,
            target_public_id=document_a.public_id,
            actor=doer_a,
            tenant=tenant_a,
        )
        assert link.is_active

    # -- workflows ---------------------------------------------------------
    def test_workflow_link_requires_workflow_permission(
        self, case_a, workflow_a, outsider, tenant_a
    ):
        """No built-in role separates cases from workflows, so the caller with
        no membership is what proves the gate -- the check keys on the
        permission helper, not on a role name."""
        from regulatory_cases.projection import can_view_workflows

        assert can_view_workflows(outsider, tenant_a) is False
        with pytest.raises(services.InvalidLinkTarget):
            services.link_target(
                kind="workflow",
                case=case_a,
                target_public_id=workflow_a.public_id,
                actor=outsider,
                tenant=tenant_a,
            )
        assert RegulatoryCaseWorkflow.objects.count() == 0

    def test_workflow_link_succeeds_with_permission(self, case_a, workflow_a, doer_a, tenant_a):
        link = services.link_target(
            kind="workflow",
            case=case_a,
            target_public_id=workflow_a.public_id,
            actor=doer_a,
            tenant=tenant_a,
        )
        assert link.is_active

    # -- checklists --------------------------------------------------------
    def test_checklist_link_requires_checklist_permission(
        self, case_a, checklist_a, support_a, tenant_a
    ):
        from regulatory_cases.projection import can_view_checklists

        assert can_view_checklists(support_a, tenant_a) is False
        with pytest.raises(services.InvalidLinkTarget):
            services.link_target(
                kind="checklist",
                case=case_a,
                target_public_id=checklist_a.public_id,
                actor=support_a,
                tenant=tenant_a,
            )
        assert RegulatoryCaseChecklist.objects.count() == 0

    def test_checklist_link_succeeds_with_permission(self, case_a, checklist_a, doer_a, tenant_a):
        link = services.link_target(
            kind="checklist",
            case=case_a,
            target_public_id=checklist_a.public_id,
            actor=doer_a,
            tenant=tenant_a,
        )
        assert link.is_active

    # -- the oracle itself -------------------------------------------------
    def test_unauthorized_absent_and_cross_tenant_are_one_outcome(
        self, case_a, document_a, document_b, support_a, doer_a, tenant_a
    ):
        """The three failures must be a single indistinguishable result.

        If they differed, a caller holding only `manage_links` could ask "does
        this UUID exist in my tenant?" and read the answer off the error.
        """
        errors = []

        # (a) exists, same tenant, caller lacks the document permission
        with pytest.raises(services.InvalidLinkTarget) as e1:
            services.link_target(
                kind="document",
                case=case_a,
                target_public_id=document_a.public_id,
                actor=support_a,
                tenant=tenant_a,
            )
        errors.append(str(e1.value))

        # (b) authorized caller, target does not exist
        with pytest.raises(services.InvalidLinkTarget) as e2:
            services.link_target(
                kind="document",
                case=case_a,
                target_public_id=uuid.uuid4(),
                actor=doer_a,
                tenant=tenant_a,
            )
        errors.append(str(e2.value))

        # (c) authorized caller, target belongs to another tenant
        with pytest.raises(services.InvalidLinkTarget) as e3:
            services.link_target(
                kind="document",
                case=case_a,
                target_public_id=document_b.public_id,
                actor=doer_a,
                tenant=tenant_a,
            )
        errors.append(str(e3.value))

        assert len(set(errors)) == 1, f"failure messages differ: {errors}"

    def test_api_responses_are_indistinguishable(
        self, client_support_a, client_doer_a, case_a, document_a, document_b
    ):
        """Same check at the HTTP boundary, which is what an attacker sees."""
        unauthorized = client_support_a.post(
            _url(case_a, "documents/"),
            {"target_public_id": str(document_a.public_id)},
            format="json",
        )
        absent = client_doer_a.post(
            _url(case_a, "documents/"),
            {"target_public_id": str(uuid.uuid4())},
            format="json",
        )
        cross = client_doer_a.post(
            _url(case_a, "documents/"),
            {"target_public_id": str(document_b.public_id)},
            format="json",
        )

        # PLATFORM_SUPPORT lacks manage_links, so it is stopped one gate
        # earlier -- 403 rather than 400. What must match is the pair that a
        # caller WITH manage_links can actually distinguish.
        assert absent.status_code == cross.status_code == 400
        assert str(absent.data["target_public_id"]) == str(cross.data["target_public_id"])
        assert unauthorized.status_code in (400, 403)

    def test_failed_link_emits_no_audit_event(self, case_a, document_a, support_a, tenant_a):
        """A refused link must leave no trace suggesting it happened."""
        from audit.models import AuditEvent

        before = AuditEvent.objects.filter(resource_id=str(case_a.public_id)).count()
        with pytest.raises(services.InvalidLinkTarget):
            services.link_target(
                kind="document",
                case=case_a,
                target_public_id=document_a.public_id,
                actor=support_a,
                tenant=tenant_a,
            )
        after = AuditEvent.objects.filter(resource_id=str(case_a.public_id))
        assert after.count() == before
        assert not after.filter(event_type="regulatory_case.document_linked").exists()


# ---------------------------------------------------------------------------
# MAJOR 2 -- database-level immutability
# ---------------------------------------------------------------------------
LINK_CASES = [
    ("workflow", "workflow_a", "workflow_item", RegulatoryCaseWorkflow),
    ("document", "document_a", "document", RegulatoryCaseDocument),
    ("checklist", "checklist_a", "checklist_execution", RegulatoryCaseChecklist),
]


@pytest.mark.django_db
class TestLinkDatabaseImmutability:
    """The ORM guards prove the manager refuses. These prove the DATABASE
    refuses, which is what matters when `instance.save()` never touches the
    manager at all."""

    def _link(self, kind, case, target, actor, tenant):
        return services.link_target(
            kind=kind,
            case=case,
            target_public_id=target.public_id,
            actor=actor,
            tenant=tenant,
        )

    @pytest.mark.parametrize("kind,fixture,field,model", LINK_CASES)
    def test_target_swap_via_save_is_rejected(
        self, request, case_a, doer_a, tenant_a, kind, fixture, field, model
    ):
        """THE finding: `link.document = other; link.save()` bypassed everything."""
        target = request.getfixturevalue(fixture)
        link = self._link(kind, case_a, target, doer_a, tenant_a)

        # A second target of the same kind, in the same tenant.
        if kind == "workflow":
            from workflows.models import WorkflowItem

            other = WorkflowItem.objects.create(tenant=tenant_a, title="Other", created_by=doer_a)
        elif kind == "document":
            from documents.models import Document

            other = Document.objects.create(
                tenant=tenant_a, title="Other doc", document_type="other"
            )
        else:
            from regulatory_cases.tests.conftest import _checklist_execution

            other = _checklist_execution(tenant_a, doer_a)

        setattr(link, field, other)
        with pytest.raises((InternalError, ProgrammingError)) as exc:
            with transaction.atomic():
                link.save()
        assert "immutable" in str(exc.value).lower()

        link.refresh_from_db()
        assert getattr(link, f"{field}_id") == target.pk

    @pytest.mark.parametrize("kind,fixture,field,model", LINK_CASES)
    def test_case_swap_is_rejected(
        self, request, case_a, tenant_a, doer_a, kind, fixture, field, model
    ):
        target = request.getfixturevalue(fixture)
        link = self._link(kind, case_a, target, doer_a, tenant_a)
        other_case = services.create_case(
            tenant=tenant_a,
            actor=doer_a,
            title="Other case",
            product_name="P",
            market="M",
            submission_type="S",
        )
        link.case = other_case
        with pytest.raises((InternalError, ProgrammingError)):
            with transaction.atomic():
                link.save()
        link.refresh_from_db()
        assert link.case_id == case_a.pk

    @pytest.mark.parametrize("kind,fixture,field,model", LINK_CASES)
    def test_tenant_swap_is_rejected(
        self, request, case_a, tenant_a, tenant_b, doer_a, kind, fixture, field, model
    ):
        """Moving a governed link into another tenant is the worst version of
        this bug, so it gets its own case on every table."""
        target = request.getfixturevalue(fixture)
        link = self._link(kind, case_a, target, doer_a, tenant_a)
        link.tenant = tenant_b
        with pytest.raises((InternalError, ProgrammingError)):
            with transaction.atomic():
                link.save()
        link.refresh_from_db()
        assert link.tenant_id == tenant_a.pk

    @pytest.mark.parametrize("kind,fixture,field,model", LINK_CASES)
    def test_label_mutation_is_rejected(
        self, request, case_a, tenant_a, doer_a, kind, fixture, field, model
    ):
        target = request.getfixturevalue(fixture)
        link = self._link(kind, case_a, target, doer_a, tenant_a)
        link.label = "tampered"
        with pytest.raises((InternalError, ProgrammingError)):
            with transaction.atomic():
                link.save()
        link.refresh_from_db()
        assert link.label == ""

    @pytest.mark.parametrize("kind,fixture,field,model", LINK_CASES)
    def test_provenance_mutation_is_rejected(
        self, request, case_a, tenant_a, doer_a, vp_a, kind, fixture, field, model
    ):
        """linked_by and public_id are the row's identity and provenance."""
        target = request.getfixturevalue(fixture)
        link = self._link(kind, case_a, target, doer_a, tenant_a)

        link.linked_by = vp_a
        with pytest.raises((InternalError, ProgrammingError)):
            with transaction.atomic():
                link.save()

        link.refresh_from_db()
        link.public_id = uuid.uuid4()
        with pytest.raises((InternalError, ProgrammingError)):
            with transaction.atomic():
                link.save()

        link.refresh_from_db()
        assert link.linked_by_id == doer_a.pk

    @pytest.mark.parametrize("kind,fixture,field,model", LINK_CASES)
    def test_valid_unlink_is_the_one_permitted_update(
        self, request, case_a, tenant_a, doer_a, kind, fixture, field, model
    ):
        target = request.getfixturevalue(fixture)
        link = self._link(kind, case_a, target, doer_a, tenant_a)
        services.unlink_target(
            kind=kind, case=case_a, link_public_id=link.public_id, actor=doer_a, tenant=tenant_a
        )
        link.refresh_from_db()
        assert link.unlinked_at is not None
        assert link.unlinked_by_id == doer_a.pk

    @pytest.mark.parametrize("kind,fixture,field,model", LINK_CASES)
    def test_frozen_field_cannot_ride_along_with_an_unlink(
        self, request, case_a, tenant_a, doer_a, kind, fixture, field, model
    ):
        """The interesting attack is not tampering alone -- it is tampering
        INSIDE a well-formed unlink, in the same statement."""
        target = request.getfixturevalue(fixture)
        link = self._link(kind, case_a, target, doer_a, tenant_a)
        table = model._meta.db_table

        with pytest.raises((InternalError, ProgrammingError)) as exc:
            with transaction.atomic(), connection.cursor() as cur:
                cur.execute(
                    f"UPDATE {table} "
                    f"SET unlinked_at = NOW(), unlinked_by_id = %s, label = %s "
                    f"WHERE id = %s",
                    [doer_a.pk, "tampered", link.pk],
                )
        assert "immutable" in str(exc.value).lower()

        link.refresh_from_db()
        assert link.unlinked_at is None, "the whole statement must be refused"
        assert link.label == ""

    @pytest.mark.parametrize("kind,fixture,field,model", LINK_CASES)
    def test_partial_unlink_stamp_is_rejected(
        self, request, case_a, tenant_a, doer_a, kind, fixture, field, model
    ):
        """Both stamps or neither: an unlinked row with no actor is a governed
        record with a hole where the accountability should be."""
        target = request.getfixturevalue(fixture)
        link = self._link(kind, case_a, target, doer_a, tenant_a)
        table = model._meta.db_table

        with pytest.raises((InternalError, ProgrammingError)) as exc:
            with transaction.atomic(), connection.cursor() as cur:
                cur.execute(f"UPDATE {table} SET unlinked_at = NOW() WHERE id = %s", [link.pk])
        assert "both unlinked_at and unlinked_by" in str(exc.value).lower()

    @pytest.mark.parametrize("kind,fixture,field,model", LINK_CASES)
    def test_unlink_is_final(self, request, case_a, tenant_a, doer_a, kind, fixture, field, model):
        target = request.getfixturevalue(fixture)
        link = self._link(kind, case_a, target, doer_a, tenant_a)
        services.unlink_target(
            kind=kind, case=case_a, link_public_id=link.public_id, actor=doer_a, tenant=tenant_a
        )
        link.refresh_from_db()

        # Re-stamping, un-unlinking and touching updated_at are all refused.
        link.unlinked_at = timezone.now()
        with pytest.raises((InternalError, ProgrammingError)) as exc:
            with transaction.atomic():
                link.save()
        assert "already unlinked" in str(exc.value).lower()

        table = model._meta.db_table
        with pytest.raises((InternalError, ProgrammingError)):
            with transaction.atomic(), connection.cursor() as cur:
                cur.execute(f"UPDATE {table} SET unlinked_at = NULL WHERE id = %s", [link.pk])

    @pytest.mark.parametrize("kind,fixture,field,model", LINK_CASES)
    def test_updated_at_alone_is_not_a_backdoor(
        self, request, case_a, tenant_a, doer_a, kind, fixture, field, model
    ):
        """`updated_at` may move only inside the sanctioned unlink. On its own
        it is an UPDATE to a frozen row and must be refused."""
        target = request.getfixturevalue(fixture)
        link = self._link(kind, case_a, target, doer_a, tenant_a)
        table = model._meta.db_table

        with pytest.raises((InternalError, ProgrammingError)) as exc:
            with transaction.atomic(), connection.cursor() as cur:
                cur.execute(f"UPDATE {table} SET updated_at = NOW() WHERE id = %s", [link.pk])
        assert "unlink must set both" in str(exc.value).lower()

    @pytest.mark.parametrize("kind,fixture,field,model", LINK_CASES)
    def test_raw_delete_is_rejected_before_and_after_unlink(
        self, request, case_a, tenant_a, doer_a, kind, fixture, field, model
    ):
        target = request.getfixturevalue(fixture)
        link = self._link(kind, case_a, target, doer_a, tenant_a)
        table = model._meta.db_table

        with pytest.raises((InternalError, ProgrammingError)) as exc:
            with transaction.atomic(), connection.cursor() as cur:
                cur.execute(f"DELETE FROM {table} WHERE id = %s", [link.pk])
        assert "cannot be deleted" in str(exc.value).lower()

        services.unlink_target(
            kind=kind, case=case_a, link_public_id=link.public_id, actor=doer_a, tenant=tenant_a
        )
        with pytest.raises((InternalError, ProgrammingError)):
            with transaction.atomic(), connection.cursor() as cur:
                cur.execute(f"DELETE FROM {table} WHERE id = %s", [link.pk])
        assert model.objects.filter(pk=link.pk).exists()

    @pytest.mark.parametrize("kind,fixture,field,model", LINK_CASES)
    def test_unqualified_bulk_update_is_rejected(
        self, request, case_a, tenant_a, doer_a, kind, fixture, field, model
    ):
        """The shape a careless cleanup script takes."""
        target = request.getfixturevalue(fixture)
        self._link(kind, case_a, target, doer_a, tenant_a)
        table = model._meta.db_table

        with pytest.raises((InternalError, ProgrammingError)):
            with transaction.atomic(), connection.cursor() as cur:
                cur.execute(f"UPDATE {table} SET label = 'wiped'")
        assert model.objects.filter(label="wiped").count() == 0


@pytest.mark.django_db
class TestTriggerInstallationAndCoverage:
    TABLES = {
        "regulatory_cases_regulatorycaseworkflow": "workflow_item_id",
        "regulatory_cases_regulatorycasedocument": "document_id",
        "regulatory_cases_regulatorycasechecklist": "checklist_execution_id",
    }

    #: Mirrors the guard in regulatory_cases/0002. `test_guard_covers_every_column`
    #: fails if the two ever drift apart.
    FROZEN = {
        "id",
        "public_id",
        "case_id",
        "tenant_id",
        "label",
        "linked_by_id",
        "linked_at",
        "created_at",
    }
    UNLINK_STAMPS = {"unlinked_at", "unlinked_by_id"}
    #: Permitted to move, but only inside the sanctioned unlink.
    TRANSITION_ONLY = {"updated_at"}

    def test_both_triggers_exist_on_every_link_table(self):
        with connection.cursor() as cur:
            for table in self.TABLES:
                cur.execute(
                    "SELECT trigger_name FROM information_schema.triggers "
                    "WHERE event_object_table = %s",
                    [table],
                )
                names = {row[0] for row in cur.fetchall()}
                assert any(n.startswith("no_delete_case_") for n in names), table
                assert any(n.startswith("guard_update_case_") for n in names), table

    def test_guard_functions_exist(self):
        with connection.cursor() as cur:
            for fn in (
                "regulatory_cases_prevent_link_delete",
                "regulatory_cases_guard_link_update",
            ):
                cur.execute("SELECT COUNT(*) FROM pg_proc WHERE proname = %s", [fn])
                assert cur.fetchone()[0] == 1, fn

    def test_guard_covers_every_column_on_every_link_table(self):
        """An enumerate-by-name guard is sound only while the enumeration is
        complete. Add a column and forget the trigger and it would be silently
        mutable inside an unlink -- so this fails the build instead of failing
        quietly in production.
        """
        with connection.cursor() as cur:
            for table, target_col in self.TABLES.items():
                cur.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
                    [table],
                )
                actual = {row[0] for row in cur.fetchall()}
                accounted = self.FROZEN | self.UNLINK_STAMPS | self.TRANSITION_ONLY | {target_col}
                assert actual == accounted, (
                    f"{table}: regulatory_cases/0002 lists columns by name -- update the "
                    f"trigger and this test together. Unaccounted: {actual - accounted}; "
                    f"stale: {accounted - actual}"
                )
