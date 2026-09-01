"""Two-gate linking authorization and database-level link immutability.

Both were MAJOR findings against Milestone 8's equivalent link tables. They are
built in from the start here and proven the same way, because "we did it right
this time" is not evidence.
"""

import uuid

import pytest
from django.db import InternalError, ProgrammingError, connection, transaction
from django.utils import timezone

from submission_dossiers import services
from submission_dossiers.models import (
    DossierSectionChecklist,
    DossierSectionDocument,
    DossierSectionWorkflow,
)

SECT = "/api/regx/v1/dossier-sections"


# ---------------------------------------------------------------------------
# Two-gate authorization
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestTargetModuleAuthorization:
    """`manage_links` alone must not be enough to link anything."""

    def test_document_link_requires_document_permission(
        self, section_a, document_a, support_a, tenant_a
    ):
        """PLATFORM_SUPPORT holds documents [] -- the document exists in the
        same tenant and linking must still fail closed."""
        from submission_dossiers.projection import can_view_documents

        assert can_view_documents(support_a, tenant_a) is False
        with pytest.raises(services.InvalidTarget):
            services.link_target(
                kind="document",
                section=section_a,
                target_public_id=document_a.public_id,
                actor=support_a,
                tenant=tenant_a,
            )
        assert DossierSectionDocument.objects.count() == 0

    def test_workflow_link_requires_workflow_permission(
        self, section_a, workflow_a, outsider, tenant_a
    ):
        """No built-in role separates dossiers from workflows, so a caller with
        no membership is what proves the gate: the check keys on the permission
        helper, never on a role name."""
        from submission_dossiers.projection import can_view_workflows

        assert can_view_workflows(outsider, tenant_a) is False
        with pytest.raises(services.InvalidTarget):
            services.link_target(
                kind="workflow",
                section=section_a,
                target_public_id=workflow_a.public_id,
                actor=outsider,
                tenant=tenant_a,
            )
        assert DossierSectionWorkflow.objects.count() == 0

    def test_checklist_link_requires_checklist_permission(
        self, section_a, checklist_a, support_a, tenant_a
    ):
        from submission_dossiers.projection import can_view_checklists

        assert can_view_checklists(support_a, tenant_a) is False
        with pytest.raises(services.InvalidTarget):
            services.link_target(
                kind="checklist",
                section=section_a,
                target_public_id=checklist_a.public_id,
                actor=support_a,
                tenant=tenant_a,
            )
        assert DossierSectionChecklist.objects.count() == 0

    @pytest.mark.parametrize(
        "kind,fixture",
        [("document", "document_a"), ("workflow", "workflow_a"), ("checklist", "checklist_a")],
    )
    def test_authorized_link_succeeds(self, request, section_a, doer_a, tenant_a, kind, fixture):
        target = request.getfixturevalue(fixture)
        link = services.link_target(
            kind=kind,
            section=section_a,
            target_public_id=target.public_id,
            actor=doer_a,
            tenant=tenant_a,
        )
        assert link.is_active

    def test_unauthorized_absent_and_cross_tenant_are_one_outcome(
        self, section_a, document_a, document_b, support_a, doer_a, tenant_a
    ):
        """If these differed, a caller holding only `manage_links` could ask
        'does this UUID exist in my tenant?' and read the answer off the error."""
        messages = []

        with pytest.raises(services.InvalidTarget) as e1:  # exists, unauthorized
            services.link_target(
                kind="document",
                section=section_a,
                target_public_id=document_a.public_id,
                actor=support_a,
                tenant=tenant_a,
            )
        messages.append(str(e1.value))

        with pytest.raises(services.InvalidTarget) as e2:  # authorized, absent
            services.link_target(
                kind="document",
                section=section_a,
                target_public_id=uuid.uuid4(),
                actor=doer_a,
                tenant=tenant_a,
            )
        messages.append(str(e2.value))

        with pytest.raises(services.InvalidTarget) as e3:  # authorized, cross-tenant
            services.link_target(
                kind="document",
                section=section_a,
                target_public_id=document_b.public_id,
                actor=doer_a,
                tenant=tenant_a,
            )
        messages.append(str(e3.value))

        assert len(set(messages)) == 1, f"failure messages differ: {messages}"

    def test_api_absent_and_cross_tenant_are_identical(self, client_doer_a, section_a, document_b):
        absent = client_doer_a.post(
            f"{SECT}/{section_a.public_id}/documents/",
            {"target_public_id": str(uuid.uuid4())},
            format="json",
        )
        cross = client_doer_a.post(
            f"{SECT}/{section_a.public_id}/documents/",
            {"target_public_id": str(document_b.public_id)},
            format="json",
        )
        assert absent.status_code == cross.status_code == 400
        assert str(absent.data["target_public_id"]) == str(cross.data["target_public_id"])

    def test_refused_link_emits_no_audit_event(
        self, section_a, dossier_a, document_a, support_a, tenant_a
    ):
        """A rejected attempt must leave no trace suggesting it happened."""
        from audit.models import AuditEvent

        before = AuditEvent.objects.filter(resource_id=str(dossier_a.public_id)).count()
        with pytest.raises(services.InvalidTarget):
            services.link_target(
                kind="document",
                section=section_a,
                target_public_id=document_a.public_id,
                actor=support_a,
                tenant=tenant_a,
            )
        after = AuditEvent.objects.filter(resource_id=str(dossier_a.public_id))
        assert after.count() == before
        assert not after.filter(event_type="dossier_section.document_linked").exists()

    def test_duplicate_link_refused(self, section_a, document_a, doer_a, tenant_a):
        services.link_target(
            kind="document",
            section=section_a,
            target_public_id=document_a.public_id,
            actor=doer_a,
            tenant=tenant_a,
        )
        with pytest.raises(services.DuplicateLink):
            services.link_target(
                kind="document",
                section=section_a,
                target_public_id=document_a.public_id,
                actor=doer_a,
                tenant=tenant_a,
            )


