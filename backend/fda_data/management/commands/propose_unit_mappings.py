"""Propose (never approve) a unit mapping for each IID potency unit string.

    python manage.py propose_unit_mappings --actor doer@example.com --dry-run
    python manage.py propose_unit_mappings --actor doer@example.com [--release <iid-release-id>]

Default release: the active IID release. Needs an ACTIVE controlled-units
release. Only strings that state a meaning exactly, and whose meaning is in
force, are proposed; the rest are listed with the reason. Idempotent.
See `fda_data/controlled_units.py`.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from fda_data.controlled_units import ProposalRefused, propose_unit_mappings
from fda_data.models import FDADatasetType, FDADataSourceRelease, FDAReleaseStatus
from fda_data.permissions import LoaderActorError, resolve_loader_actor


class Command(BaseCommand):
    help = "Create PROPOSED unit mappings for IID potency unit strings that state an exact meaning."

    def add_arguments(self, parser):
        parser.add_argument("--release", help="IID release public id (default: the active one).")
        parser.add_argument(
            "--actor", required=True, help="Email of the proposing user (holds fda_data.import)."
        )
        parser.add_argument("--dry-run", action="store_true", help="Report only; write nothing.")

    def handle(self, *args, **options):
        try:
            actor = resolve_loader_actor(options["actor"])
        except LoaderActorError as exc:
            raise CommandError(str(exc)) from None
        releases = FDADataSourceRelease.objects.filter(dataset_type=FDADatasetType.FDA_IID)
        try:
            release = (
                releases.get(public_id=options["release"])
                if options["release"]
                else releases.get(status=FDAReleaseStatus.ACTIVE)
            )
        except (FDADataSourceRelease.DoesNotExist, ValueError):
            raise CommandError(
                "No such IID release."
                if options["release"]
                else "No active IID release; pass --release."
            ) from None
        try:
            r = propose_unit_mappings(release, actor=actor, dry_run=options["dry_run"])
        except ProposalRefused as exc:
            raise CommandError(str(exc)) from None
        verb = "would propose" if options["dry_run"] else "proposed"
        self.stdout.write(f"IID release {release.public_id} ({release.status})")
        self.stdout.write(
            f"potency unit strings: {r.distinct_strings} distinct | {verb} {len(r.proposed)} | "
            f"already mapped {len(r.already_mapped)} | unclear {len(r.unclear)}"
        )
        for raw, meaning, n in r.proposed:
            self.stdout.write(f"  {verb}: {raw!r} -> {meaning}  [{n} records]")
        for raw, status in r.already_mapped:
            self.stdout.write(f"  already mapped ({status}): {raw!r}")
        for raw, why, n in r.unclear:
            self.stdout.write(f"  UNCLEAR (no proposal): {raw!r}: {why}  [{n} records]")
        self.stdout.write("\nNothing was approved. A VP reviews and approves proposals in the app.")
        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("--dry-run: nothing was written."))
