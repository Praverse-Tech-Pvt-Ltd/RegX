"""Import an official FDA source file.

Until now `fda_data` could only be fed pre-parsed JSON rows over the API, so
the step that turns a published FDA download into those rows lived nowhere.
This command is that step.

    python manage.py import_fda_release EOBZIP_2026_01.zip \\
        --dataset-type orange_book_products \\
        --source-reference "FDA Orange Book, downloaded 2026-01-15 from fda.gov"

    python manage.py import_fda_release iig_july_2026.zip \\
        --dataset-type fda_iid \\
        --source-reference "FDA IID export, downloaded 2026-01-15 from fda.gov"

`--source-reference` is required and never inferred. A file whose columns
match the Orange Book shape is not thereby proved to have come from FDA, and
stamping "FDA official" on it because the header looked right would put an
unearned provenance claim on a governed record. The operator states where the
bytes actually came from.

DATASET TYPE IS NEVER GUESSED. `Products.txt` and `Patent.txt` are both
tilde-delimited ASCII from the same archive; sniffing would eventually guess
wrong, and guessing wrong here means patent rows stored as products.
"""

from __future__ import annotations

import datetime
import io
import pathlib

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from fda_data import importer, parsers
from fda_data.checksums import sha256_payload
from fda_data.dispatch import (
    SUPPORTED_IMPORTERS,
    UnsupportedDatasetType,
    resolve_importer,
)
from fda_data.models import FDADatasetType, FDADataSourceRelease

#: dataset type -> (parser, parser identifier)
_PARSERS = {
    FDADatasetType.ORANGE_BOOK_PRODUCTS: (
        parsers.parse_orange_book_products,
        parsers.ORANGE_BOOK_PRODUCTS_PARSER,
    ),
    FDADatasetType.FDA_IID: (parsers.parse_iid, parsers.IID_CSV_PARSER),
}


class Command(BaseCommand):
    help = (
        "Parse and import an official FDA source file (Orange Book ZIP/Products.txt, "
        "or IID ZIP/IIR_OCOMM.csv)."
    )

    def add_arguments(self, parser):
        parser.add_argument("path", help="Path to the official FDA file.")
        parser.add_argument(
            "--dataset-type",
            required=True,
            choices=sorted(_PARSERS),
            help="Declared explicitly; never sniffed from the file.",
        )
        parser.add_argument(
            "--source-reference",
            required=True,
            help="Where these bytes actually came from. Recorded verbatim.",
        )
        parser.add_argument("--source-name", default="", help="Human label for the release.")
        parser.add_argument("--schema-version", default="")
        parser.add_argument(
            "--publication-date",
            default="",
            help="The date FDA published this data (YYYY-MM-DD), e.g. the source page's "
            "'content current as of' date. Recorded on the release; never inferred.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and validate only. Nothing is written.",
        )

    def handle(self, *args, **options):
        dataset_type = options["dataset_type"]
        path = pathlib.Path(options["path"])
        publication_date = None
        if options["publication_date"]:
            try:
                publication_date = datetime.date.fromisoformat(options["publication_date"])
            except ValueError:
                raise CommandError(
                    f"--publication-date must be YYYY-MM-DD, got {options['publication_date']!r}."
                ) from None

        if not path.is_file():
            raise CommandError(f"No such file: {path}")

        # Belt and braces: _PARSERS and SUPPORTED_IMPORTERS must not drift
        # apart. A parser without an importer would parse a file and then
        # have nowhere to put it.
        try:
            adapter, import_rows = resolve_importer(dataset_type)
        except UnsupportedDatasetType as exc:
            raise CommandError(
                f"{exc.reason}\nSupported: {', '.join(sorted(SUPPORTED_IMPORTERS))}"
            ) from None

        parse, parser_identifier = _PARSERS[dataset_type]
        raw = path.read_bytes()

        self.stdout.write(self.style.MIGRATE_HEADING(f"Parsing {path.name}"))
        try:
            rows = parse(raw, filename=path.name)
        except parsers.SourceFileError as exc:
            # A parse failure leaves nothing behind: no release, no row
            # results, no reconciliation counts to explain away.
            raise CommandError(str(exc)) from None

        self.stdout.write(f"  rows parsed        {len(rows)}")
        self.stdout.write(f"  parser             {parser_identifier}")
        if publication_date:
            self.stdout.write(f"  publication date   {publication_date.isoformat()}")

        neutral = adapter(rows)
        normalized_sha = sha256_payload({"rows": [n["fields"] for n in neutral]})
        self.stdout.write(f"  source bytes       {len(raw)}")
        self.stdout.write(f"  normalized sha256  {normalized_sha[:16]}...")

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("\n--dry-run: nothing was written."))
            return

        with transaction.atomic():
            release = importer.register_release(
                dataset_type=dataset_type,
                source_name=options["source_name"] or path.name,
                # Verbatim, from the operator. Never inferred.
                official_source_reference=options["source_reference"],
                file_obj=io.BytesIO(raw),
                original_filename=path.name,
                media_type=("application/zip" if raw[:2] == b"PK" else "text/plain"),
                schema_version=options["schema_version"],
                normalized_payload_sha256=normalized_sha,
                parser_identifier=parser_identifier,
                publication_date=publication_date,
            )

            already = FDADataSourceRelease.objects.filter(pk=release.pk).values_list(
                "record_count_imported", flat=True
            )[0]
            if already:
                # register_release is idempotent on (dataset_type, source
                # checksum). Re-importing the same bytes would double every
                # row result and corrupt reconciliation.
                self.stdout.write(
                    self.style.WARNING(
                        f"\nThese exact bytes are already imported as release "
                        f"{release.public_id} ({already} rows). Nothing to do."
                    )
                )
                return

            import_rows(release, neutral, None)

        release.refresh_from_db()
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Release {release.public_id} registered."))
        self.stdout.write(f"  status             {release.status}")
        self.stdout.write(f"  source sha256      {release.source_checksum_sha256[:16]}...")
        self.stdout.write(f"  extracted          {release.record_count_extracted}")
        self.stdout.write(f"  imported           {release.record_count_imported}")
        self.stdout.write(f"  failed             {release.record_count_failed}")
        self.stdout.write("")
        self.stdout.write(
            "Registered only. It is not active until it is taken through "
            "validate -> submit-review -> approve -> activate."
        )
        if release.record_count_failed:
            self.stdout.write(
                self.style.WARNING(
                    f"  {release.record_count_failed} row(s) failed -- see the "
                    f"reconciliation report before approving."
                )
            )
