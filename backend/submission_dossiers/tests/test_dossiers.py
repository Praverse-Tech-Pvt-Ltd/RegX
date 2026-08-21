"""Submission dossiers: hierarchy, readiness, blockers, links, isolation.

Cross-tenant leakage, metadata leakage and hierarchy corruption are all
release-blocking. Synthetic data only.
"""

import uuid

import pytest

from submission_dossiers import services
from submission_dossiers.models import (
    DossierSection,
    DossierSectionBlocker,
    Readiness,
    ReadinessReason,
    SectionStatus,
)
from submission_dossiers.tests.conftest import make_section

CASES = "/api/regx/v1/regulatory-cases"
DOSS = "/api/regx/v1/submission-dossiers"
SECT = "/api/regx/v1/dossier-sections"


def _refresh(section):
    section.refresh_from_db()
    return section


# ---------------------------------------------------------------------------
# Dossier lifecycle and isolation
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestDossier:
    def test_create_and_list(self, client_doer_a, case_a):
        r = client_doer_a.post(
            f"{CASES}/{case_a.public_id}/dossiers/", {"title": "Initial"}, format="json"
        )
        assert r.status_code == 201, r.content[:300]
        assert r.data["status"] == "open"
        assert "id" not in r.data

        listing = client_doer_a.get(f"{CASES}/{case_a.public_id}/dossiers/")
        assert listing.status_code == 200
        assert len(listing.data["results"]) == 1

    def test_blank_title_refused(self, client_doer_a, case_a):
        r = client_doer_a.post(
            f"{CASES}/{case_a.public_id}/dossiers/", {"title": "  "}, format="json"
        )
        assert r.status_code == 400

    def test_owner_must_be_member_of_this_tenant(self, client_doer_a, case_a, doer_b):
        cross = client_doer_a.post(
            f"{CASES}/{case_a.public_id}/dossiers/",
            {"title": "X", "owner_public_id": str(doer_b.public_id)},
            format="json",
        )
        missing = client_doer_a.post(
            f"{CASES}/{case_a.public_id}/dossiers/",
            {"title": "X", "owner_public_id": str(uuid.uuid4())},
            format="json",
        )
        assert cross.status_code == missing.status_code == 400
        assert str(cross.data["owner_public_id"]) == str(missing.data["owner_public_id"])

    def test_cross_tenant_detail_is_404_and_indistinguishable(self, client_doer_a, dossier_b):
        cross = client_doer_a.get(f"{DOSS}/{dossier_b.public_id}/")
        missing = client_doer_a.get(f"{DOSS}/{uuid.uuid4()}/")
        assert cross.status_code == missing.status_code == 404
        assert str(cross.data) == str(missing.data)

    def test_cross_tenant_mutation_refused(self, client_doer_a, dossier_b):
        assert (
            client_doer_a.patch(
                f"{DOSS}/{dossier_b.public_id}/", {"title": "x"}, format="json"
            ).status_code
            == 404
        )

    def test_cancel_then_structural_change_refused(self, client_vp_a, client_doer_a, dossier_a):
        assert (
            client_vp_a.post(f"{DOSS}/{dossier_a.public_id}/cancel/", {}, format="json").status_code
            == 200
        )
        r = client_doer_a.post(
            f"{DOSS}/{dossier_a.public_id}/sections/",
            {"section_code": "1", "title": "T"},
            format="json",
        )
        assert r.status_code == 409

    def test_terminal_dossier_cannot_be_terminated_again(self, client_vp_a, dossier_a):
        client_vp_a.post(f"{DOSS}/{dossier_a.public_id}/cancel/", {}, format="json")
        again = client_vp_a.post(f"{DOSS}/{dossier_a.public_id}/cancel/", {}, format="json")
        assert again.status_code == 409

    def test_doer_cannot_complete_or_cancel(self, client_doer_a, dossier_a):
        assert (
            client_doer_a.post(
                f"{DOSS}/{dossier_a.public_id}/complete/", {}, format="json"
            ).status_code
            == 403
        )
        assert (
            client_doer_a.post(
                f"{DOSS}/{dossier_a.public_id}/cancel/", {}, format="json"
            ).status_code
            == 403
        )


