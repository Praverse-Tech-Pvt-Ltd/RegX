"""Workflow evidence: version pinning, two-gate authorization, tenant
isolation, state rules, concurrency, audit and deletion protection.

Cross-tenant leakage here is release-blocking. Synthetic data only.
"""

import io
import threading
import uuid

import pytest
from django.db import InternalError, ProgrammingError, connection, transaction

from workflows import services
from workflows.models import WorkflowEvidence, WorkflowItem

S = WorkflowItem.State


# ---------------------------------------------------------------------------
# Fixtures -- real documents, through the document platform's own storage API.
# ---------------------------------------------------------------------------
def _make_version(
    tenant, uploader, *, title="Evidence doc", scan_status="clean", body=b"SYNTHETIC"
):
    import hashlib

    from documents.models import Document, DocumentVersion
    from documents.storage import get_storage_backend

    digest = hashlib.sha256(body).hexdigest()
    doc, _ = Document.objects.get_or_create(
        tenant=tenant, title=title, defaults={"document_type": "other"}
    )
    key = get_storage_backend().store(
        tenant_id=tenant.pk,
        file_obj=io.BytesIO(body),
        expected_sha256=digest,
        content_type="text/plain",
        original_filename=f"{title}.txt",
    )
    next_number = doc.versions.count() + 1
    return DocumentVersion.objects.create(
        document=doc,
        version_number=next_number,
        original_filename=f"{title}.txt",
        normalized_filename=f"{title}.txt",
        extension="txt",
        declared_mime_type="text/plain",
        size_bytes=len(body),
        sha256_checksum=digest,
        storage_key=key,
        scan_status=scan_status,
        uploaded_by=uploader,
    )


@pytest.fixture
def version_a(db, tenant_a, doer_a):
    return _make_version(tenant_a, doer_a, title="Tenant A evidence")


@pytest.fixture
def version_b(db, tenant_b, doer_b):
    return _make_version(tenant_b, doer_b, title="Tenant B evidence")


def _url(item, suffix=""):
    return f"/api/regx/v1/workflows/{item.public_id}/evidence/{suffix}"


# ---------------------------------------------------------------------------
# Exact-version pinning -- the core invariant
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestExactVersionPinning:
    def test_evidence_points_at_the_version_not_the_document(
        self, item_a, tenant_a, doer_a, version_a
    ):
        record = services.link_evidence(
            item=item_a,
            document_version_public_id=version_a.public_id,
            actor=doer_a,
            tenant=tenant_a,
        )
        assert record.document_version_id == version_a.pk
        assert record.document_version.sha256_checksum == version_a.sha256_checksum

    def test_a_newer_version_does_not_move_historical_evidence(
        self, item_a, tenant_a, doer_a, version_a
    ):
        """The invariant §12 exists for: upload N+1, evidence still means N."""
        record = services.link_evidence(
            item=item_a,
            document_version_public_id=version_a.public_id,
            actor=doer_a,
            tenant=tenant_a,
        )
        original_checksum = version_a.sha256_checksum

        newer = _make_version(
            tenant_a, doer_a, title="Tenant A evidence", body=b"COMPLETELY DIFFERENT CONTENT"
        )
        assert newer.document_id == version_a.document_id
        assert newer.version_number == version_a.version_number + 1
        assert newer.sha256_checksum != original_checksum

        record.refresh_from_db()
        assert record.document_version_id == version_a.pk, "evidence must not follow latest"
        assert record.document_version.sha256_checksum == original_checksum


# ---------------------------------------------------------------------------
# Security gate -- reuse of the document platform's scan rules
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestSecurityGate:
    @pytest.mark.parametrize(
        "scan_status",
        ["pending", "infected", "quarantined", "scan_failed", "scanner_unavailable"],
    )
    def test_only_clean_versions_may_be_linked(self, item_a, tenant_a, doer_a, scan_status):
        version = _make_version(
            tenant_a, doer_a, title=f"Doc {scan_status}", scan_status=scan_status
        )
        with pytest.raises(services.InvalidEvidenceTarget):
            services.link_evidence(
                item=item_a,
                document_version_public_id=version.public_id,
                actor=doer_a,
                tenant=tenant_a,
            )
        assert WorkflowEvidence.objects.count() == 0

    def test_clean_version_is_linkable(self, item_a, tenant_a, doer_a, version_a):
        record = services.link_evidence(
            item=item_a,
            document_version_public_id=version_a.public_id,
            actor=doer_a,
            tenant=tenant_a,
        )
        assert record.is_active


