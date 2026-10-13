"""Parsers for the official FDA source files.

`fda_data` was built to receive rows that somebody else had already parsed --
`importer.import_orange_book_rows` takes `list[dict]`, and the only ingestion
route was a JSON API. That left the step which turns a published FDA file into
those rows undefined and unwritten, so no real release could be imported.

This module is that step, and only that step. It parses and validates; it
persists nothing, resolves no terminology and makes no lifecycle decision.

WHAT IT REFUSES TO GUESS
-----------------------
A missing column is an error, never a blank. The adapters downstream use
`.get(col, "")`, which is correct for optional fields but means a *renamed* or
absent required column silently produces an empty value -- a real IID file
parsed against the wrong column names imports rows with no ingredient name at
all. Required columns are checked here so that cannot happen.

The same applies to values: a required cell that is empty is a rejected row
with a reason, not a record with a hole in it.
"""

from __future__ import annotations

import csv
import io
import zipfile

#: Bump when a parser's output shape changes, so a release records which
#: version of the parsing rules produced its rows.
ORANGE_BOOK_PRODUCTS_PARSER = "orange_book_products_txt:1"
IID_CSV_PARSER = "fda_iid_csv:2"

#: The Orange Book files are tilde-delimited ASCII. Not pipe: an earlier
#: version of docs/ORANGE_BOOK_INGESTION.md said pipe, and a pipe-split of a
#: tilde file yields one column per row, which then fails column validation
#: rather than importing nonsense.
ORANGE_BOOK_DELIMITER = "~"

#: Exactly the member this importer reads. `Patent.txt` and `Exclusivity.txt`
#: ship in the same ZIP and are deliberately ignored: there is no patent or
#: exclusivity model in this codebase, and feeding them to the products
#: adapter produces empty OrangeBookProduct rows that reconciliation then
#: reports as successfully imported.
ORANGE_BOOK_PRODUCTS_MEMBER = "Products.txt"

ORANGE_BOOK_PRODUCTS_REQUIRED_COLUMNS = (
    "Ingredient",
    "DF;Route",
    "Trade_Name",
    "Applicant",
    "Strength",
    "Appl_Type",
    "Appl_No",
    "Product_No",
    "TE_Code",
    "Approval_Date",
    "RLD",
    "RS",
    # RX / OTC / DISCN. Verified present in every row of EOBZIP_2026_08; it is
    # the only source of the discontinued flag, so a file without it must not
    # import as if every product were still marketed.
    "Type",
)

#: The member of the official IID ZIP that holds the data. The same ZIP ships
#: `IIR_OCOMM.xls` and a `Change_Log_Data` pair, which are not read.
IID_MEMBER = "IIR_OCOMM.csv"

#: The IID export's column names, exactly as FDA publishes them. Verified
#: against the July 2026 file (`iig_july_2026.zip`, `IIR_OCOMM.csv`). The
#: previous contract (`Inactive Ingredient`, `Potency Amount`, ...) was never
#: FDA's header, so a real file was refused. These are the contract: the parser
#: fails when one is missing rather than importing blanks. `adapters.py` keeps
#: accepting the older spellings for JSON API callers. `RECORD_UPDATED` (a "Y"
#: on rows changed in that quarter) is also published but not required.
IID_REQUIRED_COLUMNS = (
    "INGREDIENT_NAME",
    "ROUTE",
    "DOSAGE_FORM",
    "CAS_NUMBER",
    "UNII",
    "POTENCY_AMOUNT",
    "POTENCY_UNIT",
    "MAXIMUM_DAILY_EXPOSURE",
    "MAXIMUM_DAILY_EXPOSURE_UNIT",
)

#: Values every row must carry. A row missing any of these is rejected: an IID
#: precedent with no ingredient, route or dosage form cannot be matched to
#: anything. Potency and maximum daily exposure are NOT required: in the real
#: file each row carries one of them, or neither (potency unit "NA" or
#: "ADJ PH"). A blank there is FDA's data, stored as null with an explicit
#: calculability status -- never a reason to drop the row or the file.
IID_REQUIRED_VALUES = ("INGREDIENT_NAME", "ROUTE", "DOSAGE_FORM")

#: Bounds. A zip bomb and a runaway file are the same problem from the
#: parser's point of view: unbounded work triggered by untrusted input.
MAX_UNCOMPRESSED_BYTES = 256 * 1024 * 1024  # 256 MB
MAX_ROWS = 500_000


class SourceFileError(Exception):
    """The supplied file cannot be parsed as the declared dataset type."""


def _decode(raw: bytes, *, what: str) -> str:
    """ASCII with a documented fallback, never a silent replace.

    The Orange Book files are ASCII and the IID export is usually ASCII, but
    real exports have carried stray Latin-1 bytes in applicant names. Trying
    UTF-8 then Latin-1 preserves those bytes; `errors="replace"` would turn
    them into U+FFFD and quietly corrupt a value that ends up in a
    regulatory record.
    """
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise SourceFileError(f"{what}: could not be decoded as UTF-8 or Latin-1.")