# ---------------------------------------------------------------------------
# Hierarchy integrity -- security critical
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestHierarchy:
    def test_child_creation(self, dossier_a, tenant_a, doer_a, section_a):
        child = make_section(dossier_a, tenant_a, doer_a, "1.1", parent=section_a)
        assert child.parent_id == section_a.pk

    def test_self_parent_refused(self, dossier_a, tenant_a, doer_a, section_a):
        with pytest.raises(services.InvalidHierarchy):
            services.update_section(
                section=section_a, tenant=tenant_a, actor=doer_a, parent=section_a
            )

    def test_cycle_refused(self, dossier_a, tenant_a, doer_a, section_a):
        """Moving a parent beneath its own descendant would orphan the subtree
        from the root and make readiness aggregation non-terminating."""
        child = make_section(dossier_a, tenant_a, doer_a, "1.1", parent=section_a)
        grandchild = make_section(dossier_a, tenant_a, doer_a, "1.1.1", parent=child)

        for descendant in (child, grandchild):
            with pytest.raises(services.InvalidHierarchy):
                services.update_section(
                    section=section_a, tenant=tenant_a, actor=doer_a, parent=descendant
                )

    def test_cross_dossier_parent_refused(self, case_a, tenant_a, doer_a, dossier_a, section_a):
        other = services.create_dossier(
            case=case_a, tenant=tenant_a, actor=doer_a, title="Second dossier"
        )
        with pytest.raises(services.InvalidHierarchy):
            make_section(other, tenant_a, doer_a, "9", parent=section_a)

    def test_cross_tenant_parent_refused(self, dossier_a, tenant_a, doer_a, section_b):
        with pytest.raises(services.InvalidHierarchy):
            make_section(dossier_a, tenant_a, doer_a, "9", parent=section_b)

    def test_depth_limit_enforced(self, dossier_a, tenant_a, doer_a):
        """An operational ceiling, not a regulatory one -- it keeps the ancestor
        walk cheap and stops a hostile payload building an arbitrarily deep
        chain."""
        from submission_dossiers.models import MAX_SECTION_DEPTH

        parent = None
        for i in range(MAX_SECTION_DEPTH):
            parent = make_section(dossier_a, tenant_a, doer_a, f"d{i}", parent=parent)

        with pytest.raises(services.InvalidHierarchy):
            make_section(dossier_a, tenant_a, doer_a, "too-deep", parent=parent)

    def test_retired_parent_refused(self, dossier_a, tenant_a, doer_a, section_a):
        services.retire_section(section=section_a, tenant=tenant_a, actor=doer_a)
        with pytest.raises(services.InvalidHierarchy):
            make_section(dossier_a, tenant_a, doer_a, "2", parent=section_a)

    def test_section_code_unique_per_dossier(self, dossier_a, tenant_a, doer_a, section_a):
        with pytest.raises(services.DuplicateLink):
            make_section(dossier_a, tenant_a, doer_a, "1")

    def test_retired_code_may_be_reused(self, dossier_a, tenant_a, doer_a, section_a):
        """The uniqueness constraint is partial on retired_at, so retiring a
        section frees its code -- otherwise a typo would burn a code forever."""
        services.retire_section(section=section_a, tenant=tenant_a, actor=doer_a)
        again = make_section(dossier_a, tenant_a, doer_a, "1")
        assert again.section_code == "1"


