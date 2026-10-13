"""Fill empty route / dosage-form links on a release from approved mappings.

    python manage.py reresolve_terminology <release-public-id> --dry-run
    python manage.py reresolve_terminology <release-public-id>

Only for a release not yet submitted for review. Never changes or clears an
existing link. See `fda_data/reresolve.py` for the rules.
"""

from __future__ import annotations

from collections import Counter

from django.core.management.base import BaseCommand, CommandError

from fda_data.models import FDADataSourceRelease
from fda_data.reresolve import ReresolveRefused, count_unmapped, reresolve


class Command(BaseCommand):
    help = (
        "Fill empty route/dosage-form links on a not-yet-reviewed release from approved mappings."
    )

    def add_arguments(self, parser):
        parser.add_argument("release", help="Public id of the release.")
        parser.add_argument(
            "--dry-run", action="store_true", help="Show what would change; write nothing."
        )

    def handle(self, *args, **options):
        try:
            release = FDADataSourceRelease.objects.get(public_id=options["release"])
        except (FDADataSourceRelease.DoesNotExist, ValueError):
            raise CommandError(f"No release {options['release']!r}.") from None

        before = count_unmapped(release)
        try:
            changes = reresolve(release, dry_run=options["dry_run"])
        except ReresolveRefused as exc:
            raise CommandError(str(exc)) from None

        verb = "Would fill" if options["dry_run"] else "Filled"
        by_value = Counter((c.field, c.raw_value, c.new_code) for c in changes)
        self.stdout.write(f"Release {release.public_id} ({release.dataset_type}, {release.status})")
        self.stdout.write(f"  records missing a link before  {before}")
        self.stdout.write(f"  {verb.lower()} links             {len(changes)}")
        self.stdout.write(
            f"  records affected               {len({c.record_public_id for c in changes})}"
        )
        for (field, raw, code), n in sorted(by_value.items()):
            self.stdout.write(f"    {verb} {field:11} {raw!r} -> {code}  x{n}")
        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("--dry-run: nothing was written."))
        else:
            self.stdout.write(f"  records missing a link after   {count_unmapped(release)}")