def _rows_from_delimited(
    text: str, *, delimiter: str, required_columns: tuple[str, ...], what: str
) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    header = reader.fieldnames or []
    missing = [c for c in required_columns if c not in header]
    if missing:
        raise SourceFileError(
            f"{what}: missing required column(s): {', '.join(missing)}. "
            f"Found: {', '.join(header) or '(no header row)'}."
        )

    rows: list[dict] = []
    for number, row in enumerate(reader, start=1):
        if number > MAX_ROWS:
            raise SourceFileError(f"{what}: exceeds the {MAX_ROWS} row limit.")
        # csv gives None for a short row and a list under the restkey for a
        # long one. Either means the row does not match its header, which is
        # a structural fault -- not something to pad out with empties.
        if any(value is None for value in row.values()) or None in row:
            raise SourceFileError(
                f"{what}: row {number} has a different number of fields than the header."
            )
        cleaned = {k: (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
        cleaned["_row_number"] = number
        rows.append(cleaned)

    if not rows:
        raise SourceFileError(f"{what}: contains a header but no data rows.")
    return rows


# ---------------------------------------------------------------------------
# Orange Book
# ---------------------------------------------------------------------------


def _read_zip_member(raw: bytes, member_name: str) -> bytes:
    """Return the bytes of `member_name` from an official FDA ZIP
    (`Products.txt` for the Orange Book, `IIR_OCOMM.csv` for the IID).

    Every refusal here is a safety property, not a convenience check:
    traversal members cannot be written anywhere because nothing is extracted
    to disk, but a ZIP containing them is not the file it claims to be and is
    refused rather than partially trusted.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise SourceFileError(f"Not a readable ZIP archive: {exc}") from exc

    with archive:
        infos = [i for i in archive.infolist() if not i.is_dir()]

        for info in infos:
            name = info.filename
            if name.startswith("/") or ".." in name.replace("\\", "/").split("/"):
                raise SourceFileError(f"ZIP contains an unsafe member path: {name!r}")
            if name.lower().endswith((".zip", ".gz", ".tar", ".7z")):
                raise SourceFileError(f"ZIP contains a nested archive: {name!r}")

        total = sum(i.file_size for i in infos)
        if total > MAX_UNCOMPRESSED_BYTES:
            raise SourceFileError(
                f"ZIP expands to {total} bytes, over the {MAX_UNCOMPRESSED_BYTES} byte limit."
            )

        # Case-insensitive match: FDA has shipped both `Products.txt` and
        # `products.txt`. Two members differing only in case is ambiguous,
        # and picking one would be a guess about which is authoritative.
        target = member_name.lower()
        matches = [i for i in infos if i.filename.rsplit("/", 1)[-1].lower() == target]
        if not matches:
            present = ", ".join(sorted(i.filename for i in infos)) or "(empty archive)"
            raise SourceFileError(f"ZIP does not contain {member_name}. Members: {present}.")
        if len(matches) > 1:
            raise SourceFileError(
                f"ZIP contains {len(matches)} members named "
                f"{member_name}; refusing to choose between them."
            )

        member = matches[0]
        if member.file_size > MAX_UNCOMPRESSED_BYTES:
            raise SourceFileError(
                f"{member.filename} expands to {member.file_size} bytes, over the limit."
            )
        return archive.read(member)


def parse_orange_book_products(raw: bytes, *, filename: str = "") -> list[dict]:
    """Parse `Products.txt`, or the official ZIP that contains it.

    `Patent.txt` and `Exclusivity.txt` inside that ZIP are never read here.
    """
    if raw[:2] == b"PK":
        raw = _read_zip_member(raw, ORANGE_BOOK_PRODUCTS_MEMBER)
        what = f"{filename or 'archive'}:{ORANGE_BOOK_PRODUCTS_MEMBER}"
    else:
        what = filename or ORANGE_BOOK_PRODUCTS_MEMBER

    text = _decode(raw, what=what)
    return _rows_from_delimited(
        text,
        delimiter=ORANGE_BOOK_DELIMITER,
        required_columns=ORANGE_BOOK_PRODUCTS_REQUIRED_COLUMNS,
        what=what,
    )


# ---------------------------------------------------------------------------
# IID
# ---------------------------------------------------------------------------


def parse_iid(raw: bytes, *, filename: str = "") -> list[dict]:
    """Parse the official comma-delimited IID export (`IIR_OCOMM.csv`), or
    the official ZIP that contains it.

    XLSX is deliberately not handled. `openpyxl` is available, but a cell
    holding a formula with no cached result reads as `None`, and the only
    honest responses are to reject the row or evaluate the formula -- and
    evaluating spreadsheet formulas out of an untrusted file is not something
    this importer should do. Convert to CSV first; the contract is the same.
    """
    if raw[:2] == b"PK":
        raw = _read_zip_member(raw, IID_MEMBER)
        what = f"{filename or 'archive'}:{IID_MEMBER}"
    else:
        what = filename or "IID export"
    text = _decode(raw, what=what)
    rows = _rows_from_delimited(
        text,
        delimiter=",",
        required_columns=IID_REQUIRED_COLUMNS,
        what=what,
    )

    for row in rows:
        blank = [c for c in IID_REQUIRED_VALUES if not (row.get(c) or "").strip()]
        if blank:
            raise SourceFileError(
                f"{what}: row {row['_row_number']} has empty required value(s): {', '.join(blank)}."
            )
    return rows