@pytest.mark.django_db
class TestOrdering:
    def test_siblings_get_distinct_sequences(self, dossier_a, tenant_a, doer_a):
        a = make_section(dossier_a, tenant_a, doer_a, "1")
        b = make_section(dossier_a, tenant_a, doer_a, "2")
        c = make_section(dossier_a, tenant_a, doer_a, "3")
        assert len({a.sequence, b.sequence, c.sequence}) == 3

    def test_reorder_moves_and_keeps_sequences_distinct(self, dossier_a, tenant_a, doer_a):
        a = make_section(dossier_a, tenant_a, doer_a, "1")
        b = make_section(dossier_a, tenant_a, doer_a, "2")
        c = make_section(dossier_a, tenant_a, doer_a, "3")

        services.reorder_section(section=c, tenant=tenant_a, actor=doer_a, sequence=0)

        order = list(
            DossierSection.objects.filter(dossier=dossier_a, retired_at__isnull=True)
            .order_by("sequence", "id")
            .values_list("section_code", flat=True)
        )
        assert order == ["3", "1", "2"]
        seqs = list(
            DossierSection.objects.filter(dossier=dossier_a).values_list("sequence", flat=True)
        )
        assert len(set(seqs)) == len(seqs), "sequences must stay distinct among siblings"
        assert {a.pk, b.pk, c.pk}

    def test_reorder_beyond_end_clamps(self, dossier_a, tenant_a, doer_a):
        a = make_section(dossier_a, tenant_a, doer_a, "1")
        make_section(dossier_a, tenant_a, doer_a, "2")
        services.reorder_section(section=a, tenant=tenant_a, actor=doer_a, sequence=99)
        order = list(
            DossierSection.objects.filter(dossier=dossier_a)
            .order_by("sequence", "id")
            .values_list("section_code", flat=True)
        )
        assert order == ["2", "1"]


