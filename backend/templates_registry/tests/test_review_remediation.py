"""
Regression tests for the four human-review findings from the Milestone 3
review gate on PR #3:

1. Critical -- MigrationBatchReviewView resolved duplicate candidates with
   no tenant/batch scoping.
2. Major -- reconciliation CSV export was vulnerable to formula/DDE
   injection (CWE-1236).
3. Minor -- _get_or_create_draft_version() raced on version_number under
   concurrent imports to the same template.
4. Minor -- duplicate-resolution audit lacked per-candidate decision detail,
   and no audit event existed for reconciliation export.

Every test that plants a violation is noted.
"""

import csv
import io
import threading

import pytest
from django.db import connections, transaction
from rest_framework.test import APIClient

from audit.models import AuditEvent
from common.csv_safety import CSV_FORMULA_TRIGGER_CHARS, csv_safe_cell
from templates_registry import adapters, importer
from templates_registry.audit_events import TemplateEvent
from templates_registry.models import (
    RegulatoryTemplate,
    TemplateDuplicateCandidate,
    TemplateVersion,
)
from templates_registry.reconciliation import (
    _CSV_FORMULA_TRIGGER_CHARS,
    _csv_safe_cell,
    render_reconciliation_csv,
)

BASE = "/api/regx/v1"


def _client_for(user, tenant):
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(**{"HTTP_X_TENANT_SLUG": tenant.slug})
    return client


def _duplicate_candidate_in(tenant, user, source_name):
    """Runs a real migration batch containing two rows with identical
    normalized text, producing an actual TemplateDuplicateCandidate the same
    way the pipeline does in production (not a hand-built row)."""
    rows = [
        {
            "id": 1,
            "report_name": "Dup Report A",
            "module_name": "General",
            "chapter_name": "General",
            "category_name": "General",
            "question": "<p>Evaluation of isomerism and polymorphism.</p>",
        },
        {
            "id": 2,
            "report_name": "Dup Report B",
            "module_name": "General",
            "chapter_name": "General",
            "category_name": "General",
            "question": "<p>Evaluation of isomerism and polymorphism.</p>",
        },
    ]
    neutral = adapters.anda_like_adapter(rows, source_name=source_name)
    package = importer.register_source_package(
        tenant=tenant,
        source_name=source_name,
        source_type="anda_checklist",
        source_path_or_reference=f"synthetic://{source_name}.json",
        # source_name is folded into the checksum payload -- register_source_package
        # keys on (tenant, checksum), so two calls with identical row content
        # but different source_name would otherwise collide on the same
        # checksum and silently resolve to the same package (get_or_create).
        payload_for_checksum={"rows": rows, "source_name": source_name},
        imported_by=user,
    )
    batch = importer.create_migration_batch(package, user)
    importer.run_migration_batch(batch, neutral, user)
    candidate = TemplateDuplicateCandidate.objects.filter(
        subject_template_item__template_section__template_version__source_package=package
    ).first()
    assert candidate is not None, "fixture setup must produce a duplicate candidate"
    return batch, package, candidate


