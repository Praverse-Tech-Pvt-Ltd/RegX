"""Importing the same bytes twice is refused, for every import path.

Before: `import_fda_release` stopped only when `record_count_imported` > 0. An
IID release whose rows are all `review_required` has 0 there, so the same file
ran again as a silent no-op that printed "registered". The JSON API had no
check at all and answered 201. Neither applied mappings approved in between.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from django.core.management import call_command

from audit.models import AuditEvent
from fda_data.models import FDADataSourceRelease, FdaImportRowResult

FIXTURES = Path(__file__).parent / "fixtures"
PRODUCTS = (FIXTURES / "orange_book" / "products_sample.txt").read_bytes()
IID = (FIXTURES / "iid" / "iir_ocomm_sample.csv").read_bytes()
RELEASES_URL = "/api/regx/v1/fda-data/releases/"


def _run(tmp_path, data: bytes, name: str, dataset_type: str) -> str:
    path = tmp_path / name
    path.write_bytes(data)
    out = io.StringIO()
    call_command(
        "import_fda_release",
        str(path),
        dataset_type=dataset_type,
        source_reference="Test fixture: real FDA rows",
        stdout=out,
    )
    return out.getvalue()


def _snapshot(release):
    return (
        FDADataSourceRelease.objects.count(),
        FdaImportRowResult.objects.filter(release=release).count(),
        AuditEvent.objects.filter(resource_id=str(release.public_id)).count(),
    )


@pytest.mark.django_db
class TestCommandRefusesTheSameFile:
    def test_orange_book_same_file_is_refused(self, tmp_path):
        _run(tmp_path, PRODUCTS, "products.txt", "orange_book_products")
        release = FDADataSourceRelease.objects.get()
        before = _snapshot(release)
        out = _run(tmp_path, PRODUCTS, "products.txt", "orange_book_products")
        assert "Refused" in out and str(release.public_id) in out
        assert f"status: {release.status}" in out
        assert _snapshot(release) == before

    def test_iid_with_only_review_required_rows_is_refused(self, tmp_path):
        """The case the old check missed: 0 rows counted as imported."""
        _run(tmp_path, IID, "IIR_OCOMM.csv", "fda_iid")
        release = FDADataSourceRelease.objects.get()
        assert release.record_count_imported == 0
        assert FdaImportRowResult.objects.filter(release=release).count() == 11
        before = _snapshot(release)
        out = _run(tmp_path, IID, "IIR_OCOMM.csv", "fda_iid")
        assert "Refused" in out and str(release.public_id) in out
        assert "registered." not in out  # no longer looks like a fresh import
        assert _snapshot(release) == before  # no extra audit event either

    def test_a_genuinely_new_file_is_accepted(self, tmp_path):
        _run(tmp_path, IID, "IIR_OCOMM.csv", "fda_iid")
        header, first, *_ = IID.split(b"\r\n")
        out = _run(tmp_path, header + b"\r\n" + first + b"\r\n", "IIR_OCOMM_one_row.csv", "fda_iid")
        assert "Refused" not in out
        assert FDADataSourceRelease.objects.count() == 2

    def test_same_bytes_under_another_dataset_type_are_not_a_duplicate(self, tmp_path):
        """Duplicates are per dataset type; the parser still decides."""
        _run(tmp_path, PRODUCTS, "products.txt", "orange_book_products")
        from django.core.management.base import CommandError

        with pytest.raises(CommandError, match="missing required column"):
            _run(tmp_path, PRODUCTS, "products.txt", "fda_iid")


@pytest.mark.django_db
class TestJsonApiRefusesTheSamePayload:
    PAYLOAD = {
        "dataset_type": "fda_iid",
        "source_name": "iid",
        "official_source_reference": "test",
        "rows": [
            {
                "INGREDIENT_NAME": "ACACIA",
                "ROUTE": "ORAL",
                "DOSAGE_FORM": "TABLET, FILM COATED",
                "UNII": "5C5403N26O",
                "POTENCY_AMOUNT": "0.14",
                "POTENCY_UNIT": "mg",
            }
        ],
    }

    def test_duplicate_payload_returns_409_and_changes_nothing(self, api_client_doer):
        first = api_client_doer.post(RELEASES_URL, self.PAYLOAD, format="json")
        assert first.status_code == 201
        release = FDADataSourceRelease.objects.get()
        before = _snapshot(release)
        second = api_client_doer.post(RELEASES_URL, self.PAYLOAD, format="json")
        assert second.status_code == 409
        assert second.data["error_code"] == "duplicate_release"
        assert second.data["existing_release_public_id"] == str(release.public_id)
        assert second.data["existing_release_status"] == release.status
        assert _snapshot(release) == before

    def test_different_payload_is_accepted(self, api_client_doer):
        api_client_doer.post(RELEASES_URL, self.PAYLOAD, format="json")
        other = {**self.PAYLOAD, "rows": [{**self.PAYLOAD["rows"][0], "POTENCY_AMOUNT": "0.15"}]}
        assert api_client_doer.post(RELEASES_URL, other, format="json").status_code == 201
        assert FDADataSourceRelease.objects.count() == 2