# ---------------------------------------------------------------------------
# Tenant isolation -- release-blocking
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestTenantIsolation:
    def test_cannot_link_another_tenants_version(self, item_a, tenant_a, doer_a, version_b):
        with pytest.raises(services.InvalidEvidenceTarget):
            services.link_evidence(
                item=item_a,
                document_version_public_id=version_b.public_id,
                actor=doer_a,
                tenant=tenant_a,
            )
        assert WorkflowEvidence.objects.count() == 0

    def test_cross_tenant_and_nonexistent_are_indistinguishable(
        self, client_doer_a, item_a, version_b
    ):
        """Different wording would let a caller probe for documents in other
        tenants, and would disclose the scan state of one they cannot see."""
        cross = client_doer_a.post(
            _url(item_a), {"document_version_public_id": str(version_b.public_id)}, format="json"
        )
        missing = client_doer_a.post(
            _url(item_a), {"document_version_public_id": str(uuid.uuid4())}, format="json"
        )
        assert cross.status_code == missing.status_code == 400
        cross_msg = cross.data["error"]["detail"]["document_version_public_id"]
        missing_msg = missing.data["error"]["detail"]["document_version_public_id"]
        assert str(cross_msg) == str(missing_msg)

    def test_quarantined_and_nonexistent_are_indistinguishable(
        self, client_doer_a, item_a, tenant_a, doer_a
    ):
        """Scan state of a version must not leak through the error either."""
        dirty = _make_version(tenant_a, doer_a, title="Quarantined", scan_status="quarantined")
        blocked = client_doer_a.post(
            _url(item_a), {"document_version_public_id": str(dirty.public_id)}, format="json"
        )
        missing = client_doer_a.post(
            _url(item_a), {"document_version_public_id": str(uuid.uuid4())}, format="json"
        )
        assert str(blocked.data["error"]["detail"]["document_version_public_id"]) == str(
            missing.data["error"]["detail"]["document_version_public_id"]
        )

    def test_evidence_list_is_tenant_scoped(self, client_doer_a, client_doer_b, item_b, version_b):
        services.link_evidence(
            item=item_b,
            document_version_public_id=version_b.public_id,
            actor=item_b.created_by,
            tenant=item_b.tenant,
        )
        assert client_doer_a.get(_url(item_b)).status_code == 404
        assert client_doer_b.get(_url(item_b)).status_code == 200

    def test_evidence_public_id_not_usable_cross_tenant(self, client_doer_a, item_b, version_b):
        record = services.link_evidence(
            item=item_b,
            document_version_public_id=version_b.public_id,
            actor=item_b.created_by,
            tenant=item_b.tenant,
        )
        resp = client_doer_a.delete(_url(item_b, f"{record.public_id}/"))
        assert resp.status_code == 404
        record.refresh_from_db()
        assert record.is_active


