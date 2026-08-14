import os
import pandas as pd
from django.conf import settings
from django.core.management.base import BaseCommand
from AIDatabase.models import ANDA, ANDAeCTD, ANDATechnicalAcceptance

class Command(BaseCommand):
    help = "Import deficiencies data from an Excel file using excel_file.parse()"

    FILE_PATH = os.path.join(settings.BASE_DIR, 'AIDatabase', 'management', 'commands', 'FDA Deficiency RoadMap_Mar 23 2026 (For Cipla).xlsx')

    def handle(self, *args, **kwargs):
        try:
            excel_file = pd.ExcelFile(self.FILE_PATH)
            print("Sheet names:- ",excel_file.sheet_names)
            ANDA.objects.all().delete()

            for sheet_name in excel_file.sheet_names:
                self.stdout.write(f"Processing sheet: {sheet_name}")
                try:
                    if sheet_name == "eCTD Acceptance Deficiency ":
                        sheet_data = excel_file.parse(sheet_name, skiprows=2)
                        sheet_data.dropna(how="all", inplace=True)
                        self.stdout.write(f"Found {len(sheet_data)} entries in sheet: {sheet_name}")
                        sheet_data.columns = [str(col).strip() for col in sheet_data.columns]

                        sheet_data = sheet_data.rename(columns={
                            "Dosage Form": "dosage",
                            "CMC / Clinical": "cmc_clinic",
                            "Deficiency Type": "deficiency_type",
                            "Deficiency": "deficiency",
                        })

                        ANDAeCTD.objects.all().delete()
                        for _, row in sheet_data.iterrows():
                            ANDAeCTD.objects.create(
                                dosage=str(row.get('dosage', '')),
                                cmc_clinic=str(row.get('cmc_clinic', '')),
                                deficiency_type=str(row.get('deficiency_type', '')),
                                deficiency=str(row.get('deficiency', ''))
                            )

                    elif sheet_name == "Technical Acceptance Defici":
                        sheet_data = excel_file.parse(sheet_name, skiprows=4)
                        sheet_data.dropna(how="all", inplace=True)
                        self.stdout.write(f"Found {len(sheet_data)} entries in sheet: {sheet_name}")
                        sheet_data.columns = [str(col).strip() for col in sheet_data.columns]

                        sheet_data = sheet_data.rename(columns={
                            "Dosage Form": "dosage_form",
                            "Type of Dosage Form": "type_of_dosage_form",
                            "Deficiency Type": "deficiency_type",
                            "Deficiency": "deficiency",
                        })

                        ANDATechnicalAcceptance.objects.all().delete()
                        for _, row in sheet_data.iterrows():
                            ANDATechnicalAcceptance.objects.create(
                                dosage_form=str(row.get('dosage_form', '')),
                                type_of_dosage_form=str(row.get('type_of_dosage_form', '')),
                                deficiency_type=str(row.get('deficiency_type', '')),
                                deficiency=str(row.get('deficiency', ''))
                            )

                    elif sheet_name in [choice[0] for choice in ANDA.MAIN_CATEGORY]:
                        if sheet_name == "Nasal Spray-Deficiency":
                            sheet_data = excel_file.parse(sheet_name, skiprows=3)
                        else:
                            sheet_data = excel_file.parse(sheet_name, skiprows=2)
                        # sheet_data.dropna(how="all", inplace=True)
                        print(f"Found {len(sheet_data)} entries in sheet: {sheet_name}")
                        self.stdout.write(f"Found {len(sheet_data)} entries in sheet: {sheet_name}")
                        sheet_data.columns = [str(col).strip() for col in sheet_data.columns]
                        print("Columns:- ",sheet_data.columns)



                        sheet_data = sheet_data.rename(columns={
                            "Dosage Type": "dosage_form",
                            "Dosage Form": "dosage_form",
                            "CMC Section": "cmc_section",
                            "Deficiency Type": "deficiency_type",
                            "Category of Deficiency": "category_of_deficiency",
                            "Deficiency": "deficiency",
                        })
                        # if sheet_name == "Nasal Spray-Deficiency":
                        #     print(sheet_data,'--------')
                        #     print(sheet_data.columns,'=====--------')
                                # Apply strip to all columns
                        if 'dosage_form' in sheet_data.columns:
                            self.stdout.write(f"  Distinct dosage forms in this sheet: {sheet_data['dosage_form'].unique().tolist()}")

                        sheet_data = sheet_data.applymap(lambda x: str(x).strip() if isinstance(x, str) else x)

                        # ANDA.objects.filter(main_cateogry=sheet_name).delete()
                        for _, row in sheet_data.iterrows():

                            ANDA.objects.create(
                                main_cateogry=sheet_name,
                                dosage_form=str(row.get('dosage_form', '')),
                                cmc_section=str(row.get('cmc_section', '')),
                                deficiency_type=str(row.get('deficiency_type', '')),
                                category_of_deficiency=str(row.get('category_of_deficiency', '')),
                                deficiency=str(row.get('deficiency', ''))
                            )

                    self.stdout.write(self.style.SUCCESS(f"Successfully imported {len(sheet_data)} entries from sheet: {sheet_name}"))
                except Exception as e:
                    self.stderr.write(self.style.ERROR(f"Error processing sheet {sheet_name}: {e}"))

        except FileNotFoundError:
            self.stderr.write(self.style.ERROR(f"File '{self.FILE_PATH}' does not exist."))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"An error occurred: {e}"))

        total_dosage_types = ANDA.objects.values('dosage_form').distinct().count()
        self.stdout.write(self.style.SUCCESS(f"Total Dosage Types -> {total_dosage_types}"))

        # Get unique deficiency types from all relevant models
        anda_def_types = set(ANDA.objects.values_list('deficiency_type', flat=True).distinct())
        ectd_def_types = set(ANDAeCTD.objects.values_list('deficiency_type', flat=True).distinct())
        tech_def_types = set(ANDATechnicalAcceptance.objects.values_list('deficiency_type', flat=True).distinct())

        # Combine and filter out empty strings
        all_unique_deficiency_types = sorted(list(anda_def_types.union(ectd_def_types, tech_def_types)))
        all_unique_deficiency_types = [dt for dt in all_unique_deficiency_types if dt and str(dt).strip()]

        self.stdout.write(self.style.SUCCESS(f"Total Unique Deficiency Types -> {len(all_unique_deficiency_types)}"))
        for def_type in all_unique_deficiency_types:
            self.stdout.write(f"- {def_type}")
