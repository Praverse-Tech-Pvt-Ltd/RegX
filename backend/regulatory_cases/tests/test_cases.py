"""Regulatory cases: lifecycle, tenant isolation, permissions, links,
projection, audit, deletion protection and concurrency.

Cross-tenant leakage and metadata leakage here are release-blocking.
Synthetic data only.
"""

import threading
import uuid

import pytest
from django.db import connection, transaction

from regulatory_cases import services
from regulatory_cases.models import (
    CaseLinkMutationForbidden,
    CaseStatus,
    RegulatoryCase,
    RegulatoryCaseDocument,
    RegulatoryCaseWorkflow,
)

BASE = "/api/regx/v1/regulatory-cases/"


def _url(case, suffix=""):
    return f"{BASE}{case.public_id}/{suffix}"


CREATE_PAYLOAD = {
    "title": "New case",
    "product_name": "Synthetic Product",
    "market": "Synthetic Market",
    "submission_type": "Synthetic Type",
}


# ---------------------------------------------------------------------------
# Creation and case numbers
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCreation:
    def test_creates_with_tenant_local_number(self, client_doer_a):
        r = client_doer_a.post(BASE, CREATE_PAYLOAD, format="json")
        assert r.status_code == 201, r.content[:400]
        assert r.data["case_number"] == "RC-000001"
        assert r.data["status"] == CaseStatus.OPEN
        # Internal PKs are never exposed.
        assert "id" not in r.data

    def test_numbers_increment_within_a_tenant(self, tenant_a, doer_a):
        numbers = [
            services.create_case(tenant=tenant_a, actor=doer_a, **CREATE_PAYLOAD).case_number
            for _ in range(3)
        ]
        assert numbers == ["RC-000001", "RC-000002", "RC-000003"]

    def test_numbers_are_tenant_local_not_global(self, tenant_a, tenant_b, doer_a, doer_b):
        """Two tenants may both hold RC-000001; they are different cases."""
        a = services.create_case(tenant=tenant_a, actor=doer_a, **CREATE_PAYLOAD)
        b = services.create_case(tenant=tenant_b, actor=doer_b, **CREATE_PAYLOAD)
        assert a.case_number == b.case_number == "RC-000001"
        assert a.tenant_id != b.tenant_id

    def test_blank_required_fields_are_refused(self, client_doer_a):
        r = client_doer_a.post(BASE, {**CREATE_PAYLOAD, "title": "   "}, format="json")
        assert r.status_code == 400

    def test_owner_must_be_a_member_of_this_tenant(self, client_doer_a, doer_b):
        """A user from another tenant cannot be made owner, and the message does
        not distinguish that from an unknown user."""
        cross = client_doer_a.post(
            BASE, {**CREATE_PAYLOAD, "owner_public_id": str(doer_b.public_id)}, format="json"
        )
        missing = client_doer_a.post(
            BASE, {**CREATE_PAYLOAD, "owner_public_id": str(uuid.uuid4())}, format="json"
        )
        assert cross.status_code == missing.status_code == 400
        assert str(cross.data["owner_public_id"]) == str(missing.data["owner_public_id"])