@pytest.mark.django_db
class TestTenantScopedDuplicateReview:
    def test_foreign_tenant_candidate_rejected_generically(
        self,
        tenant_a,
        user_a,
        doer_membership,
        reviewer_user,
        reviewer_membership,
        tenant_b,
        user_b,
    ):
        # PLANT: a Reviewer in tenant_a submits a review referencing a
        # duplicate candidate that actually belongs to tenant_b.
        _, _, candidate_b = _duplicate_candidate_in(tenant_b, user_b, "foreign-tenant-src")
        batch_a, _, _ = _duplicate_candidate_in(tenant_a, user_a, "own-tenant-src")

        client = _client_for(reviewer_user, tenant_a)
        resp = client.post(
            f"{BASE}/migration-batches/{batch_a.public_id}/review/",
            data={
                "duplicate_resolutions": [
                    {"public_id": str(candidate_b.public_id), "resolution": "same"}
                ]
            },
            format="json",
        )

        # DETECT: generic non-disclosing rejection, not a successful mutation.
        assert resp.status_code == 404
        body = resp.json()
        assert "tenant" not in str(body).lower()

        candidate_b.refresh_from_db()
        assert candidate_b.resolution == "pending"
        assert candidate_b.reviewer_id is None
        assert not AuditEvent.objects.filter(
            event_type=TemplateEvent.DUPLICATE_CANDIDATE_RESOLVED,
            resource_id=str(candidate_b.public_id),
        ).exists()

    def test_same_tenant_different_source_package_rejected(
        self, tenant_a, user_a, doer_membership, reviewer_user, reviewer_membership
    ):
        # PLANT: same tenant, but the candidate belongs to a different
        # source package/batch than the one being reviewed.
        batch_1, _, candidate_1 = _duplicate_candidate_in(tenant_a, user_a, "batch-one-src")
        batch_2, _, _candidate_2 = _duplicate_candidate_in(tenant_a, user_a, "batch-two-src")

        client = _client_for(reviewer_user, tenant_a)
        resp = client.post(
            f"{BASE}/migration-batches/{batch_2.public_id}/review/",
            data={
                "duplicate_resolutions": [
                    {"public_id": str(candidate_1.public_id), "resolution": "distinct"}
                ]
            },
            format="json",
        )

        assert resp.status_code == 404
        candidate_1.refresh_from_db()
        assert candidate_1.resolution == "pending"

    def test_valid_candidate_resolves_successfully(
        self, tenant_a, user_a, doer_membership, reviewer_user, reviewer_membership
    ):
        batch, package, candidate = _duplicate_candidate_in(tenant_a, user_a, "valid-review-src")

        client = _client_for(reviewer_user, tenant_a)
        resp = client.post(
            f"{BASE}/migration-batches/{batch.public_id}/review/",
            data={
                "duplicate_resolutions": [
                    {
                        "public_id": str(candidate.public_id),
                        "resolution": "same",
                        "reason": "Confirmed identical text across report types.",
                    }
                ]
            },
            format="json",
        )

        assert resp.status_code == 200
        assert resp.json()["resolved"] == [str(candidate.public_id)]

        candidate.refresh_from_db()
        assert candidate.resolution == "same"
        assert candidate.reviewer_id == reviewer_user.id
        assert candidate.reason == "Confirmed identical text across report types."

        report_resp = client.get(f"{BASE}/migration-batches/{batch.public_id}/reconciliation.json")
        assert report_resp.status_code == 200
        report_candidates = report_resp.json()["duplicate_candidates"]
        assert any(
            c["public_id"] == str(candidate.public_id) and c["resolution"] == "same"
            for c in report_candidates
        )

    def test_mixed_valid_and_foreign_candidate_fully_rejected(
        self,
        tenant_a,
        user_a,
        doer_membership,
        reviewer_user,
        reviewer_membership,
        tenant_b,
        user_b,
    ):
        # PLANT: one legitimate candidate plus one foreign-tenant candidate
        # in the same request.
        batch_a, _, candidate_valid = _duplicate_candidate_in(tenant_a, user_a, "mixed-valid-src")
        _, _, candidate_foreign = _duplicate_candidate_in(tenant_b, user_b, "mixed-foreign-src")

        client = _client_for(reviewer_user, tenant_a)
        resp = client.post(
            f"{BASE}/migration-batches/{batch_a.public_id}/review/",
            data={
                "duplicate_resolutions": [
                    {"public_id": str(candidate_valid.public_id), "resolution": "same"},
                    {"public_id": str(candidate_foreign.public_id), "resolution": "distinct"},
                ]
            },
            format="json",
        )

        # DETECT: preferred behavior is full rejection -- the valid
        # candidate must NOT have been silently resolved either.
        assert resp.status_code == 404
        candidate_valid.refresh_from_db()
        assert candidate_valid.resolution == "pending"
        assert not AuditEvent.objects.filter(
            event_type=TemplateEvent.DUPLICATE_CANDIDATE_RESOLVED,
            resource_id=str(candidate_valid.public_id),
        ).exists()


