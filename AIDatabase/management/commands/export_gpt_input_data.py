"""
Export exactly what the observation-summary feature would send to the OpenAI
API, as an .xlsx workbook. Makes no API calls and costs nothing.

The block grouping, text preparation and prompt strings are imported from
AIDatabase.observation_summary rather than reimplemented here, so this export
cannot drift from what the live code actually sends.
"""

import os

import pandas as pd
from django.conf import settings
from django.core.management.base import BaseCommand

from AIDatabase import observation_summary as osum

# Excel hard-caps a single cell at 32,767 characters.
EXCEL_CELL_LIMIT = 32000


class Command(BaseCommand):
    help = "Export the observation data that would be sent to the OpenAI API to an .xlsx file."

    def add_arguments(self, parser):
        parser.add_argument(
            "--out",
            default="gpt_input_data.xlsx",
            help="Output .xlsx path (default: gpt_input_data.xlsx).",
        )
        parser.add_argument(
            "--only-pending",
            action="store_true",
            help="Export only the blocks that would actually trigger an API call.",
        )

    def handle(self, *args, **options):
        source = os.path.join(
            settings.BASE_DIR, "AIDatabase", "management", "commands",
            "Final_File_FDA_Observations_15_12_2025.xlsx",
        )
        if not os.path.exists(source):
            self.stderr.write(self.style.ERROR("Source workbook not found: %s" % source))
            return

        self.stdout.write("Reading %s" % source)
        df = pd.read_excel(source)

        for col in (osum.OBSERVATION_COLUMN, osum.DETAILS_COLUMN):
            if col not in df.columns:
                self.stderr.write(self.style.ERROR("Required column missing: %r" % col))
                return
        if osum.SUMMARY_COLUMN not in df.columns:
            df[osum.SUMMARY_COLUMN] = None

        checkpoint = osum._load_checkpoint()
        rows = self._collect_blocks(df, checkpoint)
        if options["only_pending"]:
            rows = [r for r in rows if r["Would Call API"] == "YES"]

        self._write_workbook(rows, source, options["out"], checkpoint)

    def _collect_blocks(self, df, checkpoint):
        """Group rows into observation blocks the way the summariser does."""
        blocks = []
        current = None

        def flush(block):
            if not block or not block["obs"]:
                return
            details, seen = [], set()
            for value in block["details"]:
                d = osum._normalize_text(value)
                if d and d not in seen:
                    seen.add(d)
                    details.append(d)
            merged = "\n\n".join(details)

            existing = [s for s in block["summaries"] if osum._normalize_text(s)]
            prepared = osum._truncate_text(merged) if merged else None
            limits = osum._build_summary_word_limits(prepared) if prepared else {}

            if existing:
                send, reason = "NO", "Already has a summary in the source sheet"
            elif not details:
                send, reason = "NO", "No observation details to summarise"
            elif osum._checkpoint_key(merged) in checkpoint:
                send, reason = "NO", "Already generated (present in summary_checkpoint.json)"
            else:
                send, reason = "YES", "No existing summary - would be sent to the API"

            blocks.append({
                "Block #": len(blocks) + 1,
                "Company Name": block["company"] or "",
                "Observation": block["obs"] or "",
                "Source Rows": len(block["indices"]),
                "Would Call API": send,
                "Reason": reason,
                "Original Words": limits.get("original_words", 0),
                "Requested Min Words": limits.get("min_words", 0),
                "Requested Target Words": limits.get("target_words", 0),
                "Requested Max Words": limits.get("max_words", 0),
                "max_completion_tokens": limits.get("max_tokens", 0),
                "Merged Detail Chars": len(merged),
                "Truncated For API": "YES" if prepared and len(prepared) < len(merged) else "NO",
                "Text Sent To API (prepared)": (prepared or "")[:EXCEL_CELL_LIMIT],
                "Existing Summary": (existing[0] if existing else "")[:EXCEL_CELL_LIMIT],
            })

        for idx, row in df.iterrows():
            obs = osum._normalize_observation_key(row[osum.OBSERVATION_COLUMN])
            company = osum._normalize_text(row.get("Company Name", ""))
            if current and (obs != current["obs"] or company != current["company"]):
                flush(current)
                current = None
            if current is None:
                current = {"obs": obs, "company": company, "indices": [],
                           "details": [], "summaries": []}
            current["indices"].append(idx)
            current["details"].append(row.get(osum.DETAILS_COLUMN))
            current["summaries"].append(row.get(osum.SUMMARY_COLUMN))
        flush(current)
        return blocks

    def _write_workbook(self, rows, source, out, checkpoint):
        data = pd.DataFrame(rows)
        pending = data[data["Would Call API"] == "YES"] if len(data) else data

        def total(col):
            return int(pending[col].sum()) if len(pending) else 0

        overview = pd.DataFrame([
            ("Source workbook", os.path.basename(source)),
            ("Model", osum.SUMMARY_MODEL),
            ("Temperature", osum.SUMMARY_TEMPERATURE),
            ("Max input chars per call", osum.SUMMARY_MAX_INPUT_CHARS),
            ("Retries per block on failure", osum.SUMMARY_MAX_ATTEMPTS),
            ("Observation blocks total", len(data)),
            ("Blocks that WOULD call the API", len(pending)),
            ("Blocks skipped", len(data) - len(pending)),
            ("Entries already in summary_checkpoint.json", len(checkpoint)),
            ("Chars that would be sent", total("Merged Detail Chars")),
            ("Words that would be sent", total("Original Words")),
            ("Sum of max_completion_tokens requested", total("max_completion_tokens")),
            ("ENABLE_OBSERVATION_SUMMARIES", getattr(settings, "ENABLE_OBSERVATION_SUMMARIES", False)),
        ], columns=["Item", "Value"])

        prompts = pd.DataFrame([
            ("System prompt (identical on every call)", osum.SUMMARY_SYSTEM_PROMPT),
            ("User prompt template", osum.SUMMARY_USER_PROMPT_TEMPLATE),
        ], columns=["Part", "Content"])

        with pd.ExcelWriter(out, engine="openpyxl") as writer:
            overview.to_excel(writer, sheet_name="Overview", index=False)
            data.to_excel(writer, sheet_name="GPT Input Data", index=False)
            prompts.to_excel(writer, sheet_name="Prompts", index=False)

        self.stdout.write(self.style.SUCCESS("Wrote %s" % out))
        self.stdout.write("  blocks total       : %d" % len(data))
        self.stdout.write("  would call the API : %d" % len(pending))
        self.stdout.write("  skipped            : %d" % (len(data) - len(pending)))
