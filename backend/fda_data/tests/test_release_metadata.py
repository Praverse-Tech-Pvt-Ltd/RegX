"""Release metadata: --publication-date on import, and who sees which release fields."""

from __future__ import annotations

import io
from datetime import date
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from fda_data.models import FDADataSourceRelease
from fda_data.tests._loader import loader_email

PRODUCTS = Path(__file__).parent / "fixtures" / "orange_book" / "products_sample.txt"
BASE = "/api/regx/v1/fda-data/releases/"
REF = "Test fixture: real rows from FDA EOBZIP_2026_08.zip"


def _import(tmp_path, *extra, name="products.txt"):
    path = tmp_path / name
    path.write_bytes(PRODUCTS.read_bytes())
    out = io.StringIO()
    call_command(
        "import_fda_release",
        str(path),
        "--dataset-type",
        "orange_book_products",
        "--source-reference",
        REF,
        "--actor",
        loader_email(),
        *extra,
        stdout=out,
    )
    return out.getvalue()


@pytest.mark.django_db
class TestPublicationDateOption:
    def test_publication_date_is_recorded(self, tmp_path):
        output = _import(tmp_path, "--publication-date", "2026-08-18")
        release = FDADataSourceRelease.objects.get()
        assert release.publication_date == date(2026, 8, 18)
        assert "publication date   2026-08-18" in output

    def test_without_the_option_nothing_is_inferred(self, tmp_path):
        _import(tmp_path)
        assert FDADataSourceRelease.objects.get().publication_date is None

    @pytest.mark.parametrize("bad", ["18/08/2026", "2026-13-01", "Aug 18, 2026", "2026-8-18x"])
    def test_malformed_date_is_refused_before_anything_is_written(self, tmp_path, bad):
        with pytest.raises(CommandError, match="--publication-date must be YYYY-MM-DD"):
            _import(tmp_path, "--publication-date", bad)
        assert FDADataSourceRelease.objects.count() == 0

    def test_dry_run_writes_nothing_even_with_a_date(self, tmp_path):
        output = _import(tmp_path, "--publication-date", "2026-08-18", "--dry-run")
        assert FDADataSourceRelease.objects.count() == 0
        assert "publication date   2026-08-18" in output


@pytest.fixture
def imported_release(db, tmp_path):
    _import(tmp_path, "--publication-date", "2026-08-18", name="EOBZIP_2026_08.txt")
    release = FDADataSourceRelease.objects.get()
    FDADataSourceRelease.objects.filter(pk=release.pk).update(
        notes="Dates: page 2026-08-18; file 2026-09-11."
    )
    release.refresh_from_db()
    return release


@pytest.mark.django_db
class TestReleaseFieldVisibility:
    """File name, checksum and notes are raw fields: shown to `view_raw` holders
    (Reviewer, VP), hidden from Doers. The publication date is shown to all."""

    def test_view_raw_holder_sees_file_name_checksum_and_notes(
        self, api_client_vp, imported_release
    ):
        body = api_client_vp.get(f"{BASE}{imported_release.public_id}/").json()
        assert body["original_filename"] == "EOBZIP_2026_08.txt"
        assert body["source_checksum_sha256"] == imported_release.source_checksum_sha256
        assert len(body["source_checksum_sha256"]) == 64
        assert body["notes"] == "Dates: page 2026-08-18; file 2026-09-11."
        assert body["publication_date"] == "2026-08-18"

    def test_doer_sees_publication_date_but_no_raw_fields(self, api_client_doer, imported_release):
        body = api_client_doer.get(f"{BASE}{imported_release.public_id}/").json()
        assert body["publication_date"] == "2026-08-18"
        for raw_field in ("original_filename", "source_checksum_sha256", "notes"):
            assert raw_field not in body
