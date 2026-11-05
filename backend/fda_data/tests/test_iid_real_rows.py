"""Importer fidelity against real FDA IID rows.

`fixtures/iid/iir_ocomm_sample.csv` is copied byte-for-byte from the FDA file
iig_july_2026.zip, member IIR_OCOMM.csv (SHA-256 4f3a8e37...436d302, members
dated 2026-07-21): CRLF line endings, a trailing CRLF, quoted dosage forms that
contain commas. It is public FDA data. `.gitattributes` keeps git from
normalising its line endings.

Rows (file line numbers): 2 .ALPHA.-TERPINEOL (potency %w/w), 5 and 10
.ALPHA.-TOCOPHEROL (maximum daily exposure only, one quoted form), 11
.ALPHA.-TOCOPHEROL (potency unit "NA", no values), 40 a 115-character
copolymer name (UNII "NA", no CAS), 61 ACACIA (potency mg), 72 ACESULFAME
POTASSIUM (potency mg/5ml), 86 ACETIC ACID (potency unit "ADJ PH"), 141
ACRYLATES COPOLYMER (UNII "NA", daily exposure only), 3803 ISOMALT (largest
potency shape), 4796 NORFLURANE (6-digit daily exposure, RECORD_UPDATED "Y").
"""

from __future__ import annotations

import io
import logging
import zipfile
from decimal import Decimal
from pathlib import Path

import pytest
from django.core.management import call_command

from fda_data import importer, lifecycle
from fda_data.adapters import fda_iid_adapter
from fda_data.models import (
    ControlledDosageForm,
    ControlledRoute,
    DosageFormMapping,
    FDADataSourceRelease,
    FdaImportRowResult,
    FdaImportRowResultType,
    FDAReleaseStatus,
    IIDCalculabilityStatus,
    IIDIngredient,
    IIDPrecedentRecord,
    RouteMapping,
)
from fda_data.parsers import IID_REQUIRED_COLUMNS, SourceFileError, parse_iid
from fda_data.tests._loader import loader_email

from .conftest import make_release_file

FIXTURE = Path(__file__).parent / "fixtures" / "iid" / "iir_ocomm_sample.csv"
RAW = FIXTURE.read_bytes()
HEADER, *LINES = RAW.decode("ascii").split("\r\n")
LINES = [line for line in LINES if line]


def _real_zip(csv_bytes: bytes = RAW, member: str = "IIR_OCOMM.csv") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        # The real archive also carries the .xls twin and the change log.
        z.writestr("IIR_OCOMM.xls", b"\xd0\xcf\x11\xe0 not read")
        z.writestr("Change_Log_Data.csv", b"Change ID,Snapshot Date\r\n")
        z.writestr(member, csv_bytes)
    return buf.getvalue()


def _import(tmp_path, data: bytes = RAW, name: str = "IIR_OCOMM.csv") -> FDADataSourceRelease:
    path = tmp_path / name
    path.write_bytes(data)
    call_command(
        "import_fda_release",
        str(path),
        dataset_type="fda_iid",
        source_reference="Test fixture: real rows from FDA iig_july_2026.zip",
        actor=loader_email(),
        stdout=io.StringIO(),
    )
    return FDADataSourceRelease.objects.latest("created_at")


def _record(name: str, route: str, dosage_form: str) -> IIDPrecedentRecord:
    return IIDPrecedentRecord.objects.get(
        ingredient_name_raw=name, route_raw=route, dosage_form_raw=dosage_form
    )


# ---------------------------------------------------------------------------
# Parsing the real format
# ---------------------------------------------------------------------------


