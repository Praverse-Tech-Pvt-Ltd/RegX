"""Load Controlled Correspondence best-practice guidance.

Replaces the set wholesale rather than merging: the guidance is published as a
set, and a partial overlay would mix two revisions.

    python manage.py import_best_practices --sqlite legacy.sqlite3
"""

import sqlite3

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from controlled_correspondence.models import BestPractice


class Command(BaseCommand):
    help = "Import Controlled Correspondence best practices."

    def add_arguments(self, parser):
        parser.add_argument("--sqlite", required=True)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        try:
            conn = sqlite3.connect(options["sqlite"])
        except sqlite3.OperationalError as exc:
            raise CommandError(f"Cannot open {options['sqlite']}: {exc}") from exc
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("select * from RATools_ccbestpractice").fetchall()
        except sqlite3.OperationalError as exc:
            raise CommandError(f"Source table not readable: {exc}") from exc

        if options["dry_run"]:
            self.stdout.write(
                f"  best practices would replace {BestPractice.objects.count()} with {len(rows)}"
            )
            return

        with transaction.atomic():
            BestPractice.objects.all().delete()
            BestPractice.objects.bulk_create(
                [
                    BestPractice(
                        category=(row["category"] or "").strip(),
                        sub_category=(row["sub_category"] or "").strip(),
                        guidance=row["question"] or "",
                    )
                    for row in rows
                ],
                batch_size=500,
            )
        self.stdout.write(
            self.style.SUCCESS(f"  best practices {BestPractice.objects.count()} entries")
        )
