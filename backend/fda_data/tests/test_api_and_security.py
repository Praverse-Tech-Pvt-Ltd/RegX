"""
FDA data API, export-safety, and permission-boundary tests. Every test
that plants a violation is noted.
"""

import pytest

from fda_data.models import FDADataSourceRelease, FdaImportRowResult, FdaImportRowResultType

BASE = "/api/regx/v1"


@pytest.fixture
def active_release(db):
    return FDADataSourceRelease.objects.create(
        dataset_type="fda_iid",
        source_name="FDA IID",
        official_source_reference="ref",
        source_checksum_sha256="a" * 64,
        status="active",
        original_filename="/var/secret/fda-iid-export.txt",
    )


@pytest.fixture
def row_result_with_injection_payload(db, active_release):
    return FdaImportRowResult.objects.create(
        release=active_release,
        row_locator="row-1",
        result=FdaImportRowResultType.IMPORTED,
        reason_code="",
        safe_detail="=cmd|' /C calc'!A1",
    )


@pytest.mark.django_db
class TestReconciliationExportSafety:
    def test_csv_export_neutralizes_formula_injection(
        self, api_client_vp, active_release, row_result_with_injection_payload
    ):
        # PLANTED VIOLATION (detected): a row_locator/reason_code/safe_detail
        # value beginning with =, +, -, @ must never reach the CSV response
        # as an active formula -- it must be neutralized with a leading
        # apostrophe so spreadsheet software treats it as inert text.
        FdaImportRowResult.objects.filter(pk=row_result_with_injection_payload.pk).update(
            row_locator="=SUM(A1:A9)", reason_code="+1;calc"
        )
        resp = api_client_vp.get(
            f"{BASE}/fda-data/releases/{active_release.public_id}/reconciliation.csv"
        )
        assert resp.status_code == 200
        body = resp.content.decode()
        assert "\n=SUM" not in body
        assert "\n+1;calc" not in body.replace("'+1;calc", "")
        assert "'=SUM(A1:A9)" in body
        assert "'+1;calc" in body

    def test_csv_export_no_source_file_path_leaked(
        self, api_client_vp, active_release, row_result_with_injection_payload
    ):
        # PLANTED VIOLATION (detected): the reconciliation export must never
        # leak the raw filesystem/storage path of the imported source file.
        resp = api_client_vp.get(
            f"{BASE}/fda-data/releases/{active_release.public_id}/reconciliation.csv"
        )
        assert "/var/secret" not in resp.content.decode()

    def test_json_export_no_source_file_path_leaked(
        self, api_client_vp, active_release, row_result_with_injection_payload
    ):
        resp = api_client_vp.get(
            f"{BASE}/fda-data/releases/{active_release.public_id}/reconciliation.json"
        )
        assert resp.status_code == 200
        assert "/var/secret" not in str(resp.json())

    def test_doer_cannot_export_reconciliation(
        self, api_client_doer, active_release, row_result_with_injection_payload
    ):
        # PLANTED VIOLATION (detected): a Doer (import-only role) must never
        # be able to export the reconciliation report.
        resp = api_client_doer.get(
            f"{BASE}/fda-data/releases/{active_release.public_id}/reconciliation.csv"
        )
        assert resp.status_code == 403


@pytest.mark.django_db
class TestReleaseListSafety:
    def test_no_numeric_id_in_release_list_response(self, api_client_doer, active_release):
        # PLANTED VIOLATION (detected): the release list response must
        # never expose the internal BigAutoField numeric primary key.
        resp = api_client_doer.get(f"{BASE}/fda-data/releases/")
        assert resp.status_code == 200
        result = resp.json()["results"][0]
        assert "id" not in result
        assert "pk" not in result

    def test_default_serializer_hides_raw_source_fields(self, api_client_doer, active_release):
        # Doer has view but not view_raw -- original_filename/source path
        # must not appear in the default (non-raw) serializer output.
        resp = api_client_doer.get(f"{BASE}/fda-data/releases/")
        results = resp.json()["results"]
        assert "original_filename" not in results[0]
        assert "source_checksum_sha256" not in results[0]

    def test_view_raw_holder_sees_raw_fields(self, api_client_vp, active_release):
        resp = api_client_vp.get(f"{BASE}/fda-data/releases/")
        results = resp.json()["results"]
        assert "original_filename" in results[0]


@pytest.mark.django_db
class TestApprovalSegregationOfDuties:
    def test_doer_cannot_approve_release(self, api_client_doer, active_release):
        # PLANTED VIOLATION (detected): a Doer must never be able to
        # approve an FDA data release -- approval requires an elevated
        # (Reviewer/VP) role.
        resp = api_client_doer.post(
            f"{BASE}/fda-data/releases/{active_release.public_id}/approve/",
            data={"notes": "self-approved"},
            format="json",
        )
        assert resp.status_code == 403

    def test_doer_cannot_activate_release(self, api_client_doer, active_release):
        # PLANTED VIOLATION (detected): a Doer must never be able to
        # activate an FDA data release.
        resp = api_client_doer.post(
            f"{BASE}/fda-data/releases/{active_release.public_id}/activate/",
            data={},
            format="json",
        )
        assert resp.status_code == 403