# ---------------------------------------------------------------------------
# Readiness -- derived, never claimed
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestReadiness:
    def test_new_section_is_not_ready(self, section_a):
        assert section_a.readiness == Readiness.NOT_READY
        assert section_a.readiness_reason == ReadinessReason.NO_SUPPORTING_WORK

    def test_not_applicable_short_circuits(self, section_a, tenant_a, doer_a):
        s = services.update_section(
            section=section_a,
            tenant=tenant_a,
            actor=doer_a,
            status=SectionStatus.NOT_APPLICABLE,
        )
        assert s.readiness == Readiness.NOT_APPLICABLE

    def test_complete_becomes_ready(self, section_a, tenant_a, doer_a):
        s = services.update_section(
            section=section_a, tenant=tenant_a, actor=doer_a, status=SectionStatus.COMPLETE
        )
        assert s.readiness == Readiness.READY
        assert s.readiness_reason == ReadinessReason.READY

    def test_in_progress_is_partially_ready(self, section_a, tenant_a, doer_a):
        s = services.update_section(
            section=section_a, tenant=tenant_a, actor=doer_a, status=SectionStatus.IN_PROGRESS
        )
        assert s.readiness == Readiness.PARTIALLY_READY

    def test_a_linked_document_counts_as_supporting_work(
        self, section_a, tenant_a, doer_a, document_a
    ):
        services.link_target(
            kind="document",
            section=section_a,
            target_public_id=document_a.public_id,
            actor=doer_a,
            tenant=tenant_a,
        )
        assert _refresh(section_a).readiness == Readiness.PARTIALLY_READY

    def test_open_blocker_prevents_ready(self, section_a, tenant_a, doer_a):
        services.update_section(
            section=section_a, tenant=tenant_a, actor=doer_a, status=SectionStatus.COMPLETE
        )
        assert _refresh(section_a).readiness == Readiness.READY

        services.create_blocker(
            section=section_a, tenant=tenant_a, actor=doer_a, title="Missing data"
        )
        s = _refresh(section_a)
        assert s.readiness == Readiness.NOT_READY
        assert s.readiness_reason == ReadinessReason.OPEN_BLOCKER

    def test_resolving_the_blocker_restores_ready(self, section_a, tenant_a, doer_a):
        services.update_section(
            section=section_a, tenant=tenant_a, actor=doer_a, status=SectionStatus.COMPLETE
        )
        blocker = services.create_blocker(
            section=section_a, tenant=tenant_a, actor=doer_a, title="Missing data"
        )
        services.resolve_blocker(blocker=blocker, tenant=tenant_a, actor=doer_a)
        assert _refresh(section_a).readiness == Readiness.READY

    def test_required_child_holds_parent_back(self, dossier_a, tenant_a, doer_a, section_a):
        child = make_section(dossier_a, tenant_a, doer_a, "1.1", parent=section_a, required=True)
        services.update_section(
            section=section_a, tenant=tenant_a, actor=doer_a, status=SectionStatus.COMPLETE
        )
        parent = _refresh(section_a)
        assert parent.readiness == Readiness.PARTIALLY_READY
        assert parent.readiness_reason == ReadinessReason.REQUIRED_CHILD_NOT_READY

        services.update_section(
            section=child, tenant=tenant_a, actor=doer_a, status=SectionStatus.COMPLETE
        )
        assert _refresh(section_a).readiness == Readiness.READY

    def test_optional_child_does_not_hold_parent_back(self, dossier_a, tenant_a, doer_a, section_a):
        make_section(dossier_a, tenant_a, doer_a, "1.1", parent=section_a, required=False)
        services.update_section(
            section=section_a, tenant=tenant_a, actor=doer_a, status=SectionStatus.COMPLETE
        )
        assert _refresh(section_a).readiness == Readiness.READY

    def test_not_applicable_child_does_not_hold_parent_back(
        self, dossier_a, tenant_a, doer_a, section_a
    ):
        """Otherwise ruling a section out would make its parent permanently
        unreachable."""
        child = make_section(dossier_a, tenant_a, doer_a, "1.1", parent=section_a, required=True)
        services.update_section(
            section=child, tenant=tenant_a, actor=doer_a, status=SectionStatus.NOT_APPLICABLE
        )
        services.update_section(
            section=section_a, tenant=tenant_a, actor=doer_a, status=SectionStatus.COMPLETE
        )
        assert _refresh(section_a).readiness == Readiness.READY

    def test_grandchild_propagates_up_two_levels(self, dossier_a, tenant_a, doer_a, section_a):
        child = make_section(dossier_a, tenant_a, doer_a, "1.1", parent=section_a)
        grandchild = make_section(dossier_a, tenant_a, doer_a, "1.1.1", parent=child)

        for s in (section_a, child):
            services.update_section(
                section=s, tenant=tenant_a, actor=doer_a, status=SectionStatus.COMPLETE
            )
        assert _refresh(section_a).readiness == Readiness.PARTIALLY_READY

        services.update_section(
            section=grandchild, tenant=tenant_a, actor=doer_a, status=SectionStatus.COMPLETE
        )
        assert _refresh(child).readiness == Readiness.READY
        assert _refresh(section_a).readiness == Readiness.READY

    def test_readiness_cannot_be_set_directly(self, client_doer_a, section_a):
        """Derived, never claimed: the serializer has no `readiness` field."""
        client_doer_a.patch(f"{SECT}/{section_a.public_id}/", {"readiness": "ready"}, format="json")
        assert _refresh(section_a).readiness == Readiness.NOT_READY


