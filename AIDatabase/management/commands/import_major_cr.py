import os
import pandas as pd
from django.conf import settings
from django.core.management.base import BaseCommand
from AIDatabase.models import MajorCR  # Update with your actual app name

class Command(BaseCommand):
    help = "Import Major CR deficiencies data from an Excel file"

    FILE_PATH = os.path.join(settings.BASE_DIR, 'AIDatabase', 'management', 'commands', 'FDA Major CR RoadMap_Mar 23 2026 (For Cipla).xlsx')

    def handle(self, *args, **kwargs):
        try:
            excel_file = pd.ExcelFile(self.FILE_PATH)

            # Get all sheet names that match the MAIN_CATEGORY choices
            valid_sheets = [choice[0] for choice in MajorCR.MAIN_CATEGORY]

            for sheet_name in excel_file.sheet_names:
                self.stdout.write(f"Processing sheet: {sheet_name}")

                try:
                    if sheet_name in valid_sheets:
                        if sheet_name == "Nasal Spray-Deficiency":
                            sheet_data = excel_file.parse(sheet_name, skiprows=3)
                        else:
                        # Parse the sheet, skipping header rows
                            sheet_data = excel_file.parse(sheet_name, skiprows=2)

                        initial_row_count = len(sheet_data)
                        print(f"Sheet '{sheet_name}' - Initial rows read: {initial_row_count}")
                        # Remove completely empty rows
                        sheet_data.dropna(how="all", inplace=True)
                        final_row_count = len(sheet_data)
                        print(f"Sheet '{sheet_name}' - Rows after dropna: {final_row_count}")
                        # Clean column names
                        sheet_data.columns = [str(col).strip() for col in sheet_data.columns]

                        # Rename columns to match model fields
                        sheet_data = sheet_data.rename(columns={
                            "Dosage Type": "dosage_form",
                            "Dosage Form": "dosage_form",
                            "CMC Section": "cmc_section",
                            "Deficiency Type": "deficiency_type",
                            "Category of Deficiency": "category_of_deficiency",
                            "Deficiency": "deficiency",
                        })

                        sheet_data = sheet_data.applymap(lambda x: str(x).strip() if isinstance(x, str) else x)

                        # Create MajorCR objects for each row
                        MajorCR.objects.filter(main_cateogry=sheet_name).delete()
                        print(f"Importing {len(sheet_data)} rows from sheet '{sheet_name}' into MajorCR model.")
                        for _, row in sheet_data.iterrows():
                            MajorCR.objects.create(
                                main_cateogry=sheet_name,
                                dosage_form=str(row.get('dosage_form', '') if pd.notna(row.get('dosage_form')) else '').strip()[:1000],
                                cmc_section=str(row.get('cmc_section', '') if pd.notna(row.get('cmc_section')) else '').strip()[:1000],
                                deficiency_type=str(row.get('deficiency_type', '') if pd.notna(row.get('deficiency_type')) else '').strip()[:1000],
                                category_of_deficiency=str(row.get('category_of_deficiency', '') if pd.notna(row.get('category_of_deficiency')) else '').strip()[:1000],
                                deficiency=str(row.get('deficiency', '') if pd.notna(row.get('deficiency')) else '')
                            )

                        self.stdout.write(self.style.SUCCESS(f"Successfully imported data from sheet: {sheet_name}"))
                    else:
                        self.stdout.write(f"Skipping sheet {sheet_name} - not in MAIN_CATEGORY choices")

                except Exception as e:
                    self.stderr.write(self.style.ERROR(f"Error processing sheet {sheet_name}: {e}"))

        except FileNotFoundError:
            self.stderr.write(self.style.ERROR(f"File '{self.FILE_PATH}' does not exist."))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"An error occurred: {e}"))

        print(f"Total records in MajorCR table after import: {MajorCR.objects.count()}")

        unique_dosage_forms = MajorCR.objects.exclude(dosage_form='').values_list('dosage_form', flat=True).distinct()
        total_dosage_types = unique_dosage_forms.count()
        self.stdout.write(self.style.SUCCESS(f"Total Unique Dosage Types -> {total_dosage_types}"))
        for dosage_form in unique_dosage_forms:
            if dosage_form:
                self.stdout.write(f"- {dosage_form}")
