"""Load the reviewed controlled-units list as a versioned release (draft until a VP approves).

    python manage.py load_controlled_units fda_data/reference/controlled_units_v1.json \
        --actor doer@example.com --source-reference "controlled_units_v1.json, reviewed 2026-11-16"

Registers an `FDADataSourceRelease` of type `regx_controlled_units` with the
loader recorded; that user cannot approve or activate it. Units and meanings
are in force only while the release is ACTIVE. Loading the same file twice
changes nothing. See `fda_data/controlled_units.py`.
"""

from __future__ import annotations

import pathlib

from django.core.management.base import BaseCommand, CommandError

from fda_data import controlled_units
from fda_data.permissions import LoaderActorError, resolve_loader_actor


class Command(BaseCommand):
    help = "Load the reviewed controlled-units list (units and unit meanings) as a draft release."

    def add_arguments(self, parser):
        parser.add_argument("path", help="The reviewed JSON list (fda_data/reference/...).")
        parser.add_argument(
            "--source-reference",
            required=True,
            help="Which file and which review this is. Recorded verbatim.",
        )
        parser.add_argument(
            "--actor",
            required=True,
            help="Email of the loading user (must hold fda_data.import, e.g. a Doer). "
            "That user cannot later approve or activate the release.",
        )
        parser.add_argument("--dry-run", action="store_true", help="Validate only; write nothing.")

    def handle(self, *args, **options):
        try:
            actor = resolve_loader_actor(options["actor"])
        except LoaderActorError as exc:
            raise CommandError(str(exc)) from None
        path = pathlib.Path(options["path"])
        if not path.is_file():
            raise CommandError(f"No such file: {path}")
        raw = path.read_bytes()
        try:
            snapshot = controlled_units.parse_snapshot(raw)
        except controlled_units.SnapshotError as exc:
            raise CommandError(str(exc)) from None
        self.stdout.write(
            f"  units {len(snapshot['units'])} | meanings {len(snapshot['meanings'])}"
        )
        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("--dry-run: nothing was written."))
            return
        try:
            release, summary = controlled_units.load_snapshot(
                raw=raw,
                filename=path.name,
                source_reference=options["source_reference"],
                actor=actor,
            )
        except controlled_units.SnapshotError as exc:
            raise CommandError(str(exc)) from None
        if summary.pop("already_loaded"):
            self.stdout.write(
                self.style.WARNING(
                    f"Already loaded as release {release.public_id}. Nothing changed."
                )
            )
        else:
            self.stdout.write(self.style.SUCCESS(f"Release {release.public_id} registered."))
        self.stdout.write(f"  status             {release.status}")
        self.stdout.write(
            f"  loaded by          {release.imported_by.email if release.imported_by else '-'}"
        )
        for key, value in summary.items():
            self.stdout.write(f"  {key:18} {value}")
        self.stdout.write(
            "Nothing is in force until a VP takes this release through "
            "submit-review -> approve -> activate (the loader cannot)."
        )
