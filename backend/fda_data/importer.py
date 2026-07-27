"""
Staged FDA data import pipeline.

register_release -> store file -> checksum -> extract rows -> preserve raw
-> validate schema -> normalize -> detect duplicates/schema drift ->
persist inactive reference rows -> reconciliation -> review -> approval ->
controlled activation (see lifecycle.py).

Guarantees mirrored from templates_registry.importer:
- idempotent: rerunning the same release's row set never creates duplicate
  OrangeBookProduct/IIDPrecedentRecord/FdaImportRowResult rows;
- every extracted row gets exactly one FdaImportRowResult;
- imported reference rows are never activated by this module -- only
  lifecycle.activate() (a distinct, permission-gated action) can do that,
  and only for the release itself, never per-row;
- a blank/unparseable potency or MDE value is never coerced to zero --
  it is recorded with an explicit calculability_status instead.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from .adapters import row_checksum
from .audit_events import FdaDataEvent, emit
from .models import (
    FDADataSourceRelease,
    FdaImportRowResult,
    FdaImportRowResultType,
    IIDCalculabilityStatus,
    IIDIngredient,
    IIDPrecedentRecord,
    OrangeBookApplication,
    OrangeBookProduct,
    OrangeBookProductIngredient,
    StrengthParseStatus,
)
from .storage import compute_sha256, store_fda_source_file
from .terminology import (
    lookup_dosage_form_mapping,
    lookup_route_mapping,
    lookup_unit,
    parse_strength,
)


def register_release(
    *,
    dataset_type: str,
    source_name: str,
    official_source_reference: str,
    file_obj,
    original_filename: str,
    media_type: str = "",
    schema_version: str = "",
    publication_date=None,
    imported_by=None,
) -> FDADataSourceRelease:
    """Idempotent by (dataset_type, checksum): re-registering the exact
    same file for the same dataset_type returns the existing release
    rather than creating a duplicate."""
    checksum = compute_sha256(file_obj)
    existing = FDADataSourceRelease.objects.filter(
        dataset_type=dataset_type, source_checksum_sha256=checksum
    ).first()
    if existing:
        return existing

    storage_key = store_fda_source_file(
        file_obj=file_obj,
        expected_sha256=checksum,
        content_type=media_type,
        original_filename=original_filename,
    )
    release = FDADataSourceRelease.objects.create(
        dataset_type=dataset_type,
        source_name=source_name,
        official_source_reference=official_source_reference,
        original_filename=original_filename,
        media_type=media_type,
        storage_key=storage_key,
        source_checksum_sha256=checksum,
        schema_version=schema_version,
        publication_date=publication_date,
        retrieved_at=timezone.now(),
        imported_by=imported_by,
    )
    emit(
        event_type=FdaDataEvent.RELEASE_REGISTERED,
        resource_id=str(release.public_id),
        payload={"dataset_type": dataset_type, "source_name": source_name, "checksum": checksum},
        actor_id=getattr(imported_by, "id", None),
        actor_email=getattr(imported_by, "email", ""),
    )
    emit(
        event_type=FdaDataEvent.FILE_STORED,
        resource_id=str(release.public_id),
        payload={"original_filename": original_filename},
    )
    return release


def import_orange_book_rows(release: FDADataSourceRelease, neutral_rows: list[dict], actor) -> None:
    """Idempotent: rerunning with the same neutral_rows produces the same
    OrangeBookApplication/Product rows via get_or_create, never
    duplicates."""
    emit(
        event_type=FdaDataEvent.IMPORT_STARTED,
        resource_id=str(release.public_id),
        payload={"row_count": len(neutral_rows)},
        actor_id=getattr(actor, "id", None),
    )
    release.record_count_expected = len(neutral_rows)
    already_resulted = set(
        FdaImportRowResult.objects.filter(release=release).values_list("row_locator", flat=True)
    )
    imported = duplicate = failed = 0

    for row in neutral_rows:
        locator = row["row_locator"]
        if locator in already_resulted:
            continue
        fields = row["fields"]
        checksum = row_checksum(fields)
        try:
            with transaction.atomic():
                app, _ = OrangeBookApplication.objects.get_or_create(
                    release=release,
                    application_type=fields.get("application_type", ""),
                    application_number=fields.get("application_number", ""),
                    defaults={
                        "applicant_short_name": fields.get("applicant_short_name", ""),
                        "applicant_full_name": fields.get("applicant_full_name", ""),
                        "source_row_locator": locator,
                        "raw_row_checksum": checksum,
                    },
                )
                strength = parse_strength(fields.get("strength_raw", ""))
                strength_unit = (
                    lookup_unit(strength["unit_raw"]) if strength["status"] == "parsed" else None
                )
                product, created = OrangeBookProduct.objects.get_or_create(
                    release=release,
                    application=app,
                    product_number=fields.get("product_number", ""),
                    defaults={
                        "trade_name": fields.get("trade_name", ""),
                        "active_ingredient_raw": fields.get("active_ingredient_raw", ""),
                        "dosage_form_raw": fields.get("dosage_form_raw", ""),
                        "route_raw": fields.get("route_raw", ""),
                        "dosage_form_normalized": lookup_dosage_form_mapping(
                            release.dataset_type, fields.get("dosage_form_raw", "")
                        ),
                        "route_normalized": lookup_route_mapping(
                            release.dataset_type, fields.get("route_raw", "")
                        ),
                        "strength_raw": fields.get("strength_raw", ""),
                        "strength_amount": strength["amount"],
                        "strength_unit": strength_unit,
                        "strength_parse_status": (
                            StrengthParseStatus.PARSED
                            if strength["status"] == "parsed" and strength_unit
                            else StrengthParseStatus.REVIEW_REQUIRED
                        ),
                        "rld_flag": bool(fields.get("rld_flag", False)),
                        "reference_standard_flag": bool(
                            fields.get("reference_standard_flag", False)
                        ),
                        "te_code": fields.get("te_code", ""),
                        "approval_date_text": fields.get("approval_date_text", ""),
                        "discontinued": bool(fields.get("discontinued", False)),
                        "source_row_locator": locator,
                        "raw_row_payload": row["raw_payload"],
                        "raw_row_checksum": checksum,
                    },
                )
                if fields.get("active_ingredient_raw"):
                    OrangeBookProductIngredient.objects.get_or_create(
                        product=product,
                        ingredient_raw=fields["active_ingredient_raw"],
                    )
                result_type = (
                    FdaImportRowResultType.IMPORTED if created else FdaImportRowResultType.DUPLICATE
                )
                FdaImportRowResult.objects.create(
                    release=release,
                    row_locator=locator,
                    target_public_identifier=product.public_id,
                    result=result_type,
                )
                if created:
                    imported += 1
                else:
                    duplicate += 1
        except Exception as exc:
            FdaImportRowResult.objects.get_or_create(
                release=release,
                row_locator=locator,
                defaults={
                    "result": FdaImportRowResultType.FAILED,
                    "reason_code": "import_exception",
                    "safe_detail": str(exc)[:500],
                },
            )
            failed += 1

    release.record_count_extracted = len(neutral_rows)
    release.record_count_imported = FdaImportRowResult.objects.filter(
        release=release, result=FdaImportRowResultType.IMPORTED
    ).count()
    release.record_count_failed = FdaImportRowResult.objects.filter(
        release=release, result=FdaImportRowResultType.FAILED
    ).count()
    release.save(
        update_fields=[
            "record_count_expected",
            "record_count_extracted",
            "record_count_imported",
            "record_count_failed",
            "imported_at",
            "updated_at",
        ]
        if release.imported_at
        else [
            "record_count_expected",
            "record_count_extracted",
            "record_count_imported",
            "record_count_failed",
            "updated_at",
        ]
    )
    if not release.imported_at:
        release.imported_at = timezone.now()
        release.save(update_fields=["imported_at", "updated_at"])


def import_iid_rows(release: FDADataSourceRelease, neutral_rows: list[dict], actor) -> None:
    """Idempotent per (release, raw_row_checksum). Never forces a blank or
    unparseable potency/MDE value to zero -- calculability_status records
    exactly why a value is or isn't usable."""
    emit(
        event_type=FdaDataEvent.IMPORT_STARTED,
        resource_id=str(release.public_id),
        payload={"row_count": len(neutral_rows)},
        actor_id=getattr(actor, "id", None),
    )
    release.record_count_expected = len(neutral_rows)
    already_resulted = set(
        FdaImportRowResult.objects.filter(release=release).values_list("row_locator", flat=True)
    )

    for row in neutral_rows:
        locator = row["row_locator"]
        if locator in already_resulted:
            continue
        fields = row["fields"]
        checksum = row_checksum(fields)
        try:
            with transaction.atomic():
                existing = IIDPrecedentRecord.objects.filter(
                    release=release, raw_row_checksum=checksum
                ).first()
                if existing:
                    FdaImportRowResult.objects.create(
                        release=release,
                        row_locator=locator,
                        target_public_identifier=existing.public_id,
                        result=FdaImportRowResultType.DUPLICATE,
                    )
                    continue

                ingredient = _resolve_iid_ingredient(fields)
                route_normalized = lookup_route_mapping(
                    release.dataset_type, fields.get("route_raw", "")
                )
                dosage_form_normalized = lookup_dosage_form_mapping(
                    release.dataset_type, fields.get("dosage_form_raw", "")
                )
                potency = parse_strength(
                    f"{fields.get('potency_raw', '')} {fields.get('potency_unit_raw', '')}".strip()
                )
                potency_unit = (
                    lookup_unit(fields.get("potency_unit_raw", ""))
                    if fields.get("potency_unit_raw")
                    else None
                )
                mde_raw = fields.get("mde_raw", "")
                mde_amount = None
                mde_unit = None
                if mde_raw:
                    mde_parsed = parse_strength(
                        f"{mde_raw} {fields.get('mde_unit_raw', '')}".strip()
                    )
                    if mde_parsed["status"] == "parsed":
                        mde_amount = mde_parsed["amount"]
                        mde_unit = lookup_unit(fields.get("mde_unit_raw", ""))

                status = _determine_calculability(
                    ingredient=ingredient,
                    route_normalized=route_normalized,
                    dosage_form_normalized=dosage_form_normalized,
                    potency_amount=potency["amount"] if potency["status"] == "parsed" else None,
                    potency_unit=potency_unit,
                    mde_amount=mde_amount,
                )

                record = IIDPrecedentRecord.objects.create(
                    release=release,
                    ingredient=ingredient,
                    ingredient_name_raw=fields.get("ingredient_name_raw", ""),
                    route_raw=fields.get("route_raw", ""),
                    route_normalized=route_normalized,
                    dosage_form_raw=fields.get("dosage_form_raw", ""),
                    dosage_form_normalized=dosage_form_normalized,
                    potency_amount=potency["amount"] if potency["status"] == "parsed" else None,
                    potency_unit_raw=fields.get("potency_unit_raw", ""),
                    potency_unit_normalized=potency_unit,
                    maximum_daily_exposure=mde_amount,
                    mde_unit_raw=fields.get("mde_unit_raw", ""),
                    mde_unit_normalized=mde_unit,
                    source_row_locator=locator,
                    raw_row_payload=row["raw_payload"],
                    raw_row_checksum=checksum,
                    calculability_status=status,
                )
                FdaImportRowResult.objects.create(
                    release=release,
                    row_locator=locator,
                    target_public_identifier=record.public_id,
                    result=(
                        FdaImportRowResultType.IMPORTED
                        if status == IIDCalculabilityStatus.CALCULABLE
                        else FdaImportRowResultType.REVIEW_REQUIRED
                    ),
                    reason_code=status,
                )
        except Exception as exc:
            FdaImportRowResult.objects.get_or_create(
                release=release,
                row_locator=locator,
                defaults={
                    "result": FdaImportRowResultType.FAILED,
                    "reason_code": "import_exception",
                    "safe_detail": str(exc)[:500],
                },
            )

    release.record_count_extracted = len(neutral_rows)
    release.record_count_imported = FdaImportRowResult.objects.filter(
        release=release, result=FdaImportRowResultType.IMPORTED
    ).count()
    release.record_count_failed = FdaImportRowResult.objects.filter(
        release=release, result=FdaImportRowResultType.FAILED
    ).count()
    if not release.imported_at:
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


