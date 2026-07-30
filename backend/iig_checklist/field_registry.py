"""Controlled, declarative field registry for `ApplicabilityRule.condition_json`
(see docs/MILESTONE_4D_1_IMPLEMENTATION_SPEC.md §4a/§4b).

This is intentionally a plain Python module, not a database table --
registry versions are additive and immutable once referenced by an
approved/active ChecklistVersion. A bump never mutates or deletes an
older version's field set; it only adds a new one.
"""

FIELD_REGISTRY_VERSION = 1

# Every past version's field set is retained permanently, so a rule
# authored against an old version remains validatable/reproducible.
_ALLOWED_FIELDS_BY_VERSION = {
    1: frozenset(
        {
            "product.route",
            "product.dosage_form",
            "product.release_type",
            "iid.match_status",
            "iid.has_mde",
            "iid.has_potency",
        }
    ),
}

# Registry versions no longer eligible to gate a *new* activation.
# Existing active content referencing them is entirely unaffected --
# this only blocks a version whose rules declare an unsupported
# registry from newly reaching `active`.
UNSUPPORTED_REGISTRY_VERSIONS: frozenset[int] = frozenset()


def allowed_fields_for_version(registry_version: int) -> frozenset[str]:
    return _ALLOWED_FIELDS_BY_VERSION.get(registry_version, frozenset())


def is_known_registry_version(registry_version: int) -> bool:
    return registry_version in _ALLOWED_FIELDS_BY_VERSION


def is_supported_for_activation(registry_version: int) -> bool:
    return (
        is_known_registry_version(registry_version)
        and registry_version not in UNSUPPORTED_REGISTRY_VERSIONS
    )
