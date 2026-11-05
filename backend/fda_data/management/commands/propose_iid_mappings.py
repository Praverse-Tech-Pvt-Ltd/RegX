"""Propose (never approve) IID route/dosage-form mappings onto the active SPL lists.

    python manage.py propose_iid_mappings --dry-run
    python manage.py propose_iid_mappings [--release <iid-release-public-id>]

Default release: the active IID release. Only exact matches to an active SPL
term are proposed; every other value is listed. See `fda_data/mapping_proposals.py`.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from fda_data.mapping_proposals import propose_iid_mappings
from fda_data.models import FDADatasetType, FDADataSourceRelease, FDAReleaseStatus


class Command(BaseCommand):
    help = "Create PROPOSED IID route/dosage-form mappings for exact matches to active SPL terms."

    def add_arguments(self, parser):
        parser.add_argument("--release", help="IID release public id (default: the active one).")
        parser.add_argument("--dry-run", action="store_true", help="Report only; write nothing.")

    def handle(self, *args, **options):
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

        reports = propose_iid_mappings(release, dry_run=options["dry_run"])
        verb = "would propose" if options["dry_run"] else "proposed"
        self.stdout.write(f"IID release {release.public_id} ({release.status})")
        for kind, r in reports.items():
            self.stdout.write(
                f"\n{kind}: {r.distinct_values} distinct values | {verb} {len(r.proposed)} | "
                f"already mapped {len(r.already_mapped)} | not exact {len(r.not_exact)}"
            )
            for raw, status in r.already_mapped:
                self.stdout.write(f"  already mapped ({status}): {raw}")
            for raw, n in r.not_exact:
                self.stdout.write(f"  NOT EXACT (no proposal): {raw!r}  [{n} records]")
        self.stdout.write("\nNothing was approved. A VP reviews and approves proposals in the app.")
        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("--dry-run: nothing was written."))