# ---------------------------------------------------------------------------
# Safe projection
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestSafeProjection:
    def test_section_only_caller_sees_no_document_detail(
        self, client_support_a, section_a, document_a, doer_a, tenant_a
    ):
        services.link_target(
            kind="document",
            section=section_a,
            target_public_id=document_a.public_id,
            actor=doer_a,
            tenant=tenant_a,
        )
        r = client_support_a.get(f"{SECT}/{section_a.public_id}/")
        assert r.status_code == 200
        row = r.data["documents"][0]
        assert row["restricted"] is True
        assert "document" not in row
        assert document_a.title not in str(r.data)

    def test_permitted_caller_sees_detail(
        self, client_doer_a, section_a, document_a, doer_a, tenant_a
    ):
        services.link_target(
            kind="document",
            section=section_a,
            target_public_id=document_a.public_id,
            actor=doer_a,
            tenant=tenant_a,
        )
        row = client_doer_a.get(f"{SECT}/{section_a.public_id}/").data["documents"][0]
        assert "restricted" not in row
        assert row["document"]["title"] == document_a.title

    def test_module_counts_are_null_not_zero_when_withheld(
        self, section_a, workflow_a, doer_a, outsider, tenant_a
    ):
        """Reporting zero would be worse than reporting nothing: it asserts
        something false about resources the caller cannot see."""
        from submission_dossiers.projection import module_counts

        services.link_target(
            kind="workflow",
            section=section_a,
            target_public_id=workflow_a.public_id,
            actor=doer_a,
            tenant=tenant_a,
        )
        withheld = module_counts([section_a.pk], outsider, tenant_a)
        assert withheld["workflow_evidence_links"] is None

        allowed = module_counts([section_a.pk], doer_a, tenant_a)
        assert allowed["workflow_evidence_links"] == 0

    def test_linked_by_email_is_never_projected(
        self, client_doer_a, section_a, document_a, doer_a, tenant_a
    ):
        services.link_target(
            kind="document",
            section=section_a,
            target_public_id=document_a.public_id,
            actor=doer_a,
            tenant=tenant_a,
        )
        r = client_doer_a.get(f"{SECT}/{section_a.public_id}/")
        assert doer_a.email not in str(r.data)


