"""Importer fidelity against real FDA Orange Book rows.

The fixtures in `fixtures/orange_book/` are copied byte-for-byte from the FDA
file EOBZIP_2026_08.zip (SHA-256 84e616aa...a3298e): CRLF line endings, no
newline after the last row, lower-case member names in the ZIP. They are public
FDA data. `.gitattributes` keeps git from normalising their line endings.

Rows: AMZEEQ N212379/001 (RX, RLD+RS), AZELAIC ACID A210928/001 (DISCN),
BUDESONIDE A215328/001 (RX, TE AB, RS only), ALUPENT N016402/001 (DISCN,
"Approved Prior to Jan 1, 1982"), MEN'S ROGAINE N021812/001 (OTC, RLD+RS).
"""

from __future__ import annotations

import io
import locale
import logging
import zipfile
from datetime import date
from pathlib import Path

import pytest
from django.core.management import call_command

from fda_data.importer import APPROVAL_DATE_UNPARSED, parse_approval_date
from fda_data.models import (
    FDADataSourceRelease,
    FdaImportRowResult,
    FDAReleaseStatus,
    OrangeBookProduct,
)
from fda_data.parsers import SourceFileError, parse_orange_book_products
from fda_data.tests._loader import loader_email

FIXTURES = Path(__file__).parent / "fixtures" / "orange_book"
PRODUCTS = (FIXTURES / "products_sample.txt").read_bytes()
PATENTS = (FIXTURES / "patent_sample.txt").read_bytes()
EXCLUSIVITY = (FIXTURES / "exclusivity_sample.txt").read_bytes()
SEARCH = "/api/regx/v1/fda-data/orange-book/products/"


def _real_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        # Lower-case member names, as in the real archive.
        z.writestr("products.txt", PRODUCTS)
        z.writestr("patent.txt", PATENTS)
        z.writestr("exclusivity.txt", EXCLUSIVITY)
    return buf.getvalue()


def _import(tmp_path, data: bytes = PRODUCTS, name: str = "products.txt") -> FDADataSourceRelease:
    path = tmp_path / name
    path.write_bytes(data)
    call_command(
        "import_fda_release",
        str(path),
        dataset_type="orange_book_products",
        source_reference="Test fixture: real rows from FDA EOBZIP_2026_08.zip",
        actor=loader_email(),
        stdout=io.StringIO(),
    )
    return FDADataSourceRelease.objects.latest("created_at")


def _product(appl_no: str) -> OrangeBookProduct:
    return OrangeBookProduct.objects.get(application__application_number=appl_no)


# ---------------------------------------------------------------------------
# Parsing the real format
# ---------------------------------------------------------------------------


class TestRealFormatParsing:
    def test_fixture_is_the_real_byte_format(self):
        assert b"\r\n" in PRODUCTS
        assert not PRODUCTS.endswith(b"\n")

    def test_parses_all_rows_with_all_fourteen_columns(self):
        rows = parse_orange_book_products(PRODUCTS, filename="products.txt")
        assert len(rows) == 5
        assert rows[0]["Type"] == "RX"
        assert rows[0]["Applicant_Full_Name"] == "JOURNEY MEDICAL CORP"
        # CRLF never leaks into a value, including the final row with no newline.
        assert all("\r" not in v for r in rows for v in r.values() if isinstance(v, str))
        assert rows[-1]["Applicant_Full_Name"] == "KENVUE BRANDS LLC"

    def test_real_zip_reads_only_lower_case_products_member(self):
        rows = parse_orange_book_products(_real_zip(), filename="EOBZIP_2026_08.zip")
        assert len(rows) == 5
        assert "Patent_No" not in rows[0]
        assert "Exclusivity_Code" not in rows[0]


