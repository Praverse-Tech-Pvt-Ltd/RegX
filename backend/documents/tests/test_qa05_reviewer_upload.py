"""QA-05 (docs/qa/QA_CODEX_REPORT.md): Reviewers could not attach documents.

Owner decision 2026-11-18 (PROJECT_OVERVIEW §12 item 9): Reviewers must be able to
attach documents; VP stays as it is (refused). Reviewer now may upload a document
and add a version, in its own tenant only. Reviewer still may not archive (there is
no delete) or restore, and there is no metadata-editing endpoint for anyone. Every
upload and version writes audit events.
"""

import pytest

from audit.models import AuditEvent
from authorization.models import MembershipRole, Role
from tenancy.models import TenantMembership

from .test_api import BASE_URL, _client_for, _pdf_upload, _post_doc

pytestmark = pytest.mark.django_db


def _member(user, tenant, role_name):
    membership, _ = TenantMembership.objects.get_or_create(
        tenant=tenant, user=user, defaults={"is_active": True}
    )
    role, _ = Role.objects.get_or_create(name=role_name, defaults={"is_system_role": True})
    MembershipRole.objects.get_or_create(membership=membership, role=role)
    return user


def _user(email):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(
        email=email, password="TestPass1234!", full_name=email
    )


def _add_version(client, doc_id, pdf_bytes):
    return client.post(
        f"{BASE_URL}{doc_id}/versions/",
        data={"file": _pdf_upload(pdf_bytes, "v2.pdf")},
        format="multipart",
    )


@pytest.fixture
def eager(settings, local_storage):
    settings.CELERY_TASK_ALWAYS_EAGER = True


class TestReviewerMayAttach:
    def test_reviewer_uploads_and_it_is_audited(
        self, eager, user_b, tenant_a, reviewer_membership, valid_pdf_bytes
    ):
        resp = _post_doc(_client_for(user_b, tenant_a), valid_pdf_bytes, "Reviewer attachment")
        assert resp.status_code == 201, resp.content[:300]
        doc_events = set(
            AuditEvent.objects.filter(
                resource_id=resp.json()["public_id"], actor_email=user_b.email
            ).values_list("event_type", flat=True)
        )
        assert "document.created" in doc_events, doc_events
        all_events = set(
            AuditEvent.objects.filter(actor_email=user_b.email).values_list("event_type", flat=True)
        )
        assert len(all_events - {"document.created"}) >= 1, all_events  # the version's own events

    def test_reviewer_adds_a_version_and_it_is_audited(
        self, eager, user_a, user_b, tenant_a, doer_membership, reviewer_membership, valid_pdf_bytes
    ):
        doc = _post_doc(_client_for(user_a, tenant_a), valid_pdf_bytes, "Doer document").json()
        before = AuditEvent.objects.filter(actor_email=user_b.email).count()
        resp = _add_version(_client_for(user_b, tenant_a), doc["public_id"], valid_pdf_bytes)
        assert resp.status_code == 201, resp.content[:300]
        assert AuditEvent.objects.filter(actor_email=user_b.email).count() > before


class TestReviewerLimits:
    def test_reviewer_cannot_upload_in_another_tenant(
        self, eager, user_b, tenant_a, tenant_b, reviewer_membership, valid_pdf_bytes
    ):
        resp = _post_doc(_client_for(user_b, tenant_b), valid_pdf_bytes, "Cross-tenant")
        assert resp.status_code in (403, 404)

    def test_reviewer_cannot_add_a_version_to_another_tenants_document(
        self, eager, user_b, tenant_a, tenant_b, reviewer_membership, valid_pdf_bytes
    ):
        other_doer = _member(_user("doer@other.test"), tenant_b, Role.BuiltIn.DOER)
        doc = _post_doc(_client_for(other_doer, tenant_b), valid_pdf_bytes, "Other tenant").json()
        resp = _add_version(_client_for(user_b, tenant_a), doc["public_id"], valid_pdf_bytes)
        assert resp.status_code in (403, 404)

    def test_reviewer_cannot_archive(
        self, eager, user_a, user_b, tenant_a, doer_membership, reviewer_membership, valid_pdf_bytes
    ):
        doc = _post_doc(_client_for(user_a, tenant_a), valid_pdf_bytes, "Keep me").json()
        resp = _client_for(user_b, tenant_a).post(
            f"{BASE_URL}{doc['public_id']}/archive/", {}, format="json"
        )
        assert resp.status_code == 403


class TestOtherRolesUnchanged:
    def test_vp_still_cannot_upload(self, eager, tenant_a, valid_pdf_bytes):
        vp = _member(_user("vp@qa05.test"), tenant_a, Role.BuiltIn.VP)
        assert _post_doc(_client_for(vp, tenant_a), valid_pdf_bytes, "VP").status_code == 403

    def test_doer_still_uploads(self, eager, user_a, tenant_a, doer_membership, valid_pdf_bytes):
        assert _post_doc(_client_for(user_a, tenant_a), valid_pdf_bytes, "Doer").status_code == 201

    def test_tenant_admin_still_uploads_and_archives(
        self, eager, user_a, tenant_a, admin_membership, valid_pdf_bytes
    ):
        client = _client_for(user_a, tenant_a)
        doc = _post_doc(client, valid_pdf_bytes, "Admin").json()
        assert client.post(
            f"{BASE_URL}{doc['public_id']}/archive/", {}, format="json"
        ).status_code in (200, 204)
