# F-3 re-check from the raw IID file (2026-11-27)

**What F-3 says** (`docs/VALIDATION_REPORT_2026-11-19.md`, finding F-3):
- no row of the FDA IID July 2026 file has both a potency value and a maximum daily exposure;
- so on real data a within-limit result is always "Review required", "Pass with IID precedent" never occurs, and formulas E and F never run.

The rule that produces this is `backend/iid_assessment/decisions.py:201-232`: a pass needs a usable daily maximum, otherwise `MDE_UNAVAILABLE` → review required.

**This re-check counts from the raw file, not from the database.**
- It reads `IIR_OCOMM.csv` straight out of the FDA zip, without extracting it.
- The zip is the same one the importer loaded in October: its SHA-256 and the CSV's SHA-256 match the hashes recorded on 2026-10-13.

## Result

| Rows in the file | With a potency value | With a maximum daily exposure | **With both** | With neither (counted directly) |
|---:|---:|---:|---:|---:|
| 9,071 | 3,805 | 4,059 | **0** | 1,207 |

- **F-3 is confirmed.** The counts are the same whether "has a value" means "not blank" or "parses as a number".
- **What it means:** a potency comparison and a daily-maximum comparison can never both run on one IID record from this file. This is a property of FDA's data, not a REGX defect.
- **What it depends on:** whether a per-day check can use a different record, which is the per-day rule (White Paper spec Q8). That decision is still with iCretegy and the regulatory reviewer.

## The file

| | |
|---|---|
| **File** | `iig_july_2026.zip`, 382,910 bytes, SHA-256 `d08cf074fb381dea17f922cb9c085750878e366516236471d97f18e9980c987e`. The owner's download, kept at `D:/Praverse/data/fda/iid/2026-10-12/` (not in the repo) |
| **Member checked** | `IIR_OCOMM.csv`, 644,025 bytes, SHA-256 `4f3a8e371551a97e362424bbaa211af19dbb5b7919d7db1ae86379598436d302` |
| **Other members** | `IIR_OCOMM.xls`, `Change_Log_Data.csv`, `Change_Log_Data.xls` |
| **FDA release date** | **Not confirmed from FDA.** What the file itself shows: all four members are dated **2026-07-21** inside the zip, and the newest snapshot in `Change_Log_Data.csv` is labelled **"Q3 2026"**. FDA's online IID database page (read 2026-11-26) gives no date for this file; it now says **"Data Through: September 21, 2026"** and **"Database Last Updated: October 19, 2026"**, so FDA has published data newer than this file. The newer release was not downloaded, so whether F-3 still holds on it is **not checked** |

## Raw line and row check

The question: is 9,071 every data row, or could blank lines or quoted fields with line breaks make the physical line count and the CSV row count differ?

| Check | Result |
|---|---|
| Physical lines | **9,072**, every one ending in CRLF; the file ends with a line break; no bare LF or CR |
| CSV records (Python `csv` module) | **9,072** = **1 header** (10 fields) + **9,071 data rows** |
| Blank records | 0 |
| Records with a different number of fields from the header | 0 |
| Records with a line break inside a quoted field | 0 |
| Physical lines minus CSV records | **0** |

- **9,071 is every data row in the file.** The line count and the row count agree exactly, and nothing was skipped.
- **"Neither" is counted directly** (rows where both the potency field and the daily-maximum field are blank): **1,207**. It is not worked out by subtraction. As a cross-check, 3,805 + 4,059 + 0 + 1,207 = 9,071.

Script: `D:/Praverse/session-work/2026-11-27/tools/f3_raw_lines.py`, run as `python -I f3_raw_lines.py D:/Praverse/data/fda/iid/2026-10-12/iig_july_2026.zip`. Output, as run:

