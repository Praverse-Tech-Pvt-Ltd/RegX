"""Milestone 4D-3 -- calculation binding registry and resolver declarations.

Database-free by construction.  This module defines *what* each approved
calculation needs and validates those declarations at import time.  It never
touches the ORM: resolving declarations into real values is the job of the
deferred ``resolve_calculation_inputs()`` service.

Approved specification: docs/MILESTONE_4D_3_IMPLEMENTATION_SPEC.md
  - M4D3-REG-001..020  registry contract and import-time self-check
  - M4D3-INP-001..009  the six allow-listed resolver forms
  - M4D3-MAP-001..010  complete kwarg mapping for all six calculations
  - M4D3-UNC-003/006   canonical unit vocabulary and per-kwarg target units
  - M4D3-FCR-002..014  subject-component selector; form B disabled
  - M4D3-TRG-001..007  calculation_dependencies vs recalculation_triggers
  - M4D3-DAG-001       calculation graph limits
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from iid_assessment import calculations as engine
from iid_assessment.unit_conversion import DIMENSION_OF_UNIT

# ---------------------------------------------------------------------------
# M4D3-DAG-001 -- calculation graph limits.
#
# Named to avoid collision with applicability.MAX_RECURSION_DEPTH, which bounds
# condition-tree nesting and is unrelated (M4D3-DAG-001).
# ---------------------------------------------------------------------------

CALCULATION_MAX_DEPENDENCY_DEPTH = 5
CALCULATION_MAX_CASCADE_NODES = 10


class RegistryConfigurationError(RuntimeError):
    """Raised when a registry entry or resolver declaration is invalid."""


# ---------------------------------------------------------------------------
# Resolver forms (M4D3-INP-003..008)
# ---------------------------------------------------------------------------

SOURCE_QUESTION_RESPONSE = "question_response"
SOURCE_FORMULATION_FIELD = "formulation_field"
SOURCE_MAXIMUM_DAILY_UNITS = "maximum_daily_units"
SOURCE_ASSESSMENT_SNAPSHOT = "assessment_snapshot"
SOURCE_CALCULATION_OUTCOME = "calculation_outcome"
SOURCE_CONSTANT = "constant"

ALLOWED_RESOLVER_SOURCES: frozenset[str] = frozenset(
    {
        SOURCE_QUESTION_RESPONSE,
        SOURCE_FORMULATION_FIELD,
        SOURCE_MAXIMUM_DAILY_UNITS,
        SOURCE_ASSESSMENT_SNAPSHOT,
        SOURCE_CALCULATION_OUTCOME,
        SOURCE_CONSTANT,
    }
)

# Exact permitted keys per form.  Anything else is rejected (M4D3-INP-003..008).
#
# The dict literal is wrapped immediately, so no mutable alias is ever bound:
# the outer mapping is read-only and each key set is already a frozenset, so no
# caller can add a resolver form or widen an existing one.
_RESOLVER_KEYS: MappingProxyType[str, tuple[frozenset[str], frozenset[str]]] = MappingProxyType(
    {
        # source: (required keys, optional keys)
        SOURCE_QUESTION_RESPONSE: (
            frozenset({"source", "question_code", "value_field", "expected_type"}),
            frozenset({"required_unit", "unit_source"}),
        ),
        SOURCE_FORMULATION_FIELD: (
            frozenset({"source", "object", "field", "expected_type"}),
            frozenset(
                {"unit_field", "required_unit", "component_selector", "required_component_type"}
            ),
        ),
        SOURCE_MAXIMUM_DAILY_UNITS: (
            frozenset({"source", "resolver_version", "expected_type"}),
            frozenset(),
        ),
        SOURCE_ASSESSMENT_SNAPSHOT: (
            frozenset({"source", "field", "expected_type"}),
            frozenset({"unit_field", "required_unit"}),
        ),
        SOURCE_CALCULATION_OUTCOME: (
            frozenset({"source", "question_code", "field", "required_status", "expected_type"}),
            frozenset({"required_unit", "unit_source"}),
        ),
        SOURCE_CONSTANT: (
            frozenset({"source", "value", "type", "binding_version"}),
            frozenset(),
        ),
    }
)

FORMULATION_OBJECTS: frozenset[str] = frozenset({"formulation_version", "formulation_component"})

# M4D3-INP-006 -- the only snapshot fields a resolver may read.  These are the
# actual AssessmentSnapshot field names; ``selected_iid_*`` are kwargs, not
# model fields (M4D3-INP-015).
SNAPSHOT_VALUE_FIELDS: frozenset[str] = frozenset({"iid_potency_amount", "iid_mde"})
SNAPSHOT_UNIT_FIELDS: frozenset[str] = frozenset({"iid_potency_unit", "iid_mde_unit"})
SNAPSHOT_CONTEXT_FIELDS: frozenset[str] = frozenset(
    {"public_id", "tenant", "formulation_component_public_id", "iid_release_public_id"}
)

EXPECTED_TYPES: frozenset[str] = frozenset({"decimal", "string", "uuid"})

# M4D3-FCR-002..004 -- subject-component selector forms.
SELECTOR_RESPONSE_REFERENCE = "response_reference"
SELECTOR_REGISTRY_COMPONENT_CODE = "registry_component_code"

#: M4D3-FCR-004/012 -- form B is DISABLED for 4D-3.  ``FormulationComponent``
#: has no immutable unique component-code field, so activation rejects it.
DISABLED_SELECTOR_TYPES: frozenset[str] = frozenset({SELECTOR_REGISTRY_COMPONENT_CODE})
ENABLED_SELECTOR_TYPES: frozenset[str] = frozenset({SELECTOR_RESPONSE_REFERENCE})

COMPONENT_TYPE_ACTIVE = "active"
COMPONENT_TYPE_INACTIVE = "inactive"
COMPONENT_TYPES: frozenset[str] = frozenset({COMPONENT_TYPE_ACTIVE, COMPONENT_TYPE_INACTIVE})


@dataclass(frozen=True, slots=True)
class SnapshotUnitRef:
    """Convert into the unit named by an AssessmentSnapshot field.

    Used where the target unit is not a literal but the IID reference unit, so
    each comparison is made between like quantities (M4D3-UNC-006).
    """

    unit_field: str


# ---------------------------------------------------------------------------
# Governed question codes referenced by resolver declarations.
#
# These are structural binding points, not regulatory checklist content (which
# remains out of scope, SCOPE-OUT / X-06).  Activation validates that each code
# exists in the ChecklistVersion being activated (M4D3-REG-018).
# ---------------------------------------------------------------------------

Q_SUBJECT_COMPONENT = "Q_SUBJECT_COMPONENT"
Q_DAILY_EXPOSURE = "Q_DAILY_EXPOSURE"


def _component_selector() -> MappingProxyType[str, Any]:
    """The single enabled subject-component selector (M4D3-FCR-003/013)."""
    return MappingProxyType(
        {"type": SELECTOR_RESPONSE_REFERENCE, "question_code": Q_SUBJECT_COMPONENT}
    )


def _component_quantity_resolver(required_unit: Any) -> MappingProxyType[str, Any]:
    """Form B resolver for FormulationComponent.quantity_per_dosage_unit."""
    return MappingProxyType(
        {
            "source": SOURCE_FORMULATION_FIELD,
            "object": "formulation_component",
            "field": "quantity_per_dosage_unit",
            "unit_field": "quantity_unit",
            "required_unit": required_unit,
            "expected_type": "decimal",
            "component_selector": _component_selector(),
            "required_component_type": COMPONENT_TYPE_INACTIVE,
        }
    )


def _snapshot_resolver(value_field: str, unit_field: str) -> MappingProxyType[str, Any]:
    """Form D resolver reading a persisted governed IID value."""
    return MappingProxyType(
        {
            "source": SOURCE_ASSESSMENT_SNAPSHOT,
            "field": value_field,
            "unit_field": unit_field,
            "expected_type": "decimal",
        }
    )


@dataclass(frozen=True, slots=True)
class RegistryEntry:
    """One immutable calculation binding.

    The registry *mapping key* is the identifier; it is deliberately absent
    from this structure so the two can never disagree (M4D3-REG-005/020).
    """

    calculation_name: str
    function: Callable[..., engine.CalculationResult]
    formula_version: str
    binding_version: str
    input_resolvers: MappingProxyType[str, Any]
    calculation_dependencies: tuple[str, ...]
    recalculation_triggers: tuple[str, ...]
    required_units: MappingProxyType[str, Any]
    output_unit: str
    rounding_rule: str
    allowed_answer_type: str
    allowed_data_source: str = "system_calculated"
    validation_rules: tuple[str, ...] = field(default_factory=tuple)


_ROUNDING_UNROUNDED = "none (Decimal, unrounded)"
_ANSWER_TYPE_CALCULATED_VALUE = "calculated_value"


# ---------------------------------------------------------------------------
# M4D3-REG-007 / M4D3-MAP-001..006 -- the six approved bindings.
# ---------------------------------------------------------------------------

CALCULATION_BINDING_REGISTRY: MappingProxyType[str, RegistryEntry] = MappingProxyType(
    {
        # -- A: excipient % w/w (M4D3-MAP-001) ------------------------------
        "percentage_w_w": RegistryEntry(
            calculation_name="calculate_percentage_w_w",
            function=engine.calculate_percentage_w_w,
            formula_version=engine.FORMULA_VERSION,
            binding_version="1.0.0",
            input_resolvers=MappingProxyType(
                {
                    "quantity_per_unit_grams": _component_quantity_resolver("gram"),
                    "total_dosage_unit_weight_grams": MappingProxyType(
                        {
                            "source": SOURCE_FORMULATION_FIELD,
                            "object": "formulation_version",
                            "field": "total_dosage_unit_weight",
                            "unit_field": "total_dosage_unit_weight_unit",
                            "required_unit": "gram",
                            "expected_type": "decimal",
                        }
                    ),
                }
            ),
            calculation_dependencies=(),
            recalculation_triggers=(Q_SUBJECT_COMPONENT,),
            required_units=MappingProxyType(
                {
                    "quantity_per_unit_grams": "gram",
                    "total_dosage_unit_weight_grams": "gram",
                }
            ),
            output_unit="percent_w_w",
            rounding_rule=_ROUNDING_UNROUNDED,
            allowed_answer_type=_ANSWER_TYPE_CALCULATED_VALUE,
            validation_rules=("total_dosage_unit_weight must be non-zero",),
        ),
        # -- B: proposed maximum daily exposure (M4D3-MAP-002) --------------
        "daily_exposure": RegistryEntry(
            calculation_name="calculate_daily_exposure",
            function=engine.calculate_daily_exposure,
            formula_version=engine.FORMULA_VERSION,
            binding_version="1.0.0",
            input_resolvers=MappingProxyType(
                {
                    "quantity_per_dosage_unit": _component_quantity_resolver("gram"),
                    "maximum_dosage_units_per_day": MappingProxyType(
                        {
                            "source": SOURCE_MAXIMUM_DAILY_UNITS,
                            "resolver_version": "1.0",
                            "expected_type": "decimal",
                        }
                    ),
                }
            ),
            calculation_dependencies=(),
            recalculation_triggers=(Q_SUBJECT_COMPONENT,),
            required_units=MappingProxyType({"quantity_per_dosage_unit": "gram"}),
            # M4D3-MAP-007 -- the engine sets no unit; the service records
            # gram-per-day so form E has an explicit source unit.
            output_unit="gram",
            rounding_rule=_ROUNDING_UNROUNDED,
            allowed_answer_type=_ANSWER_TYPE_CALCULATED_VALUE,
        ),
        # -- C: % of selected IID potency (M4D3-MAP-003) --------------------
        "percentage_of_iid_potency": RegistryEntry(
            calculation_name="calculate_percentage_of_potency",
            function=engine.calculate_percentage_of_potency,
            formula_version=engine.FORMULA_VERSION,
            binding_version="1.0.0",
            input_resolvers=MappingProxyType(
                {
                    "converted_proposed_quantity": _component_quantity_resolver(
                        SnapshotUnitRef("iid_potency_unit")
                    ),
                    "selected_iid_potency_amount": _snapshot_resolver(
                        "iid_potency_amount", "iid_potency_unit"
                    ),
                }
            ),
            calculation_dependencies=(),
            recalculation_triggers=(Q_SUBJECT_COMPONENT,),
            required_units=MappingProxyType(
                {"converted_proposed_quantity": SnapshotUnitRef("iid_potency_unit")}
            ),
            output_unit="percent_of_potency",
            rounding_rule=_ROUNDING_UNROUNDED,
            allowed_answer_type=_ANSWER_TYPE_CALCULATED_VALUE,
        ),
        # -- D: difference from IID potency (M4D3-MAP-004) ------------------
        "difference_from_iid_potency": RegistryEntry(
            calculation_name="calculate_difference_from_potency",
            function=engine.calculate_difference_from_potency,
            formula_version=engine.FORMULA_VERSION,
            binding_version="1.0.0",
            input_resolvers=MappingProxyType(
                {
                    "selected_iid_potency_amount": _snapshot_resolver(
                        "iid_potency_amount", "iid_potency_unit"
                    ),
                    "converted_proposed_quantity": _component_quantity_resolver(
                        SnapshotUnitRef("iid_potency_unit")
                    ),
                }
            ),
            calculation_dependencies=(),
            recalculation_triggers=(Q_SUBJECT_COMPONENT,),
            required_units=MappingProxyType(
                {"converted_proposed_quantity": SnapshotUnitRef("iid_potency_unit")}
            ),
            output_unit="",
            rounding_rule=_ROUNDING_UNROUNDED,
            allowed_answer_type=_ANSWER_TYPE_CALCULATED_VALUE,
        ),
        # -- E: % of selected IID MDE (M4D3-MAP-005) ------------------------
        "percentage_of_iid_mde": RegistryEntry(
            calculation_name="calculate_percentage_of_mde",
            function=engine.calculate_percentage_of_mde,
            formula_version=engine.FORMULA_VERSION,
            binding_version="1.0.0",
            input_resolvers=MappingProxyType(
                {
                    "converted_proposed_daily_exposure": MappingProxyType(
                        {
                            "source": SOURCE_CALCULATION_OUTCOME,
                            "question_code": Q_DAILY_EXPOSURE,
                            "field": "value",
                            "required_status": "complete",
                            "required_unit": SnapshotUnitRef("iid_mde_unit"),
                            "unit_source": "gram",
                            "expected_type": "decimal",
                        }
                    ),
                    "selected_iid_mde": _snapshot_resolver("iid_mde", "iid_mde_unit"),
                }
            ),
            # M4D3-MAP-010 -- the MDE calculations take no direct component
            # input; their subject component is inherited from the upstream
            # daily-exposure response, which is their only trigger.
            calculation_dependencies=(Q_DAILY_EXPOSURE,),
            recalculation_triggers=(Q_DAILY_EXPOSURE,),
            required_units=MappingProxyType(
                {"converted_proposed_daily_exposure": SnapshotUnitRef("iid_mde_unit")}
            ),
            output_unit="percent_of_mde",
            rounding_rule=_ROUNDING_UNROUNDED,
            allowed_answer_type=_ANSWER_TYPE_CALCULATED_VALUE,
        ),
        # -- F: difference from IID MDE (M4D3-MAP-006) ----------------------
        "difference_from_iid_mde": RegistryEntry(
            calculation_name="calculate_difference_from_mde",
            function=engine.calculate_difference_from_mde,
            formula_version=engine.FORMULA_VERSION,
            binding_version="1.0.0",
            input_resolvers=MappingProxyType(
                {
                    "selected_iid_mde": _snapshot_resolver("iid_mde", "iid_mde_unit"),
                    "converted_proposed_daily_exposure": MappingProxyType(
                        {
                            "source": SOURCE_CALCULATION_OUTCOME,
                            "question_code": Q_DAILY_EXPOSURE,
                            "field": "value",
                            "required_status": "complete",
                            "required_unit": SnapshotUnitRef("iid_mde_unit"),
                            "unit_source": "gram",
                            "expected_type": "decimal",
                        }
                    ),
                }
            ),
            # M4D3-MAP-010 -- the MDE calculations take no direct component
            # input; their subject component is inherited from the upstream
            # daily-exposure response, which is their only trigger.
            calculation_dependencies=(Q_DAILY_EXPOSURE,),
            recalculation_triggers=(Q_DAILY_EXPOSURE,),
            required_units=MappingProxyType(
                {"converted_proposed_daily_exposure": SnapshotUnitRef("iid_mde_unit")}
            ),
            output_unit="",
            rounding_rule=_ROUNDING_UNROUNDED,
            allowed_answer_type=_ANSWER_TYPE_CALCULATED_VALUE,
        ),
    }
)


# ---------------------------------------------------------------------------
# Resolver declaration validation (M4D3-INP-003..009)
# ---------------------------------------------------------------------------


def _validate_unit(where: str, value: Any) -> None:
    """A unit is either a canonical literal or a snapshot unit reference."""
    if isinstance(value, SnapshotUnitRef):
        if value.unit_field not in SNAPSHOT_UNIT_FIELDS:
            raise RegistryConfigurationError(
                f"{where}: unknown snapshot unit field {value.unit_field!r}"
            )
        return
    if not isinstance(value, str) or not value:
        raise RegistryConfigurationError(f"{where}: unit must be a non-empty string")
    # M4D3-UNC-003 -- canonical full-word units only; no shorthand.
    if value not in DIMENSION_OF_UNIT:
        raise RegistryConfigurationError(
            f"{where}: {value!r} is not a canonical unit (expected e.g. 'gram', not 'g')"
        )


def _validate_component_selector(where: str, selector: Any) -> None:
    """M4D3-FCR-002..004/012 -- component selector declaration."""
    if not isinstance(selector, dict | MappingProxyType):
        raise RegistryConfigurationError(f"{where}: component_selector must be a mapping")
    sel_type = selector.get("type")
    if sel_type in DISABLED_SELECTOR_TYPES:
        raise RegistryConfigurationError(
            f"{where}: component_selector_form_disabled -- {sel_type!r} is not "
            "enabled in 4D-3; use response_reference"
        )
    if sel_type not in ENABLED_SELECTOR_TYPES:
        raise RegistryConfigurationError(f"{where}: unknown component selector type {sel_type!r}")
    expected = {"type", "question_code"}
    if set(selector) != expected:
        raise RegistryConfigurationError(
            f"{where}: component_selector keys {sorted(set(selector))} != {sorted(expected)}"
        )
    if not isinstance(selector["question_code"], str) or not selector["question_code"]:
        raise RegistryConfigurationError(f"{where}: selector question_code must be set")


def validate_resolver_declaration(kwarg: str, decl: Any) -> None:
    """Validate one resolver declaration.  Pure -- no ORM access.

    Raises :class:`RegistryConfigurationError` describing the exact violation.
    """
    where = f"resolver[{kwarg}]"
    if not isinstance(decl, dict | MappingProxyType):
        raise RegistryConfigurationError(f"{where}: declaration must be a mapping")

    source = decl.get("source")
    if source not in ALLOWED_RESOLVER_SOURCES:
        raise RegistryConfigurationError(f"{where}: unknown resolver source {source!r}")

    required, optional = _RESOLVER_KEYS[source]
    keys = set(decl)
    missing = required - keys
    if missing:
        raise RegistryConfigurationError(f"{where}: missing keys {sorted(missing)}")
    extra = keys - required - optional
    if extra:
        raise RegistryConfigurationError(f"{where}: forbidden keys {sorted(extra)}")

    if source != SOURCE_CONSTANT and decl.get("expected_type") not in EXPECTED_TYPES:
        raise RegistryConfigurationError(
            f"{where}: expected_type must be one of {sorted(EXPECTED_TYPES)}"
        )

    for unit_key in ("required_unit", "unit_source"):
        if unit_key in keys and decl[unit_key] is not None:
            _validate_unit(f"{where}.{unit_key}", decl[unit_key])

    if source == SOURCE_QUESTION_RESPONSE:
        if decl["value_field"] != "raw_value":
            raise RegistryConfigurationError(
                f"{where}: question_response may only read 'raw_value'"
            )
        if not isinstance(decl["question_code"], str) or not decl["question_code"]:
            raise RegistryConfigurationError(f"{where}: question_code must be set")

    elif source == SOURCE_FORMULATION_FIELD:
        if decl["object"] not in FORMULATION_OBJECTS:
            raise RegistryConfigurationError(
                f"{where}: object must be one of {sorted(FORMULATION_OBJECTS)}"
            )
        if decl["object"] == "formulation_component":
            if "component_selector" not in keys:
                raise RegistryConfigurationError(
                    f"{where}: component_selector is mandatory for object='formulation_component'"
                )
            _validate_component_selector(where, decl["component_selector"])
            if decl.get("required_component_type") not in COMPONENT_TYPES:
                raise RegistryConfigurationError(
                    f"{where}: required_component_type must be one of {sorted(COMPONENT_TYPES)}"
                )
        elif "component_selector" in keys:
            raise RegistryConfigurationError(
                f"{where}: component_selector is only valid for a component object"
            )
        if not isinstance(decl["field"], str) or not decl["field"]:
            raise RegistryConfigurationError(f"{where}: field must be set")

    elif source == SOURCE_ASSESSMENT_SNAPSHOT:
        if decl["field"] not in SNAPSHOT_VALUE_FIELDS | SNAPSHOT_CONTEXT_FIELDS:
            raise RegistryConfigurationError(
                f"{where}: {decl['field']!r} is not a permitted snapshot field"
            )
        if "unit_field" in keys and decl["unit_field"] not in SNAPSHOT_UNIT_FIELDS:
            raise RegistryConfigurationError(
                f"{where}: {decl['unit_field']!r} is not a snapshot unit field"
            )

    elif source == SOURCE_CALCULATION_OUTCOME:
        if decl["field"] != "value":
            raise RegistryConfigurationError(f"{where}: calculation_outcome may only read 'value'")
        if decl["required_status"] != "complete":
            raise RegistryConfigurationError(f"{where}: required_status must be 'complete'")
        if not isinstance(decl["question_code"], str) or not decl["question_code"]:
            raise RegistryConfigurationError(f"{where}: question_code must be set")

    elif source == SOURCE_CONSTANT:
        if decl["type"] not in {"decimal", "string"}:
            raise RegistryConfigurationError(f"{where}: constant type is invalid")
        if isinstance(decl["value"], list | dict | set):
            raise RegistryConfigurationError(f"{where}: constant must be immutable")

    # M4D3-INP-011 / M4D3-SEC-001 -- no dynamic code anywhere in a declaration.
    for key, value in decl.items():
        if callable(value):
            raise RegistryConfigurationError(
                f"{where}.{key}: callables are not permitted in declarations"
            )
        if isinstance(value, str) and any(
            token in value for token in ("eval(", "exec(", "import ", "__", "SELECT ", ";")
        ):
            raise RegistryConfigurationError(
                f"{where}.{key}: declaration contains prohibited content"
            )


# ---------------------------------------------------------------------------
# Registry import-time self-check (M4D3-REG-009/020, M4D3-TRG-006)
# ---------------------------------------------------------------------------

_APPROVED_CALCULATION_NAMES: frozenset[str] = frozenset(
    {
        "calculate_percentage_w_w",
        "calculate_daily_exposure",
        "calculate_percentage_of_potency",
        "calculate_difference_from_potency",
        "calculate_percentage_of_mde",
        "calculate_difference_from_mde",
    }
)

_VERSION_PARTS = 3


def _validate_version(where: str, value: str) -> None:
    parts = value.split(".")
    if len(parts) != _VERSION_PARTS or not all(p.isdigit() for p in parts):
        raise RegistryConfigurationError(f"{where}: malformed version {value!r}")


def _validate_registry() -> None:
    seen_names: set[str] = set()

    for identifier, entry in CALCULATION_BINDING_REGISTRY.items():
        where = f"registry[{identifier}]"

        if not isinstance(identifier, str) or not identifier:
            raise RegistryConfigurationError("registry key must be a non-empty string")
        if identifier != identifier.lower() or not identifier.replace("_", "").isalnum():
            raise RegistryConfigurationError(f"{where}: identifier must be a lowercase ASCII slug")
        if len(identifier) > 100:
            raise RegistryConfigurationError(
                f"{where}: identifier exceeds CharField(max_length=100)"
            )
        if not isinstance(entry, RegistryEntry):
            raise RegistryConfigurationError(f"{where}: entry must be a RegistryEntry")

        # M4D3-REG-009 -- calculation_name must be an approved function name and
        # must actually match the bound function.
        if entry.calculation_name not in _APPROVED_CALCULATION_NAMES:
            raise RegistryConfigurationError(
                f"{where}: unknown calculation_name {entry.calculation_name!r}"
            )
        if entry.function.__name__ != entry.calculation_name:
            raise RegistryConfigurationError(
                f"{where}: function {entry.function.__name__!r} does not match "
                f"calculation_name {entry.calculation_name!r}"
            )
        if entry.calculation_name in seen_names:
            raise RegistryConfigurationError(
                f"{where}: duplicate calculation_name {entry.calculation_name!r}"
            )
        seen_names.add(entry.calculation_name)

        if entry.formula_version != engine.FORMULA_VERSION:
            raise RegistryConfigurationError(
                f"{where}: formula_version {entry.formula_version!r} != engine "
                f"{engine.FORMULA_VERSION!r}"
            )
        _validate_version(f"{where}.binding_version", entry.binding_version)

        if entry.allowed_data_source != "system_calculated":
            raise RegistryConfigurationError(
                f"{where}: allowed_data_source must be 'system_calculated'"
            )
        if entry.allowed_answer_type != _ANSWER_TYPE_CALCULATED_VALUE:
            raise RegistryConfigurationError(
                f"{where}: unsupported answer type {entry.allowed_answer_type!r}"
            )

        # M4D3-INP-002 -- every kwarg of the bound function must have a resolver.
        import inspect

        signature = inspect.signature(entry.function)
        expected_kwargs = set(signature.parameters)
        declared = set(entry.input_resolvers)
        if declared != expected_kwargs:
            raise RegistryConfigurationError(
                f"{where}: resolvers {sorted(declared)} do not cover function "
                f"kwargs {sorted(expected_kwargs)}"
            )

        for kwarg, decl in entry.input_resolvers.items():
            validate_resolver_declaration(kwarg, decl)

        # M4D3-TRG-006 -- both sets must match the resolver declarations.
        form_e = tuple(
            decl["question_code"]
            for decl in entry.input_resolvers.values()
            if decl.get("source") == SOURCE_CALCULATION_OUTCOME
        )
        if tuple(sorted(entry.calculation_dependencies)) != tuple(sorted(form_e)):
            raise RegistryConfigurationError(
                f"{where}: calculation_dependencies {entry.calculation_dependencies} "
                f"do not match form E resolvers {form_e}"
            )

        expected_triggers: set[str] = set(form_e)
        for decl in entry.input_resolvers.values():
            if decl.get("source") == SOURCE_QUESTION_RESPONSE:
                expected_triggers.add(decl["question_code"])
            selector = decl.get("component_selector")
            if selector is not None:
                expected_triggers.add(selector["question_code"])
        if set(entry.recalculation_triggers) != expected_triggers:
            raise RegistryConfigurationError(
                f"{where}: recalculation_triggers {sorted(entry.recalculation_triggers)} "
                f"do not match resolver declarations {sorted(expected_triggers)}"
            )

        if entry.output_unit and entry.output_unit not in DIMENSION_OF_UNIT:
            # Percentage-style outputs are dimensionless labels, not convertible
            # units; only reject an unknown *convertible* unit declaration.
            if entry.output_unit not in {"percent_w_w", "percent_of_potency", "percent_of_mde"}:
                raise RegistryConfigurationError(
                    f"{where}: unknown output unit {entry.output_unit!r}"
                )


def get_entry(identifier: str) -> RegistryEntry | None:
    """M4D3-REG-012 -- explicit lookup with None handling; never raises KeyError."""
    return CALCULATION_BINDING_REGISTRY.get(identifier)


_validate_registry()