@pytest.mark.django_db(transaction=True)
class TestCaseNumberConcurrency:
    def test_two_simultaneous_creates_get_different_numbers(self, tenant_a, doer_a):
        """The sequence row is claimed under select_for_update, so a race
        produces two numbers rather than an IntegrityError or a duplicate."""
        barrier = threading.Barrier(2)
        results, errors = [], []

        def create():
            try:
                barrier.wait(timeout=10)
                case = services.create_case(tenant=tenant_a, actor=doer_a, **CREATE_PAYLOAD)
                results.append(case.case_number)
            except Exception as exc:
                errors.append(exc)
            finally:
                connection.close()

        threads = [threading.Thread(target=create) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20)

        assert errors == [], f"concurrent create failed: {errors}"
        assert sorted(results) == ["RC-000001", "RC-000002"]
        assert RegulatoryCase.objects.filter(tenant=tenant_a).count() == 2

    def test_unique_constraint_is_the_real_guarantee(self, tenant_a, doer_a):
        """Even if the sequence were bypassed, the database refuses a duplicate."""
        from django.db.utils import IntegrityError

        services.create_case(tenant=tenant_a, actor=doer_a, **CREATE_PAYLOAD)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                RegulatoryCase.objects.create(
                    tenant=tenant_a,
                    case_number="RC-000001",
                    created_by=doer_a,
                    **CREATE_PAYLOAD,
                )


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestTenantIsolation:
    def test_list_shows_only_this_tenant(self, client_doer_a, case_a, case_b):
        r = client_doer_a.get(BASE)
        assert r.status_code == 200
        ids = {row["public_id"] for row in r.data["results"]}
        assert str(case_a.public_id) in ids
        assert str(case_b.public_id) not in ids

    def test_cross_tenant_detail_is_404_not_403(self, client_doer_a, case_b):
        """403 would confirm the case exists."""
        r = client_doer_a.get(_url(case_b))
        assert r.status_code == 404

    def test_cross_tenant_and_nonexistent_are_indistinguishable(self, client_doer_a, case_b):
        cross = client_doer_a.get(_url(case_b))
        missing = client_doer_a.get(f"{BASE}{uuid.uuid4()}/")
        assert cross.status_code == missing.status_code == 404
        assert str(cross.data) == str(missing.data)

    def test_cross_tenant_mutation_is_refused(self, client_doer_a, case_b):
        assert client_doer_a.patch(_url(case_b), {"title": "x"}, format="json").status_code == 404

    @pytest.mark.parametrize("kind", ["workflows", "documents", "checklists"])
    def test_cross_tenant_link_endpoints_are_404(self, client_doer_a, case_b, kind):
        assert client_doer_a.get(_url(case_b, f"{kind}/")).status_code == 404


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestPermissions:
    def test_outsider_cannot_reach_cases(self, outsider, tenant_a, case_a):
        from rest_framework.test import APIClient

        client = APIClient()
        client.force_authenticate(user=outsider)
        client.credentials(HTTP_X_TENANT_SLUG=tenant_a.slug)
        assert client.get(BASE).status_code in (403, 404)

    def test_doer_cannot_complete_or_cancel(self, client_doer_a, case_a):
        """DOER holds view/create/edit/manage_links and neither terminal action."""
        assert client_doer_a.post(_url(case_a, "complete/"), {}, format="json").status_code == 403
        assert client_doer_a.post(_url(case_a, "cancel/"), {}, format="json").status_code == 403

    def test_vp_can_complete_and_cancel(self, client_vp_a, tenant_a, doer_a):
        first = services.create_case(tenant=tenant_a, actor=doer_a, **CREATE_PAYLOAD)
        second = services.create_case(tenant=tenant_a, actor=doer_a, **CREATE_PAYLOAD)
        assert client_vp_a.post(_url(first, "complete/"), {}, format="json").status_code == 200
        assert client_vp_a.post(_url(second, "cancel/"), {}, format="json").status_code == 200

    def test_vp_cannot_edit_or_manage_links(self, client_vp_a, case_a, workflow_a):
        assert client_vp_a.patch(_url(case_a), {"title": "x"}, format="json").status_code == 403
        r = client_vp_a.post(
            _url(case_a, "workflows/"),
            {"target_public_id": str(workflow_a.public_id)},
            format="json",
        )
        assert r.status_code == 403

    def test_support_can_view_but_not_mutate(self, client_support_a, case_a):
        assert client_support_a.get(_url(case_a)).status_code == 200
        assert client_support_a.post(BASE, CREATE_PAYLOAD, format="json").status_code == 403
        assert (
            client_support_a.patch(_url(case_a), {"title": "x"}, format="json").status_code == 403
        )

    def test_permissions_block_is_advisory_and_honest(self, client_doer_a, case_a):
        r = client_doer_a.get(_url(case_a))
        perms = r.data["permissions"]
        assert perms["can_edit"] is True
        assert perms["can_manage_links"] is True
        assert perms["can_complete"] is False
        assert perms["can_cancel"] is False