def _resolve_iid_ingredient(fields: dict) -> IIDIngredient | None:
    name = (fields.get("ingredient_name_raw") or "").strip()
    unii = (fields.get("unii") or "").strip()
    if not name:
        return None
    if unii:
        existing = IIDIngredient.objects.filter(unii=unii).first()
        if existing:
            return existing
    normalized = name.upper()
    existing = IIDIngredient.objects.filter(normalized_name=normalized).first()
    if existing:
        return existing
    return IIDIngredient.objects.create(
        canonical_name=name,
        normalized_name=normalized,
        unii=unii,
        cas_number=fields.get("cas_number", ""),
    )


def _determine_calculability(
    *,
    ingredient,
    route_normalized,
    dosage_form_normalized,
    potency_amount,
    potency_unit,
    mde_amount,
) -> str:
    if ingredient is None:
        return IIDCalculabilityStatus.INGREDIENT_AMBIGUOUS
    if route_normalized is None:
        return IIDCalculabilityStatus.ROUTE_UNMAPPED
    if dosage_form_normalized is None:
        return IIDCalculabilityStatus.DOSAGE_FORM_UNMAPPED
    if potency_amount is None:
        return IIDCalculabilityStatus.POTENCY_MISSING
    if potency_unit is None:
        return IIDCalculabilityStatus.POTENCY_UNIT_MISSING
    if mde_amount is None:
        # A record can still be CALCULABLE for potency-only comparison;
        # MDE-specific comparisons separately check for this at
        # calculation time (iid_assessment) and return MDE_UNAVAILABLE
        # there rather than blocking the whole record here.
        return IIDCalculabilityStatus.CALCULABLE
    return IIDCalculabilityStatus.CALCULABLE