@pytest.mark.django_db
class TestDossierAggregation:
    def test_empty_dossier_is_not_ready(self, client_doer_a, dossier_a):
        """An empty outline is not a finished one. Reporting READY for it would
        be the most misleading possible answer."""
        r = client_doer_a.get(f"{DOSS}/{dossier_a.public_id}/")
        assert r.data["summary"]["overall_readiness"] == Readiness.NOT_READY
        assert r.data["summary"]["total_sections"] == 0

    def test_summary_counts(self, client_doer_a, dossier_a, tenant_a, doer_a):
        a = make_section(dossier_a, tenant_a, doer_a, "1")
        make_section(dossier_a, tenant_a, doer_a, "2", required=False)
        c = make_section(dossier_a, tenant_a, doer_a, "3")
        services.update_section(
            section=a, tenant=tenant_a, actor=doer_a, status=SectionStatus.COMPLETE
        )
        services.update_section(
            section=c, tenant=tenant_a, actor=doer_a, status=SectionStatus.NOT_APPLICABLE
        )

        s = client_doer_a.get(f"{DOSS}/{dossier_a.public_id}/").data["summary"]
        assert s["total_sections"] == 3
        assert s["required_sections"] == 2
        assert s["ready"] == 1
        assert s["not_applicable"] == 1

    def test_overall_ready_only_when_every_required_section_is(
        self, client_doer_a, dossier_a, tenant_a, doer_a
    ):
        a = make_section(dossier_a, tenant_a, doer_a, "1")
        b = make_section(dossier_a, tenant_a, doer_a, "2")
        services.update_section(
            section=a, tenant=tenant_a, actor=doer_a, status=SectionStatus.COMPLETE
        )
        mid = client_doer_a.get(f"{DOSS}/{dossier_a.public_id}/").data["summary"]
        assert mid["overall_readiness"] == Readiness.PARTIALLY_READY

        services.update_section(
            section=b, tenant=tenant_a, actor=doer_a, status=SectionStatus.COMPLETE
        )
        done = client_doer_a.get(f"{DOSS}/{dossier_a.public_id}/").data["summary"]
        assert done["overall_readiness"] == Readiness.READY


@pytest.mark.django_db
class TestCompletionGate:
    def test_completion_refused_while_not_ready(self, client_vp_a, dossier_a, tenant_a, doer_a):
        make_section(dossier_a, tenant_a, doer_a, "1")
        r = client_vp_a.post(f"{DOSS}/{dossier_a.public_id}/complete/", {}, format="json")
        assert r.status_code == 409
        assert "reason_code" in r.data

    def test_completion_allowed_when_ready(self, client_vp_a, dossier_a, tenant_a, doer_a):
        s = make_section(dossier_a, tenant_a, doer_a, "1")
        services.update_section(
            section=s, tenant=tenant_a, actor=doer_a, status=SectionStatus.COMPLETE
        )
        r = client_vp_a.post(f"{DOSS}/{dossier_a.public_id}/complete/", {}, format="json")
        assert r.status_code == 200, r.content[:300]
        assert r.data["status"] == "completed"

    def test_refusal_names_no_restricted_resource(
        self, client_vp_a, dossier_a, tenant_a, doer_a, document_a
    ):
        """The refusal carries a reason CODE, never the identity of a section
        or resource the caller may not be entitled to see."""
        s = make_section(dossier_a, tenant_a, doer_a, "1")
        services.link_target(
            kind="document",
            section=s,
            target_public_id=document_a.public_id,
            actor=doer_a,
            tenant=tenant_a,
        )
        r = client_vp_a.post(f"{DOSS}/{dossier_a.public_id}/complete/", {}, format="json")
        assert r.status_code == 409
        body = str(r.data)
        assert document_a.title not in body
        assert s.title not in body

    def test_completion_is_not_an_approval_claim(self, client_vp_a, dossier_a, tenant_a, doer_a):
        """Guards the wording: a regulatory boundary, not a nicety."""
        s = make_section(dossier_a, tenant_a, doer_a, "1")
        services.update_section(
            section=s, tenant=tenant_a, actor=doer_a, status=SectionStatus.COMPLETE
        )
        r = client_vp_a.post(f"{DOSS}/{dossier_a.public_id}/complete/", {}, format="json")
        body = str(r.data).lower()
        for forbidden in (
            "approved",
            "approval",
            "compliant",
            "agency",
            "authorised",
            "authorized",
        ):
            assert forbidden not in body