# ---------------------------------------------------------------------------
# Status gating
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestStatusGating:
    def test_complete_then_no_structural_change(
        self, client_vp_a, client_doer_a, case_a, workflow_a
    ):
        assert client_vp_a.post(_url(case_a, "complete/"), {}, format="json").status_code == 200

        assert client_doer_a.patch(_url(case_a), {"title": "x"}, format="json").status_code == 409
        r = client_doer_a.post(
            _url(case_a, "workflows/"),
            {"target_public_id": str(workflow_a.public_id)},
            format="json",
        )
        assert r.status_code == 409

    def test_cancel_then_no_structural_change(self, client_vp_a, client_doer_a, case_a, document_a):
        assert client_vp_a.post(_url(case_a, "cancel/"), {}, format="json").status_code == 200
        r = client_doer_a.post(
            _url(case_a, "documents/"),
            {"target_public_id": str(document_a.public_id)},
            format="json",
        )
        assert r.status_code == 409

    def test_terminal_case_cannot_be_terminated_again(self, client_vp_a, case_a):
        assert client_vp_a.post(_url(case_a, "complete/"), {}, format="json").status_code == 200
        again = client_vp_a.post(_url(case_a, "cancel/"), {}, format="json")
        assert again.status_code == 409

    def test_unlink_refused_on_a_terminal_case(
        self, client_vp_a, client_doer_a, case_a, workflow_a
    ):
        link = services.link_target(
            kind="workflow",
            case=case_a,
            target_public_id=workflow_a.public_id,
            actor=case_a.created_by,
            tenant=case_a.tenant,
        )
        client_vp_a.post(_url(case_a, "complete/"), {}, format="json")
        r = client_doer_a.delete(_url(case_a, f"workflows/{link.public_id}/"))
        assert r.status_code == 409

    def test_completing_is_not_an_approval_claim(self, client_vp_a, case_a):
        """Guards the wording, which is a regulatory boundary, not a nicety."""
        r = client_vp_a.post(_url(case_a, "complete/"), {}, format="json")
        assert r.status_code == 200
        body = str(r.data).lower()
        for forbidden in ("approved", "approval", "authorised", "authorized", "cleared"):
            assert forbidden not in body


# ---------------------------------------------------------------------------
# Linking -- one parametrised sweep over all three kinds
# ---------------------------------------------------------------------------
LINK_KINDS = [
    ("workflows", "workflow_a", "workflow_b"),
    ("documents", "document_a", "document_b"),
]