# ---------------------------------------------------------------------------
# Database-level immutability
# ---------------------------------------------------------------------------
LINK_CASES = [
    ("document", "document_a", "document", DossierSectionDocument),
    ("workflow", "workflow_a", "workflow_item", DossierSectionWorkflow),
    ("checklist", "checklist_a", "checklist_execution", DossierSectionChecklist),
]


@pytest.mark.django_db
class TestLinkDatabaseImmutability:
    """The manager proves the ORM refuses. These prove the DATABASE refuses,
    which is what matters when `instance.save()` never touches the manager."""

    def _link(self, kind, section, target, actor, tenant):
        return services.link_target(
            kind=kind,
            section=section,
            target_public_id=target.public_id,
            actor=actor,
            tenant=tenant,
        )

    @pytest.mark.parametrize("kind,fixture,field,model", LINK_CASES)
    def test_target_swap_via_save_is_rejected(
        self, request, section_a, doer_a, tenant_a, kind, fixture, field, model
    ):
        target = request.getfixturevalue(fixture)
        link = self._link(kind, section_a, target, doer_a, tenant_a)

        if kind == "document":
            from documents.models import Document

            other = Document.objects.create(tenant=tenant_a, title="Other", document_type="other")
        elif kind == "workflow":
            from workflows.models import WorkflowItem

            other = WorkflowItem.objects.create(tenant=tenant_a, title="Other", created_by=doer_a)
        else:
            from submission_dossiers.tests.conftest import _checklist_execution

            other = _checklist_execution(tenant_a, doer_a)

        setattr(link, field, other)
        with pytest.raises((InternalError, ProgrammingError)) as exc:
            with transaction.atomic():
                link.save()
        assert "immutable" in str(exc.value).lower()

        link.refresh_from_db()
        assert getattr(link, f"{field}_id") == target.pk

    @pytest.mark.parametrize("kind,fixture,field,model", LINK_CASES)
    def test_section_swap_is_rejected(
        self, request, dossier_a, section_a, doer_a, tenant_a, kind, fixture, field, model
    ):
        from submission_dossiers.tests.conftest import make_section

        target = request.getfixturevalue(fixture)
        link = self._link(kind, section_a, target, doer_a, tenant_a)
        other_section = make_section(dossier_a, tenant_a, doer_a, "other")

        link.section = other_section
        with pytest.raises((InternalError, ProgrammingError)):
            with transaction.atomic():
                link.save()
        link.refresh_from_db()
        assert link.section_id == section_a.pk

    @pytest.mark.parametrize("kind,fixture,field,model", LINK_CASES)
    def test_tenant_swap_is_rejected(
        self, request, section_a, doer_a, tenant_a, tenant_b, kind, fixture, field, model
    ):
        """Moving a governed link into another tenant is the worst version of
        this bug, so every table gets its own case."""
        target = request.getfixturevalue(fixture)
        link = self._link(kind, section_a, target, doer_a, tenant_a)
        link.tenant = tenant_b
        with pytest.raises((InternalError, ProgrammingError)):
            with transaction.atomic():
                link.save()
        link.refresh_from_db()
        assert link.tenant_id == tenant_a.pk

    @pytest.mark.parametrize("kind,fixture,field,model", LINK_CASES)
    def test_provenance_and_purpose_mutation_rejected(
        self, request, section_a, doer_a, vp_a, tenant_a, kind, fixture, field, model
    ):
        target = request.getfixturevalue(fixture)
        link = self._link(kind, section_a, target, doer_a, tenant_a)

        for attr, value in (
            ("purpose", "tampered"),
            ("linked_by", vp_a),
            ("public_id", uuid.uuid4()),
            ("linked_at", timezone.now()),
        ):
            link.refresh_from_db()
            setattr(link, attr, value)
            with pytest.raises((InternalError, ProgrammingError)):
                with transaction.atomic():
                    link.save()

        link.refresh_from_db()
        assert link.purpose == ""
        assert link.linked_by_id == doer_a.pk

    @pytest.mark.parametrize("kind,fixture,field,model", LINK_CASES)
    def test_valid_unlink_allowed(
        self, request, section_a, doer_a, tenant_a, kind, fixture, field, model
    ):
        target = request.getfixturevalue(fixture)
        link = self._link(kind, section_a, target, doer_a, tenant_a)
        services.unlink_target(
            kind=kind,
            section=section_a,
            link_public_id=link.public_id,
            actor=doer_a,
            tenant=tenant_a,
        )
        link.refresh_from_db()
        assert link.unlinked_at is not None
        assert link.unlinked_by_id == doer_a.pk

    @pytest.mark.parametrize("kind,fixture,field,model", LINK_CASES)
    def test_frozen_field_cannot_ride_along_with_unlink(
        self, request, section_a, doer_a, tenant_a, kind, fixture, field, model
    ):
        """Tampering INSIDE a well-formed unlink, in the same statement, is the
        attack a stamps-only guard would wave through."""
        target = request.getfixturevalue(fixture)
        link = self._link(kind, section_a, target, doer_a, tenant_a)
        table = model._meta.db_table

        with pytest.raises((InternalError, ProgrammingError)) as exc:
            with transaction.atomic(), connection.cursor() as cur:
                cur.execute(
                    f"UPDATE {table} SET unlinked_at = NOW(), unlinked_by_id = %s, "
                    f"purpose = %s WHERE id = %s",
                    [doer_a.pk, "tampered", link.pk],
                )
        assert "immutable" in str(exc.value).lower()

        link.refresh_from_db()
        assert link.unlinked_at is None, "the whole statement must be refused"
        assert link.purpose == ""

    @pytest.mark.parametrize("kind,fixture,field,model", LINK_CASES)
    def test_partial_stamp_rejected(
        self, request, section_a, doer_a, tenant_a, kind, fixture, field, model
    ):
        target = request.getfixturevalue(fixture)
        link = self._link(kind, section_a, target, doer_a, tenant_a)
        table = model._meta.db_table
        with pytest.raises((InternalError, ProgrammingError)) as exc:
            with transaction.atomic(), connection.cursor() as cur:
                cur.execute(f"UPDATE {table} SET unlinked_at = NOW() WHERE id = %s", [link.pk])
        assert "both unlinked_at and unlinked_by" in str(exc.value).lower()

    @pytest.mark.parametrize("kind,fixture,field,model", LINK_CASES)
    def test_updated_at_alone_is_not_a_backdoor(
        self, request, section_a, doer_a, tenant_a, kind, fixture, field, model
    ):
        target = request.getfixturevalue(fixture)
        link = self._link(kind, section_a, target, doer_a, tenant_a)
        table = model._meta.db_table
        with pytest.raises((InternalError, ProgrammingError)) as exc:
            with transaction.atomic(), connection.cursor() as cur:
                cur.execute(f"UPDATE {table} SET updated_at = NOW() WHERE id = %s", [link.pk])
        assert "unlink must set both" in str(exc.value).lower()

    @pytest.mark.parametrize("kind,fixture,field,model", LINK_CASES)
    def test_unlink_is_final(
        self, request, section_a, doer_a, tenant_a, kind, fixture, field, model
    ):
        target = request.getfixturevalue(fixture)
        link = self._link(kind, section_a, target, doer_a, tenant_a)
        services.unlink_target(
            kind=kind,
            section=section_a,
            link_public_id=link.public_id,
            actor=doer_a,
            tenant=tenant_a,
        )
        link.refresh_from_db()

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
    def test_delete_rejected_before_and_after_unlink(
        self, request, section_a, doer_a, tenant_a, kind, fixture, field, model
    ):
        target = request.getfixturevalue(fixture)
        link = self._link(kind, section_a, target, doer_a, tenant_a)
        table = model._meta.db_table

        with pytest.raises((InternalError, ProgrammingError)) as exc:
            with transaction.atomic(), connection.cursor() as cur:
                cur.execute(f"DELETE FROM {table} WHERE id = %s", [link.pk])
        assert "cannot be deleted" in str(exc.value).lower()

        services.unlink_target(
            kind=kind,
            section=section_a,
            link_public_id=link.public_id,
            actor=doer_a,
            tenant=tenant_a,
        )
        with pytest.raises((InternalError, ProgrammingError)):
            with transaction.atomic(), connection.cursor() as cur:
                cur.execute(f"DELETE FROM {table} WHERE id = %s", [link.pk])
        assert model.objects.filter(pk=link.pk).exists()

    @pytest.mark.parametrize("kind,fixture,field,model", LINK_CASES)
    def test_unqualified_bulk_update_rejected(
        self, request, section_a, doer_a, tenant_a, kind, fixture, field, model
    ):
        target = request.getfixturevalue(fixture)
        self._link(kind, section_a, target, doer_a, tenant_a)
        table = model._meta.db_table
        with pytest.raises((InternalError, ProgrammingError)):
            with transaction.atomic(), connection.cursor() as cur:
                cur.execute(f"UPDATE {table} SET purpose = 'wiped'")
        assert model.objects.filter(purpose="wiped").count() == 0