class TestRealFormatParsing:
    def test_fixture_is_the_real_byte_format(self):
        assert RAW.endswith(b"\r\n")
        assert RAW.count(b"\r\n") == 12
        assert HEADER == (
            "INGREDIENT_NAME,ROUTE,DOSAGE_FORM,CAS_NUMBER,UNII,POTENCY_AMOUNT,"
            "POTENCY_UNIT,MAXIMUM_DAILY_EXPOSURE,MAXIMUM_DAILY_EXPOSURE_UNIT,RECORD_UPDATED"
        )

    def test_parses_every_row_with_every_column(self):
        rows = parse_iid(RAW, filename="IIR_OCOMM.csv")
        assert len(rows) == 11
        assert all(set(IID_REQUIRED_COLUMNS) <= set(r) for r in rows)

    def test_quoted_dosage_form_keeps_its_comma(self):
        rows = parse_iid(RAW, filename="IIR_OCOMM.csv")
        assert rows[2]["DOSAGE_FORM"] == "TABLET, FILM COATED"
        assert rows[2]["MAXIMUM_DAILY_EXPOSURE"] == "246"

    def test_rows_without_potency_are_accepted(self):
        """Potency and maximum daily exposure are alternatives in the real
        file. The old contract refused a blank potency, which refused the
        whole July 2026 file (5,266 such rows)."""
        rows = parse_iid(RAW, filename="IIR_OCOMM.csv")
        assert sum(1 for r in rows if not r["POTENCY_AMOUNT"]) == 7

    def test_real_zip_reads_only_the_csv_member(self):
        rows = parse_iid(_real_zip(), filename="iig_july_2026.zip")
        assert len(rows) == 11
        assert rows[0]["INGREDIENT_NAME"] == ".ALPHA.-TERPINEOL"

    def test_zip_without_the_csv_member_is_refused(self):
        with pytest.raises(SourceFileError, match="IIR_OCOMM.csv"):
            parse_iid(_real_zip(member="OTHER.csv"), filename="iig.zip")


class TestMalformedRows:
    @pytest.mark.parametrize("column", IID_REQUIRED_COLUMNS)
    def test_missing_column_is_refused(self, column):
        idx = HEADER.split(",").index(column)
        header = ",".join(c for i, c in enumerate(HEADER.split(",")) if i != idx)
        # Line 2 (.ALPHA.-TERPINEOL) has no quoted field, so a plain split is exact.
        row = ",".join(c for i, c in enumerate(LINES[0].split(",")) if i != idx)
        with pytest.raises(SourceFileError, match=column):
            parse_iid(f"{header}\r\n{row}\r\n".encode("ascii"))

    def test_the_old_guessed_header_is_refused(self):
        old = (
            b"Inactive Ingredient,Route,Dosage Form,CAS Number,UNII,"
            b"Potency Amount,Potency Unit\r\nSYNTHETIC,ORAL,TABLET,,X,1,mg\r\n"
        )
        with pytest.raises(SourceFileError, match="missing required column"):
            parse_iid(old)

    @pytest.mark.parametrize("column", ["INGREDIENT_NAME", "ROUTE", "DOSAGE_FORM"])
    def test_empty_identity_value_is_refused(self, column):
        values = LINES[0].split(",")
        values[HEADER.split(",").index(column)] = ""
        with pytest.raises(SourceFileError, match="empty required value"):
            parse_iid(f"{HEADER}\r\n{','.join(values)}\r\n".encode("ascii"))

    def test_real_row_with_a_field_removed_is_refused(self):
        short = ",".join(LINES[0].split(",")[:-1])
        with pytest.raises(SourceFileError, match="different number of fields"):
            parse_iid(f"{HEADER}\r\n{short}\r\n".encode("ascii"))

    def test_real_row_with_an_extra_field_is_refused(self):
        with pytest.raises(SourceFileError, match="different number of fields"):
            parse_iid(f"{HEADER}\r\n{LINES[0]},EXTRA\r\n".encode("ascii"))


class TestParseIidAmount:
    @pytest.mark.parametrize(
        "text,expected", [("0.14", Decimal("0.14")), ("239360", Decimal("239360")), ("11", 11)]
    )
    def test_plain_decimals_parse(self, text, expected):
        assert importer.parse_iid_amount(text) == (Decimal(expected), False)

    def test_blank_is_no_value_not_a_failure(self):
        assert importer.parse_iid_amount("") == (None, False)

    @pytest.mark.parametrize("text", ["1,200", "<5", "NA", "5 mg", "-1", ".5"])
    def test_anything_else_is_reported_unparsed(self, text):
        assert importer.parse_iid_amount(text) == (None, True)