@pytest.mark.django_db
class TestLinking:
    @pytest.mark.parametrize("path,own,other", LINK_KINDS)
    def test_authorized_link_succeeds(self, request, client_doer_a, case_a, path, own, other):
        target = request.getfixturevalue(own)
        r = client_doer_a.post(
            _url(case_a, f"{path}/"), {"target_public_id": str(target.public_id)}, format="json"
        )
        assert r.status_code == 201, r.content[:300]

    @pytest.mark.parametrize("path,own,other", LINK_KINDS)
    def test_cross_tenant_target_fails_closed(
        self, request, client_doer_a, case_a, path, own, other
    ):
        target = request.getfixturevalue(other)
        r = client_doer_a.post(
            _url(case_a, f"{path}/"), {"target_public_id": str(target.public_id)}, format="json"
        )
        assert r.status_code == 400
        assert RegulatoryCaseWorkflow.objects.count() == 0
        assert RegulatoryCaseDocument.objects.count() == 0

    @pytest.mark.parametrize("path,own,other", LINK_KINDS)
    def test_cross_tenant_and_absent_are_indistinguishable(
        self, request, client_doer_a, case_a, path, own, other
    ):
        """Otherwise a caller could probe another tenant for the existence of a
        workflow or document by comparing the two errors."""
        target = request.getfixturevalue(other)
        cross = client_doer_a.post(
            _url(case_a, f"{path}/"), {"target_public_id": str(target.public_id)}, format="json"
        )
        missing = client_doer_a.post(
            _url(case_a, f"{path}/"), {"target_public_id": str(uuid.uuid4())}, format="json"
        )
        assert cross.status_code == missing.status_code == 400
        assert str(cross.data["target_public_id"]) == str(missing.data["target_public_id"])

    @pytest.mark.parametrize("path,own,other", LINK_KINDS)
    def test_duplicate_active_link_is_refused(
        self, request, client_doer_a, case_a, path, own, other
    ):
        target = request.getfixturevalue(own)
        body = {"target_public_id": str(target.public_id)}
        assert client_doer_a.post(_url(case_a, f"{path}/"), body, format="json").status_code == 201
        second = client_doer_a.post(_url(case_a, f"{path}/"), body, format="json")
        assert second.status_code == 409

    @pytest.mark.parametrize("path,own,other", LINK_KINDS)
    def test_unlink_then_relink_is_allowed(self, request, client_doer_a, case_a, path, own, other):
        """The unique constraint is partial, so retiring a link frees the pair."""
        target = request.getfixturevalue(own)
        body = {"target_public_id": str(target.public_id)}
        created = client_doer_a.post(_url(case_a, f"{path}/"), body, format="json")
        link_id = created.data["public_id"]

        assert client_doer_a.delete(_url(case_a, f"{path}/{link_id}/")).status_code == 204
        assert client_doer_a.post(_url(case_a, f"{path}/"), body, format="json").status_code == 201

    def test_unlink_stamps_and_never_deletes(self, client_doer_a, case_a, workflow_a, doer_a):
        link = services.link_target(
            kind="workflow",
            case=case_a,
            target_public_id=workflow_a.public_id,
            actor=doer_a,
            tenant=case_a.tenant,
        )
        client_doer_a.delete(_url(case_a, f"workflows/{link.public_id}/"))

        link.refresh_from_db()
        assert link.unlinked_at is not None
        assert link.unlinked_by_id == doer_a.pk
        # The row survives: the case history records that it was once cited.
        assert RegulatoryCaseWorkflow.objects.filter(pk=link.pk).exists()

    def test_orm_delete_paths_are_blocked(self, case_a, workflow_a, doer_a):
        link = services.link_target(
            kind="workflow",
            case=case_a,
            target_public_id=workflow_a.public_id,
            actor=doer_a,
            tenant=case_a.tenant,
        )
        with pytest.raises(CaseLinkMutationForbidden):
            link.delete()
        with pytest.raises(CaseLinkMutationForbidden):
            RegulatoryCaseWorkflow.objects.filter(pk=link.pk).delete()
        with pytest.raises(CaseLinkMutationForbidden):
            RegulatoryCaseWorkflow.objects.filter(pk=link.pk).update(label="x")


@pytest.mark.django_db(transaction=True)
class TestConcurrentLinking:
    def test_two_simultaneous_links_produce_exactly_one(self, tenant_a, doer_a):
        """The partial unique constraint makes the database the arbiter."""
        case = services.create_case(tenant=tenant_a, actor=doer_a, **CREATE_PAYLOAD)
        from workflows.models import WorkflowItem

        item = WorkflowItem.objects.create(tenant=tenant_a, title="Race target", created_by=doer_a)

        barrier = threading.Barrier(2)
        wins, losses = [], []

        def attempt():
            try:
                barrier.wait(timeout=10)
                services.link_target(
                    kind="workflow",
                    case=case,
                    target_public_id=item.public_id,
                    actor=doer_a,
                    tenant=tenant_a,
                )
                wins.append(1)
            except services.DuplicateLink:
                losses.append(1)
            except Exception as exc:
                losses.append(exc)
            finally:
                connection.close()

        threads = [threading.Thread(target=attempt) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20)

        assert len(wins) == 1, f"expected one winner, got wins={wins} losses={losses}"
        assert (
            RegulatoryCaseWorkflow.objects.filter(
                case=case, workflow_item=item, unlinked_at__isnull=True
            ).count()
            == 1
        )


