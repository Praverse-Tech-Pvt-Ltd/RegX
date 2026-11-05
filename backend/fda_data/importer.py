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

import logging
import re
from datetime import date
from decimal import Decimal, InvalidOperation

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
    normalized_payload_sha256: str = "",
    parser_identifier: str = "",
) -> FDADataSourceRelease:
    """Idempotent by (dataset_type, checksum): re-registering the exact
    same bytes for the same dataset_type returns the existing release
    rather than creating a duplicate.

    `source_checksum_sha256` is the checksum of `file_obj` -- the bytes the
    caller actually supplied. For `import_fda_release` that is the published
    FDA file or ZIP; for the JSON API it is the canonical rows payload. The
    field has always meant this, and P5 does not change it.

    `normalized_payload_sha256` is separate and optional: the checksum of the
    canonical rows after parsing. Two different source files that normalize
    to identical rows share it while keeping distinct source checksums, so
    the provenance distinction survives.
    """
    checksum = compute_sha256(file_obj)
    file_obj.seek(0, 2)
    size_bytes = file_obj.tell()
    file_obj.seek(0)
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
        normalized_payload_sha256=normalized_payload_sha256,
        source_file_size_bytes=size_bytes,
        parser_identifier=parser_identifier,
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


logger = logging.getLogger(__name__)

#: FDA's documented stand-in for products approved before 1982 (the exact
#: spelling in EOBZIP_2026_08, 5,873 rows). It is recognised, not a parse
#: failure: the text is kept and `approval_date` stays NULL -- never a guessed
#: 1982-01-01.
PRE_1982_APPROVAL_TEXT = "approved prior to jan 1, 1982"

#: Reason code recorded on the row's FdaImportRowResult when an approval date
#: cannot be read, so the gap is auditable per row rather than silently empty.
APPROVAL_DATE_UNPARSED = "approval_date_unparsed"


#: English month abbreviations as FDA writes them. A fixed table rather than
#: strptime's `%b`, which reads month names from the process locale: under a
#: German or French LC_TIME, "Oct 18, 2019" would not parse.
_MONTHS = {
    m: i
    for i, m in enumerate(
        ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"),
        start=1,
    )
}
_FDA_DATE = re.compile(r"([A-Za-z]{3}) (\d{1,2}), (\d{4})")


def parse_approval_date(text: str) -> tuple[date | None, bool]:
    """Return (date, unparsed) for an Orange Book `Approval_Date` value.

    "Mmm d, yyyy" and "Mmm dd, yyyy", parsed without reference to the system
    locale. Empty text and the documented pre-1982 phrase return (None, False).
    Anything else returns (None, True) so the caller records it instead of
    dropping it.
    """
    value = (text or "").strip()
    if not value or value.lower() == PRE_1982_APPROVAL_TEXT:
        return None, False
    match = _FDA_DATE.fullmatch(value)
    month = _MONTHS.get(match.group(1).upper()) if match else None
    if month is None:
        return None, True
    try:
        return date(int(match.group(3)), month, int(match.group(2))), False
    except ValueError:  # e.g. "Feb 30, 2020"
        return None, True


