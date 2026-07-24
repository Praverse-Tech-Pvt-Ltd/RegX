# Template Normalization

## Principle: normalization is additive, never destructive

Every imported `TemplateSourceRecord` preserves its original `raw_text`,
`raw_payload` (the full original row), `raw_checksum`, `source_locator`,
`extraction_method`, and `encoding` exactly as extracted. Normalization never
overwrites any of these fields — it only produces a separate normalized value
plus a `NormalizationMapping` audit row recording the raw value, the
normalized value, the rule applied, and (for reviewed corrections) the
reviewer and reason.

## Pipeline (`normalize_text_field`)

Applied to each item's question/title text, in order, each step only
recorded as a mapping if it actually changed something:

1. `html_to_text` — strips CKEditor-style `<p>`/`<br/>` markup to plain text
   (`<br/>` → newline, adjacent `<p>` blocks → blank line, remaining tags
   removed, entities unescaped).
2. `mojibake_repair` — replaces a small, targeted table of known corruption
   patterns found during source inventory (e.g. the literal `U+FFFD`
   replacement character standing in for an apostrophe, `â€™`/`â€œ`
   sequences, `Ã©`/`Ã¨`).
3. `unicode_nfc` — Unicode NFC normalization.
4. `whitespace_collapse` — collapses runs of spaces/tabs, normalizes
   line endings.
5. `embedded_numbering_split` — splits a leading `"1. "`/`"2) "` ordinal out
   of the text into a separate `numbering_prefix`, stored in
   `TemplateItem.metadata`, never in `normalized_text` itself.

## Category normalization (`normalize_category_value`)

Category/label values are normalized non-destructively too, but with a
narrower rule: **only a reviewed mapping-table entry may change spelling**
(e.g. fixing a genuine typo like "Fromulation" → "Formulation"). Absent a
mapping-table entry, only mojibake repair + whitespace collapse are applied —
never a guessed spelling correction. This is deliberate: the pipeline must
never silently "fix" content a human hasn't actually reviewed.

## What is explicitly not implemented

- No fuzzy/ML-based text correction ("ftfy"-style universal repair) — the
  mojibake table is a small, targeted list matched against patterns actually
  observed during source inventory.
- No automatic category reclassification without an explicit mapping-table
  entry.

Verified by `templates_registry/tests/test_importer.py::TestNormalization`
and planted-failure scenario #4 in `test_planted_failures.py`.