# ---------------------------------------------------------------------------
# Projection -- case view is not resource view
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestSafeProjection:
    def test_case_only_caller_sees_identity_but_no_document_detail(
        self, client_support_a, case_a, document_a, doer_a
    ):
        """PLATFORM_SUPPORT holds regulatory_cases.view and documents []."""
        services.link_target(
            kind="document",
            case=case_a,
            target_public_id=document_a.public_id,
            actor=doer_a,
            tenant=case_a.tenant,
        )
        r = client_support_a.get(_url(case_a))
        assert r.status_code == 200
        row = r.data["documents"][0]

        assert row["restricted"] is True
        assert "document" not in row
        # The title must not appear anywhere in the response.
        assert document_a.title not in str(r.data)

    def test_document_holder_sees_detail(self, client_doer_a, case_a, document_a, doer_a):
        services.link_target(
            kind="document",
            case=case_a,
            target_public_id=document_a.public_id,
            actor=doer_a,
            tenant=case_a.tenant,
        )
        r = client_doer_a.get(_url(case_a))
        row = r.data["documents"][0]
        assert "restricted" not in row
        assert row["document"]["title"] == document_a.title

    def test_workflow_detail_is_withheld_without_workflow_permission(
        self, case_a, workflow_a, doer_a, outsider, tenant_a
    ):
        """Exercised against the projection directly, not through a role.

        Unlike documents, NO built-in role currently separates cases from
        workflows: PLATFORM_SUPPORT holds `workflows.view`, so it legitimately
        sees workflow detail. That is the platform's own configuration, not a
        leak -- but it means a role-based test here would prove nothing about
        the gate. `outsider` has no membership, so `has_workflow_permission`
        returns False, which is what the projection actually keys on.
        """
        from regulatory_cases.projection import can_view_workflows, project_links

        link = services.link_target(
            kind="workflow",
            case=case_a,
            target_public_id=workflow_a.public_id,
            actor=doer_a,
            tenant=case_a.tenant,
        )
        assert can_view_workflows(outsider, tenant_a) is False

        rows = project_links("workflow", [link], outsider, tenant_a)
        assert rows[0]["restricted"] is True
        assert "workflow" not in rows[0]
        assert workflow_a.title not in str(rows)

    def test_workflow_detail_is_shown_with_workflow_permission(
        self, case_a, workflow_a, doer_a, tenant_a
    ):
        from regulatory_cases.projection import project_links

        link = services.link_target(
            kind="workflow",
            case=case_a,
            target_public_id=workflow_a.public_id,
            actor=doer_a,
            tenant=case_a.tenant,
        )
        rows = project_links("workflow", [link], doer_a, tenant_a)
        assert "restricted" not in rows[0]
        assert rows[0]["workflow"]["title"] == workflow_a.title

    def test_restricted_row_still_carries_a_stable_identifier(
        self, client_support_a, case_a, document_a, doer_a
    ):
        """An opaque UUID discloses nothing, and the UI needs a stable key."""
        services.link_target(
            kind="document",
            case=case_a,
            target_public_id=document_a.public_id,
            actor=doer_a,
            tenant=case_a.tenant,
        )
        row = client_support_a.get(_url(case_a)).data["documents"][0]
        assert row["document_public_id"] == str(document_a.public_id)
        assert row["public_id"]

    def test_checklist_detail_is_withheld_without_checklist_permission(
        self, case_a, checklist_a, doer_a, outsider, tenant_a
    ):
        """The third of the three separations, proven the same way as workflows.

        PLATFORM_SUPPORT cannot serve here either -- what matters is the gate,
        and `outsider` has no membership, so `has_iig_checklist_permission`
        returns False, which is what the projection keys on.
        """
        from regulatory_cases.projection import can_view_checklists, project_links

        link = services.link_target(
            kind="checklist",
            case=case_a,
            target_public_id=checklist_a.public_id,
            actor=doer_a,
            tenant=tenant_a,
        )
        assert can_view_checklists(outsider, tenant_a) is False

        rows = project_links("checklist", [link], outsider, tenant_a)
        assert rows[0]["restricted"] is True
        assert "checklist" not in rows[0]
        # The execution's own status must not appear anywhere in the row.
        assert checklist_a.status not in str(rows[0].get("checklist", ""))

    def test_checklist_link_is_tenant_scoped(self, client_doer_a, case_a, checklist_b):
        """A checklist execution in another tenant cannot be linked, and the
        refusal is indistinguishable from an absent one."""
        cross = client_doer_a.post(
            _url(case_a, "checklists/"),
            {"target_public_id": str(checklist_b.public_id)},
            format="json",
        )
        missing = client_doer_a.post(
            _url(case_a, "checklists/"),
            {"target_public_id": str(uuid.uuid4())},
            format="json",
        )
        assert cross.status_code == missing.status_code == 400
        assert str(cross.data["target_public_id"]) == str(missing.data["target_public_id"])

    def test_checklist_link_duplicate_is_refused(self, client_doer_a, case_a, checklist_a):
        body = {"target_public_id": str(checklist_a.public_id)}
        assert (
            client_doer_a.post(_url(case_a, "checklists/"), body, format="json").status_code == 201
        )
        assert (
            client_doer_a.post(_url(case_a, "checklists/"), body, format="json").status_code == 409
        )

    def test_summary_state_counts_are_gated_on_workflow_permission(
        self, case_a, workflow_a, doer_a, outsider, tenant_a
    ):
        """The summary must not disclose through a count what the rows withhold.

        A caller who cannot see a single workflow title must not learn how many
        of the case's workflows are open, completed, or carry evidence.
        """
        from regulatory_cases.views import _summary

        services.link_target(
            kind="workflow",
            case=case_a,
            target_public_id=workflow_a.public_id,
            actor=doer_a,
            tenant=tenant_a,
        )
        links = {
            kind: services.active_links(kind=kind, case=case_a)
            for kind in ("workflow", "document", "checklist")
        }

        withheld = _summary(links, outsider, tenant_a)
        assert withheld["workflows"] == 1, "link count is case-level and stays visible"
        assert withheld["workflows_open"] is None
        assert withheld["workflows_completed"] is None
        assert withheld["evidence_links"] is None

        allowed = _summary(links, doer_a, tenant_a)
        assert allowed["workflows_open"] == 1
        assert allowed["evidence_links"] == 0

    def test_linked_by_email_is_never_projected(self, client_doer_a, case_a, document_a, doer_a):
        """The case permission entitles the caller to case activity, not to
        another member's personal data."""
        services.link_target(
            kind="document",
            case=case_a,
            target_public_id=document_a.public_id,
            actor=doer_a,
            tenant=case_a.tenant,
        )
        r = client_doer_a.get(_url(case_a))
        assert doer_a.email not in str(r.data)


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestAudit:
    def _events(self, case):
        from audit.models import AuditEvent

        return AuditEvent.objects.filter(resource_id=str(case.public_id))

    def test_create_complete_cancel_are_recorded(self, tenant_a, doer_a, vp_a):
        case = services.create_case(tenant=tenant_a, actor=doer_a, **CREATE_PAYLOAD)
        services.complete_case(case=case, tenant=tenant_a, actor=vp_a)
        types = set(self._events(case).values_list("event_type", flat=True))
        assert "regulatory_case.created" in types
        assert "regulatory_case.completed" in types

    def test_link_and_unlink_are_recorded(self, case_a, workflow_a, doer_a):
        link = services.link_target(
            kind="workflow",
            case=case_a,
            target_public_id=workflow_a.public_id,
            actor=doer_a,
            tenant=case_a.tenant,
        )
        services.unlink_target(
            kind="workflow",
            case=case_a,
            link_public_id=link.public_id,
            actor=doer_a,
            tenant=case_a.tenant,
        )
        types = set(self._events(case_a).values_list("event_type", flat=True))
        assert "regulatory_case.workflow_linked" in types
        assert "regulatory_case.workflow_unlinked" in types

    def test_document_title_is_never_audited(self, tenant_a, doer_a):
        """A document title can itself disclose the subject of a submission,
        and an audit row has different retention from the document."""
        from documents.models import Document

        doc = Document.objects.create(
            tenant=tenant_a, title="SECRET_PROJECT_CODENAME", document_type="other"
        )
        case = services.create_case(tenant=tenant_a, actor=doer_a, **CREATE_PAYLOAD)
        services.link_target(
            kind="document",
            case=case,
            target_public_id=doc.public_id,
            actor=doer_a,
            tenant=tenant_a,
        )
        payloads = str(list(self._events(case).values_list("payload", flat=True)))
        assert "SECRET_PROJECT_CODENAME" not in payloads

    def test_update_records_field_names_not_values(self, case_a, tenant_a, doer_a):
        services.update_case(
            case=case_a, tenant=tenant_a, actor=doer_a, product_name="CONFIDENTIAL_MOLECULE"
        )
        payloads = str(list(self._events(case_a).values_list("payload", flat=True)))
        assert "product_name" in payloads
        assert "CONFIDENTIAL_MOLECULE" not in payloads

    def test_reason_text_is_not_recorded(self, case_a, tenant_a, vp_a):
        services.cancel_case(
            case=case_a, tenant=tenant_a, actor=vp_a, reason="SENSITIVE_WITHDRAWAL_REASON"
        )
        payloads = str(list(self._events(case_a).values_list("payload", flat=True)))
        assert "SENSITIVE_WITHDRAWAL_REASON" not in payloads
        assert "reason_supplied" in payloads