@pytest.mark.django_db
class TestTriggerInstallationAndCoverage:
    TABLES = {
        "submission_dossiers_dossiersectiondocument": "document_id",
        "submission_dossiers_dossiersectionworkflow": "workflow_item_id",
        "submission_dossiers_dossiersectionchecklist": "checklist_execution_id",
    }

    #: Mirrors the guard in submission_dossiers/0002. The coverage test below
    #: fails if the two ever drift apart.
    FROZEN = {
        "id",
        "public_id",
        "section_id",
        "tenant_id",
        "purpose",
        "linked_by_id",
        "linked_at",
        "created_at",
    }
    UNLINK_STAMPS = {"unlinked_at", "unlinked_by_id"}
    TRANSITION_ONLY = {"updated_at"}

    def test_triggers_exist_on_every_link_table(self):
        with connection.cursor() as cur:
            for table in self.TABLES:
                cur.execute(
                    "SELECT trigger_name FROM information_schema.triggers "
                    "WHERE event_object_table = %s",
                    [table],
                )
                names = {row[0] for row in cur.fetchall()}
                assert any(n.startswith("no_delete_section_") for n in names), table
                assert any(n.startswith("guard_update_section_") for n in names), table

    def test_guard_functions_exist(self):
        with connection.cursor() as cur:
            for fn in (
                "submission_dossiers_prevent_link_delete",
                "submission_dossiers_guard_link_update",
            ):
                cur.execute("SELECT COUNT(*) FROM pg_proc WHERE proname = %s", [fn])
                assert cur.fetchone()[0] == 1, fn

    def test_guard_covers_every_column_on_every_link_table(self):
        """An enumerate-by-name guard is sound only while the enumeration is
        complete. Add a column and forget the trigger and it would be silently
        mutable inside an unlink -- so this fails the build instead."""
        with connection.cursor() as cur:
            for table, target_col in self.TABLES.items():
                cur.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
                    [table],
                )
                actual = {row[0] for row in cur.fetchall()}
                accounted = self.FROZEN | self.UNLINK_STAMPS | self.TRANSITION_ONLY | {target_col}
                assert actual == accounted, (
                    f"{table}: submission_dossiers/0002 lists columns by name -- update the "
                    f"trigger and this test together. Unaccounted: {actual - accounted}; "
                    f"stale: {accounted - actual}"
                )