# ---------------------------------------------------------------------------
# Blockers
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestBlockers:
    def test_create_and_resolve(self, client_doer_a, section_a, tenant_a, doer_a):
        r = client_doer_a.post(
            f"{SECT}/{section_a.public_id}/blockers/", {"title": "Missing"}, format="json"
        )
        assert r.status_code == 201
        assert r.data["status"] == "open"

        resolved = client_doer_a.post(
            f"/api/regx/v1/section-blockers/{r.data['public_id']}/resolve/", {}, format="json"
        )
        assert resolved.status_code == 200
        assert resolved.data["status"] == "resolved"
        assert resolved.data["resolved_by"] is not None

    def test_double_resolution_refused(self, section_a, tenant_a, doer_a):
        b = services.create_blocker(
            section=section_a, tenant=tenant_a, actor=doer_a, title="Missing"
        )
        services.resolve_blocker(blocker=b, tenant=tenant_a, actor=doer_a)
        with pytest.raises(services.DossierLocked):
            services.resolve_blocker(blocker=b, tenant=tenant_a, actor=doer_a)

    def test_history_is_retained_after_resolution(self, section_a, tenant_a, doer_a):
        b = services.create_blocker(
            section=section_a, tenant=tenant_a, actor=doer_a, title="Missing"
        )
        services.resolve_blocker(blocker=b, tenant=tenant_a, actor=doer_a)
        assert DossierSectionBlocker.objects.filter(pk=b.pk).exists()

    def test_resolution_consistency_is_enforced_by_the_database(self, section_a, tenant_a, doer_a):
        """A resolved blocker must carry who and when. Without the constraint
        the two halves could drift and a resolved row could exist with no
        accountability on it."""
        from django.db import IntegrityError, transaction

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                DossierSectionBlocker.objects.create(
                    tenant=tenant_a,
                    section=section_a,
                    title="Bad",
                    status="resolved",
                    created_by=doer_a,
                )

    def test_cross_tenant_blocker_is_404(self, client_doer_a, section_b, tenant_b, doer_b):
        b = services.create_blocker(
            section=section_b, tenant=tenant_b, actor=doer_b, title="Other tenant"
        )
        r = client_doer_a.post(
            f"/api/regx/v1/section-blockers/{b.public_id}/resolve/", {}, format="json"
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Section retirement and deletion protection
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestRetirementAndDeletionProtection:
    def test_retire_keeps_the_row(self, section_a, tenant_a, doer_a):
        services.retire_section(section=section_a, tenant=tenant_a, actor=doer_a)
        s = _refresh(section_a)
        assert s.retired_at is not None
        assert s.retired_by_id == doer_a.pk
        assert DossierSection.objects.filter(pk=s.pk).exists()

    def test_retire_refused_while_children_are_active(self, dossier_a, tenant_a, doer_a, section_a):
        make_section(dossier_a, tenant_a, doer_a, "1.1", parent=section_a)
        with pytest.raises(services.InvalidHierarchy):
            services.retire_section(section=section_a, tenant=tenant_a, actor=doer_a)

    def test_retired_section_refuses_further_change(self, section_a, tenant_a, doer_a):
        services.retire_section(section=section_a, tenant=tenant_a, actor=doer_a)
        with pytest.raises(services.DossierLocked):
            services.update_section(
                section=section_a, tenant=tenant_a, actor=doer_a, title="Renamed"
            )

    def test_linked_document_cannot_be_deleted(self, section_a, tenant_a, doer_a, document_a):
        from django.db.models import ProtectedError

        services.link_target(
            kind="document",
            section=section_a,
            target_public_id=document_a.public_id,
            actor=doer_a,
            tenant=tenant_a,
        )
        with pytest.raises(ProtectedError):
            document_a.delete()

    def test_protection_survives_unlink(self, section_a, tenant_a, doer_a, document_a):
        from django.db.models import ProtectedError

        link = services.link_target(
            kind="document",
            section=section_a,
            target_public_id=document_a.public_id,
            actor=doer_a,
            tenant=tenant_a,
        )
        services.unlink_target(
            kind="document",
            section=section_a,
            link_public_id=link.public_id,
            actor=doer_a,
            tenant=tenant_a,
        )
        with pytest.raises(ProtectedError):
            document_a.delete()

    def test_section_with_links_cannot_be_deleted(self, section_a, tenant_a, doer_a, document_a):
        from django.db.models import ProtectedError

        services.link_target(
            kind="document",
            section=section_a,
            target_public_id=document_a.public_id,
            actor=doer_a,
            tenant=tenant_a,
        )
        with pytest.raises(ProtectedError):
            section_a.delete()

    def test_dossier_with_sections_cannot_be_deleted(self, dossier_a, section_a):
        from django.db.models import ProtectedError

        with pytest.raises(ProtectedError):
            dossier_a.delete()

    def test_case_with_dossiers_cannot_be_deleted(self, case_a, dossier_a):
        from django.db.models import ProtectedError

        with pytest.raises(ProtectedError):
            case_a.delete()

    def test_tenant_with_dossiers_cannot_be_deleted(self, tenant_a, dossier_a):
        from django.db.models import ProtectedError

        with pytest.raises(ProtectedError):
            tenant_a.delete()


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestAudit:
    def _events(self, dossier):
        from audit.models import AuditEvent

        return AuditEvent.objects.filter(resource_id=str(dossier.public_id))

    def test_lifecycle_events_recorded(self, dossier_a, tenant_a, doer_a, vp_a, section_a):
        services.update_section(
            section=section_a, tenant=tenant_a, actor=doer_a, status=SectionStatus.COMPLETE
        )
        services.complete_dossier(dossier=dossier_a, tenant=tenant_a, actor=vp_a)
        types = set(self._events(dossier_a).values_list("event_type", flat=True))
        assert "submission_dossier.created" in types
        assert "dossier_section.created" in types
        assert "dossier_section.completed" in types
        assert "submission_dossier.completed" in types

    def test_link_and_unlink_recorded(self, section_a, dossier_a, tenant_a, doer_a, document_a):
        link = services.link_target(
            kind="document",
            section=section_a,
            target_public_id=document_a.public_id,
            actor=doer_a,
            tenant=tenant_a,
        )
        services.unlink_target(
            kind="document",
            section=section_a,
            link_public_id=link.public_id,
            actor=doer_a,
            tenant=tenant_a,
        )
        types = set(self._events(dossier_a).values_list("event_type", flat=True))
        assert "dossier_section.document_linked" in types
        assert "dossier_section.document_unlinked" in types

    def test_free_text_never_reaches_the_payload(self, dossier_a, tenant_a, doer_a):
        """Section titles, notes and blocker text describe the submission, and
        an audit row has different retention from the section."""
        s = make_section(
            dossier_a,
            tenant_a,
            doer_a,
            "1",
            description="SECRET_PRODUCT_DESCRIPTION",
            notes="SECRET_INTERNAL_NOTE",
        )
        services.create_blocker(
            section=s,
            tenant=tenant_a,
            actor=doer_a,
            title="SECRET_BLOCKER_TITLE",
            description="SECRET_BLOCKER_DETAIL",
        )
        payloads = str(list(self._events(dossier_a).values_list("payload", flat=True)))
        for secret in (
            "SECRET_PRODUCT_DESCRIPTION",
            "SECRET_INTERNAL_NOTE",
            "SECRET_BLOCKER_TITLE",
            "SECRET_BLOCKER_DETAIL",
        ):
            assert secret not in payloads

    def test_update_records_field_names_not_values(self, section_a, dossier_a, tenant_a, doer_a):
        services.update_section(
            section=section_a, tenant=tenant_a, actor=doer_a, title="CONFIDENTIAL_TITLE"
        )
        payloads = str(list(self._events(dossier_a).values_list("payload", flat=True)))
        assert "title" in payloads
        assert "CONFIDENTIAL_TITLE" not in payloads