# ---------------------------------------------------------------------------
# Deletion protection
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestDeletionProtection:
    def test_linked_document_cannot_be_deleted(self, case_a, document_a, doer_a):
        from django.db.models import ProtectedError

        services.link_target(
            kind="document",
            case=case_a,
            target_public_id=document_a.public_id,
            actor=doer_a,
            tenant=case_a.tenant,
        )
        with pytest.raises(ProtectedError):
            document_a.delete()

    def test_protection_survives_unlink(self, case_a, document_a, doer_a):
        """The historical record that a case cited a document is itself
        governed, so deleting the document would strand it."""
        from django.db.models import ProtectedError

        link = services.link_target(
            kind="document",
            case=case_a,
            target_public_id=document_a.public_id,
            actor=doer_a,
            tenant=case_a.tenant,
        )
        services.unlink_target(
            kind="document",
            case=case_a,
            link_public_id=link.public_id,
            actor=doer_a,
            tenant=case_a.tenant,
        )
        with pytest.raises(ProtectedError):
            document_a.delete()

    def test_linked_workflow_cannot_be_deleted(self, case_a, workflow_a, doer_a):
        from django.db.models import ProtectedError

        services.link_target(
            kind="workflow",
            case=case_a,
            target_public_id=workflow_a.public_id,
            actor=doer_a,
            tenant=case_a.tenant,
        )
        with pytest.raises(ProtectedError):
            workflow_a.delete()

    def test_case_with_links_cannot_be_deleted(self, case_a, workflow_a, doer_a):
        from django.db.models import ProtectedError

        services.link_target(
            kind="workflow",
            case=case_a,
            target_public_id=workflow_a.public_id,
            actor=doer_a,
            tenant=case_a.tenant,
        )
        with pytest.raises(ProtectedError):
            case_a.delete()

    def test_tenant_with_cases_cannot_be_deleted(self, tenant_a, case_a):
        from django.db.models import ProtectedError

        with pytest.raises(ProtectedError):
            tenant_a.delete()


