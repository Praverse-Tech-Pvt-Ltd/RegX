"""P5: official-file parsing, explicit dataset dispatch and split provenance.

Two defects were found live before this was written, and the first two classes
below are their regression gates:

  * a patent row, posted as `orange_book_patents`, was routed through the
    PRODUCTS adapter and created an `OrangeBookProduct` with an empty
    ingredient, trade name and strength -- which reconciliation then reported
    as `imported: 1`
  * an unsupported terminology payload registered a release and returned
    HTTP 201 with `extracted: 0, imported: 0`, a success response for work
    that never happened

Everything else here exists because a parser that guesses is worse than no
parser: the fixtures are deliberately malformed in the specific ways a real
download goes wrong.

All fixture content is synthetic. No row here is FDA data, and nothing in this
file is loaded into a non-test database.
"""

from __future__ import annotations

import hashlib
import io
import zipfile

import pytest

from fda_data.models import FDADatasetType, FDADataSourceRelease, OrangeBookProduct
from fda_data.parsers import (
    ORANGE_BOOK_DELIMITER,
    SourceFileError,
    parse_iid,
    parse_orange_book_products,
)

pytestmark = pytest.mark.django_db

RELEASES_URL = "/api/regx/v1/fda-data/releases/"

# --- synthetic fixtures, in the official shapes -----------------------------

PRODUCTS_HEADER = (
    "Ingredient~DF;Route~Trade_Name~Applicant~Strength~Appl_Type~Appl_No~"
    "Product_No~TE_Code~Approval_Date~RLD~RS~Type"
)
PRODUCTS_ROW = (
    "SYNTHETIC-ACETAMINOPHEN~TABLET;ORAL~SYNTHETIC-BRAND~SYNTH LABS~500MG~"
    "A~099999~001~AB~Jan 1, 2020~No~No~RX"
)
PRODUCTS_TXT = f"{PRODUCTS_HEADER}\n{PRODUCTS_ROW}\n".encode()

IID_CSV = (
    b"INGREDIENT_NAME,ROUTE,DOSAGE_FORM,CAS_NUMBER,UNII,POTENCY_AMOUNT,POTENCY_UNIT,"
    b"MAXIMUM_DAILY_EXPOSURE,MAXIMUM_DAILY_EXPOSURE_UNIT,RECORD_UPDATED\n"
    b"SYNTHETIC-STARCH,ORAL,TABLET,9005258,O8232NY3SJ,50,MG,,,\n"
)


