"""Milestone 4D-4 -- governed controlled export of an approved execution.

Specification: ``MILESTONE_4D_DISCOVERY.md`` §17 (controlled exports) and §18
(reproducibility); ``MILESTONE_4D_4_DISCOVERY.md`` §I / §I.1 for the approved
provenance contract (``4D4-DEC-005``) and ``4D4-DEC-006`` for canonical form.

Three properties this module exists to guarantee:

1. **The export is a projection, not a dump.** Every exported field is named
   explicitly. ``4D4-DEC-005`` requires an allow-list rather than serialising
   ``CalculationOutcome.input_provenance`` unchanged, so a key added to that
   column in future cannot reach a regulatory artifact without a governed
   decision. `_normalise_input_provenance()` is where that is enforced.

2. **The ordinary read model is untouched.** 4D-3 deliberately keeps provenance
   out of the UI projection because it is not display data. Export provenance is
   assembled here, server-side, behind a dedicated permission -- the
   ``ChecklistResponse``/``CalculationOutcome`` API serializers are not widened.

3. **The artifact is reproducible.** The same governed state canonicalises to the
   same bytes and therefore the same SHA-256, on any machine, in any locale,
   regardless of dict construction order.

**Checksum scope.** §17 requires "a SHA-256 checksum computed over the canonical
serialized export payload" -- singular and format-independent, and ``DEC-006``
defines canonical form in *data* terms (key ordering, decimal rendering,
timestamps, UTF-8), not CSV-row terms. So there is one governed ``payload``,
hashed once; JSON and CSV are two renderings of it and both carry that same
checksum.

``generated_at`` is **inside** the hashed payload. ``4D4-DEC-005`` is explicit --
"All provenance included in the controlled export participates in the canonical
serialized payload covered by the SHA-256 checksum" -- and it lists
``generated_at`` as included artifact provenance. An earlier revision of this
module placed it in an unhashed envelope on the theory that two exports of
identical regulatory state ought to agree; independent review found that property
is nowhere in the specification, and that excluding the timestamp defeated §17's
stated purpose, which is to "verify a previously-issued export was not altered
after the fact" -- an issued artifact whose timestamp can be rewritten without
breaking its checksum is not tamper-evident. Two exports taken at different times
legitimately differ. Reproducibility means *the same complete canonical payload
yields the same hash*, not that two separate export runs agree.

Only the checksum itself stays outside the hashed bytes, because a hash cannot
cover itself. ``export_schema_version`` is inside, so a shape change is also
tamper-evident.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from decimal import Decimal

from common.csv_safety import csv_safe_cell

from .calculation_translation import format_decimal_plain

__all__ = [
    "EXPORT_SCHEMA_VERSION",
    "ControlledExportError",
    "ExecutionNotExportable",
    "ExportPermissionDenied",
    "build_export_artifact",
    "canonical_bytes",
    "checksum_for",
    "export_execution",
    "render_csv",
    "render_json",
]

#: Single source of truth for the artifact shape (``4D4-DEC-005`` §13). Bumping
#: this is a governed change: historical artifacts must stay interpretable, so a
#: new version never silently reinterprets an old one.
EXPORT_SCHEMA_VERSION = "1"

CHECKSUM_ALGORITHM = "sha256"


class ControlledExportError(Exception):
    """Base for governed export refusals."""


class ExecutionNotExportable(ControlledExportError):
    """§17 -- only a completed (``approved``) execution may be exported."""


class ExportPermissionDenied(ControlledExportError):
    """§17 -- the caller lacks ``iig_checklist.export_checklist``."""


#: §17 -- export is offered for an approved execution only.
EXPORTABLE_EXECUTION_STATUSES: frozenset[str] = frozenset({"approved"})

#: ``4D4-DEC-005`` -- the only per-input provenance fields that may leave the
#: system. Anything else in the stored column is dropped, including keys added
#: after this list was written. Ordering here is documentation; canonicalisation
#: sorts keys anyway.
ALLOWED_INPUT_DESCRIPTOR_FIELDS: frozenset[str] = frozenset(
    {
        "source_kind",
        "source_public_id",
        "source_question_code",
        "value",
        "expected_type",
        "source_unit",
        "target_unit",
        "conversion_factor",
        "conversion_rule_version",
        "detail_code",
    }
)

#: Top-level provenance keys carried through, with their exported names. The
#: stored column also holds per-kwarg descriptors, handled separately.
_PROVENANCE_SCALAR_KEYS = {
    "calculation_name": "calculation_name",
    "formula_version": "formula_version",
    "_registry_binding_version": "registry_binding_version",
    "_subject_component_public_id": "subject_component_public_id",
    "assessment_snapshot_public_id": "assessment_snapshot_public_id",
}

_PROVENANCE_LIST_KEYS = {
    "upstream_outcome_public_ids": "upstream_outcome_public_ids",
    "subject_component_sources": "subject_component_sources",
}


# ---------------------------------------------------------------------------
# Canonicalisation -- 4D4-DEC-006
# ---------------------------------------------------------------------------


def _canonical_scalar(value):
    """Render one leaf deterministically.

    Decimals go through the project's plain-notation formatter rather than
    ``float()`` or ``str()``: a regulated figure must not round-trip through a
    binary float, and ``str(Decimal("1E-7"))`` would emit exponent notation that
    a later reader has to decode.
    """
    if isinstance(value, Decimal):
        return format_decimal_plain(value)
    if isinstance(value, bool) or value is None or isinstance(value, int | str):
        return value
    if isinstance(value, float):
        # No governed value is a float. Reaching here means an unreviewed field
        # entered the payload, and silently accepting it would make the checksum
        # depend on binary rounding.
        raise ControlledExportError(
            "float is not a permitted governed export value; use Decimal or a string"
        )
    if hasattr(value, "isoformat"):
        return _iso_utc(value)
    raise ControlledExportError(f"unsupported export value type: {type(value).__name__}")


def _iso_utc(moment) -> str:
    """ISO-8601 in UTC with a trailing ``Z``, second-resolution-stable.

    Timezone-aware values are converted to UTC; naive values are treated as UTC
    rather than guessed at, so the rendering never depends on server locale.
    """
    from datetime import UTC

    if getattr(moment, "tzinfo", None) is not None:
        moment = moment.astimezone(UTC)
    return moment.replace(tzinfo=None).isoformat(timespec="microseconds") + "Z"


def _canonicalise(value):
    """Recursively normalise a payload into canonical, JSON-safe primitives."""
    if isinstance(value, dict):
        # Sorted here as well as in json.dumps so nested structures are stable
        # even if a caller serialises a sub-tree independently.
        return {str(key): _canonicalise(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, list | tuple):
        return [_canonicalise(item) for item in value]
    return _canonical_scalar(value)


def canonical_bytes(payload) -> bytes:
    """The exact bytes the checksum is taken over.

    ``sort_keys`` makes the result independent of dict construction order;
    ``ensure_ascii=False`` with an explicit UTF-8 encode keeps non-ASCII stable
    rather than escaping it differently across versions; the compact separators
    remove insignificant whitespace so formatting can never alter the hash.
    """
    return json.dumps(
        _canonicalise(payload),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def checksum_for(payload) -> str:
    """Lowercase hex SHA-256 over the canonical bytes of ``payload``."""
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


# ---------------------------------------------------------------------------
# Provenance projection -- 4D4-DEC-005
# ---------------------------------------------------------------------------


def _normalise_input_provenance(stored) -> dict:
    """Project the stored provenance column onto the approved allow-list.

    Deliberately positive-listed. The stored form is already built to
    M4D3-PRV-002 ("public identifiers, governed codes and unit evidence only"),
    so this is not compensating for an unsafe column -- it is making the export a
    versioned contract rather than a mirror of whatever the column holds.
    """
    if not isinstance(stored, dict):
        return {}

    projected: dict = {}
    for stored_key, exported_key in _PROVENANCE_SCALAR_KEYS.items():
        value = stored.get(stored_key)
        if value is not None:
            projected[exported_key] = value

    for stored_key, exported_key in _PROVENANCE_LIST_KEYS.items():
        value = stored.get(stored_key)
        if isinstance(value, list | tuple) and value:
            projected[exported_key] = list(value)

    inputs: dict = {}
    for key, descriptor in stored.items():
        if key in _PROVENANCE_SCALAR_KEYS or key in _PROVENANCE_LIST_KEYS:
            continue
        if not isinstance(descriptor, dict):
            # A non-descriptor top-level key is not part of the contract.
            continue
        allowed = {
            field: descriptor[field]
            for field in sorted(descriptor)
            if field in ALLOWED_INPUT_DESCRIPTOR_FIELDS and descriptor[field] is not None
        }
        if allowed:
            inputs[key] = allowed
    if inputs:
        projected["inputs"] = inputs

    return projected


def _outcome_projection(outcome) -> dict | None:
    """The governed calculated-result projection (``4D4-DEC-005`` §I.1).

    ``outcome.inputs`` is deliberately absent: the per-input descriptors already
    carry the governed values with their source, unit and conversion evidence,
    so exporting the raw kwargs would duplicate regulated data with less context.
    """
    if outcome is None:
        return None
    return {
        "outcome_public_id": str(outcome.public_id),
        "status": outcome.status,
        "value": None if outcome.value is None else format_decimal_plain(outcome.value),
        "unit": outcome.unit or None,
        "reason_code": outcome.reason_code or None,
        "provenance": _normalise_input_provenance(outcome.input_provenance),
    }


def _response_projection(response, outcome) -> dict:
    question = response.question
    return {
        "question_public_id": str(question.public_id),
        "question_code": question.code,
        "answer_type": question.answer_type,
        "response_public_id": str(response.public_id),
        "response_version": response.version,
        "raw_value": response.raw_value,
        "is_not_applicable": response.is_not_applicable,
        "not_applicable_reason": response.not_applicable_reason or None,
        "data_source_type_snapshot": response.data_source_type_snapshot,
        "system_derived_value": response.system_derived_value,
        "calculation": _outcome_projection(outcome),
    }


# ---------------------------------------------------------------------------
# Artifact assembly
# ---------------------------------------------------------------------------


def build_export_artifact(*, execution, generated_at):
    """Assemble the governed artifact for one approved execution.

    Reads only pinned records -- the execution's own responses and the checklist
    version it was created against (§18). No live FDA or formulation source is
    re-queried, so a later change to reference data cannot alter a previously
    exported regulatory state.
    """
    from .models import CalculationOutcome, ChecklistResponse

    if execution.status not in EXPORTABLE_EXECUTION_STATUSES:
        raise ExecutionNotExportable(execution.status)

    responses = list(
        ChecklistResponse.objects.filter(execution=execution)
        .select_related("question")
        .order_by("question__display_order", "question__code", "public_id")
    )

    outcomes: dict[int, object] = {}
    for outcome in CalculationOutcome.objects.filter(response__execution=execution).order_by(
        "public_id"
    ):
        # One outcome per response is a governed invariant enforced by the
        # writer; first-by-public_id matches how the writer and resolver select.
        outcomes.setdefault(outcome.response_id, outcome)

    version = execution.checklist_version
    payload = {
        "export_schema_version": EXPORT_SCHEMA_VERSION,
        # 4D4-DEC-005 "Checksum coverage": included artifact provenance
        # participates in the hashed payload. See the module docstring.
        "generated_at": _iso_utc(generated_at),
        "execution": {
            "execution_public_id": str(execution.public_id),
            "status": execution.status,
            "formulation_version_public_id": str(execution.formulation_version.public_id),
            "reviewer_conclusion_note": execution.reviewer_conclusion_note or None,
        },
        "checklist_definition": {
            "definition_public_id": str(version.definition.public_id),
            "definition_code": version.definition.code,
            "version_public_id": str(version.public_id),
            "version_number": version.version_number,
        },
        "responses": [
            _response_projection(response, outcomes.get(response.pk)) for response in responses
        ],
    }

    # The envelope carries only what cannot be hashed: the checksum itself.
    # generated_at lives in the payload alone -- duplicating it here would create
    # a second copy that could drift from the one the checksum attests to.
    return {
        "checksum": {"algorithm": CHECKSUM_ALGORITHM, "value": checksum_for(payload)},
        "payload": payload,
    }


# ---------------------------------------------------------------------------
# Renderings -- one artifact, two representations
# ---------------------------------------------------------------------------


def render_json(artifact) -> str:
    """JSON rendering. Canonical so the served bytes are themselves stable."""
    return json.dumps(
        _canonicalise(artifact), sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )


def export_execution(*, tenant, execution_public_id, actor, fmt="json"):
    """The governed entry point. Returns ``(artifact, rendered_text)``.

    Ordering matches the platform convention already used by every governed
    checklist service: tenant-scoped lookup **first**, so a cross-tenant id is a
    404 through ``visible_to()`` and never a 403 that would confirm the record
    exists; then the dedicated export permission; then lifecycle.

    The audit event is emitted only after the artifact exists, and carries the
    checksum so the trail can later attest to a specific issued export (§17).
    """
    from django.db import transaction as db_transaction
    from django.utils import timezone
    from rest_framework.exceptions import NotFound

    from .audit import IigChecklistEvent, emit
    from .models import ChecklistExecution
    from .permissions import PERM_EXPORT_CHECKLIST, has_iig_checklist_permission

    try:
        execution = (
            ChecklistExecution.objects.visible_to(tenant)
            .select_related("checklist_version__definition", "formulation_version")
            .get(public_id=execution_public_id)
        )
    except ChecklistExecution.DoesNotExist:
        raise NotFound() from None

    if not has_iig_checklist_permission(actor, tenant, PERM_EXPORT_CHECKLIST):
        raise ExportPermissionDenied()

    artifact = build_export_artifact(execution=execution, generated_at=timezone.now())
    rendered = render_csv(artifact) if fmt == "csv" else render_json(artifact)

    def _audit():
        emit(
            event_type=IigChecklistEvent.EXECUTION_EXPORTED,
            resource_id=str(execution.public_id),
            actor_id=getattr(actor, "id", None),
            actor_email=getattr(actor, "email", ""),
            tenant_id=getattr(tenant, "id", None),
            payload={
                "execution_public_id": str(execution.public_id),
                "execution_status": execution.status,
                "export_schema_version": EXPORT_SCHEMA_VERSION,
                "format": fmt,
                "checksum_algorithm": artifact["checksum"]["algorithm"],
                "checksum": artifact["checksum"]["value"],
                "generated_at": artifact["payload"]["generated_at"],
                "response_count": len(artifact["payload"]["responses"]),
                "checklist_version_public_id": (
                    artifact["payload"]["checklist_definition"]["version_public_id"]
                ),
            },
        )

    db_transaction.on_commit(_audit)
    return artifact, rendered


CSV_RESPONSE_COLUMNS = (
    "question_code",
    "question_public_id",
    "answer_type",
    "response_public_id",
    "response_version",
    "raw_value",
    "is_not_applicable",
    "not_applicable_reason",
    "data_source_type_snapshot",
    "system_derived_value",
    "calculation_outcome_public_id",
    "calculation_status",
    "calculation_value",
    "calculation_unit",
    "calculation_reason_code",
    "calculation_provenance",
)


def _csv_cell(value) -> str:
    """One CSV cell: JSON-encode structure, then neutralise formula injection.

    Every cell goes through the shared helper -- §17 requires it and forbids new
    CSV-safety code.
    """
    if value is None:
        rendered = ""
    elif isinstance(value, bool):
        rendered = "true" if value else "false"
    elif isinstance(value, dict | list):
        rendered = json.dumps(
            _canonicalise(value), sort_keys=True, ensure_ascii=False, separators=(",", ":")
        )
    else:
        rendered = str(_canonical_scalar(value))
    return csv_safe_cell(rendered)


def render_csv(artifact) -> str:
    """CSV rendering of the *same* artifact -- a flattening, not a second model.

    Two sections: the envelope and execution identity as ``field,value`` rows,
    then the per-response table. The checksum carried here is the one taken over
    the canonical payload, so a CSV and a JSON export of the same state attest to
    the same bytes.
    """
    payload = artifact["payload"]
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    writer.writerow(["field", "value"])
    metadata = [
        ("export_schema_version", payload["export_schema_version"]),
        ("generated_at", payload["generated_at"]),
        ("checksum_algorithm", artifact["checksum"]["algorithm"]),
        ("checksum_value", artifact["checksum"]["value"]),
        ("execution_public_id", payload["execution"]["execution_public_id"]),
        ("execution_status", payload["execution"]["status"]),
        (
            "formulation_version_public_id",
            payload["execution"]["formulation_version_public_id"],
        ),
        ("reviewer_conclusion_note", payload["execution"]["reviewer_conclusion_note"]),
        ("definition_public_id", payload["checklist_definition"]["definition_public_id"]),
        ("definition_code", payload["checklist_definition"]["definition_code"]),
        ("version_public_id", payload["checklist_definition"]["version_public_id"]),
        ("version_number", payload["checklist_definition"]["version_number"]),
    ]
    for field, value in metadata:
        writer.writerow([_csv_cell(field), _csv_cell(value)])

    writer.writerow([])
    writer.writerow([_csv_cell(column) for column in CSV_RESPONSE_COLUMNS])

    for response in payload["responses"]:
        calculation = response["calculation"] or {}
        writer.writerow(
            [
                _csv_cell(response["question_code"]),
                _csv_cell(response["question_public_id"]),
                _csv_cell(response["answer_type"]),
                _csv_cell(response["response_public_id"]),
                _csv_cell(response["response_version"]),
                _csv_cell(response["raw_value"]),
                _csv_cell(response["is_not_applicable"]),
                _csv_cell(response["not_applicable_reason"]),
                _csv_cell(response["data_source_type_snapshot"]),
                _csv_cell(response["system_derived_value"]),
                _csv_cell(calculation.get("outcome_public_id")),
                _csv_cell(calculation.get("status")),
                _csv_cell(calculation.get("value")),
                _csv_cell(calculation.get("unit")),
                _csv_cell(calculation.get("reason_code")),
                _csv_cell(calculation.get("provenance")),
            ]
        )

    return buffer.getvalue()
