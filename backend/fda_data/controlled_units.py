"""Controlled units, increment 2: the reviewed unit list and unit-mapping proposals.

Design: docs/CONTROLLED_UNITS_DESIGN.md sections 2-3. Increment 1 added
`QuantityExpression` (family x basis). This module loads the units and the
meanings the IID needs, and proposes how each IID potency unit string maps to a
meaning. It compares nothing (increment 3).

HOW THE LIST GETS IN (same pattern as `spl_terminology`)
--------------------------------------------------------
1. The list is a reviewed JSON file in `fda_data/reference/` (not an FDA file).
2. `load_snapshot` registers it as an `FDADataSourceRelease` of type
   `regx_controlled_units` with the loader recorded (`--actor`), and one
   `FdaImportRowResult` per unit and per meaning. Loading the same bytes twice
   returns the same release and changes nothing.
3. The release goes through the normal lifecycle; a VP approves and activates
   it, and the loader can do neither (`lifecycle._refuse_loader`).
4. **A unit or meaning is in force only while the release that lists it is
   ACTIVE** (`in_force_expressions`). Nothing is flipped on activation.

`ControlledUnit.active` is left False on purpose: it is the legacy importer's
lookup flag (`terminology.lookup_unit`). Setting it would make future IID
imports fill `potency_unit_normalized` and could make records "calculable" for
the old matching path, bypassing the family-and-basis rule. Whether and how the
two paths meet is for increment 3.

PROPOSALS
---------
`propose_unit_mappings` reads every distinct `potency_unit_raw` of an IID
release and proposes a `UnitMapping` (status PROPOSED, `quantity_expression`
set) only when the string matches the strict grammar below exactly AND the
meaning it states is in force. Everything else (e.g. `mg/mg`, `NA`, `ADJ PH`, a
meaning not in the active list) is reported with the reason, never guessed.
Idempotent: a string with a current mapping in any status is skipped. A VP
reviews and approves in the app (reviewer != approver, as for routes and forms).
Maximum-daily-exposure units are out of scope (Q8).
"""

from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .audit_events import FdaDataEvent, emit
from .checksums import sha256_payload
from .importer import register_release
from .models import (
    ControlledUnit,
    FDADatasetType,
    FDADataSourceRelease,
    FdaImportRowResult,
    FdaImportRowResultType,
    FDAReleaseStatus,
    IIDPrecedentRecord,
    MappingDecisionStatus,
    QuantityBasis,
    QuantityExpression,
    QuantityFamily,
    UnitDimension,
    UnitMapping,
)

DATASET = FDADatasetType.REGX_CONTROLLED_UNITS
FORMAT = "regx_controlled_units:1"
PARSER_IDENTIFIER = "regx_controlled_units_json:1"

#: reason_code on each FdaImportRowResult of a units release.
UNIT_NEW, UNIT_UNCHANGED = "unit_new", "unit_unchanged"
MEANING_NEW, MEANING_UNCHANGED = "meaning_new", "meaning_unchanged"


class SnapshotError(Exception):
    """The reviewed list is malformed or conflicts with existing units."""


# --- the reviewed list -------------------------------------------------------