def import_orange_book_rows(release: FDADataSourceRelease, neutral_rows: list[dict], actor) -> None:
    """Idempotent: rerunning with the same neutral_rows produces the same
    OrangeBookApplication/Product rows via get_or_create, never
    duplicates."""
    emit(
        event_type=FdaDataEvent.IMPORT_STARTED,
        resource_id=str(release.public_id),
        payload={"row_count": len(neutral_rows)},
        actor_id=getattr(actor, "id", None),
        actor_email=getattr(actor, "email", ""),
    )
    release.record_count_expected = len(neutral_rows)
    already_resulted = set(
        FdaImportRowResult.objects.filter(release=release).values_list("row_locator", flat=True)
    )
    imported = duplicate = failed = 0
    unparsed_dates = 0

    for row in neutral_rows:
        locator = row["row_locator"]
        if locator in already_resulted:
            continue
        fields = row["fields"]
        checksum = row_checksum(fields)
        approval_date, date_unparsed = parse_approval_date(fields.get("approval_date_text", ""))
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
                        "approval_date": approval_date,
                        "approval_date_text": fields.get("approval_date_text", ""),
                        "marketing_category": fields.get("marketing_category", ""),
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
                    reason_code=APPROVAL_DATE_UNPARSED if date_unparsed else "",
                    safe_detail=(
                        f"Approval_Date not parsed; kept as text: "
                        f"{fields.get('approval_date_text', '')[:100]}"
                        if date_unparsed
                        else ""
                    ),
                )
                if date_unparsed and created:
                    unparsed_dates += 1
                    logger.warning(
                        "Orange Book approval date not parsed; kept as text (release=%s, row=%s)",
                        release.public_id,
                        locator,
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

    if unparsed_dates:
        logger.warning(
            "Orange Book import: %s approval date(s) not parsed and kept as text "
            "(release=%s, reason_code=%s)",
            unparsed_dates,
            release.public_id,
            APPROVAL_DATE_UNPARSED,
        )
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


#: The IID publishes amounts and units in separate columns, and every amount
#: in the July 2026 file is a plain decimal ("0.5", "1200"). Anything else is
#: kept as text and flagged, never guessed at.
_IID_PLAIN_AMOUNT = re.compile(r"^[0-9]+(?:\.[0-9]+)?$")

#: UNII placeholder the IID writes when an ingredient has no UNII (1,595 rows
#: in the July 2026 file, across 819 different ingredient names). It is not an
#: identifier: matching on it would merge all those ingredients into one.
_IID_UNII_PLACEHOLDERS = {"", "NA"}


def parse_iid_amount(text: str) -> tuple[Decimal | None, bool]:
    """Return (amount, unparsed) for an IID amount column.

    Blank -> (None, False): FDA stated no value. A plain decimal -> (amount,
    False). Anything else -> (None, True): the caller keeps the text and flags
    the row.
    """
    text = (text or "").strip()
    if not text:
        return None, False
    if _IID_PLAIN_AMOUNT.match(text):
        try:
            return Decimal(text), False
        except InvalidOperation:
            return None, True
    return None, True


def import_iid_rows(release: FDADataSourceRelease, neutral_rows: list[dict], actor) -> None:
    """Idempotent per (release, raw_row_checksum). Never forces a blank or
    unparseable potency/MDE value to zero -- calculability_status records
    exactly why a value is or isn't usable."""
    emit(
        event_type=FdaDataEvent.IMPORT_STARTED,
        resource_id=str(release.public_id),
        payload={"row_count": len(neutral_rows)},
        actor_id=getattr(actor, "id", None),
        actor_email=getattr(actor, "email", ""),
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
                # Amount and unit are separate IID columns, so the amount is
                # parsed on its own: joining them first made units such as
                # "mg/5ml" unparseable and dropped a plain number with them.
                potency_text = (fields.get("potency_raw") or "").strip()
                potency_amount, potency_unparsed = parse_iid_amount(potency_text)
                potency_unit = (
                    lookup_unit(fields.get("potency_unit_raw", ""))
                    if fields.get("potency_unit_raw")
                    else None
                )
                mde_text = (fields.get("mde_raw") or "").strip()
                mde_amount, mde_unparsed = parse_iid_amount(mde_text)
                mde_unit = (
                    lookup_unit(fields.get("mde_unit_raw", ""))
                    if mde_amount is not None and fields.get("mde_unit_raw")
                    else None
                )
                unparsed = [
                    f"{column} not parsed; kept as text: {text[:100]}"
                    for column, text, flag in (
                        ("POTENCY_AMOUNT", potency_text, potency_unparsed),
                        ("MAXIMUM_DAILY_EXPOSURE", mde_text, mde_unparsed),
                    )
                    if flag
                ]

                status = _determine_calculability(
                    ingredient=ingredient,
                    route_normalized=route_normalized,
                    dosage_form_normalized=dosage_form_normalized,
                    potency_amount=potency_amount,
                    potency_unit=potency_unit,
                    mde_amount=mde_amount,
                    potency_unparsed=potency_unparsed,
                )

                record = IIDPrecedentRecord.objects.create(
                    release=release,
                    ingredient=ingredient,
                    ingredient_name_raw=fields.get("ingredient_name_raw", ""),
                    route_raw=fields.get("route_raw", ""),
                    route_normalized=route_normalized,
                    dosage_form_raw=fields.get("dosage_form_raw", ""),
                    dosage_form_normalized=dosage_form_normalized,
                    potency_amount=potency_amount,
                    potency_amount_raw=potency_text,
                    potency_unit_raw=fields.get("potency_unit_raw", ""),
                    potency_unit_normalized=potency_unit,
                    maximum_daily_exposure=mde_amount,
                    mde_amount_raw=mde_text,
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
                        if status == IIDCalculabilityStatus.CALCULABLE and not unparsed
                        else FdaImportRowResultType.REVIEW_REQUIRED
                    ),
                    reason_code=status,
                    safe_detail="; ".join(unparsed),
                )
                if unparsed:
                    logger.warning(
                        "IID amount not parsed; kept as text (release=%s, row=%s)",
                        release.public_id,
                        locator,
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
    if unii.upper() in _IID_UNII_PLACEHOLDERS:
        unii = ""
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
    potency_unparsed=False,
) -> str:
    if ingredient is None:
        return IIDCalculabilityStatus.INGREDIENT_AMBIGUOUS
    if route_normalized is None:
        return IIDCalculabilityStatus.ROUTE_UNMAPPED
    if dosage_form_normalized is None:
        return IIDCalculabilityStatus.DOSAGE_FORM_UNMAPPED
    if potency_amount is None:
        if potency_unparsed:
            return IIDCalculabilityStatus.POTENCY_UNPARSEABLE
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