class TestMalformedRows:
    def test_file_without_type_column_is_refused(self):
        header, *rows = PRODUCTS.decode("ascii").split("\r\n")
        cols = header.split("~")
        idx = cols.index("Type")
        stripped = [
            "~".join(c for i, c in enumerate(line.split("~")) if i != idx)
            for line in [header, *rows]
        ]
        with pytest.raises(SourceFileError, match="Type"):
            parse_orange_book_products("\r\n".join(stripped).encode("ascii"))

    def test_real_row_with_a_field_removed_is_refused(self):
        header, first, *rest = PRODUCTS.decode("ascii").split("\r\n")
        short = "~".join(first.split("~")[:-1])  # drop Applicant_Full_Name
        with pytest.raises(SourceFileError, match="different number of fields"):
            parse_orange_book_products("\r\n".join([header, short, *rest]).encode("ascii"))

    def test_real_row_with_an_extra_field_is_refused(self):
        header, first, *rest = PRODUCTS.decode("ascii").split("\r\n")
        with pytest.raises(SourceFileError, match="different number of fields"):
            parse_orange_book_products(
                "\r\n".join([header, first + "~EXTRA", *rest]).encode("ascii")
            )


# ---------------------------------------------------------------------------
# Approval dates
# ---------------------------------------------------------------------------


class TestParseApprovalDate:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Oct 18, 2019", date(2019, 10, 18)),
            ("Oct 7, 2020", date(2020, 10, 7)),  # single-digit day, as in the real file
            ("Apr 12, 2023", date(2023, 4, 12)),
        ],
    )
    def test_real_formats_parse(self, text, expected):
        assert parse_approval_date(text) == (expected, False)

    def test_pre_1982_phrase_is_recognised_not_a_failure(self):
        assert parse_approval_date("Approved Prior to Jan 1, 1982") == (None, False)

    def test_empty_is_not_a_failure(self):
        assert parse_approval_date("") == (None, False)

    @pytest.mark.parametrize("text", ["Oct 2019", "2019-10-18", "Octember 18, 2019", "N/A"])
    def test_anything_else_is_reported_unparsed(self, text):
        assert parse_approval_date(text) == (None, True)

    def test_every_month_parses(self):
        months = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
        for number, name in enumerate(months, start=1):
            assert parse_approval_date(f"{name} 1, 2020") == (date(2020, number, 1), False)

    def test_impossible_date_is_reported_unparsed(self):
        assert parse_approval_date("Feb 30, 2020") == (None, True)

    def test_parsing_ignores_the_system_locale(self):
        """`%b` in strptime reads month names from LC_TIME; the parser must not.

        Skips where no non-English locale is installed (the slim test image has
        only C/POSIX). Independence there holds by construction: the parser
        uses a fixed English month table and no locale-aware call.
        """
        original = locale.setlocale(locale.LC_TIME)
        for candidate in ("de_DE.UTF-8", "de_DE.utf8", "fr_FR.UTF-8", "German", "French"):
            try:
                locale.setlocale(locale.LC_TIME, candidate)
                break
            except locale.Error:
                continue
        else:
            pytest.skip("no non-English locale installed")
        try:
            assert parse_approval_date("Oct 18, 2019") == (date(2019, 10, 18), False)
            assert parse_approval_date("Mar 3, 2021") == (date(2021, 3, 3), False)
        finally:
            locale.setlocale(locale.LC_TIME, original)