@pytest.mark.django_db
class TestCsvFormulaInjectionNeutralization:
    @pytest.mark.parametrize(
        "raw,expected_neutralized",
        [
            ("=1+1", True),
            ("+SUM(1,2)", True),
            ("-10+20", True),
            ("@SUM(1,2)", True),
            ("\tformula-after-tab", True),
            ("\r\nformula-after-crlf", True),
            ("   =cmd|'/c calc'!A1", True),
            ("Hello World", False),
            ("12345", False),
            ("<script>alert(1)</script>", False),
        ],
    )
    def test_csv_safe_cell_neutralizes_only_formula_triggers(self, raw, expected_neutralized):
        # Exercises the promoted public helper directly (MILESTONE_4D_DISCOVERY.md
        # section 17). The module-local `_csv_safe_cell` is a compatibility alias
        # for the same object, proven by the delegation test below.
        result = csv_safe_cell(raw)
        if expected_neutralized:
            # PLANTED VIOLATION (detected): a formula-trigger value must be
            # prefixed so spreadsheet software renders it as literal text.
            assert result.startswith("'")
            assert result[1:] == raw
        else:
            assert result == raw

    def test_csv_safe_cell_handles_none_and_empty(self):
        assert csv_safe_cell(None) == ""
        assert csv_safe_cell("") == ""

    def test_the_private_alias_delegates_to_the_promoted_public_helper(self):
        """One implementation platform-wide, not two that agree today.

        Identity -- not merely equal behaviour -- is what proves no duplicate
        helper has reappeared in `templates_registry`.
        """
        assert _csv_safe_cell is csv_safe_cell
        assert _CSV_FORMULA_TRIGGER_CHARS is CSV_FORMULA_TRIGGER_CHARS

    def test_render_reconciliation_csv_neutralizes_every_column(self):
        report = {
            "records": [
                {
                    "source_record_identifier": "=1+1",
                    "target_public_identifier": "@evil",
                    "result": "imported",
                    "reason_code": "+SUM(1,2)",
                }
            ]
        }
        csv_body = render_reconciliation_csv(report)
        rows = list(csv.reader(io.StringIO(csv_body)))
        assert rows[0] == [
            "source_record_identifier",
            "target_public_identifier",
            "result",
            "reason_code",
        ]
        assert rows[1] == ["'=1+1", "'@evil", "imported", "'+SUM(1,2)"]

    def test_csv_remains_parseable_with_commas_quotes_and_newlines(self):
        report = {
            "records": [
                {
                    "source_record_identifier": 'id, with "quotes" and\nnewline',
                    "target_public_identifier": None,
                    "result": "imported",
                    "reason_code": "",
                }
            ]
        }
        csv_body = render_reconciliation_csv(report)
        rows = list(csv.reader(io.StringIO(csv_body)))
        assert rows[1][0] == 'id, with "quotes" and\nnewline'

    def test_malicious_identifier_is_neutralized_in_csv_but_not_in_database(self, tenant_a, user_a):
        # PLANTED VIOLATION (detected): a Doer-controlled record identifier
        # containing a formula trigger must be neutralized only in the
        # rendered export, never mutated in the stored raw database value.
        rows = [
            {
                "id": 1,
                "report_name": "R",
                "module_name": "General",
                "chapter_name": "General",
                "category_name": "General",
                "question": "<p>Q1</p>",
            }
        ]
        neutral = adapters.anda_like_adapter(rows, source_name="csv-injection-src")
        neutral[0]["identifier"] = "=1+1"
        package = importer.register_source_package(
            tenant=tenant_a,
            source_name="csv-injection-src",
            source_type="anda_checklist",
            source_path_or_reference="synthetic://csv-injection.json",
            payload_for_checksum={"rows": rows},
            imported_by=user_a,
        )
        batch = importer.create_migration_batch(package, user_a)
        importer.run_migration_batch(batch, neutral, user_a)

        from templates_registry.models import TemplateSourceRecord
        from templates_registry.reconciliation import build_reconciliation_report

        record = TemplateSourceRecord.objects.get(source_package=package)
        assert record.source_record_identifier == "=1+1"

        report = build_reconciliation_report(batch)
        csv_body = render_reconciliation_csv(report)
        assert "'=1+1" in csv_body
        assert "\n=1+1," not in csv_body

        record.refresh_from_db()
        assert record.source_record_identifier == "=1+1"


