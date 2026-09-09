"""Load the FDA inspection corpus from the legacy sqlite snapshot.

Replaces a corpus wholesale rather than merging: the source is a published set,
and a partial overlay would leave rows from two publications indistinguishable.

    python manage.py import_inspections --sqlite legacy.sqlite3
    python manage.py import_inspections --sqlite legacy.sqlite3 --only warning_letters
"""

import sqlite3

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from inspections.models import (
    Form483Inspection,
    Form483Observation,
    Form483System,
    WarningLetter,
)


def _text(value):
    return (value or "").strip()


class Command(BaseCommand):
    help = "Import FDA Form 483 inspections and Warning Letters."

    def add_arguments(self, parser):
        parser.add_argument("--sqlite", required=True, help="Legacy iPharmaAI snapshot.")
        parser.add_argument(
            "--only",
            choices=["form483", "warning_letters"],
            help="Import just one corpus. Default is both.",
        )
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        try:
            conn = sqlite3.connect(options["sqlite"])
        except sqlite3.OperationalError as exc:
            raise CommandError("Cannot open %s: %s" % (options["sqlite"], exc))
        conn.row_factory = sqlite3.Row

        wanted = {options["only"]} if options["only"] else {"form483", "warning_letters"}
        if "form483" in wanted:
            self._form483(conn, options["dry_run"])
        if "warning_letters" in wanted:
            self._warning_letters(conn, options["dry_run"])

    # -- Form 483 ---------------------------------------------------------
    def _form483(self, conn, dry_run):
        try:
            masters = conn.execute("select * from AIDatabase_form483master").fetchall()
        except sqlite3.OperationalError as exc:
            self.stderr.write("  form483: skipped (%s)" % exc)
            return

        if dry_run:
            observations = conn.execute(
                "select count(*) from AIDatabase_form483observation"
            ).fetchone()[0]
            self.stdout.write(
                "  form483         would replace %d inspections with %d (%d observations)"
                % (Form483Inspection.objects.count(), len(masters), observations)
            )
            return

        with transaction.atomic():
            # Cascades to systems and observations.
            Form483Inspection.objects.all().delete()
            for master in masters:
                inspection = Form483Inspection.objects.create(
                    company_name=_text(master["company_name"]),
                    city=_text(master["city"]),
                    state=_text(master["state"]),
                    type_of_establishment=_text(master["type_of_establishment"]),
                    date_of_inspection=master["date_of_inspection"] or None,
                    investigator_name=_text(master["investigator_name"]),
                )
                systems = conn.execute(
                    "select * from AIDatabase_form483system where master_id = ?",
                    (master["id"],),
                ).fetchall()
                for source_system in systems:
                    system = Form483System.objects.create(
                        inspection=inspection, system=_text(source_system["system"])
                    )
                    observations = conn.execute(
                        "select * from AIDatabase_form483observation where system_id = ?",
                        (source_system["id"],),
                    ).fetchall()
                    seen_numbers = set()
                    for observation in observations:
                        number = observation["observation_number"] or 0
                        # The model constrains observation_number to be unique
                        # per system. The legacy schema had no such constraint,
                        # so duplicates exist; the first occurrence wins and the
                        # rest are reported rather than silently dropped.
                        if number in seen_numbers:
                            self.stderr.write(
                                "    duplicate observation %s under system %s (%s) - skipped"
                                % (number, system.system, inspection.company_name)
                            )
                            continue
                        seen_numbers.add(number)
                        parts = conn.execute(
                            "select content from AIDatabase_form483obeservationcontent "
                            "where observation_id = ? order by id",
                            (observation["id"],),
                        ).fetchall()
                        Form483Observation.objects.create(
                            system=system,
                            observation_number=number,
                            content="\n\n".join(
                                _text(part["content"])
                                for part in parts
                                if _text(part["content"])
                            ),
                        )
        self.stdout.write(
            self.style.SUCCESS(
                "  form483         %d inspections, %d observations"
                % (Form483Inspection.objects.count(), Form483Observation.objects.count())
            )
        )

    # -- Warning letters --------------------------------------------------
    def _warning_letters(self, conn, dry_run):
        try:
            rows = conn.execute("select * from AIDatabase_warningletter").fetchall()
        except sqlite3.OperationalError as exc:
            self.stderr.write("  warning_letters: skipped (%s)" % exc)
            return

        if dry_run:
            self.stdout.write(
                "  warning_letters would replace %d with %d"
                % (WarningLetter.objects.count(), len(rows))
            )
            return

        with transaction.atomic():
            WarningLetter.objects.all().delete()
            WarningLetter.objects.bulk_create(
                [
                    WarningLetter(
                        company_name=_text(row["company_name"]),
                        recipient_name=_text(row["recipient_name"]),
                        date_of_issue=row["date_of_issue"] or None,
                        location=_text(row["location"]),
                        city_state=_text(row["city_state"]),
                        country=_text(row["country"]),
                        date_of_inspection=row["date_of_inspection"] or None,
                        investigator_names=_text(row["investigator_names"]),
                        body=_text(row["warning_letter"]),
                        summary=_text(row["ai_summary"]),
                    )
                    for row in rows
                ],
                batch_size=500,
            )
        self.stdout.write(
            self.style.SUCCESS("  warning_letters %d letters" % WarningLetter.objects.count())
        )
