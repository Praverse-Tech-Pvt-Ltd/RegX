"""The fixed, synthetic prompt set for `manage.py ai_benchmark`.

Every word here was written for this benchmark. The site, products and events
are invented; nothing is taken from client documents, the development
database, any FDA record or the separate 483 codebase. Keep it that way until
the data checks in docs/AI_INTEGRATION_RUNBOOK.md are done.

`mode` maps each prompt to the SOW latency target it is measured against:
"fast" (p95 under 5 s) for short questions, "think" (p95 under 10 s) for the
long and long-context ones.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BenchmarkPrompt:
    name: str
    mode: str  # "fast" or "think"
    request: str


_OBSERVATION = (
    "Synthetic inspection note (invented for testing). During a review at a "
    "fictional tablet plant, the team found that the cleaning log for mixer M-2 "
    "had three entries signed after the shift had ended, the line clearance "
    "checklist for batch 0007 was missing the second-person check, and the "
    "temperature chart for the warehouse showed a gap of six hours with no "
    "explanation. The plant's own procedure says deviations must be opened "
    "within one working day; for the warehouse gap, the deviation was opened "
    "nine days later. Training records show two operators had not completed "
    "the updated cleaning procedure before they performed the cleaning."
)

_PARAGRAPH = (
    "Synthetic procedure text (invented for testing). Section {n}: Before a "
    "piece of equipment is used for a new product, the operator confirms that "
    "the previous product has been removed, that the cleaning record is "
    "complete and signed, and that the equipment status label shows CLEAN with "
    "today's date. Any doubt is escalated to the shift supervisor, who records "
    "the decision. Records are kept for the life of the product plus one year. "
)

BENCHMARK_PROMPTS: tuple[BenchmarkPrompt, ...] = (
    BenchmarkPrompt(
        name="short-definition",
        mode="fast",
        request="In one sentence, what is a batch record in tablet manufacturing?",
    ),
    BenchmarkPrompt(
        name="short-yes-no",
        mode="fast",
        request="Answer yes or no, then one sentence: should a cleaning log be signed "
        "by the person who did the cleaning?",
    ),
    BenchmarkPrompt(
        name="long-regulatory-summary",
        mode="think",
        request="Summarise the main problems in this note in three bullet points, "
        "most serious first.\n\n" + _OBSERVATION,
    ),
    BenchmarkPrompt(
        name="long-regulatory-actions",
        mode="think",
        request="List the corrective actions this note suggests, each with the "
        "record that would show it was done.\n\n" + _OBSERVATION,
    ),
    BenchmarkPrompt(
        name="long-context-lookup",
        mode="think",
        request="Below is a long procedure. Which section number says how long "
        "records are kept, and for how long? If every section says the same, "
        "say so.\n\n" + "".join(_PARAGRAPH.format(n=n) for n in range(1, 61)),
    ),
)

#: SOW latency targets, seconds, p95 end to end.
TARGET_P95_SECONDS = {"fast": 5.0, "think": 10.0}
