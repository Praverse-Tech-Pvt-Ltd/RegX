import pandas as pd
from openpyxl import load_workbook
from RATools.models import DMFReviewTableQuestion
from openpyxl.styles import PatternFill
import os
from django.core.management.base import BaseCommand
from django.conf import settings


# Load the Excel workbook
file_path = os.path.join(settings.BASE_DIR, 'AIDatabase', 'management', 'commands', 'dmf review doc clean.xlsx')
wb = load_workbook(file_path, data_only=True)
sheet = wb.active

# Define expected background colors (RGB values) for categories
COLOR_ORANGE = 'FFE36C0A'  # Orange for Module
COLOR_LIGHT_ORANGE = 'FFFBE5D5'  #  light orange for Ctaegory

def get_cell_color(cell):
    try:
        fill = cell.fill
        if fill and fill.fgColor and fill.fgColor.rgb:
            print("hex string",fill.fgColor.rgb)
            return fill.fgColor.rgb  # This should return an ARGB formatted hex string
        elif fill and fill.start_color.index:  # Some styles store colors differently
            print("different color",fill.start_color.index)
            return fill.start_color.index
    except Exception as e:
        print(f"Error extracting color: {e}")
    return None


# Initialize tracking variables
current_module = ""
current_category = ""
current_question = ""
questions = []

# Iterate through the rows in the sheet, starting from row 2 to skip the header
# for row in sheet.iter_rows(min_row=1, max_row=sheet.max_row):
#     cell_module = row[0]  # Column A (Module)
#     cell_category_question = row[1]  # Column B (Category/Question)

#     module_value = cell_module.value.strip() if cell_module.value else None
#     category_question_value = cell_category_question.value.strip() if cell_category_question.value else None

#     module_color = get_cell_color(cell_module)
#     category_question_color = get_cell_color(cell_category_question)

#     if module_value and module_color == COLOR_ORANGE:
#         current_module = module_value
#         current_category = ""  # Reset category when a new module is detected
#         print(f"Detected Module: {current_module}")

#     if category_question_value and category_question_color == COLOR_LIGHT_ORANGE:
#         current_category = category_question_value
#         print(f"Detected Category: {current_category}")

#     # If it's neither a module nor category, consider it as a question
#     if category_question_value and category_question_color not in [COLOR_ORANGE, COLOR_LIGHT_ORANGE]:
#         current_question = category_question_value
#         print(f"Detected Question: {current_question}")

#     # Save questions under the current module and category
#     if current_module and current_category and current_question:
#         questions.append({
#             'module': current_module,
#             'category': current_category,
#             'question': current_question,
#         })

for row in sheet.iter_rows(min_row=1, max_row=sheet.max_row):  # Start from row 2, skipping header
    cell_module = row[0]  # Column A (Module)
    cell_category_question = row[1]  # Column B (Category/Question)

    module_value = cell_module.value.strip() if cell_module.value else None
    category_question_value = cell_category_question.value.strip() if cell_category_question.value else None

    module_color = get_cell_color(cell_module)
    category_question_color = get_cell_color(cell_category_question)

    # Check if the cell in column A (Modules) is detected correctly
    if module_value and module_color == COLOR_ORANGE:
        current_module = module_value
        current_category = ""  # Reset category when a new module is detected
        current_question = ""  # Reset question to avoid carryover
        print(f"Detected Module: {current_module}")

    # Check if the cell in column B (Categories) is detected correctly
    if category_question_value and category_question_color == COLOR_LIGHT_ORANGE:
        current_category = category_question_value
        current_question = ""  # Reset question to avoid carryover
        print(f"Detected Category: {current_category}")

    # If neither module nor category, assume it's a question under the current category
    if category_question_value and category_question_color not in [COLOR_ORANGE, COLOR_LIGHT_ORANGE]:
        current_question = category_question_value
        print(f"Detected Question: {current_question}")

    # Ensure we store the question only if module and category exist
    if current_module and current_category and current_question:
        questions.append({
            'module': current_module,
            'category': current_category,
            'question': current_question,
        })

        # Reset the question after storing to prevent carryover
        current_question = ""

print("Data extraction completed.")

# Save extracted data into Django model
def import_data():
    for entry in questions:
        DMFReviewTableQuestion.objects.create(
            module=entry['module'],
            category=entry['category'],
            question=entry['question'],
        )
    print("Data imported successfully!")

# Run the import function
import_data()

# print("questions", questions)
# print("\nExtracted Questions:")
# for q in questions:
#     print("\n---")
#     print(f"module: {q['module']}")
#     print(f"category: {q['category']}")
#     print(f"Question: {q['question']}")