# ---------------------------------------------------------------------------
# Two independent authorization gates
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestTwoAuthorizationGates:
    def test_workflow_permission_alone_does_not_grant_document_detail(
        self, tenant_a, item_a, doer_a, version_a
    ):
        """PLATFORM_SUPPORT holds workflows.view and NO document permission.
        It may see that evidence exists; it must not see document detail."""
        from rest_framework.test import APIClient

        from workflows.tests.conftest import _make_user, _membership_with_role

        services.link_evidence(
            item=item_a,
            document_version_public_id=version_a.public_id,
            actor=doer_a,
            tenant=tenant_a,
        )
        support = _make_user("wf-support-a@example.com", "Support A")
        _membership_with_role(tenant_a, support, "platform_support")
        client = APIClient()
        client.force_authenticate(user=support)
        client.credentials(HTTP_X_TENANT_SLUG=tenant_a.slug)

        resp = client.get(_url(item_a))
        assert resp.status_code == 200
        row = resp.data[0]
        assert "document" not in row, "document detail leaked to a caller without documents.view"
        # Identity is still present -- opaque UUIDs disclose nothing alone.
        assert row["document_version_public_id"] == str(version_a.public_id)

    def test_document_viewer_sees_detail(self, client_doer_a, item_a, tenant_a, doer_a, version_a):
        services.link_evidence(
            item=item_a,
            document_version_public_id=version_a.public_id,
            actor=doer_a,
            tenant=tenant_a,
        )
        row = client_doer_a.get(_url(item_a)).data[0]
        assert row["document"]["sha256_checksum"] == version_a.sha256_checksum

    def test_linking_requires_document_permission(self, tenant_a, item_a, version_a):
        """A role with workflows.manage_evidence but no documents.view must not
        be able to cite a document it cannot see."""
        from rest_framework.test import APIClient

        from authorization.models import MembershipRole, Role
        from tenancy.models import TenantMembership
        from workflows.permissions import ROLE_PERMISSIONS
        from workflows.tests.conftest import _make_user

        user = _make_user("wf-evidence-only@example.com", "Evidence Only")
        membership, _ = TenantMembership.objects.get_or_create(tenant=tenant_a, user=user)
        role, _ = Role.objects.get_or_create(tenant=tenant_a, name="evidence_only")
        MembershipRole.objects.get_or_create(membership=membership, role=role)
        ROLE_PERMISSIONS["evidence_only"] = ["workflows.view", "workflows.manage_evidence"]
        try:
            client = APIClient()
            client.force_authenticate(user=user)
            client.credentials(HTTP_X_TENANT_SLUG=tenant_a.slug)
            resp = client.post(
                _url(item_a),
                {"document_version_public_id": str(version_a.public_id)},
                format="json",
            )
            assert resp.status_code == 403
            assert WorkflowEvidence.objects.count() == 0
        finally:
            ROLE_PERMISSIONS.pop("evidence_only", None)

    def test_reviewer_cannot_manage_evidence(self, client_reviewer_a, item_a, version_a):
        resp = client_reviewer_a.post(
            _url(item_a), {"document_version_public_id": str(version_a.public_id)}, format="json"
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Workflow state rules
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestStateRules:
    def _advance(self, item, tenant, doer, reviewer, to_state):
        services.perform_transition(item=item, action="submit", actor=doer, tenant=tenant)
        if to_state == S.SUBMITTED:
            return
        services.perform_transition(item=item, action="begin_review", actor=reviewer, tenant=tenant)
        if to_state == S.IN_REVIEW:
            return
        if to_state == S.APPROVED:
            services.perform_transition(item=item, action="approve", actor=reviewer, tenant=tenant)
        elif to_state == S.REJECTED:
            services.perform_transition(
                item=item, action="reject", actor=reviewer, tenant=tenant, reason="no"
            )

    @pytest.mark.parametrize("state", [S.SUBMITTED, S.IN_REVIEW, S.APPROVED, S.REJECTED])
    def test_evidence_locked_outside_draft(
        self, item_a, tenant_a, doer_a, reviewer_a, version_a, state
    ):
        self._advance(item_a, tenant_a, doer_a, reviewer_a, state)
        item_a.refresh_from_db()
        with pytest.raises(services.EvidenceLocked):
            services.link_evidence(
                item=item_a,
                document_version_public_id=version_a.public_id,
                actor=doer_a,
                tenant=tenant_a,
            )

    def test_cancelled_evidence_is_immutable(self, item_a, tenant_a, doer_a, version_a):
        record = services.link_evidence(
            item=item_a,
            document_version_public_id=version_a.public_id,
            actor=doer_a,
            tenant=tenant_a,
        )
        services.perform_transition(
            item=item_a, action="cancel", actor=doer_a, tenant=tenant_a, reason="stop"
        )
        item_a.refresh_from_db()
        with pytest.raises(services.EvidenceLocked):
            services.unlink_evidence(
                item=item_a, evidence_public_id=record.public_id, actor=doer_a, tenant=tenant_a
            )
        record.refresh_from_db()
        assert record.is_active, "approved/cancelled evidence must survive intact"

    def test_return_to_draft_reopens_evidence(
        self, item_a, tenant_a, doer_a, reviewer_a, version_a
    ):
        self._advance(item_a, tenant_a, doer_a, reviewer_a, S.REJECTED)
        item_a.refresh_from_db()
        services.perform_transition(
            item=item_a, action="return_to_draft", actor=doer_a, tenant=tenant_a
        )
        item_a.refresh_from_db()
        record = services.link_evidence(
            item=item_a,
            document_version_public_id=version_a.public_id,
            actor=doer_a,
            tenant=tenant_a,
        )
        assert record.is_active


# ---------------------------------------------------------------------------
# Duplicates, unlink and relink
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestDuplicatesAndUnlink:
    def test_duplicate_link_refused(self, item_a, tenant_a, doer_a, version_a):
        services.link_evidence(
            item=item_a,
            document_version_public_id=version_a.public_id,
            actor=doer_a,
            tenant=tenant_a,
        )
        with pytest.raises(services.DuplicateEvidence):
            services.link_evidence(
                item=item_a,
                document_version_public_id=version_a.public_id,
                actor=doer_a,
                tenant=tenant_a,
            )
        assert WorkflowEvidence.objects.filter(unlinked_at__isnull=True).count() == 1

    def test_unlink_preserves_the_row(self, item_a, tenant_a, doer_a, version_a):
        record = services.link_evidence(
            item=item_a,
            document_version_public_id=version_a.public_id,
            actor=doer_a,
            tenant=tenant_a,
        )
        services.unlink_evidence(
            item=item_a, evidence_public_id=record.public_id, actor=doer_a, tenant=tenant_a
        )
        record.refresh_from_db()
        assert record.unlinked_at is not None
        assert record.unlinked_by_id == doer_a.pk
        assert WorkflowEvidence.objects.filter(pk=record.pk).exists(), "history must survive"

    def test_relink_after_unlink_is_allowed(self, item_a, tenant_a, doer_a, version_a):
        first = services.link_evidence(
            item=item_a,
            document_version_public_id=version_a.public_id,
            actor=doer_a,
            tenant=tenant_a,
        )
        services.unlink_evidence(
            item=item_a, evidence_public_id=first.public_id, actor=doer_a, tenant=tenant_a
        )
        second = services.link_evidence(
            item=item_a,
            document_version_public_id=version_a.public_id,
            actor=doer_a,
            tenant=tenant_a,
        )
        assert second.pk != first.pk
        assert WorkflowEvidence.objects.filter(document_version=version_a).count() == 2

    def test_active_list_excludes_unlinked(self, item_a, tenant_a, doer_a, version_a):
        record = services.link_evidence(
            item=item_a,
            document_version_public_id=version_a.public_id,
            actor=doer_a,
            tenant=tenant_a,
        )
        assert services.active_evidence_for(item_a, tenant_a).count() == 1
        services.unlink_evidence(
            item=item_a, evidence_public_id=record.public_id, actor=doer_a, tenant=tenant_a
        )
        assert services.active_evidence_for(item_a, tenant_a).count() == 0


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------
@pytest.mark.django_db(transaction=True)
class TestConcurrentLinking:
    def test_two_simultaneous_links_produce_exactly_one(self, tenant_a, doer_a):
        from django.db import connection as conn

        item = WorkflowItem.objects.create(
            tenant=tenant_a, created_by=doer_a, title="Evidence race"
        )
        version = _make_version(tenant_a, doer_a, title="Race doc")

        barrier = threading.Barrier(2, timeout=20)
        outcomes: dict[str, str] = {}

        def attempt(name):
            try:
                barrier.wait()
                services.link_evidence(
                    item=item,
                    document_version_public_id=version.public_id,
                    actor=doer_a,
                    tenant=tenant_a,
                )
                outcomes[name] = "ok"
            except services.DuplicateEvidence:
                outcomes[name] = "duplicate"
            except Exception as exc:
                outcomes[name] = f"error:{type(exc).__name__}"
            finally:
                conn.close()

        threads = [threading.Thread(target=attempt, args=(n,)) for n in ("a", "b")]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert len(outcomes) == 2, outcomes
        assert sorted(outcomes.values()) == ["duplicate", "ok"], outcomes
        assert (
            WorkflowEvidence.objects.filter(
                workflow_item=item, document_version=version, unlinked_at__isnull=True
            ).count()
            == 1
        )


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestAudit:
    def test_link_and_unlink_emit_allow_listed_events(self, item_a, tenant_a, doer_a, version_a):
        from audit.models import AuditEvent
        from workflows.audit_events import _ALLOWED_PAYLOAD_KEYS

        record = services.link_evidence(
            item=item_a,
            document_version_public_id=version_a.public_id,
            actor=doer_a,
            tenant=tenant_a,
        )
        linked = AuditEvent.objects.filter(event_type="workflow.evidence_linked").latest(
            "created_at"
        )
        assert set(linked.payload).issubset(_ALLOWED_PAYLOAD_KEYS)
        assert linked.payload["document_version_public_id"] == str(version_a.public_id)
        assert linked.payload["evidence_public_id"] == str(record.public_id)

        services.unlink_evidence(
            item=item_a, evidence_public_id=record.public_id, actor=doer_a, tenant=tenant_a
        )
        assert AuditEvent.objects.filter(event_type="workflow.evidence_unlinked").exists()

    def test_filename_is_never_audited(self, item_a, tenant_a, doer_a):
        """A filename is user-supplied and can disclose subject matter. Public
        IDs resolve to it for anyone holding documents.view, which is the gate."""
        from audit.models import AuditEvent

        version = _make_version(tenant_a, doer_a, title="SECRET_PROJECT_CODENAME")
        services.link_evidence(
            item=item_a,
            document_version_public_id=version.public_id,
            actor=doer_a,
            tenant=tenant_a,
        )
        event = AuditEvent.objects.filter(event_type="workflow.evidence_linked").latest(
            "created_at"
        )
        assert "SECRET_PROJECT_CODENAME" not in str(event.payload)


# ---------------------------------------------------------------------------
# No file duplication, and deletion protection
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestNoDuplicationAndDeletionProtection:
    def test_evidence_stores_no_file_bytes(self, item_a, tenant_a, doer_a, version_a):
        """The document platform stays the sole owner of storage."""
        record = services.link_evidence(
            item=item_a,
            document_version_public_id=version_a.public_id,
            actor=doer_a,
            tenant=tenant_a,
        )
        field_names = {f.name for f in record._meta.get_fields()}
        for forbidden in ("storage_key", "sha256_checksum", "size_bytes", "content", "file"):
            assert forbidden not in field_names, f"{forbidden} must not be duplicated onto evidence"

    def test_linked_version_cannot_be_deleted(self, item_a, tenant_a, doer_a, version_a):
        from documents.deletion_protection import DocumentVersionDeleteForbidden

        services.link_evidence(
            item=item_a,
            document_version_public_id=version_a.public_id,
            actor=doer_a,
            tenant=tenant_a,
        )
        with pytest.raises(DocumentVersionDeleteForbidden):
            version_a.delete()

    def test_protection_survives_unlink(self, item_a, tenant_a, doer_a, version_a):
        """The historical record that a version was cited is itself governed,
        so deleting the version would strand it."""
        from documents.deletion_protection import DocumentVersionDeleteForbidden

        record = services.link_evidence(
            item=item_a,
            document_version_public_id=version_a.public_id,
            actor=doer_a,
            tenant=tenant_a,
        )
        services.unlink_evidence(
            item=item_a, evidence_public_id=record.public_id, actor=doer_a, tenant=tenant_a
        )
        with pytest.raises(DocumentVersionDeleteForbidden):
            version_a.delete()


# ---------------------------------------------------------------------------
# Database-level protection
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestDatabaseLevelProtection:
    TABLE = "workflows_workflowevidence"

    def _linked(self, item, tenant, actor, version):
        return services.link_evidence(
            item=item,
            document_version_public_id=version.public_id,
            actor=actor,
            tenant=tenant,
        )

    def test_raw_delete_is_rejected(self, item_a, tenant_a, doer_a, version_a):
        record = self._linked(item_a, tenant_a, doer_a, version_a)
        with pytest.raises((InternalError, ProgrammingError)) as exc:
            with transaction.atomic(), connection.cursor() as cur:
                cur.execute(f"DELETE FROM {self.TABLE} WHERE id = %s", [record.pk])
        assert "cannot be deleted" in str(exc.value).lower()
        assert WorkflowEvidence.objects.filter(pk=record.pk).exists()

    def test_raw_update_of_a_governed_field_is_rejected(self, item_a, tenant_a, doer_a, version_a):
        record = self._linked(item_a, tenant_a, doer_a, version_a)
        with pytest.raises((InternalError, ProgrammingError)) as exc:
            with transaction.atomic(), connection.cursor() as cur:
                cur.execute(
                    f"UPDATE {self.TABLE} SET label = 'tampered' WHERE id = %s", [record.pk]
                )
        assert "immutable" in str(exc.value).lower()
        record.refresh_from_db()
        assert record.label == ""

    def test_raw_repoint_to_another_version_is_rejected(self, item_a, tenant_a, doer_a, version_a):
        """The pinning invariant, enforced by the database rather than by rule."""
        record = self._linked(item_a, tenant_a, doer_a, version_a)
        other = _make_version(tenant_a, doer_a, title="Other doc")
        with pytest.raises((InternalError, ProgrammingError)):
            with transaction.atomic(), connection.cursor() as cur:
                cur.execute(
                    f"UPDATE {self.TABLE} SET document_version_id = %s WHERE id = %s",
                    [other.pk, record.pk],
                )
        record.refresh_from_db()
        assert record.document_version_id == version_a.pk

    def test_unlink_stamp_is_the_one_permitted_update(self, item_a, tenant_a, doer_a, version_a):
        record = self._linked(item_a, tenant_a, doer_a, version_a)
        services.unlink_evidence(
            item=item_a, evidence_public_id=record.public_id, actor=doer_a, tenant=tenant_a
        )
        record.refresh_from_db()
        assert record.unlinked_at is not None

    def test_an_unlinked_row_cannot_be_touched_again(self, item_a, tenant_a, doer_a, version_a):
        record = self._linked(item_a, tenant_a, doer_a, version_a)
        services.unlink_evidence(
            item=item_a, evidence_public_id=record.public_id, actor=doer_a, tenant=tenant_a
        )
        with pytest.raises((InternalError, ProgrammingError)) as exc:
            with transaction.atomic(), connection.cursor() as cur:
                cur.execute(
                    f"UPDATE {self.TABLE} SET unlinked_at = NULL WHERE id = %s", [record.pk]
                )
        assert "already unlinked" in str(exc.value).lower()

    def test_orm_bulk_paths_are_blocked(self, item_a, tenant_a, doer_a, version_a):
        from workflows.models import WorkflowEvidenceMutationForbidden

        record = self._linked(item_a, tenant_a, doer_a, version_a)
        with pytest.raises(WorkflowEvidenceMutationForbidden):
            WorkflowEvidence.objects.filter(pk=record.pk).update(label="x")
        with pytest.raises(WorkflowEvidenceMutationForbidden):
            WorkflowEvidence.objects.filter(pk=record.pk).delete()
        with pytest.raises(WorkflowEvidenceMutationForbidden):
            record.delete()


# ---------------------------------------------------------------------------
# API surface
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestApi:
    def test_link_list_unlink_round_trip(self, client_doer_a, item_a, version_a):
        created = client_doer_a.post(
            _url(item_a),
            {"document_version_public_id": str(version_a.public_id), "label": "Protocol"},
            format="json",
        )
        assert created.status_code == 201
        evidence_id = created.data["public_id"]
        assert created.data["label"] == "Protocol"

        listing = client_doer_a.get(_url(item_a))
        assert listing.status_code == 200
        assert [r["public_id"] for r in listing.data] == [evidence_id]

        removed = client_doer_a.delete(_url(item_a, f"{evidence_id}/"))
        assert removed.status_code == 200
        assert client_doer_a.get(_url(item_a)).data == []

    def test_no_internal_pk_exposed(self, client_doer_a, item_a, version_a):
        created = client_doer_a.post(
            _url(item_a), {"document_version_public_id": str(version_a.public_id)}, format="json"
        )
        assert "id" not in created.data
        assert "pk" not in created.data
        assert "document_version" not in created.data
        uuid.UUID(created.data["public_id"])

    def test_locked_state_returns_409(self, client_doer_a, client_reviewer_a, item_a, version_a):
        client_doer_a.post(_url(item_a).replace("/evidence/", "/submit/"), {}, format="json")
        resp = client_doer_a.post(
            _url(item_a), {"document_version_public_id": str(version_a.public_id)}, format="json"
        )
        assert resp.status_code == 409
        assert resp.data["current_state"] == S.SUBMITTED

    def test_duplicate_returns_409(self, client_doer_a, item_a, version_a):
        body = {"document_version_public_id": str(version_a.public_id)}
        assert client_doer_a.post(_url(item_a), body, format="json").status_code == 201
        assert client_doer_a.post(_url(item_a), body, format="json").status_code == 409

    def test_evidence_endpoints_reject_unsupported_methods(self, client_doer_a, item_a):
        assert client_doer_a.put(_url(item_a), {}, format="json").status_code == 405
        assert client_doer_a.patch(_url(item_a), {}, format="json").status_code == 405
