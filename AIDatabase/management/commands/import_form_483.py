'''Testing'''
import os
import pandas as pd
import re
import io
from PIL import Image
import openpyxl
from django.core.management.base import BaseCommand
from django.core.files.base import ContentFile
from AIDatabase.models import Form483Master, Form483System, Form483Observation, Form483ObeservationContent
from django.conf import settings
from django.db import transaction
from datetime import datetime

class Command(BaseCommand):
    help = 'Imports observation data from Excel file for both 2023 and 2024'

    def handle(self, *args, **kwargs):
        try:
            # Define file paths
            file_path = os.path.join(settings.BASE_DIR, 'AIDatabase', 'management', 'commands', 'FDA form 483 database - Drugs_Final (1).xlsx')

            # Load Excel file for pandas processing
            df = pd.read_excel(file_path, sheet_name=None, header=1)
            # self.stdout.write(f"Sheets found: {list(df.keys())}")

            # Load Excel file for image processing
            workbook = openpyxl.load_workbook(file_path, data_only=True)

            # Process both 2023 and 2024 sheets
            for year in ['2024', '2023','2022']:
                if year not in df:
                    # self.stdout.write(self.style.WARNING(f'Sheet for {year} not found'))
                    continue

                # self.stdout.write(f"Processing {year} data...")

                sheet_df = df[year]
                ws = workbook[year]

                # Set up image storage for current year
                image_folder = os.path.join(settings.MEDIA_ROOT, f'temp_images_{year}')
                os.makedirs(image_folder, exist_ok=True)

                # Process and map images
                image_map = {}
                for img in ws._images:
                    try:
                        img_data = img._data()
                        img_stream = io.BytesIO(img_data)
                        image = Image.open(img_stream)
                        anchor = img.anchor
                        row = anchor._from.row
                        col = anchor._from.col

                        # Save temporary image
                        image_path = os.path.join(image_folder, f'image_{row}_{col}.png')
                        image.save(image_path)
                        image_map[(row, col)] = image_path
                    except Exception as e:
                        # self.stdout.write(self.style.WARNING(f'Error processing image in {year}: {str(e)}'))
                        continue

                # Clean column names
                sheet_df.columns = sheet_df.columns.str.strip()

                # Verify required columns
                required_columns = [
                    'Company Name', 'City, Country', 'Form 483 Observations',
                    'FDA Investigator(s) name', 'Month of Inspection', 'System',
                    'Type of Establishment'
                ]
                missing_columns = [col for col in required_columns if col not in sheet_df.columns]
                if missing_columns:
                    # self.stdout.write(self.style.ERROR(f"Missing required columns in {year}: {missing_columns}"))
                    continue

                # Process data row by row
                current_master = None
                current_system = None
                current_observation = None

                for idx, row in sheet_df.iterrows():
                    try:
                        # self.stdout.write(f"Processing row {idx + 1} for {year}...")  # Log current row number

                        with transaction.atomic():
                            # Process Company Name
                            if pd.notna(row['Company Name']):
                                company_name = str(row['Company Name']).strip()
                                current_master, _ = Form483Master.objects.get_or_create(
                                    company_name=company_name,
                                    defaults={'company_name': company_name}
                                )
                                # self.stdout.write(f"Created/updated Master for company: {company_name}")

                            # Process City, Country
                            if pd.notna(row['City, Country']):
                                city_country = str(row['City, Country']).strip()
                                city_parts = city_country.split(',', 1)
                                current_master.city = city_parts[0].strip() if city_parts else ''
                                current_master.state = city_parts[1].strip() if len(city_parts) > 1 else ''

                            # Process FDA Investigators
                            if pd.notna(row['FDA Investigator(s) name']):
                                current_master.investigator_name = str(row['FDA Investigator(s) name']).strip()

                            # Process Inspection Date
                            if pd.notna(row['Month of Inspection']):
                                date_of_inspection = str(row['Month of Inspection']).strip()
                                # self.stdout.write(f"Raw date_of_inspection value: {date_of_inspection}")

                                # Handle "Feb,2024" or "Feb, 2024" type formats
                                if re.match(r"^[A-Za-z]{3},\d{4}$", date_of_inspection):  # Match formats like "Feb,2024"
                                    try:
                                        # Add a space after the comma if missing
                                        date_of_inspection = date_of_inspection.replace(',', ', ')

                                        # Normalize month abbreviations to a standard format (first letter capitalized)
                                        date_of_inspection = date_of_inspection.title()

                                        # Parse the month-year format (e.g., Feb, 2024)
                                        date_obj = datetime.strptime(date_of_inspection, "%b, %Y")

                                        # Convert to the desired format (2024-02-01, where '01' is the first day of the month)
                                        formatted_date = date_obj.strftime("%Y-%m-01")
                                        current_master.date_of_inspection = formatted_date  # Save in the desired format
                                        current_master.year_of_inspection = str(date_obj.year)
                                    except ValueError as e:
                                        self.stdout.write(self.style.WARNING(f"Failed to parse date for {date_of_inspection} using Feb, 2024 format: {str(e)}"))


                                # Try all other date formats if the first one failed
                                else:
                                    date_formats = [
                                        "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y",  # Example formats: 2024-11-18, 11/18/2024, 18/11/2024
                                        "%b, %Y", "%B, %Y",  # Example formats: Jul, 2023, November, 2023
                                        "%Y-%m-%d %H:%M:%S"  # Datetime format: 2023-02-01 00:00:00
                                    ]
                                    parsed = False  # Flag to track if parsing was successful
                                    for date_format in date_formats:
                                        try:
                                            date_obj = datetime.strptime(date_of_inspection, date_format)
                                            current_master.date_of_inspection = date_obj.date()  # Ensure it's a date (not datetime)
                                            current_master.year_of_inspection = str(date_obj.year)
                                            parsed = True  # Successful parsing
                                            break  # Exit after the first successful parse
                                        except ValueError:
                                            continue  # Try the next format if the current one fails

                                    # If parsing failed
                                    if not parsed:
                                        # self.stdout.write(self.style.WARNING(f"Failed to parse Month of Inspection for row {idx}: {date_of_inspection}"))
                                        current_master.date_of_inspection = None


                            # Set year of inspection if not already set
                            if not current_master.year_of_inspection and pd.notna(row['Year of Inspection']):
                                current_master.year_of_inspection = str(row['Year of Inspection']).strip()

                            # Process Type of Establishment
                            if pd.notna(row['Type of Establishment']):
                                current_master.type_of_establishment = str(row['Type of Establishment']).strip()

                            current_master.save()
                            # self.stdout.write(f"Saved Master: {current_master.company_name}")

                            # Process System
                            if pd.notna(row['System']):
                                system_names = [x.strip() for x in str(row['System']).split(',') if x.strip()]
                                for system_name in system_names:
                                    current_system, _ = Form483System.objects.get_or_create(
                                        master=current_master,
                                        system=system_name
                                    )
                                    # self.stdout.write(f"Created/updated System: {system_name}")

                            # Process Observations Obervation 2  Obeservation 2
                            if pd.notna(row['Form 483 Observations']):
                                observation_list = [x.replace("Observation","").replace("Obervation","").replace("Obeservation","").replace("Obesrvation","").replace("OBSERVATION","").strip() for x in str(row['Form 483 Observations']).split(',') if x.replace("Observation","").replace("Obervation","").replace("Obeservation","").replace("Obesrvation","").strip()]
                                for observation_number in observation_list:
                                    current_observation, _ = Form483Observation.objects.get_or_create(
                                        system=current_system,
                                        observation_number=int(observation_number)
                                    )
                                    # self.stdout.write(f"Created/updated Observation: {observation_number}")

                            # Process Observation Details and Images
                            if pd.notna(row['Unnamed: 9']) and current_observation:
                                observation_details = str(row['Unnamed: 9']).strip()
                                prefix_match = re.match(r"([A-Za-z]+)\.", observation_details)
                                observation_type = f"Type {prefix_match.group(1)}" if prefix_match else "General"

                                # Create observation detail
                                observation_detail = Form483ObeservationContent(
                                    observation=current_observation,
                                    content_category=observation_type,
                                    content=observation_details
                                )

                                # Handle image if available
                                image_path = image_map.get((idx + 2, 9))  # +2 for header offset
                                if image_path and os.path.exists(image_path):
                                    with open(image_path, 'rb') as img_file:
                                        image_name = f'observation_{current_observation.id}_image.png'
                                        observation_detail.image.save(
                                            image_name,
                                            ContentFile(img_file.read()),
                                            save=False
                                        )
                                        # self.stdout.write(f"Saved image for Observation ID {current_observation.id} at {image_path}")

                                observation_detail.save()
                                # self.stdout.write(f"Saved ObservationDetail: {observation_type} for Observation {current_observation.id}")
                    except Exception as e:
                        self.stdout.write(self.style.ERROR(f"Error processing row {idx + 1}: {str(e)}"))
                        self.stdout.write(self.style.ERROR(f"Row data: {row}"))
                        continue
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Overall error: {str(e)}"))