```text
zip: D:/Praverse/data/fda/iid/2026-10-12/iig_july_2026.zip | bytes: 382910 | sha256: d08cf074fb381dea17f922cb9c085750878e366516236471d97f18e9980c987e
zip members: [('IIR_OCOMM.xls', 1174016, (2026, 7, 21, 4, 25, 52)), ('Change_Log_Data.csv', 5414, (2026, 7, 21, 4, 32, 16)), ('Change_Log_Data.xls', 30208, (2026, 7, 21, 4, 31, 48)), ('IIR_OCOMM.csv', 644025, (2026, 7, 21, 4, 25, 30))]
member: IIR_OCOMM.csv | bytes: 644025 | sha256: 4f3a8e371551a97e362424bbaa211af19dbb5b7919d7db1ae86379598436d302
starts with UTF-8 BOM: False

[physical lines]
  LF characters (line breaks): 9072
  of which CRLF: 9072 | bare LF: 0 | bare CR: 0
  file ends with a line break: True
  physical lines (wc -l style, plus a last unterminated line if any): 9072
  blank physical lines (incl. the empty piece after a final newline): 1

[CSV records]
  records parsed (incl. header): 9072
  header records: 1 | header fields: 10
  data records: 9071
  blank data records: 0
  data records whose field count differs from the header: 0 []
  data records with a line break inside a quoted field: 0 []
  last physical line consumed by the reader: 9072
  lines minus records: 0

[direct counts over 9071 non-blank data records]
  potency value present: 3805
  maximum daily exposure present: 4059
  both present: 0
  neither present (counted directly): 1207
  RECORD_UPDATED: earliest ['Y'] latest ['Y'] | distinct 1
```

## The script, as run

`D:/Praverse/session-work/2026-11-27/tools/f3_iid_counts.py`, run as `python -I f3_iid_counts.py D:/Praverse/data/fda/iid/2026-10-12/iig_july_2026.zip`:

```python
"""F-3 re-check from the raw July 2026 IID file (not the database).

Reads IIR_OCOMM.csv straight from the FDA zip (nothing extracted) and counts the rows with a potency
value, with a maximum daily exposure value, and with both. "Has a value" = the field is not blank
after trimming; the same counts are also given for values that parse as a number.
usage: python -I f3_iid_counts.py <iig_july_2026.zip>
"""
import csv
import hashlib
import io
import sys
import zipfile
from collections import Counter

path = sys.argv[1]
data = open(path, "rb").read()
print("zip:", path)
print("zip sha256:", hashlib.sha256(data).hexdigest(), "| bytes:", len(data))
z = zipfile.ZipFile(io.BytesIO(data))
info = z.getinfo("IIR_OCOMM.csv")
raw = z.read(info)
print("member: IIR_OCOMM.csv | bytes:", len(raw), "| sha256:", hashlib.sha256(raw).hexdigest(), "| date:", info.date_time)
text = raw.decode("utf-8-sig")
rows = [r for r in csv.reader(io.StringIO(text))]
header, body = rows[0], [r for r in rows[1:] if r]
print("columns:", header)
D = [dict(zip(header, r)) for r in body]
print("data rows:", len(D))

POT, MDE = "POTENCY_AMOUNT", "MAXIMUM_DAILY_EXPOSURE"


def present(v):
    return bool((v or "").strip())


def numeric(v):
    try:
        float((v or "").strip())
        return True
    except ValueError:
        return False


for label, test in (("non-blank", present), ("parses as a number", numeric)):
    c = Counter((test(d[POT]), test(d[MDE])) for d in D)
    print(f"\n[{label}]")
    print(f"  rows with a potency value:            {c[(True, False)] + c[(True, True)]}")
    print(f"  rows with a maximum daily exposure:   {c[(False, True)] + c[(True, True)]}")
    print(f"  rows with both:                       {c[(True, True)]}")
    print(f"  rows with neither:                    {c[(False, False)]}")
    print(f"  total:                                {sum(c.values())}")
```

## Its output, as run

```text
zip: D:/Praverse/data/fda/iid/2026-10-12/iig_july_2026.zip
zip sha256: d08cf074fb381dea17f922cb9c085750878e366516236471d97f18e9980c987e | bytes: 382910
member: IIR_OCOMM.csv | bytes: 644025 | sha256: 4f3a8e371551a97e362424bbaa211af19dbb5b7919d7db1ae86379598436d302 | date: (2026, 7, 21, 4, 25, 30)
columns: ['INGREDIENT_NAME', 'ROUTE', 'DOSAGE_FORM', 'CAS_NUMBER', 'UNII', 'POTENCY_AMOUNT', 'POTENCY_UNIT', 'MAXIMUM_DAILY_EXPOSURE', 'MAXIMUM_DAILY_EXPOSURE_UNIT', 'RECORD_UPDATED']
data rows: 9071

[non-blank]
  rows with a potency value:            3805
  rows with a maximum daily exposure:   4059
  rows with both:                       0
  rows with neither:                    1207
  total:                                9071

[parses as a number]
  rows with a potency value:            3805
  rows with a maximum daily exposure:   4059
  rows with both:                       0
  rows with neither:                    1207
  total:                                9071
```