def _zip(members: list[tuple[str, bytes]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in members:
            archive.writestr(name, payload)
    return buffer.getvalue()


# ===========================================================================
# MANDATORY GATE 1 -- a patent row must never create an OrangeBookProduct
# ===========================================================================


class TestPatentRowNeverCreatesAProduct:
    PATENT_ROW = {
        "Appl_Type": "N",
        "Appl_No": "012345",
        "Product_No": "001",
        "Patent_No": "9999999",
        "Patent_Expire_Date_Text": "Jan 1, 2030",
        "Drug_Substance_Flag": "Y",
    }

    def test_patent_dataset_is_refused_before_anything_is_written(self, api_client_doer):
        response = api_client_doer.post(
            RELEASES_URL,
            {
                "dataset_type": "orange_book_patents",
                "source_name": "patents",
                "official_source_reference": "test",
                "rows": [self.PATENT_ROW],
            },
            format="json",
        )
        assert response.status_code == 400
        assert response.data["error_code"] == "unsupported_dataset_type"

        # The gate itself.
        assert OrangeBookProduct.objects.count() == 0
        # And no release, so reconciliation has nothing to misreport.
        assert FDADataSourceRelease.objects.count() == 0

    def test_exclusivity_dataset_is_refused_the_same_way(self, api_client_doer):
        response = api_client_doer.post(
            RELEASES_URL,
            {
                "dataset_type": "orange_book_exclusivity",
                "source_name": "exclusivity",
                "official_source_reference": "test",
                "rows": [{"Appl_No": "012345", "Exclusivity_Code": "NCE"}],
            },
            format="json",
        )
        assert response.status_code == 400
        assert OrangeBookProduct.objects.count() == 0

    def test_a_products_zip_containing_patent_txt_imports_only_products(self):
        """The official ZIP ships Patent.txt beside Products.txt. Its presence
        must not put patent rows through the products parser."""
        archive = _zip(
            [
                ("Products.txt", PRODUCTS_TXT),
                ("Patent.txt", b"Appl_Type~Appl_No~Patent_No\nN~012345~9999999\n"),
                ("Exclusivity.txt", b"Appl_Type~Appl_No~Exclusivity_Code\nN~012345~NCE\n"),
            ]
        )
        rows = parse_orange_book_products(archive, filename="EOBZIP.zip")
        assert len(rows) == 1
        assert rows[0]["Ingredient"] == "SYNTHETIC-ACETAMINOPHEN"
        assert "Patent_No" not in rows[0]


# ===========================================================================
# MANDATORY GATE 2 -- unsupported types never succeed with zero rows
# ===========================================================================


class TestUnsupportedDatasetTypesAreRefused:
    @pytest.mark.parametrize(
        "dataset_type",
        [
            "fda_route_terminology",
            "fda_dosage_form_terminology",
            "fda_substance_identifiers",
            "orange_book_discontinued",
        ],
    )
    def test_no_201_with_zero_imported_rows(self, api_client_doer, dataset_type):
        response = api_client_doer.post(
            RELEASES_URL,
            {
                "dataset_type": dataset_type,
                "source_name": "probe",
                "official_source_reference": "test",
                "rows": [{"Route": "ORAL", "Code": "C38288"}],
            },
            format="json",
        )
        assert response.status_code == 400, (
            f"{dataset_type} returned {response.status_code}; an unsupported "
            f"type must never look like a successful import"
        )
        assert FDADataSourceRelease.objects.count() == 0

    def test_the_refusal_explains_itself_and_lists_what_is_supported(self, api_client_doer):
        response = api_client_doer.post(
            RELEASES_URL,
            {
                "dataset_type": "fda_route_terminology",
                "source_name": "probe",
                "official_source_reference": "test",
                "rows": [],
            },
            format="json",
        )
        assert "not implemented" in response.data["detail"].lower()
        assert set(response.data["supported_dataset_types"]) == {
            "orange_book_products",
            "fda_iid",
        }

    def test_every_declared_dataset_type_is_supported_or_explicitly_refused(self):
        """An enum member must not imply support. This fails if someone adds a
        dataset type without either an importer or a stated reason."""
        from fda_data.dispatch import SUPPORTED_IMPORTERS, UNSUPPORTED_REASONS

        for value, _label in FDADatasetType.choices:
            assert value in SUPPORTED_IMPORTERS or value in UNSUPPORTED_REASONS, (
                f"{value} is declared but neither importable nor explained"
            )

    def test_supported_types_still_import(self, api_client_doer):
        response = api_client_doer.post(
            RELEASES_URL,
            {
                "dataset_type": "orange_book_products",
                "source_name": "products",
                "official_source_reference": "test",
                "rows": [
                    {
                        "Ingredient": "SYNTHETIC-ACETAMINOPHEN",
                        "DF;Route": "TABLET;ORAL",
                        "Trade_Name": "SYNTHETIC-BRAND",
                        "Applicant": "SYNTH LABS",
                        "Strength": "500MG",
                        "Appl_Type": "A",
                        "Appl_No": "099999",
                        "Product_No": "001",
                        "TE_Code": "AB",
                        "Approval_Date": "Jan 1, 2020",
                        "RLD": "No",
                        "RS": "No",
                    }
                ],
            },
            format="json",
        )
        assert response.status_code == 201
        assert OrangeBookProduct.objects.count() == 1


# ===========================================================================
# Orange Book parser
# ===========================================================================


class TestOrangeBookParser:
    def test_parses_a_plain_products_file(self):
        rows = parse_orange_book_products(PRODUCTS_TXT, filename="Products.txt")
        assert len(rows) == 1
        assert rows[0]["Trade_Name"] == "SYNTHETIC-BRAND"
        assert rows[0]["_row_number"] == 1

    def test_parses_the_official_zip(self):
        rows = parse_orange_book_products(_zip([("Products.txt", PRODUCTS_TXT)]))
        assert len(rows) == 1

    def test_delimiter_is_tilde_not_pipe(self):
        """The previous documentation said pipe-delimited. A pipe split of a
        tilde file yields one column, which must fail loudly."""
        piped = PRODUCTS_TXT.replace(b"~", b"|")
        with pytest.raises(SourceFileError, match="missing required column"):
            parse_orange_book_products(piped, filename="Products.txt")
        assert ORANGE_BOOK_DELIMITER == "~"

    def test_missing_products_member_is_refused(self):
        archive = _zip([("Patent.txt", b"Appl_No~Patent_No\nN~1\n")])
        with pytest.raises(SourceFileError, match="does not contain Products.txt"):
            parse_orange_book_products(archive)

    def test_duplicate_products_members_are_refused(self):
        archive = _zip([("Products.txt", PRODUCTS_TXT), ("sub/Products.txt", PRODUCTS_TXT)])
        with pytest.raises(SourceFileError, match="refusing to choose"):
            parse_orange_book_products(archive)

    def test_path_traversal_member_is_refused(self):
        archive = _zip([("../../etc/passwd", b"x"), ("Products.txt", PRODUCTS_TXT)])
        with pytest.raises(SourceFileError, match="unsafe member path"):
            parse_orange_book_products(archive)

    def test_nested_archive_is_refused(self):
        archive = _zip([("Products.txt", PRODUCTS_TXT), ("inner.zip", b"PK\x03\x04")])
        with pytest.raises(SourceFileError, match="nested archive"):
            parse_orange_book_products(archive)

    def test_missing_required_column_is_refused(self):
        header = PRODUCTS_HEADER.replace("~Strength", "")
        broken = f"{header}\n{PRODUCTS_ROW}\n".encode()
        with pytest.raises(SourceFileError, match="Strength"):
            parse_orange_book_products(broken, filename="Products.txt")

    def test_short_row_is_refused_rather_than_padded(self):
        broken = f"{PRODUCTS_HEADER}\nONLY~TWO\n".encode()
        with pytest.raises(SourceFileError, match="different number of fields"):
            parse_orange_book_products(broken, filename="Products.txt")

    def test_header_with_no_data_rows_is_refused(self):
        with pytest.raises(SourceFileError, match="no data rows"):
            parse_orange_book_products(f"{PRODUCTS_HEADER}\n".encode(), filename="Products.txt")

    def test_latin1_bytes_are_preserved_not_replaced(self):
        """A stray non-UTF-8 byte in an applicant name must survive as a
        character, not become U+FFFD in a governed record."""
        row = PRODUCTS_ROW.replace("SYNTH LABS", "SYNTH\xe9 LABS")
        raw = f"{PRODUCTS_HEADER}\n{row}\n".encode("latin-1")
        rows = parse_orange_book_products(raw, filename="Products.txt")
        assert "�" not in rows[0]["Applicant"]
        assert rows[0]["Applicant"] == "SYNTH\xe9 LABS"

    def test_not_a_zip_and_not_delimited_is_refused(self):
        with pytest.raises(SourceFileError):
            parse_orange_book_products(b"PK\x03\x04 truncated garbage")


# ===========================================================================
# IID parser -- official column contract
# ===========================================================================


class TestIidParser:
    def test_parses_the_official_columns(self):
        rows = parse_iid(IID_CSV, filename="iid.csv")
        assert rows[0]["INGREDIENT_NAME"] == "SYNTHETIC-STARCH"
        assert rows[0]["POTENCY_AMOUNT"] == "50"
        assert rows[0]["POTENCY_UNIT"] == "MG"

    @pytest.mark.parametrize(
        "column",
        ["INGREDIENT_NAME", "POTENCY_AMOUNT", "POTENCY_UNIT", "UNII", "MAXIMUM_DAILY_EXPOSURE"],
    )
    def test_missing_required_column_is_refused(self, column):
        text = IID_CSV.decode()
        header, row = text.splitlines()[0], text.splitlines()[1]
        index = header.split(",").index(column)
        new_header = ",".join(c for i, c in enumerate(header.split(",")) if i != index)
        new_row = ",".join(c for i, c in enumerate(row.split(",")) if i != index)
        with pytest.raises(SourceFileError, match=column):
            parse_iid(f"{new_header}\n{new_row}\n".encode(), filename="iid.csv")

    @pytest.mark.parametrize("column", ["INGREDIENT_NAME", "ROUTE", "DOSAGE_FORM"])
    def test_empty_required_value_is_refused_not_blank_filled(self, column):
        """The old adapter used .get(col, ""), so a missing value became an
        empty string. Potency is no longer required here: the real file leaves
        it blank on rows that state a maximum daily exposure instead (see
        test_iid_real_rows.py)."""
        text = IID_CSV.decode()
        header = text.splitlines()[0].split(",")
        values = text.splitlines()[1].split(",")
        values[header.index(column)] = ""
        broken = f"{','.join(header)}\n{','.join(values)}\n".encode()
        with pytest.raises(SourceFileError, match="empty required value"):
            parse_iid(broken, filename="iid.csv")


class TestIidAdapterColumnNames:
    def test_official_names_populate_the_neutral_row(self):
        from fda_data.adapters import fda_iid_adapter

        fields = fda_iid_adapter(
            [
                {
                    "Inactive Ingredient": "SYNTHETIC-STARCH",
                    "Potency Amount": "50",
                    "Potency Unit": "MG",
                    "Route": "ORAL",
                    "Dosage Form": "TABLET",
                    "CAS Number": "9005-25-8",
                    "UNII": "O8232NY3SJ",
                }
            ]
        )[0]["fields"]
        assert fields["ingredient_name_raw"] == "SYNTHETIC-STARCH"
        assert fields["potency_raw"] == "50"
        assert fields["potency_unit_raw"] == "MG"

    def test_legacy_names_still_work_for_existing_api_callers(self):
        from fda_data.adapters import fda_iid_adapter

        fields = fda_iid_adapter(
            [{"Ingredient Name": "SYNTHETIC-STARCH", "Potency": "50", "Unit": "MG"}]
        )[0]["fields"]
        assert fields["ingredient_name_raw"] == "SYNTHETIC-STARCH"
        assert fields["potency_raw"] == "50"
        assert fields["potency_unit_raw"] == "MG"


# ===========================================================================
# Provenance
# ===========================================================================


class TestProvenance:
    def _import(self, tmp_path, monkeypatch):
        from django.core.management import call_command

        path = tmp_path / "Products.txt"
        path.write_bytes(PRODUCTS_TXT)
        out = io.StringIO()
        call_command(
            "import_fda_release",
            str(path),
            dataset_type="orange_book_products",
            source_reference="Synthetic test fixture, not FDA data",
            stdout=out,
        )
        return FDADataSourceRelease.objects.get(), out.getvalue()

    def test_source_checksum_is_the_sha256_of_the_exact_file_bytes(self, tmp_path, monkeypatch):
        release, _ = self._import(tmp_path, monkeypatch)
        assert release.source_checksum_sha256 == hashlib.sha256(PRODUCTS_TXT).hexdigest()

    def test_normalized_payload_checksum_is_recorded_separately(self, tmp_path, monkeypatch):
        release, _ = self._import(tmp_path, monkeypatch)
        assert release.normalized_payload_sha256
        assert release.normalized_payload_sha256 != release.source_checksum_sha256

    def test_filename_size_and_parser_are_preserved(self, tmp_path, monkeypatch):
        release, _ = self._import(tmp_path, monkeypatch)
        assert release.original_filename == "Products.txt"
        assert release.source_file_size_bytes == len(PRODUCTS_TXT)
        assert release.parser_identifier == "orange_book_products_txt:1"

    def test_source_reference_is_recorded_verbatim_and_never_invented(self, tmp_path, monkeypatch):
        """Matching the Orange Book column shape does not prove FDA origin."""
        release, _ = self._import(tmp_path, monkeypatch)
        assert release.official_source_reference == ("Synthetic test fixture, not FDA data")
        assert "FDA official" not in release.official_source_reference

    def test_json_api_records_no_parser_identifier(self, api_client_doer):
        """No parser ran, so the field stays blank rather than claiming one."""
        api_client_doer.post(
            RELEASES_URL,
            {
                "dataset_type": "fda_iid",
                "source_name": "iid",
                "official_source_reference": "test",
                "rows": [
                    {
                        "Inactive Ingredient": "SYNTHETIC-STARCH",
                        "Potency Amount": "50",
                        "Potency Unit": "MG",
                        "Route": "ORAL",
                        "Dosage Form": "TABLET",
                        "CAS Number": "9005-25-8",
                        "UNII": "O8232NY3SJ",
                    }
                ],
            },
            format="json",
        )
        assert FDADataSourceRelease.objects.get().parser_identifier == ""


class TestFileImportIdempotency:
    def test_importing_the_same_bytes_twice_creates_one_release(self, tmp_path):
        from django.core.management import call_command

        path = tmp_path / "Products.txt"
        path.write_bytes(PRODUCTS_TXT)
        args = {
            "dataset_type": "orange_book_products",
            "source_reference": "Synthetic test fixture",
        }
        from django.core.management.base import CommandError

        call_command("import_fda_release", str(path), stdout=io.StringIO(), **args)
        # Contract changed on purpose: a refused duplicate now exits with
        # code 3 (it used to print a notice and exit 0; 2 is argparse usage).
        with pytest.raises(CommandError, match="already imported") as exc:
            call_command("import_fda_release", str(path), stdout=io.StringIO(), **args)
        assert exc.value.returncode == 3

        assert FDADataSourceRelease.objects.count() == 1
        # The row was not imported twice.
        assert OrangeBookProduct.objects.count() == 1

    def test_dry_run_writes_nothing(self, tmp_path):
        from django.core.management import call_command

        path = tmp_path / "Products.txt"
        path.write_bytes(PRODUCTS_TXT)
        out = io.StringIO()
        call_command(
            "import_fda_release",
            str(path),
            dataset_type="orange_book_products",
            source_reference="Synthetic test fixture",
            dry_run=True,
            stdout=out,
        )
        assert "nothing was written" in out.getvalue().lower()
        assert FDADataSourceRelease.objects.count() == 0