# ---------------------------------------------------------------------------
# Import: Type, discontinued, RLD/RS, dates
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestImportFidelity:
    def test_type_is_stored_and_discn_marks_discontinued(self, tmp_path):
        _import(tmp_path)
        assert (_product("210928").marketing_category, _product("210928").discontinued) == (
            "DISCN",
            True,
        )
        assert (_product("016402").marketing_category, _product("016402").discontinued) == (
            "DISCN",
            True,
        )
        assert (_product("212379").marketing_category, _product("212379").discontinued) == (
            "RX",
            False,
        )
        assert (_product("215328").marketing_category, _product("215328").discontinued) == (
            "RX",
            False,
        )
        assert (_product("021812").marketing_category, _product("021812").discontinued) == (
            "OTC",
            False,
        )

    def test_rld_and_rs_follow_the_real_yes_no_values(self, tmp_path):
        _import(tmp_path)
        amzeeq, budesonide, azelaic = _product("212379"), _product("215328"), _product("210928")
        assert (amzeeq.rld_flag, amzeeq.reference_standard_flag) == (True, True)
        assert (budesonide.rld_flag, budesonide.reference_standard_flag) == (False, True)
        assert (azelaic.rld_flag, azelaic.reference_standard_flag) == (False, False)

    def test_approval_dates_are_parsed_into_the_date_field(self, tmp_path):
        _import(tmp_path)
        assert _product("212379").approval_date == date(2019, 10, 18)
        assert _product("210928").approval_date == date(2020, 10, 7)

    def test_pre_1982_keeps_text_and_null_date_without_a_warning(self, tmp_path):
        release = _import(tmp_path)
        alupent = _product("016402")
        assert alupent.approval_date is None
        assert alupent.approval_date_text == "Approved Prior to Jan 1, 1982"
        result = FdaImportRowResult.objects.get(
            release=release, target_public_identifier=alupent.public_id
        )
        assert result.reason_code == ""

    def test_unparseable_date_is_kept_flagged_and_logged_never_dropped(self, tmp_path, caplog):
        bad = PRODUCTS.replace(b"~Oct 18, 2019~", b"~Oct 2019~")
        assert bad != PRODUCTS
        with caplog.at_level(logging.WARNING, logger="fda_data.importer"):
            release = _import(tmp_path, bad)
        amzeeq = _product("212379")
        assert amzeeq.approval_date is None
        assert amzeeq.approval_date_text == "Oct 2019"
        result = FdaImportRowResult.objects.get(
            release=release, target_public_identifier=amzeeq.public_id
        )
        assert result.result == "imported"
        assert result.reason_code == APPROVAL_DATE_UNPARSED
        assert "Oct 2019" in result.safe_detail
        release.refresh_from_db()
        assert release.record_count_imported == 5  # still counted: kept, not dropped
        messages = [r.getMessage() for r in caplog.records if r.name == "fda_data.importer"]
        assert any("not parsed" in m for m in messages)
        assert any("1 approval date(s) not parsed" in m for m in messages)


# ---------------------------------------------------------------------------
# Search by trade name and application number
# ---------------------------------------------------------------------------


@pytest.fixture
def active_real_release(db, tmp_path):
    release = _import(tmp_path)
    FDADataSourceRelease.objects.filter(pk=release.pk).update(status=FDAReleaseStatus.ACTIVE)
    return release


@pytest.mark.django_db
class TestSearch:
    def _names(self, client, query):
        resp = client.get(SEARCH + query)
        assert resp.status_code == 200
        return sorted(r["trade_name"] for r in resp.json()["results"])

    def test_trade_name_is_case_insensitive_substring(self, api_client_doer, active_real_release):
        assert self._names(api_client_doer, "?trade_name=amzeeq") == ["AMZEEQ"]
        assert self._names(api_client_doer, "?trade_name=rogaine") == ["MEN'S ROGAINE"]

    @pytest.mark.parametrize("value", ["212379", "N212379", "NDA212379", "nda 212379", " 212379 "])
    def test_application_number_accepts_common_forms(
        self, api_client_doer, active_real_release, value
    ):
        assert self._names(api_client_doer, f"?application_number={value}") == ["AMZEEQ"]

    def test_short_number_is_zero_padded(self, api_client_doer, active_real_release):
        assert self._names(api_client_doer, "?application_number=16402") == ["ALUPENT"]

    def test_type_prefix_must_agree(self, api_client_doer, active_real_release):
        assert self._names(api_client_doer, "?application_number=A212379") == []
        assert self._names(api_client_doer, "?application_number=ANDA210928") == ["AZELAIC ACID"]

    @pytest.mark.parametrize("value", ["21237X", "1234567", "X212379", "%25"])
    def test_malformed_numbers_match_nothing(self, api_client_doer, active_real_release, value):
        assert self._names(api_client_doer, f"?application_number={value}") == []

    def test_results_carry_marketing_category_and_discontinued(
        self, api_client_doer, active_real_release
    ):
        resp = api_client_doer.get(SEARCH + "?application_number=210928")
        row = resp.json()["results"][0]
        assert (row["marketing_category"], row["discontinued"]) == ("DISCN", True)
        assert row["approval_date"] == "2020-10-07"

    def test_inactive_release_is_not_searched(self, api_client_doer, tmp_path):
        _import(tmp_path)  # registered, not activated
        assert self._names(api_client_doer, "?trade_name=amzeeq") == []
