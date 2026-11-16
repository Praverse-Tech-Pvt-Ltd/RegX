"""Test helpers: the unit MEANING a synthetic IID record's fixture intends.

Since controlled units increment 3 there is one comparison path: a record's
potency (and per-day exposure) is used only through `potency_expression` /
`mde_expression`. Fixtures that relied on the legacy `potency_unit_normalized`
/ `mde_unit_normalized` link now state the same intent on the new path.
"""


def per_dose_unit(unit):
    from fda_data.models import QuantityExpression

    return QuantityExpression.objects.get_or_create(
        family=unit.dimension, basis="per_dose_unit", numerator_unit=unit
    )[0]


def per_day(unit):
    from fda_data.models import QuantityExpression

    return QuantityExpression.objects.get_or_create(
        family=unit.dimension, basis="per_day", numerator_unit=unit
    )[0]


def put_in_force(expression, raw_unit: str, *, n: int = 1):
    """Make `raw_unit` resolve to `expression` on the new path, as after review:
    an ACTIVE controlled-units release listing the meaning, and an APPROVED
    current unit mapping. Synthetic shortcut for tests; the governed path is
    load_controlled_units -> VP approval, propose_unit_mappings -> VP approval."""
    from fda_data.models import (
        FDADataSourceRelease,
        FdaImportRowResult,
        FDAReleaseStatus,
        UnitMapping,
    )

    release, _ = FDADataSourceRelease.objects.get_or_create(
        dataset_type="regx_controlled_units",
        status=FDAReleaseStatus.ACTIVE,
        defaults={
            "source_name": "test unit list",
            "official_source_reference": "test",
            "source_checksum_sha256": f"{n:064x}",
        },
    )
    FdaImportRowResult.objects.get_or_create(
        release=release,
        row_locator=f"meaning:{expression.pk}",
        defaults={
            "target_public_identifier": expression.public_id,
            "result": "imported",
            "reason_code": "meaning_new",
        },
    )
    UnitMapping.objects.get_or_create(
        source_dataset="fda_iid",
        source_raw_value=raw_unit,
        is_current=True,
        defaults={"status": "approved", "quantity_expression": expression},
    )
    return release
