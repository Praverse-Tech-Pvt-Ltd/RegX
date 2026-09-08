"""Load an FDA deficiency roadmap into the corpus.

Reads the legacy sqlite snapshot or an .xlsx roadmap. Replaces a corpus
wholesale rather than merging: a roadmap is published as a set, and a partial
overlay would leave rows from two publications indistinguishable.

    python manage.py import_deficiencies --sqlite db_17_1_2.sqlite3
    python manage.py import_deficiencies --xlsx roadmap.xlsx --corpus anda
"""

import sqlite3

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from deficiencies.models import DeficiencyCorpus, DeficiencyRecord

#: Legacy table -> corpus. The legacy column `main_cateogry` is misspelled in the
#: source schema; it is mapped to `main_category` here rather than carried over.
LEGACY_TABLES = {
    "AIDatabase_anda": DeficiencyCorpus.ANDA,
    "AIDatabase_majorcr": DeficiencyCorpus.MAJOR_CR,
}
LEGACY_COLUMNS = [
    "main_cateogry",
    "dosage_form",
    "cmc_section",
    "deficiency_type",
    "category_of_deficiency",
    "deficiency",
]


class Command(BaseCommand):
    help = "Import FDA deficiency roadmap records."

    def add_arguments(self, parser):
        parser.add_argument("--sqlite", help="Legacy iPharmaAI sqlite snapshot.")
        parser.add_argument("--xlsx", help="Roadmap .xlsx export.")
        parser.add_argument(
            "--corpus",
            choices=[c.value for c in DeficiencyCorpus],
            help="Required with --xlsx; inferred per table with --sqlite.",
        )
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **o):
        if bool(o["sqlite"]) == bool(o["xlsx"]):
            raise CommandError("Give exactly one of --sqlite or --xlsx.")
        if o["xlsx"] and not o["corpus"]:
            raise CommandError("--xlsx requires --corpus.")

        batches = (
            self._read_sqlite(o["sqlite"]) if o["sqlite"] else self._read_xlsx(o["xlsx"], o["corpus"])
        )

        for corpus, rows in batches:
            existing = DeficiencyRecord.objects.filter(corpus=corpus).count()
            if o["dry_run"]:
                self.stdout.write(
                    f"  {corpus:10} would replace {existing} with {len(rows)} rows"
                )
                continue
            with transaction.atomic():
                DeficiencyRecord.objects.filter(corpus=corpus).delete()
                DeficiencyRecord.objects.bulk_create(
                    [DeficiencyRecord(corpus=corpus, **r) for r in rows], batch_size=500
                )
            self.stdout.write(
                self.style.SUCCESS(f"  {corpus:10} {existing} -> {len(rows)} rows")
            )

    def _read_sqlite(self, path):
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        out = []
        for table, corpus in LEGACY_TABLES.items():
            try:
                cursor = conn.execute(f"select {','.join(LEGACY_COLUMNS)} from {table}")
            except sqlite3.OperationalError as exc:
                self.stderr.write(f"  skipping {table}: {exc}")
                continue
            rows = []
            for n, row in enumerate(cursor, start=1):
                rows.append(
                    {
                        "main_category": (row["main_cateogry"] or "").strip(),
                        "dosage_form": (row["dosage_form"] or "").strip(),
                        "cmc_section": (row["cmc_section"] or "").strip(),
                        "deficiency_type": (row["deficiency_type"] or "").strip(),
                        "category_of_deficiency": (row["category_of_deficiency"] or "").strip(),
                        "deficiency": row["deficiency"] or "",
                        "source_row_number": n,
                    }
                )
            out.append((corpus, rows))
        return out

    def _read_xlsx(self, path, corpus):
        import pandas as pd

        df = pd.read_excel(path)
        lower = {str(c).strip().lower(): c for c in df.columns}

        def col(*names):
            for n in names:
                if n in lower:
                    return lower[n]
            return None

        mapping = {
            "main_category": col("main category", "main_cateogry", "main_category"),
            "dosage_form": col("dosage form", "dosage_form"),
            "cmc_section": col("cmc section", "cmc_section"),
            "deficiency_type": col("deficiency type", "deficiency_type"),
            "category_of_deficiency": col("category of deficiency", "category_of_deficiency"),
            "deficiency": col("deficiency"),
        }
        missing = [k for k, v in mapping.items() if v is None]
        if missing:
            raise CommandError(f"Columns not found in {path}: {missing}")

        rows = []
        for n, (_, r) in enumerate(df.iterrows(), start=1):
            rows.append(
                {
                    k: ("" if r[src] is None else str(r[src]).strip())
                    for k, src in mapping.items()
                }
                | {"source_row_number": n}
            )
        return [(corpus, rows)]