@pytest.mark.django_db(transaction=True)
class TestConcurrentVersionAllocation:
    def test_concurrent_imports_allocate_distinct_version_numbers(self, tenant_a, user_a):
        # PLANTED VIOLATION (detected): two threads racing to create the
        # first draft version for the same template (via two different
        # source packages, so the existing-draft short-circuit doesn't just
        # return the same row) must not collide on version_number.
        template = RegulatoryTemplate.objects.create(
            tenant=tenant_a, canonical_code="CONCURRENCY-TPL", title="Concurrency Template"
        )
        package_1 = importer.register_source_package(
            tenant=tenant_a,
            source_name="concurrency-src-1",
            source_type="anda_checklist",
            source_path_or_reference="synthetic://concurrency-1.json",
            # Distinct payload per package -- register_source_package keys
            # on (tenant, checksum), so identical payloads would collapse
            # both calls onto the same package via get_or_create.
            payload_for_checksum={"rows": [], "marker": "concurrency-src-1"},
            imported_by=user_a,
        )
        package_2 = importer.register_source_package(
            tenant=tenant_a,
            source_name="concurrency-src-2",
            source_type="anda_checklist",
            source_path_or_reference="synthetic://concurrency-2.json",
            payload_for_checksum={"rows": [], "marker": "concurrency-src-2"},
            imported_by=user_a,
        )

        template_id = template.pk
        errors = []
        barrier = threading.Barrier(2)

        def worker(package_id):
            try:
                barrier.wait(timeout=5)
                tpl = RegulatoryTemplate.objects.get(pk=template_id)
                pkg = type(package_1).objects.get(pk=package_id)
                with transaction.atomic():
                    importer._get_or_create_draft_version(tpl, pkg, user_a)
            except Exception as exc:
                errors.append(exc)
            finally:
                connections.close_all()

        t1 = threading.Thread(target=worker, args=(package_1.pk,))
        t2 = threading.Thread(target=worker, args=(package_2.pk,))
        t1.start()
        t2.start()
        t1.join(timeout=15)
        t2.join(timeout=15)

        assert not errors, f"concurrent allocation raised: {errors}"

        versions = list(
            TemplateVersion.objects.filter(template=template).order_by("version_number")
        )
        assert len(versions) == 2
        assert [v.version_number for v in versions] == [1, 2]

    def test_rerun_after_concurrency_fix_remains_idempotent(self, tenant_a, user_a, anda_like_rows):
        neutral = adapters.anda_like_adapter(anda_like_rows, source_name="post-fix-idempotent")
        package = importer.register_source_package(
            tenant=tenant_a,
            source_name="post-fix-idempotent",
            source_type="anda_checklist",
            source_path_or_reference="synthetic://post-fix-idempotent.json",
            payload_for_checksum={"rows": anda_like_rows},
            imported_by=user_a,
        )
        batch = importer.create_migration_batch(package, user_a)
        importer.run_migration_batch(batch, neutral, user_a)
        version_count = TemplateVersion.objects.filter(source_package=package).count()

        importer.run_migration_batch(batch, neutral, user_a)
        assert TemplateVersion.objects.filter(source_package=package).count() == version_count


