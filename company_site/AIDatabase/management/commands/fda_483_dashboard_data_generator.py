import pandas as pd
import json

# Load the Excel file
df = pd.read_excel("AIDatabase/management/commands/Final_File_FDA_Observations_15_12_2025.xlsx")

# Show available columns
# print("Columns:", df.columns.tolist())

# Rename year column for consistency
df = df.rename(columns={"Year of Inspection": "Year"})

# Drop rows with missing year or system
df = df.dropna(subset=['Year', 'System'])
df['Year'] = df['Year'].astype(int)

# Define the years and the desired system names
years = list(range(2018, 2026))  # 2018 to 2025
labels = years  # for final JS-style output
print("Total observations:- ", len(df))
# Mapping and normalization
system_labels = {
    "quality system": "Quality System",
    "facilities and equipment system": "Facilities and Equipment System",
    "laboratory control system": "Laboratory Control System",
    "production system": "Production System",
    "packaging and labeling system": "Packaging and Labeling System",
    "packaging and labelling system": "Packaging and Labeling System",  # UK spelling
    "material system": "Material System"
}

# Normalize system names
df['System'] = df['System'].str.strip().str.lower()
df['System'] = df['System'].map(system_labels)

# Filter only valid system names
df = df[df['System'].notna()]

# Initialize final structure
final_data = {label: [0] * len(years) for label in set(system_labels.values())}

# Populate counts
for _, row in df.iterrows():
    year = row['Year']
    system = row['System']
    if year in years:
        index = years.index(year)
        final_data[system][index] += 1

# Output JS-style constant block
print("\n// Years for X-axis")
print(f"const labels = {labels};\n")
print("// Actual observations for different categories")
print("const data = {")
for system, counts in final_data.items():
    print(f'  "{system}": {counts},')
print("};")


# Clean and process the investigator names
# Some rows might contain multiple investigators separated by commas

from collections import Counter

# Drop NaN values and split by commas
all_investigators = df["FDA Investigator(s) name"].dropna().str.split(",")

# Flatten the list and strip whitespace
flat_investigators = [name.strip() for sublist in all_investigators for name in sublist]

# Count occurrences
investigator_counts = Counter(flat_investigators)

# Get top 10
top_10_investigators = investigator_counts.most_common(10)

# Convert to DataFrame for display
top_10_df = pd.DataFrame(top_10_investigators, columns=["Investigator", "Count"])
print(top_10_df)



system_column = 'System'  # or 'observations.system' if nested, adjust accordingly

# Clean system names to ensure consistency (strip whitespace, case-normalize, etc.)
df[system_column] = df[system_column].str.strip()

# Group by system and count
system_counts = df[system_column].value_counts()

# Print the system labels and their counts as lists
labels = list(system_counts.index)
data = list(system_counts.values)

print("labels =", labels)
print("data =", data)

df["Type of establishment"] = df["Type of establishment"].str.strip()

# Define the labels of interest
labels = [
    "API Manufacturer",
    "Contract Drug Manufacturer",
    "Prescription (Rx) Drug Manufacturer"
]

# Count occurrences for each label
data = [df[df["Type of establishment"] == label].shape[0] for label in labels]

# Print results
for label, count in zip(labels, data):
    print(f"{label}: {count}")

# Optional: for JS chart integration
print("\n// JS ready:")
print("const labels = " + str(labels) + ";")
print("const data = " + str(data) + ";")




import pandas as pd

# Load the Excel file
file_path = "AIDatabase\management\commands\Warning_Letters_Final_9_12_2025.xlsx"
df = pd.ExcelFile(file_path)

# Check sheet names
df.sheet_names

data = pd.read_excel(file_path, sheet_name="Final Files For Deploy")

# Calculate total companies and total warning letters
total_companies = data["Company Name"].nunique()
total_letters = len(data)

# Calculate yearwise company count
yearwise_company_count = data.groupby("Year")["Company Name"].nunique().reset_index()
yearwise_company_count.columns = ["Year", "Unique Company Count"]

print(total_companies, total_letters, yearwise_company_count)