# ---------------------------------------------------------------------------
# Import fidelity
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestImportFidelity:
    def test_every_row_is_stored_with_one_row_result(self, tmp_path):
        release = _import(tmp_path)
        assert release.iid_records.count() == 11
        assert FdaImportRowResult.objects.filter(release=release).count() == 11
        assert release.record_count_failed == 0
        # No controlled routes are loaded, so nothing is calculable yet.
        assert set(release.iid_records.values_list("calculability_status", flat=True)) == {
            IIDCalculabilityStatus.ROUTE_UNMAPPED
        }

    def test_import_does_not_advance_the_lifecycle(self, tmp_path):
        release = _import(tmp_path)
        assert release.status not in (FDAReleaseStatus.APPROVED, FDAReleaseStatus.ACTIVE)

    def test_potency_row_keeps_number_and_text(self, tmp_path):
        _import(tmp_path)
        r = _record("ACACIA", "ORAL", "TABLET, FILM COATED")
        assert r.potency_amount == Decimal("0.14")
        assert r.potency_amount_raw == "0.14"
        assert r.potency_unit_raw == "mg"
        assert r.maximum_daily_exposure is None
        assert r.mde_amount_raw == ""
        assert r.mde_unit_raw == ""
        assert r.raw_row_payload["CAS_NUMBER"] == "9000015"

    def test_amount_with_a_per_volume_unit_is_not_dropped(self, tmp_path):
        """Amount and unit used to be joined and parsed together; "45 mg/5ml"
        failed that pattern and the plain number 45 was lost."""
        _import(tmp_path)
        r = _record("ACESULFAME POTASSIUM", "ORAL", "POWDER, FOR SUSPENSION")
        assert r.potency_amount == Decimal("45")
        assert r.potency_unit_raw == "mg/5ml"

    def test_daily_exposure_row_stores_amount_unit_and_text(self, tmp_path):
        _import(tmp_path)
        r = _record("NORFLURANE", "RESPIRATORY (INHALATION)", "AEROSOL, METERED")
        assert r.maximum_daily_exposure == Decimal("239360")
        assert r.mde_amount_raw == "239360"
        assert r.mde_unit_raw == "mg"
        assert r.potency_amount is None
        assert r.potency_amount_raw == ""
        assert r.raw_row_payload["RECORD_UPDATED"] == "Y"

    @pytest.mark.parametrize(
        "name,route,form,unit",
        [
            (".ALPHA.-TOCOPHEROL", "TOPICAL", "OINTMENT", "NA"),
            ("ACETIC ACID", "ENDOTRACHEAL", "SUSPENSION", "ADJ PH"),
        ],
    )
    def test_rows_with_no_amount_keep_their_unit_text(self, tmp_path, name, route, form, unit):
        _import(tmp_path)
        r = _record(name, route, form)
        assert r.potency_amount is None
        assert r.maximum_daily_exposure is None
        assert r.potency_unit_raw == unit

    def test_unii_placeholder_never_merges_ingredients(self, tmp_path):
        """1,595 real rows carry UNII "NA". Matching on it merged 819
        different ingredients into whichever came first."""
        _import(tmp_path)
        copolymer = _record("ACRYLATES COPOLYMER", "ORAL", "TABLET").ingredient
        film = IIDPrecedentRecord.objects.get(route_raw="TRANSDERMAL").ingredient
        assert copolymer != film
        assert copolymer.unii == "" and film.unii == ""
        assert not IIDIngredient.objects.filter(unii="NA").exists()

    def test_same_ingredient_with_a_real_unii_is_shared(self, tmp_path):
        _import(tmp_path)
        records = IIDPrecedentRecord.objects.filter(ingredient_name_raw=".ALPHA.-TOCOPHEROL")
        assert records.count() == 3
        assert len({r.ingredient_id for r in records}) == 1
        assert records[0].ingredient.unii == "H4N855PNZ1"

    def test_reimporting_the_same_file_changes_nothing(self, tmp_path):
        release = _import(tmp_path)
        neutral = fda_iid_adapter(parse_iid(RAW))
        importer.import_iid_rows(release, neutral, None)
        assert release.iid_records.count() == 11
        assert FdaImportRowResult.objects.filter(release=release).count() == 11