def _decimal(value, where: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise SnapshotError(f"{where}: {value!r} is not a number.") from None
    if not number.is_finite() or number <= 0:
        raise SnapshotError(f"{where}: {value!r} must be a positive number.")
    return number


def parse_snapshot(raw: bytes) -> dict:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SnapshotError(f"Not a UTF-8 JSON file: {exc}") from exc
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise SnapshotError(f'The file must be a JSON object with "format": "{FORMAT}".')
    units, meanings = data.get("units"), data.get("meanings")
    if not isinstance(units, list) or not units or not isinstance(meanings, list) or not meanings:
        raise SnapshotError('Both "units" and "meanings" must be non-empty lists.')

    parsed_units = []
    for n, u in enumerate(units, start=1):
        where = f"units[{n}]"
        if not isinstance(u, dict) or set(u) != {"code", "symbol", "dimension", "factor_to_base"}:
            raise SnapshotError(f"{where}: needs exactly code, symbol, dimension, factor_to_base.")
        if u["dimension"] not in (UnitDimension.MASS, UnitDimension.VOLUME):
            raise SnapshotError(f"{where}: dimension must be mass or volume.")
        parsed_units.append(
            {
                "code": str(u["code"]).strip(),
                "symbol": str(u["symbol"]).strip(),
                "dimension": u["dimension"],
                "factor_to_base": _decimal(u["factor_to_base"], where),
            }
        )
    codes = [u["code"] for u in parsed_units]
    if len(set(codes)) != len(codes) or not all(codes):
        raise SnapshotError("Unit codes must be present and unique.")

    allowed = {"family", "basis", "numerator", "denominator_amount", "denominator_unit"}
    parsed_meanings = []
    for n, m in enumerate(meanings, start=1):
        where = f"meanings[{n}]"
        if not isinstance(m, dict) or not {"family", "basis"} <= set(m) or not set(m) <= allowed:
            raise SnapshotError(f"{where}: needs family and basis; allowed keys {sorted(allowed)}.")
        for key in ("numerator", "denominator_unit"):
            if key in m and m[key] not in codes:
                raise SnapshotError(f"{where}: {key} {m[key]!r} is not a listed unit.")
        parsed_meanings.append(
            {
                "family": m["family"],
                "basis": m["basis"],
                "numerator": m.get("numerator"),
                "denominator_amount": _decimal(m["denominator_amount"], where)
                if "denominator_amount" in m
                else None,
                "denominator_unit": m.get("denominator_unit"),
            }
        )
    keys = [_meaning_key(m) for m in parsed_meanings]
    if len(set(keys)) != len(keys):
        raise SnapshotError("A meaning is listed twice.")
    return {"units": parsed_units, "meanings": parsed_meanings}


def _meaning_key(m: dict) -> tuple:
    amount = m["denominator_amount"]
    return (
        m["family"],
        m["basis"],
        m["numerator"],
        amount.normalize() if amount is not None else None,
        m["denominator_unit"],
    )


def _find_expression(m: dict, units: dict) -> QuantityExpression | None:
    qs = QuantityExpression.objects.filter(
        family=m["family"],
        basis=m["basis"],
        numerator_unit=units.get(m["numerator"]),
        denominator_unit=units.get(m["denominator_unit"]),
    )
    qs = (
        qs.filter(denominator_amount=m["denominator_amount"])
        if m["denominator_amount"] is not None
        else qs.filter(denominator_amount__isnull=True)
    )
    return qs.first()


def load_snapshot(
    *, raw: bytes, filename: str, source_reference: str, actor=None
) -> tuple[FDADataSourceRelease, dict]:
    """Register the reviewed list as a release (draft until a VP approves and
    activates it). Existing units are never changed: a listed unit whose code
    exists with a different symbol, dimension or factor refuses the load."""
    snapshot = parse_snapshot(raw)
    with transaction.atomic():
        release = register_release(
            dataset_type=DATASET,
            source_name="REGX controlled units (reviewed list)",
            official_source_reference=source_reference,
            file_obj=io.BytesIO(raw),
            original_filename=filename,
            media_type="application/json",
            imported_by=actor,
            normalized_payload_sha256=sha256_payload(
                {
                    "units": [
                        {**u, "factor_to_base": str(u["factor_to_base"])} for u in snapshot["units"]
                    ],
                    "meanings": [
                        [str(x) if x is not None else None for x in _meaning_key(m)]
                        for m in snapshot["meanings"]
                    ],
                }
            ),
            parser_identifier=PARSER_IDENTIFIER,
        )
        if FdaImportRowResult.objects.filter(release=release).exists():
            return release, {"already_loaded": True, **summarise(release)}

        units: dict[str, ControlledUnit] = {}
        for n, u in enumerate(snapshot["units"], start=1):
            unit = ControlledUnit.objects.filter(code=u["code"]).first()
            if unit is None:
                # active=False: kept out of the legacy importer's lookup (see module doc).
                unit = ControlledUnit.objects.create(
                    code=u["code"],
                    symbol=u["symbol"],
                    dimension=u["dimension"],
                    conversion_factor_to_base=u["factor_to_base"],
                    active=False,
                )
                outcome = UNIT_NEW
            elif (unit.symbol, unit.dimension, unit.conversion_factor_to_base) != (
                u["symbol"],
                u["dimension"],
                u["factor_to_base"],
            ):
                raise SnapshotError(
                    f"Unit {u['code']!r} already exists with a different symbol, dimension or "
                    "factor. Existing units are never changed by a load."
                )
            else:
                outcome = UNIT_UNCHANGED
            units[u["code"]] = unit
            FdaImportRowResult.objects.create(
                release=release,
                row_locator=f"unit:{n}",
                target_public_identifier=unit.public_id,
                result=FdaImportRowResultType.IMPORTED,
                reason_code=outcome,
            )

        for n, m in enumerate(snapshot["meanings"], start=1):
            expression = _find_expression(m, units)
            outcome = MEANING_UNCHANGED
            if expression is None:
                expression = QuantityExpression(
                    family=m["family"],
                    basis=m["basis"],
                    numerator_unit=units.get(m["numerator"]),
                    denominator_amount=m["denominator_amount"],
                    denominator_unit=units.get(m["denominator_unit"]),
                )
                try:
                    expression.full_clean()
                except ValidationError as exc:
                    raise SnapshotError(f"meanings[{n}]: {'; '.join(exc.messages)}") from None
                expression.save()
                outcome = MEANING_NEW
            FdaImportRowResult.objects.create(
                release=release,
                row_locator=f"meaning:{n}",
                target_public_identifier=expression.public_id,
                result=FdaImportRowResultType.IMPORTED,
                reason_code=outcome,
                safe_detail=str(expression),
            )

        total = len(snapshot["units"]) + len(snapshot["meanings"])
        release.record_count_expected = total
        release.record_count_extracted = total
        release.record_count_imported = total
        release.record_count_failed = 0
        release.imported_at = timezone.now()
        release.save(
            update_fields=[
                "record_count_expected",
                "record_count_extracted",
                "record_count_imported",
                "record_count_failed",
                "imported_at",
                "updated_at",
            ]
        )
    return release, {"already_loaded": False, **summarise(release)}


def summarise(release: FDADataSourceRelease) -> dict:
    results = FdaImportRowResult.objects.filter(release=release)
    return {
        code: results.filter(reason_code=code).count()
        for code in (UNIT_NEW, UNIT_UNCHANGED, MEANING_NEW, MEANING_UNCHANGED)
    }


def active_release() -> FDADataSourceRelease | None:
    return FDADataSourceRelease.objects.filter(
        dataset_type=DATASET, status=FDAReleaseStatus.ACTIVE
    ).first()


def in_force_expressions() -> set[int]:
    """Primary keys of the meanings listed by the ACTIVE units release (empty if none)."""
    release = active_release()
    if release is None:
        return set()
    ids = FdaImportRowResult.objects.filter(
        release=release, reason_code__in=(MEANING_NEW, MEANING_UNCHANGED)
    ).values_list("target_public_identifier", flat=True)
    return set(
        QuantityExpression.objects.filter(public_id__in=list(ids)).values_list("pk", flat=True)
    )


class UnitMeaningLookup:
    """The meaning of an IID unit string, for the importer and re-resolve: the
    `quantity_expression` of the APPROVED, current unit mapping for the string,
    and only while that meaning is in force. None otherwise. Reads the in-force
    set once per instance."""

    def __init__(self):
        self._in_force: set[int] | None = None

    def lookup(self, raw: str) -> QuantityExpression | None:
        if not raw:
            return None
        if self._in_force is None:
            self._in_force = in_force_expressions()
        if not self._in_force:
            return None
        mapping = (
            UnitMapping.objects.filter(
                source_dataset=FDADatasetType.FDA_IID,
                source_raw_value=raw,
                is_current=True,
                status=MappingDecisionStatus.APPROVED,
                quantity_expression_id__in=self._in_force,
            )
            .select_related("quantity_expression")
            .first()
        )
        return mapping.quantity_expression if mapping else None


# --- IID unit strings --------------------------------------------------------

_PER_DOSE = re.compile(r"^(mg|ml)$")
_PERCENT = re.compile(r"^%(w/w|w/v|v/v)$")
_PER_VOLUME = re.compile(r"^(mg|ml)/([0-9]+(?:\.[0-9]+)?)ml$")
_UNIT_FAMILY = {"mg": QuantityFamily.MASS, "ml": QuantityFamily.VOLUME}
_PERCENT_BASIS = {"w/w": QuantityBasis.W_W, "w/v": QuantityBasis.W_V, "v/v": QuantityBasis.V_V}


@dataclass(frozen=True)
class StatedMeaning:
    family: str
    basis: str
    numerator: str | None
    denominator_amount: Decimal | None
    denominator_unit: str | None


def parse_unit_string(raw: str) -> StatedMeaning | None:
    """The meaning an IID potency unit string states, or None when it states no
    exact meaning. Lower-case and trimmed; no other normalisation, no guessing."""
    value = (raw or "").strip().lower()
    if m := _PER_DOSE.match(value):
        return StatedMeaning(_UNIT_FAMILY[m[1]], QuantityBasis.PER_DOSE_UNIT, m[1], None, None)
    if m := _PERCENT.match(value):
        return StatedMeaning(QuantityFamily.PERCENTAGE, _PERCENT_BASIS[m[1]], None, None, None)
    if m := _PER_VOLUME.match(value):
        amount = Decimal(m[2])
        if amount <= 0:
            return None
        return StatedMeaning(_UNIT_FAMILY[m[1]], QuantityBasis.PER_VOLUME, m[1], amount, "ml")
    return None


def _in_force_match(stated: StatedMeaning, in_force: set[int]) -> QuantityExpression | None:
    qs = QuantityExpression.objects.filter(
        pk__in=in_force, family=stated.family, basis=stated.basis
    ).select_related("numerator_unit", "denominator_unit")
    for expression in qs:
        if (
            expression.numerator_unit.code if expression.numerator_unit_id else None
        ) != stated.numerator:
            continue
        if (
            expression.denominator_unit.code if expression.denominator_unit_id else None
        ) != stated.denominator_unit:
            continue
        if expression.denominator_amount != stated.denominator_amount:
            continue
        return expression
    return None


#: Why a string got no proposal (report wording).
NO_STATED_MEANING = "states no exact meaning (no basis, not a unit, or unknown form)"
NOT_IN_FORCE = "its meaning is not in the active controlled-units release"

REASON = (
    "The unit string states this meaning exactly (strict grammar: mg | ml | %w/w | %w/v | %v/v | "
    "mg/<n>ml | ml/<n>ml), and the meaning is in the active controlled-units release. "
    "Proposed automatically; needs review."
)


class ProposalRefused(Exception):
    pass


@dataclass
class UnitProposalReport:
    distinct_strings: int = 0
    proposed: list[tuple[str, str, int]] = field(default_factory=list)  # (raw, meaning, records)
    already_mapped: list[tuple[str, str]] = field(default_factory=list)  # (raw, status)
    unclear: list[tuple[str, str, int]] = field(default_factory=list)  # (raw, why, records)


def propose_unit_mappings(
    release: FDADataSourceRelease, *, actor=None, dry_run=False
) -> UnitProposalReport:
    if release.dataset_type != FDADatasetType.FDA_IID:
        raise ProposalRefused(f"Release {release.public_id} is not an IID release.")
    in_force = in_force_expressions()
    if not in_force:
        raise ProposalRefused(
            "No active controlled-units release. Load it with load_controlled_units and have a "
            "VP approve and activate it first."
        )
    report = UnitProposalReport()
    counts: dict[str, int] = {}
    for value in (
        IIDPrecedentRecord.objects.filter(release=release)
        .exclude(potency_unit_raw="")
        .values_list("potency_unit_raw", flat=True)
    ):
        counts[value] = counts.get(value, 0) + 1
    report.distinct_strings = len(counts)
    with transaction.atomic():
        for raw in sorted(counts):
            existing = UnitMapping.objects.filter(
                source_dataset=FDADatasetType.FDA_IID, source_raw_value=raw, is_current=True
            ).first()
            if existing:
                report.already_mapped.append((raw, existing.status))
                continue
            stated = parse_unit_string(raw)
            if stated is None:
                report.unclear.append((raw, NO_STATED_MEANING, counts[raw]))
                continue
            expression = _in_force_match(stated, in_force)
            if expression is None:
                report.unclear.append((raw, NOT_IN_FORCE, counts[raw]))
                continue
            report.proposed.append((raw, str(expression), counts[raw]))
            if dry_run:
                continue
            mapping = UnitMapping.objects.create(
                source_dataset=FDADatasetType.FDA_IID,
                source_raw_value=raw,
                status=MappingDecisionStatus.PROPOSED,
                reason=REASON,
                quantity_expression=expression,
            )
            emit(
                event_type=FdaDataEvent.MAPPING_PROPOSED,
                resource_type="fda_data_mapping",
                resource_id=str(mapping.public_id),
                actor_id=getattr(actor, "id", None),
                actor_email=getattr(actor, "email", ""),
                payload={
                    "mapping_type": "unit",
                    "source_dataset": FDADatasetType.FDA_IID,
                    "source_raw_value": raw,
                    "quantity_expression": str(expression.public_id),
                    "meaning": str(expression),
                    "release": str(release.public_id),
                    "rule": "exact_unit_string_grammar",
                },
            )
    return report


# --- Formulation-side meanings (increment 4, design section 3E) ---------------

#: Spellings of a formulation's `quantity_unit` and the ControlledUnit code they
#: name. Only exact names; nothing is guessed.
_UNIT_SPELLINGS = {
    "mg": "mg",
    "milligram": "mg",
    "milligrams": "mg",
    "ml": "ml",
    "millilitre": "ml",
    "milliliter": "ml",
    "millilitres": "ml",
    "milliliters": "ml",
}
PERCENT_UNIT = "percent"


def in_force_expression(public_id) -> QuantityExpression | None:
    """The meaning with this public id, only while the active unit list lists it."""
    expression = (
        QuantityExpression.objects.select_related("numerator_unit", "denominator_unit")
        .filter(public_id=public_id)
        .first()
    )
    if expression is None or expression.pk not in in_force_expressions():
        return None
    return expression


def stated_amount_problem(expression: QuantityExpression, quantity_unit: str) -> str | None:
    """Why a formulation amount entered in `quantity_unit` cannot carry this
    meaning, or None when it can.

    The amount is read in the meaning's own numerator unit (a percentage for a
    percentage meaning), so the entered unit must be exactly that. A per-day
    meaning is refused: comparing per day needs the Q8 rule.
    """
    unit = (quantity_unit or "").strip().lower()
    if expression.basis == QuantityBasis.PER_DAY:
        return "a per-day meaning cannot be stated yet: comparing per day is not supported yet"
    if expression.family == QuantityFamily.PERCENTAGE:
        if unit != PERCENT_UNIT:
            return f"a percentage meaning needs the amount entered with unit '{PERCENT_UNIT}'"
        return None
    numerator = expression.numerator_unit.code.lower() if expression.numerator_unit_id else ""
    if _UNIT_SPELLINGS.get(unit) != numerator:
        return (
            f"the amount must be entered in '{numerator}', the unit this meaning states "
            f"(got '{quantity_unit}')"
        )
    return None


def in_force_meanings() -> list[QuantityExpression]:
    """Every meaning a formulation may state: in force, and not per day."""
    return list(
        QuantityExpression.objects.select_related("numerator_unit", "denominator_unit")
        .filter(pk__in=in_force_expressions())
        .exclude(basis=QuantityBasis.PER_DAY)
        .order_by("family", "basis", "denominator_amount", "pk")
    )
