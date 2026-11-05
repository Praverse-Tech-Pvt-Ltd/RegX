"""Load a saved FDA SPL route or dosage-form list as controlled vocabulary.

    python manage.py load_spl_terminology route-administration.csv \\
        --list routes --page-date 2021-10-29 --actor doer@example.com \\
        --source-reference "FDA SPL Route of Administration page, saved 2026-10-13 from fda.gov"

The file is a CSV snapshot of FDA's table (`spl_term,nci_code`), saved by an
operator. Nothing is fetched from fda.gov. The load registers a versioned
release and creates new terms as draft; the vocabulary only changes when that
release is approved and activated (see `fda_data/spl_terminology.py`).
Loading the same file twice changes nothing.
"""

from __future__ import annotations

import datetime
import pathlib

from django.core.management.base import BaseCommand, CommandError

from fda_data import spl_terminology
from fda_data.permissions import LoaderActorError, resolve_loader_actor


class Command(BaseCommand):
    help = "Load a saved FDA SPL route or dosage-form CSV snapshot (routes and dosage forms only)."

    def add_arguments(self, parser):
        parser.add_argument("path", help="CSV snapshot with header spl_term,nci_code.")
        parser.add_argument("--list", required=True, choices=sorted(spl_terminology.SPL_LISTS))
        parser.add_argument(
            "--page-date",
            required=True,
            help="The FDA page's 'content current as of' date (YYYY-MM-DD).",
        )
        parser.add_argument(
            "--source-reference",
            required=True,
            help="Where and when the page was saved. Recorded verbatim.",
        )
        parser.add_argument(
            "--actor",
            required=True,
            help="Email of the user doing this load. Must be an existing, active user "
            "holding fda_data.import (Doer). Recorded on the release and its audit "
            "events; that user cannot later approve or activate the release.",
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="Validate the snapshot only; write nothing."
        )

    def handle(self, *args, **options):
        path = pathlib.Path(options["path"])
        try:
            actor = resolve_loader_actor(options["actor"])
        except LoaderActorError as exc:
            raise CommandError(str(exc)) from None
        if not path.is_file():
            raise CommandError(f"No such file: {path}")
        try:
            page_date = datetime.date.fromisoformat(options["page_date"])
        except ValueError:
            raise CommandError(
                f"--page-date must be YYYY-MM-DD, got {options['page_date']!r}."
            ) from None
        raw = path.read_bytes()

        try:
            terms = spl_terminology.parse_snapshot(raw)
        except spl_terminology.SnapshotError as exc:
            raise CommandError(str(exc)) from None
        self.stdout.write(f"  terms in snapshot  {len(terms)}")
        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("--dry-run: nothing was written."))
            return

        release, summary = spl_terminology.load_snapshot(
            list_name=options["list"],
            raw=raw,
            filename=path.name,
            page_date=page_date,
            source_reference=options["source_reference"],
            actor=actor,
        )
        if summary["already_loaded"]:
            self.stdout.write(
                self.style.WARNING(
                    f"These exact bytes are already loaded as release {release.public_id}. "
                    "Nothing changed."
                )
            )
        else:
            self.stdout.write(self.style.SUCCESS(f"Release {release.public_id} registered."))
        self.stdout.write(f"  status             {release.status}")
        loader = release.imported_by.email if release.imported_by else "(not recorded)"
        self.stdout.write(f"  loaded by          {loader}")
        self.stdout.write(f"  source sha256      {release.source_checksum_sha256[:16]}...")
        self.stdout.write(f"  new terms (draft)  {summary[spl_terminology.NEW]}")
        self.stdout.write(f"  unchanged          {summary[spl_terminology.UNCHANGED]}")
        self.stdout.write(f"  label changes      {summary[spl_terminology.LABEL_CHANGED]}")
        self.stdout.write(f"  not in snapshot    {summary['not_in_snapshot']}")
        self.stdout.write(
            "Nothing is active until this release is taken through "
            "validate -> submit-review -> approve -> activate."
        )