@pytest.mark.django_db
class TestUnparseableValues:
    def _import_rows(self, rows, user):
        release = importer.register_release(
            dataset_type="fda_iid",
            source_name="FDA IID",
            official_source_reference="ref",
            file_obj=make_release_file(rows),
            original_filename="iid.json",
            imported_by=user,
        )
        importer.import_iid_rows(release, fda_iid_adapter(rows), user)
        return release

    def _real_row(self, line_index):
        return parse_iid(f"{HEADER}\r\n{LINES[line_index]}\r\n".encode("ascii"))[0]

    def test_unparseable_potency_is_kept_flagged_and_logged(self, user_a, caplog):
        route = ControlledRoute.objects.create(
            code="C38288", canonical_label="ORAL", lifecycle="active"
        )
        form = ControlledDosageForm.objects.create(
            code="C42998", canonical_label="TABLET", lifecycle="active"
        )
        RouteMapping.objects.create(
            source_dataset="fda_iid",
            source_raw_value="ORAL",
            controlled_route=route,
            status="approved",
        )
        DosageFormMapping.objects.create(
            source_dataset="fda_iid",
            source_raw_value="TABLET",
            controlled_dosage_form=form,
            status="approved",
        )
        row = self._real_row(8)  # ACRYLATES COPOLYMER,ORAL,TABLET
        row["POTENCY_AMOUNT"] = "1,200"
        row["POTENCY_UNIT"] = "mg"
        with caplog.at_level(logging.WARNING, logger="fda_data.importer"):
            release = self._import_rows([row], user_a)
        record = release.iid_records.get()
        assert record.potency_amount is None
        assert record.potency_amount_raw == "1,200"
        assert record.calculability_status == IIDCalculabilityStatus.POTENCY_UNPARSEABLE
        result = FdaImportRowResult.objects.get(release=release)
        assert result.result == FdaImportRowResultType.REVIEW_REQUIRED
        assert "POTENCY_AMOUNT not parsed; kept as text: 1,200" in result.safe_detail
        assert "IID amount not parsed" in caplog.text

    def test_unparseable_daily_exposure_is_kept_and_flagged(self, user_a):
        row = self._real_row(10)  # NORFLURANE
        row["MAXIMUM_DAILY_EXPOSURE"] = "<239360"
        release = self._import_rows([row], user_a)
        record = release.iid_records.get()
        assert record.maximum_daily_exposure is None
        assert record.mde_amount_raw == "<239360"
        assert record.mde_unit_raw == "mg"
        result = FdaImportRowResult.objects.get(release=release)
        assert result.result == FdaImportRowResultType.REVIEW_REQUIRED
        assert "MAXIMUM_DAILY_EXPOSURE not parsed; kept as text: <239360" in result.safe_detail


@pytest.mark.django_db
class TestLifecycleUnchanged:
    def test_review_approve_activate_with_segregation_of_duties(self, tmp_path, user_a, vp_user):
        release = _import(tmp_path)
        release.imported_by = user_a
        release.save(update_fields=["imported_by"])
        lifecycle.submit_for_review(release, user_a)
        with pytest.raises(Exception, match="cannot approve a release they imported"):
            lifecycle.approve(release, user_a)
        lifecycle.approve(release, vp_user)
        release = lifecycle.activate(release, vp_user)
        assert release.status == FDAReleaseStatus.ACTIVE
        assert release.iid_records.count() == 11
