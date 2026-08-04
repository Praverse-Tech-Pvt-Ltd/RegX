"""Milestone 4D-3 -- pure calculation status translation and closed vocabularies.

This module is deliberately database-free.  It performs no ORM access, opens no
transaction and reads no request state.  Everything here is a pure function or
immutable data, so it can be imported and unit-tested without PostgreSQL.

Approved specification: docs/MILESTONE_4D_3_IMPLEMENTATION_SPEC.md
  - M4D3-TRL-001..006  translation contract
  - M4D3-RSN-001..012  closed reason-code vocabularies
  - M4D3-IFV-001..008  input-failure vocabulary and deterministic mapping

Three distinct vocabularies live here and are never interchangeable
(M4D3-RSN-011):

  ALLOWED_REASON_CODES          -> CalculationOutcome.reason_code
  ALLOWED_RESOLVER_DETAIL_CODES -> detail codes recorded in input_provenance
  ALLOWED_INPUT_FAILURE_CODES   -> resolver failure codes (provenance metadata)

History reason codes and service-level rejection codes deliberately live
elsewhere (see governed_vocabularies.py) so the categories cannot blur.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

from iid_assessment.calculations import CalculationResult

# ---------------------------------------------------------------------------
# Stored CalculationStatus values (iig_checklist.enums.CalculationStatus)
#
# Mirrored as plain strings so this module stays importable without Django.
# validate_against_enums() cross-checks them against the real TextChoices.
# ---------------------------------------------------------------------------

STATUS_DATA_REQUIRED = "data_required"
STATUS_CALCULATING = "calculating"
STATUS_COMPLETE = "complete"
STATUS_ERROR = "error"

STORED_STATUSES: frozenset[str] = frozenset(
    {STATUS_DATA_REQUIRED, STATUS_CALCULATING, STATUS_COMPLETE, STATUS_ERROR}
)

# `calculating` is reserved for a future asynchronous engine and is never
# written by 4D-3 (M4D3-MDL-007, SCOPE-OUT-13).
STATUSES_WRITABLE_BY_4D3: frozenset[str] = frozenset(
    {STATUS_DATA_REQUIRED, STATUS_COMPLETE, STATUS_ERROR}
)


# ---------------------------------------------------------------------------
# M4D3-RSN-001 -- canonical CalculationOutcome.reason_code vocabulary
# ---------------------------------------------------------------------------

ALLOWED_REASON_CODES: frozenset[str] = frozenset(
    {
        # Engine-derived scientific / regulatory codes.
        "DATA_REQUIRED",
        "INGREDIENT_UNRESOLVED",
        "ROUTE_MISMATCH",
        "DOSAGE_FORM_MISMATCH",
        "UNIT_MISMATCH",
        "FDA_VALUE_UNAVAILABLE",
        "NOT_COMPARABLE",
        "REGULATORY_REVIEW_REQUIRED",
        # 4D-3 translation / governance codes.
        "UNKNOWN_ENGINE_STATUS",
        "UNKNOWN_REGISTRY_IDENTIFIER",
        "INVALID_GENERATED_AT",
        "DEPENDENCY_DEPTH_EXCEEDED",
        "CASCADE_NODE_LIMIT_EXCEEDED",
        "DEPENDENCY_CYCLE",
        # M4D3-RSN-009 -- input-resolution codes, one meaning each.
        "INPUT_RESOLUTION_FAILED",
        "TENANT_ISOLATION_VIOLATION",
        "DUPLICATE_UPSTREAM_OUTCOME",
        "SNAPSHOT_RESOLUTION_FAILED",
        "FORMULATION_COMPONENT_RESOLUTION_FAILED",
    }
)

# M4D3-RSN-010 -- scientific codes never reused for configuration, security or
# data-integrity faults.
SCIENTIFIC_REASON_CODES: frozenset[str] = frozenset(
    {
        "NOT_COMPARABLE",
        "UNIT_MISMATCH",
        "FDA_VALUE_UNAVAILABLE",
        "REGULATORY_REVIEW_REQUIRED",
        "DATA_REQUIRED",
    }
)


# ---------------------------------------------------------------------------
# M4D3-RSN-006 -- resolver detail codes (provenance metadata only)
# ---------------------------------------------------------------------------

ALLOWED_RESOLVER_DETAIL_CODES: frozenset[str] = frozenset(
    {
        "MAX_DAILY_UNITS_REQUIRED",
        "MAX_DAILY_UNITS_SOURCE_INVALID",
        "MAX_DAILY_UNITS_SOURCE_AMBIGUOUS",
        "MAX_DAILY_UNITS_SOURCE_DISAGREEMENT",
        "ROUTE_NOT_PROVIDED",
        "DOSAGE_FORM_NOT_PROVIDED",
    }
)


# ---------------------------------------------------------------------------
# M4D3-IFV-001 -- closed input-failure vocabulary.
#
# No textual cardinality is stated here; the enumeration is authoritative and
# its size is asserted once in the test suite.
# ---------------------------------------------------------------------------

ALLOWED_INPUT_FAILURE_CODES: frozenset[str] = frozenset(
    {
        "INPUT_RESPONSE_MISSING",
        "INPUT_RESPONSE_NOT_APPLICABLE",
        "INPUT_REVIEW_REQUIRED",
        "INPUT_VALUE_INVALID",
        "INPUT_VALUE_NOT_COMPARABLE",
        "INPUT_UNIT_MISSING",
        "INPUT_UNIT_UNSUPPORTED",
        "INPUT_UNIT_DIMENSION_MISMATCH",
        "INPUT_DENSITY_REQUIRED",
        "FORMULATION_COMPONENT_MISSING",
        "FORMULATION_COMPONENT_AMBIGUOUS",
        "FORMULATION_COMPONENT_TYPE_MISMATCH",
        "FORMULATION_COMPONENT_WRONG_FORMULATION",
        "FORMULATION_COMPONENT_TENANT_MISMATCH",
        "FORMULATION_COMPONENT_REFERENCE_INVALID",
        "FORMULATION_FIELD_MISSING",
        "ASSESSMENT_SNAPSHOT_MISSING",
        "ASSESSMENT_SNAPSHOT_DUPLICATE",
        "ASSESSMENT_SNAPSHOT_TENANT_MISMATCH",
        "ASSESSMENT_SNAPSHOT_COMPONENT_MISMATCH",
        "ASSESSMENT_SNAPSHOT_RELEASE_MISMATCH",
        "ASSESSMENT_FIELD_MISSING",
        "UPSTREAM_CALCULATION_MISSING",
        "UPSTREAM_CALCULATION_INCOMPLETE",
        "UPSTREAM_CALCULATION_DUPLICATE",
        "UPSTREAM_CALCULATION_COMPONENT_MISMATCH",
        "INPUT_TENANT_MISMATCH",
        "INPUT_RESOLVER_UNKNOWN",
        "UNKNOWN_INTERNAL_FAILURE",
    }
)


# ---------------------------------------------------------------------------
# Value rules (M4D3-OUT-008)
# ---------------------------------------------------------------------------

VALUE_RULE_NULL = "null"
VALUE_RULE_ENGINE_VALUE = "engine_value"

VALUE_RULES: frozenset[str] = frozenset({VALUE_RULE_NULL, VALUE_RULE_ENGINE_VALUE})


@dataclass(frozen=True, slots=True)
class OutcomeMapping:
    """One deterministic (status, reason_code, value rule) triple."""

    status: str
    reason_code: str
    value_rule: str


# ---------------------------------------------------------------------------
# M4D3-IFV-003 -- complete one-to-one input-failure mapping.
#
# Every code maps to exactly one status, one canonical reason_code and one
# value rule.  There is no conditional, callable or implementer-choice entry.
# ---------------------------------------------------------------------------

_MISSING_DATA = OutcomeMapping(STATUS_DATA_REQUIRED, "DATA_REQUIRED", VALUE_RULE_NULL)

INPUT_FAILURE_MAPPING: MappingProxyType[str, OutcomeMapping] = MappingProxyType(
    {
        # -- Missing required data -> data_required / DATA_REQUIRED ----------
        "INPUT_RESPONSE_MISSING": _MISSING_DATA,
        "INPUT_RESPONSE_NOT_APPLICABLE": _MISSING_DATA,
        "FORMULATION_COMPONENT_MISSING": _MISSING_DATA,
        "FORMULATION_FIELD_MISSING": _MISSING_DATA,
        "ASSESSMENT_SNAPSHOT_MISSING": _MISSING_DATA,
        "ASSESSMENT_FIELD_MISSING": _MISSING_DATA,
        "UPSTREAM_CALCULATION_MISSING": _MISSING_DATA,
        "UPSTREAM_CALCULATION_INCOMPLETE": _MISSING_DATA,
        "INPUT_UNIT_MISSING": _MISSING_DATA,
        # -- Regulatory review ------------------------------------------------
        "INPUT_REVIEW_REQUIRED": OutcomeMapping(
            STATUS_ERROR, "REGULATORY_REVIEW_REQUIRED", VALUE_RULE_NULL
        ),
        # -- Malformed input / configuration faults ---------------------------
        # M4D3-IFV-004: malformed input is NOT scientific non-comparability.
        "INPUT_VALUE_INVALID": OutcomeMapping(
            STATUS_ERROR, "INPUT_RESOLUTION_FAILED", VALUE_RULE_NULL
        ),
        "INPUT_RESOLVER_UNKNOWN": OutcomeMapping(
            STATUS_ERROR, "INPUT_RESOLUTION_FAILED", VALUE_RULE_NULL
        ),
        "UNKNOWN_INTERNAL_FAILURE": OutcomeMapping(
            STATUS_ERROR, "INPUT_RESOLUTION_FAILED", VALUE_RULE_NULL
        ),
        "UPSTREAM_CALCULATION_COMPONENT_MISMATCH": OutcomeMapping(
            STATUS_ERROR, "INPUT_RESOLUTION_FAILED", VALUE_RULE_NULL
        ),
        # -- Genuine scientific non-comparability -----------------------------
        "INPUT_VALUE_NOT_COMPARABLE": OutcomeMapping(
            STATUS_ERROR, "NOT_COMPARABLE", VALUE_RULE_NULL
        ),
        "INPUT_DENSITY_REQUIRED": OutcomeMapping(
            STATUS_ERROR, "NOT_COMPARABLE", VALUE_RULE_NULL
        ),
        # -- Unit faults ------------------------------------------------------
        "INPUT_UNIT_UNSUPPORTED": OutcomeMapping(
            STATUS_ERROR, "UNIT_MISMATCH", VALUE_RULE_NULL
        ),
        "INPUT_UNIT_DIMENSION_MISMATCH": OutcomeMapping(
            STATUS_ERROR, "UNIT_MISMATCH", VALUE_RULE_NULL
        ),
        # -- Tenant isolation (security) --------------------------------------
        # M4D3-IFV-005: never DATA_REQUIRED, never NOT_COMPARABLE.
        "INPUT_TENANT_MISMATCH": OutcomeMapping(
            STATUS_ERROR, "TENANT_ISOLATION_VIOLATION", VALUE_RULE_NULL
        ),
        "FORMULATION_COMPONENT_TENANT_MISMATCH": OutcomeMapping(
            STATUS_ERROR, "TENANT_ISOLATION_VIOLATION", VALUE_RULE_NULL
        ),
        "ASSESSMENT_SNAPSHOT_TENANT_MISMATCH": OutcomeMapping(
            STATUS_ERROR, "TENANT_ISOLATION_VIOLATION", VALUE_RULE_NULL
        ),
        # -- Data integrity ----------------------------------------------------
        "UPSTREAM_CALCULATION_DUPLICATE": OutcomeMapping(
            STATUS_ERROR, "DUPLICATE_UPSTREAM_OUTCOME", VALUE_RULE_NULL
        ),
        # -- Snapshot resolution ----------------------------------------------
        "ASSESSMENT_SNAPSHOT_DUPLICATE": OutcomeMapping(
            STATUS_ERROR, "SNAPSHOT_RESOLUTION_FAILED", VALUE_RULE_NULL
        ),
        "ASSESSMENT_SNAPSHOT_COMPONENT_MISMATCH": OutcomeMapping(
            STATUS_ERROR, "SNAPSHOT_RESOLUTION_FAILED", VALUE_RULE_NULL
        ),
        "ASSESSMENT_SNAPSHOT_RELEASE_MISMATCH": OutcomeMapping(
            STATUS_ERROR, "SNAPSHOT_RESOLUTION_FAILED", VALUE_RULE_NULL
        ),
        # -- Component resolution ----------------------------------------------
        "FORMULATION_COMPONENT_AMBIGUOUS": OutcomeMapping(
            STATUS_ERROR, "FORMULATION_COMPONENT_RESOLUTION_FAILED", VALUE_RULE_NULL
        ),
        "FORMULATION_COMPONENT_TYPE_MISMATCH": OutcomeMapping(
            STATUS_ERROR, "FORMULATION_COMPONENT_RESOLUTION_FAILED", VALUE_RULE_NULL
        ),
        "FORMULATION_COMPONENT_WRONG_FORMULATION": OutcomeMapping(
            STATUS_ERROR, "FORMULATION_COMPONENT_RESOLUTION_FAILED", VALUE_RULE_NULL
        ),
        "FORMULATION_COMPONENT_REFERENCE_INVALID": OutcomeMapping(
            STATUS_ERROR, "FORMULATION_COMPONENT_RESOLUTION_FAILED", VALUE_RULE_NULL
        ),
    }
)


# ---------------------------------------------------------------------------
# M4D3-TRL-002 -- engine status -> stored status translation.
#
# The engine stores the RESOLVED string in CalculationResult.status, so the
# alias attribute names (UNIT_CONVERSION_FAILED, IID_VALUE_MISSING, ...) never
# need enumerating here (M4D3-TRL-003).
# ---------------------------------------------------------------------------

ENGINE_STATUS_MAPPING: MappingProxyType[str, OutcomeMapping] = MappingProxyType(
    {
        "OK": OutcomeMapping(STATUS_COMPLETE, "", VALUE_RULE_ENGINE_VALUE),
        "DATA_REQUIRED": _MISSING_DATA,
        "INGREDIENT_UNRESOLVED": OutcomeMapping(
            STATUS_ERROR, "INGREDIENT_UNRESOLVED", VALUE_RULE_NULL
        ),
        "ROUTE_MISMATCH": OutcomeMapping(STATUS_ERROR, "ROUTE_MISMATCH", VALUE_RULE_NULL),
        "DOSAGE_FORM_MISMATCH": OutcomeMapping(
            STATUS_ERROR, "DOSAGE_FORM_MISMATCH", VALUE_RULE_NULL
        ),
        "UNIT_MISMATCH": OutcomeMapping(STATUS_ERROR, "UNIT_MISMATCH", VALUE_RULE_NULL),
        "FDA_VALUE_UNAVAILABLE": OutcomeMapping(
            STATUS_ERROR, "FDA_VALUE_UNAVAILABLE", VALUE_RULE_NULL
        ),
        "NOT_COMPARABLE": OutcomeMapping(STATUS_ERROR, "NOT_COMPARABLE", VALUE_RULE_NULL),
        "REGULATORY_REVIEW_REQUIRED": OutcomeMapping(
            STATUS_ERROR, "REGULATORY_REVIEW_REQUIRED", VALUE_RULE_NULL
        ),
    }
)

# M4D3-TRL-002 -- fail-closed fallback.  Never maps to complete.
UNKNOWN_ENGINE_STATUS_MAPPING = OutcomeMapping(
    STATUS_ERROR, "UNKNOWN_ENGINE_STATUS", VALUE_RULE_NULL
)

# M4D3-TRL-005 -- malformed / naive generated_at.
INVALID_GENERATED_AT_MAPPING = OutcomeMapping(
    STATUS_ERROR, "INVALID_GENERATED_AT", VALUE_RULE_NULL
)


@dataclass(frozen=True, slots=True)
class TranslatedOutcome:
    """Result of translating an engine CalculationResult into stored values."""

    status: str
    reason_code: str
    value: object | None
    generated_at: datetime | None


def parse_generated_at(raw: str) -> datetime | None:
    """M4D3-TRL-004/005.

    Return a timezone-aware ``datetime`` for a valid ISO-8601 string carrying a
    UTC offset or ``Z`` suffix.  Return ``None`` for empty, malformed or
    timezone-naive input -- the caller then fails closed.
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    if text.endswith(("z", "Z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        # Naive datetimes are rejected -- never silently assumed to be UTC.
        return None
    return parsed


def translate_engine_status(engine_result: CalculationResult) -> TranslatedOutcome:
    """M4D3-TRL-001..006 -- pure engine-to-stored translation.

    Returns the stored status, canonical reason code, value and parsed
    ``generated_at``.  Never returns an engine-layer string as the stored
    status and never defaults to ``complete``.
    """
    mapping = ENGINE_STATUS_MAPPING.get(
        getattr(engine_result, "status", None), UNKNOWN_ENGINE_STATUS_MAPPING
    )

    generated_at = parse_generated_at(getattr(engine_result, "generated_at", "") or "")
    if generated_at is None:
        # M4D3-TRL-005 -- timestamp failure outranks the engine result.
        return TranslatedOutcome(
            status=INVALID_GENERATED_AT_MAPPING.status,
            reason_code=INVALID_GENERATED_AT_MAPPING.reason_code,
            value=None,
            generated_at=None,
        )

    value = (
        engine_result.value
        if mapping.value_rule == VALUE_RULE_ENGINE_VALUE
        else None
    )
    return TranslatedOutcome(
        status=mapping.status,
        reason_code=mapping.reason_code,
        value=value,
        generated_at=generated_at,
    )


def translate_input_failure(detail_code: str) -> OutcomeMapping:
    """M4D3-IFV-003/008 -- deterministic resolver-failure translation.

    An unrecognised detail code is treated as ``UNKNOWN_INTERNAL_FAILURE`` and
    can never yield ``complete``.
    """
    return INPUT_FAILURE_MAPPING.get(
        detail_code, INPUT_FAILURE_MAPPING["UNKNOWN_INTERNAL_FAILURE"]
    )


# ---------------------------------------------------------------------------
# Import-time self-validation (M4D3-REG-009 pattern applied to vocabularies).
# A violation raises at import so a bad deployment fails fast rather than
# producing invalid regulated outcomes.
# ---------------------------------------------------------------------------


class VocabularyConfigurationError(RuntimeError):
    """Raised when a closed vocabulary or mapping is internally inconsistent."""


def _validate_vocabularies() -> None:
    code_pattern_ok = lambda c: (  # noqa: E731 - local predicate, not exported
        isinstance(c, str) and c and c == c.upper() and c.replace("_", "").isalnum()
    )

    for name, vocab in (
        ("ALLOWED_REASON_CODES", ALLOWED_REASON_CODES),
        ("ALLOWED_RESOLVER_DETAIL_CODES", ALLOWED_RESOLVER_DETAIL_CODES),
        ("ALLOWED_INPUT_FAILURE_CODES", ALLOWED_INPUT_FAILURE_CODES),
    ):
        for code in vocab:
            if not code_pattern_ok(code):
                raise VocabularyConfigurationError(
                    f"{name} contains a non-canonical code: {code!r}"
                )
            if len(code) > 100:
                raise VocabularyConfigurationError(
                    f"{name} code exceeds reason_code max_length=100: {code!r}"
                )

    # M4D3-RSN-007 -- detail codes never double as canonical reason codes.
    overlap = ALLOWED_REASON_CODES & ALLOWED_RESOLVER_DETAIL_CODES
    if overlap:
        raise VocabularyConfigurationError(
            f"reason/resolver-detail vocabularies overlap: {sorted(overlap)}"
        )

    # Every input-failure code must map, and every mapping must be in vocabulary.
    unmapped = ALLOWED_INPUT_FAILURE_CODES - set(INPUT_FAILURE_MAPPING)
    if unmapped:
        raise VocabularyConfigurationError(
            f"input-failure codes without a mapping: {sorted(unmapped)}"
        )
    unknown = set(INPUT_FAILURE_MAPPING) - ALLOWED_INPUT_FAILURE_CODES
    if unknown:
        raise VocabularyConfigurationError(
            f"mapping rows outside the closed vocabulary: {sorted(unknown)}"
        )

    for source, label in (
        (INPUT_FAILURE_MAPPING, "INPUT_FAILURE_MAPPING"),
        (ENGINE_STATUS_MAPPING, "ENGINE_STATUS_MAPPING"),
    ):
        for code, mapping in source.items():
            if not isinstance(mapping, OutcomeMapping):
                raise VocabularyConfigurationError(
                    f"{label}[{code}] is not a static OutcomeMapping"
                )
            if mapping.status not in STATUSES_WRITABLE_BY_4D3:
                raise VocabularyConfigurationError(
                    f"{label}[{code}] uses status {mapping.status!r}"
                )
            if mapping.value_rule not in VALUE_RULES:
                raise VocabularyConfigurationError(
                    f"{label}[{code}] has invalid value rule {mapping.value_rule!r}"
                )
            if mapping.reason_code and mapping.reason_code not in ALLOWED_REASON_CODES:
                raise VocabularyConfigurationError(
                    f"{label}[{code}] uses unknown reason code {mapping.reason_code!r}"
                )
            # Only a complete outcome may carry a value; everything else is null.
            if mapping.value_rule == VALUE_RULE_ENGINE_VALUE and (
                mapping.status != STATUS_COMPLETE
            ):
                raise VocabularyConfigurationError(
                    f"{label}[{code}] carries a value without status=complete"
                )
            if mapping.status == STATUS_COMPLETE and mapping.reason_code:
                raise VocabularyConfigurationError(
                    f"{label}[{code}] is complete but carries a reason code"
                )

    # M4D3-IFV-005 -- category guards that must never regress.
    for code in (
        "INPUT_TENANT_MISMATCH",
        "FORMULATION_COMPONENT_TENANT_MISMATCH",
        "ASSESSMENT_SNAPSHOT_TENANT_MISMATCH",
    ):
        if INPUT_FAILURE_MAPPING[code].reason_code != "TENANT_ISOLATION_VIOLATION":
            raise VocabularyConfigurationError(
                f"{code} must map to TENANT_ISOLATION_VIOLATION"
            )
    if INPUT_FAILURE_MAPPING["UPSTREAM_CALCULATION_DUPLICATE"].reason_code != (
        "DUPLICATE_UPSTREAM_OUTCOME"
    ):
        raise VocabularyConfigurationError(
            "UPSTREAM_CALCULATION_DUPLICATE must map to DUPLICATE_UPSTREAM_OUTCOME"
        )


def validate_against_enums() -> None:
    """Cross-check the mirrored status strings against the real Django enum.

    Kept separate from import-time validation because it needs Django settings
    configured.  It still performs no database access.
    """
    from .enums import CalculationStatus  # local import -- needs django.setup()

    actual = {choice.value for choice in CalculationStatus}
    if actual != STORED_STATUSES:
        raise VocabularyConfigurationError(
            f"stored status mirror {sorted(STORED_STATUSES)} does not match "
            f"CalculationStatus {sorted(actual)}"
        )


_validate_vocabularies()
