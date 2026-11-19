"""Import an official FDA source file.

Until now `fda_data` could only be fed pre-parsed JSON rows over the API, so
the step that turns a published FDA download into those rows lived nowhere.
This command is that step.

    python manage.py import_fda_release EOBZIP_2026_01.zip \\
        --dataset-type orange_book_products --actor doer@example.com \\
        --source-reference "FDA Orange Book, downloaded 2026-01-15 from fda.gov"

    python manage.py import_fda_release iig_july_2026.zip \\
        --dataset-type fda_iid --actor doer@example.com \\
        --source-reference "FDA IID export, downloaded 2026-01-15 from fda.gov"

`--source-reference` is required and never inferred. A file whose columns
match the Orange Book shape is not thereby proved to have come from FDA, and
stamping "FDA official" on it because the header looked right would put an
unearned provenance claim on a governed record. The operator states where the
bytes actually came from.

DATASET TYPE IS NEVER GUESSED. `Products.txt` and `Patent.txt` are both
tilde-delimited ASCII from the same archive; sniffing would eventually guess
wrong, and guessing wrong here means patent rows stored as products.

EXIT CODES: 0 imported (or --dry-run); 1 error; 2 usage error (Django's argument
parser, e.g. a missing required option); 3 refused because the same data is
already imported for this dataset type (nothing was changed).

THE SAME DATA IS REFUSED (owner decision 2026-11-18). "The same" is the exact
bytes, or the same normalised content: the sorted per-row hashes, ignoring line
endings and trailing whitespace (`checksums.content_fingerprint`), so a copy of
the file re-saved with CRLF line endings is refused too.

DELIBERATE RE-IMPORT (IID only). `--deliberate-reimport --reason "..."` imports
data that is already imported as a NEW release, linked to the earlier one
(`reimport_of`) with the written reason, and audited. Use it when mappings
approved since the earlier release was reviewed would now link more records
(an already-reviewed release can never be re-resolved). The new release goes
through the whole lifecycle like any other: re-resolve, validate, submit for
review, approve and activate by someone other than the loader. On activation
it supersedes the active release, which stays as history and stays readable.
"""

from __future__ import annotations

import datetime
import io
import pathlib

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from fda_data import importer, parsers
from fda_data.checksums import content_fingerprint, sha256_payload
from fda_data.dispatch import (
    SUPPORTED_IMPORTERS,
    UnsupportedDatasetType,
    resolve_importer,
)
from fda_data.models import FDADatasetType, FdaImportRowResult
from fda_data.permissions import LoaderActorError, resolve_loader_actor

DUPLICATE_EXIT_CODE = 3

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
        parser.add_argument(
            "--actor",
            required=True,
            help="Email of the user doing this load. Must be an existing, active user "
            "holding fda_data.import (Doer). Recorded on the release and its audit "
            "events; that user cannot later approve or activate the release.",
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
        parser.add_argument(
            "--deliberate-reimport",
            action="store_true",
            help="IID only. Import data that is ALREADY imported, on purpose, as a new "
            "release linked to the earlier one. Needs --reason.",
        )
        parser.add_argument(
            "--reason",
            default="",
            help="Required with --deliberate-reimport: why the same data is imported again. "
            "Recorded on the release and in the audit trail.",
        )

    def handle(self, *args, **options):
        dataset_type = options["dataset_type"]
        path = pathlib.Path(options["path"])
        try:
            actor = resolve_loader_actor(options["actor"])
        except LoaderActorError as exc:
            raise CommandError(str(exc)) from None
        publication_date = None
        if options["publication_date"]:
            try:
                publication_date = datetime.date.fromisoformat(options["publication_date"])
            except ValueError:
                raise CommandError(
                    f"--publication-date must be YYYY-MM-DD, got {options['publication_date']!r}."
                ) from None

        deliberate = options["deliberate_reimport"]
        reason = (options["reason"] or "").strip()
        if deliberate and not reason:
            raise CommandError(
                "--deliberate-reimport needs --reason: say why the same data is imported again."
            )
        if reason and not deliberate:
            raise CommandError("--reason is only used with --deliberate-reimport.")
        if deliberate and dataset_type != "fda_iid":
            raise CommandError("--deliberate-reimport is available for the FDA IID only.")

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
        fingerprint = content_fingerprint([n["fields"] for n in neutral])
        self.stdout.write(f"  source bytes       {len(raw)}")
        self.stdout.write(f"  normalized sha256  {normalized_sha[:16]}...")
        self.stdout.write(f"  content print      {fingerprint[:16]}...")

        duplicate = importer.find_imported_duplicate(
            dataset_type,
            io.BytesIO(raw),
            content_fingerprint=fingerprint,
            normalized_payload_sha256=normalized_sha,
        )
        if deliberate and duplicate is None:
            raise CommandError(
                "--deliberate-reimport: this data is not imported yet, so there is nothing to "
                "re-import. Import it normally (without --deliberate-reimport and --reason)."
            )

        if options["dry_run"]:
            if duplicate is not None:
                self.stdout.write(
                    f"  same data as       release {duplicate.public_id} ({duplicate.status})"
                )
            self.stdout.write(self.style.WARNING("\n--dry-run: nothing was written."))
            return

        if duplicate and not deliberate:
            # Importing the same data again would change nothing and would
            # not apply mappings approved since; it only looked like a new
            # import. Exit code 3: distinct from errors (1), from argument-
            # parser usage errors (2) and from success.
            results = FdaImportRowResult.objects.filter(release=duplicate).count()
            raise CommandError(
                f"Refused: the same data is already imported as release "
                f"{duplicate.public_id} (status: {duplicate.status}, "
                f"{results} row results); same content even if line endings or "
                "trailing spaces differ. Nothing was changed. To import it again on "
                "purpose (IID only), use --deliberate-reimport with --reason.",
                returncode=DUPLICATE_EXIT_CODE,
            )

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
                imported_by=actor,
                content_fingerprint=fingerprint,
                reimport_of=duplicate if deliberate else None,
                reimport_reason=reason if deliberate else "",
            )
            import_rows(release, neutral, actor)

        release.refresh_from_db()
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Release {release.public_id} registered."))
        self.stdout.write(f"  status             {release.status}")
        self.stdout.write(f"  loaded by          {actor.email}")
        if release.reimport_of_id:
            self.stdout.write(
                f"  re-import of       release {duplicate.public_id} ({duplicate.status}); "
                "it stays as history and is superseded only when this one is activated"
            )
            self.stdout.write(f"  reason             {release.reimport_reason}")
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