@pytest.mark.django_db
class TestReconciliationAuditCompleteness:
    def test_duplicate_resolution_audit_contains_decision_and_reason(
        self, tenant_a, user_a, doer_membership, reviewer_user, reviewer_membership
    ):
        batch, _, candidate = _duplicate_candidate_in(tenant_a, user_a, "audit-detail-src")
        client = _client_for(reviewer_user, tenant_a)
        resp = client.post(
            f"{BASE}/migration-batches/{batch.public_id}/review/",
            data={
                "duplicate_resolutions": [
                    {
                        "public_id": str(candidate.public_id),
                        "resolution": "distinct",
                        "reason": "Different section context, not a true duplicate.",
                    }
                ]
            },
            format="json",
        )
        assert resp.status_code == 200

        event = AuditEvent.objects.get(
            event_type=TemplateEvent.DUPLICATE_CANDIDATE_RESOLVED,
            resource_id=str(candidate.public_id),
        )
        assert event.payload["previous_resolution"] == "pending"
        assert event.payload["new_resolution"] == "distinct"
        assert event.payload["reason"] == "Different section context, not a true duplicate."
        assert event.payload["batch"] == str(batch.public_id)

    def test_csv_export_emits_one_audit_event(
        self, tenant_a, user_a, vp_user, vp_membership, doer_membership
    ):
        _, package, _ = _duplicate_candidate_in(tenant_a, user_a, "audit-csv-export-src")
        batch = importer.MigrationBatch.objects.get(source_package=package)
        client = _client_for(vp_user, tenant_a)
        resp = client.get(f"{BASE}/migration-batches/{batch.public_id}/reconciliation.csv")
        assert resp.status_code == 200

        events = AuditEvent.objects.filter(
            event_type=TemplateEvent.RECONCILIATION_EXPORTED, resource_id=str(batch.public_id)
        )
        assert events.count() == 1
        assert events.first().payload["format"] == "csv"

    def test_json_export_emits_one_audit_event(
        self, tenant_a, user_a, vp_user, vp_membership, doer_membership
    ):
        _, package, _ = _duplicate_candidate_in(tenant_a, user_a, "audit-json-export-src")
        batch = importer.MigrationBatch.objects.get(source_package=package)
        client = _client_for(vp_user, tenant_a)
        resp = client.get(f"{BASE}/migration-batches/{batch.public_id}/reconciliation.json")
        assert resp.status_code == 200

        events = AuditEvent.objects.filter(
            event_type=TemplateEvent.RECONCILIATION_EXPORTED, resource_id=str(batch.public_id)
        )
        assert events.count() == 1
        assert events.first().payload["format"] == "json"

    def test_unauthorized_export_emits_no_audit_event(self, tenant_a, user_a, doer_membership):
        # PLANTED VIOLATION (detected): a Doer lacks export permission --
        # the request must 403 and must not emit a success audit event.
        _, package, _ = _duplicate_candidate_in(tenant_a, user_a, "audit-unauthorized-src")
        batch = importer.MigrationBatch.objects.get(source_package=package)
        client = _client_for(user_a, tenant_a)
        resp = client.get(f"{BASE}/migration-batches/{batch.public_id}/reconciliation.csv")
        assert resp.status_code == 403
        assert not AuditEvent.objects.filter(
            event_type=TemplateEvent.RECONCILIATION_EXPORTED, resource_id=str(batch.public_id)
        ).exists()

    def test_cross_tenant_export_emits_no_audit_event(
        self, tenant_a, user_a, doer_membership, tenant_b, user_b, vp_user, vp_membership
    ):
        from authorization.models import MembershipRole, Role
        from tenancy.models import TenantMembership

        _, package, _ = _duplicate_candidate_in(tenant_a, user_a, "audit-cross-tenant-src")
        batch = importer.MigrationBatch.objects.get(source_package=package)

        membership = TenantMembership.objects.create(tenant=tenant_b, user=user_b)
        role, _ = Role.objects.get_or_create(tenant=None, name="vp", defaults={"is_system": True})
        MembershipRole.objects.create(membership=membership, role=role)

        client = _client_for(user_b, tenant_b)
        resp = client.get(f"{BASE}/migration-batches/{batch.public_id}/reconciliation.json")
        assert resp.status_code == 404
        assert not AuditEvent.objects.filter(
            event_type=TemplateEvent.RECONCILIATION_EXPORTED, resource_id=str(batch.public_id)
        ).exists()