# ---------------------------------------------------------------------------
# Summary counts
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestSummary:
    def test_counts_reflect_active_links_only(
        self, client_doer_a, case_a, workflow_a, document_a, doer_a
    ):
        services.link_target(
            kind="workflow",
            case=case_a,
            target_public_id=workflow_a.public_id,
            actor=doer_a,
            tenant=case_a.tenant,
        )
        link = services.link_target(
            kind="document",
            case=case_a,
            target_public_id=document_a.public_id,
            actor=doer_a,
            tenant=case_a.tenant,
        )
        services.unlink_target(
            kind="document",
            case=case_a,
            link_public_id=link.public_id,
            actor=doer_a,
            tenant=case_a.tenant,
        )
        summary = client_doer_a.get(_url(case_a)).data["summary"]
        assert summary["workflows"] == 1
        assert summary["documents"] == 0
        assert summary["workflows_open"] == 1
        assert summary["workflows_completed"] == 0

    def test_detail_query_count_does_not_grow_with_links(self, client_doer_a, tenant_a, doer_a):
        """Guards the N+1 risk by the property that matters: cost must be flat
        in the number of links.

        Asserting an absolute number would encode today's fixed overhead
        (authentication, tenant resolution and a membership lookup per module
        permission) and break on unrelated changes. What must never change is
        the SHAPE: ten links cost what one costs.
        """
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from workflows.models import WorkflowItem

        def measure(link_count: int) -> int:
            case = services.create_case(tenant=tenant_a, actor=doer_a, **CREATE_PAYLOAD)
            for i in range(link_count):
                item = WorkflowItem.objects.create(
                    tenant=tenant_a, title=f"Item {i}", created_by=doer_a
                )
                services.link_target(
                    kind="workflow",
                    case=case,
                    target_public_id=item.public_id,
                    actor=doer_a,
                    tenant=tenant_a,
                )
            url = _url(case)
            client_doer_a.get(url)  # warm lazily-built caches
            with CaptureQueriesContext(connection) as ctx:
                client_doer_a.get(url)
            return len(ctx.captured_queries)

        one, ten = measure(1), measure(10)
        assert one == ten, f"query count grows with links: 1 link -> {one}, 10 links -> {ten}"


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestUpdate:
    def test_patch_changes_only_supplied_fields(self, client_doer_a, case_a):
        r = client_doer_a.patch(_url(case_a), {"title": "Renamed"}, format="json")
        assert r.status_code == 200
        assert r.data["title"] == "Renamed"
        assert r.data["product_name"] == case_a.product_name

    def test_empty_patch_is_refused(self, client_doer_a, case_a):
        assert client_doer_a.patch(_url(case_a), {}, format="json").status_code == 400

    def test_case_number_cannot_be_patched(self, client_doer_a, case_a):
        client_doer_a.patch(_url(case_a), {"case_number": "RC-999999"}, format="json")
        case_a.refresh_from_db()
        assert case_a.case_number == "RC-000001"

    def test_status_cannot_be_patched_directly(self, client_doer_a, case_a):
        """Status moves only through complete/cancel, each with its own
        permission -- otherwise edit would silently grant both."""
        client_doer_a.patch(_url(case_a), {"status": "completed"}, format="json")
        case_a.refresh_from_db()
        assert case_a.status == CaseStatus.OPEN
