import json
import os
from django.conf import settings
import pandas as pd
from django.core.management.base import BaseCommand
from AIDatabase.models import InvestigatorThemedKeywords

FILE_PATH = os.path.join(settings.BASE_DIR, 'AIDatabase', 'management', 'commands', 'FDA_CGMP_Keywords_All_6_Systems.xlsx')
KEYWORD_COLUMN = "Keyword / Observation Term"
TITLE_SUFFIX = " — FDA 483 Keyword Reference"


class Command(BaseCommand):
    help = "Import themed keywords from Excel into DB"

    def get_section_title(self, xls, sheet_name):
        title_row = pd.read_excel(xls, sheet_name=sheet_name, header=None, nrows=1)
        raw_title = str(title_row.iloc[0, 0]).strip()

        if raw_title and raw_title.lower() != "nan":
            return raw_title.replace(TITLE_SUFFIX, "").strip()

        return sheet_name.strip()

    def get_keywords(self, xls, sheet_name):
        df = pd.read_excel(xls, sheet_name=sheet_name, header=1)
        df.columns = df.columns.astype(str).str.strip()

        if KEYWORD_COLUMN not in df.columns:
            return []

        return (
            df[KEYWORD_COLUMN]
            .dropna()
            .astype(str)
            .str.strip()
            .loc[lambda s: s.ne("")]
            .tolist()
        )

    def handle(self, *args, **kwargs):
        xls = pd.ExcelFile(FILE_PATH)

        total_inserted = 0

        for sheet_name in xls.sheet_names:
            section_title = self.get_section_title(xls, sheet_name)

            # 🔥 Clean system name (remove numbering like "1. ")
            system_name = section_title.split(". ", 1)[-1]

            keywords = self.get_keywords(xls, sheet_name)

            for keyword in keywords:
                obj, created = InvestigatorThemedKeywords.objects.get_or_create(
                    system_name=system_name,
                    keyword=keyword
                )

                if created:
                    total_inserted += 1

        self.stdout.write(self.style.SUCCESS(
            f"✅ Import completed. {total_inserted} new keywords added."
        ))
