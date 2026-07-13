from django.shortcuts import render
from django.db.models import Prefetch
from .filters import *
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from AdminMaster.models import *
from .models import *
from django.http import JsonResponse
from django.db.models import Count
from rest_framework.decorators import api_view
from django.core.exceptions import ObjectDoesNotExist
from django.views.decorators.csrf import csrf_exempt
import openai
from django.conf import settings
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated,AllowAny
from rest_framework.authentication import SessionAuthentication
from .models import ChatMessage
from .serializers import ChatMessageSerializer
from django.http import HttpResponse
import json
import pandas as pd
import openai
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import AllowAny
from .models import ChatMessage  # Ensure your model is imported
from django.contrib.auth.decorators import login_required
from django.db.models import Min,Max
import matplotlib.pyplot as plt
import seaborn as sns
from fuzzywuzzy import process
import time
import hashlib
import os
import uuid
import re
from datetime import datetime
from AdminMaster.models import AssignChecker
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
import shutil
from django.core.files import File
from django.core.files.base import ContentFile
from AIDatabase.models import (
    ObservationImage,
    ObservationImageExcelMaster,
    GMPCExcelMaster,
    WarningLetterExcelMaster,
    WarningLetterPdf,
    Form483ExcelNewData,
    WarningLetterExcelNewData,
    UserCheckedUpdate
)
from .observation_summary import process_observation_summary
from collections import Counter

from decouple import config
from django.utils.timezone import now
from django.utils.text import slugify


class CsrfExemptSessionAuthentication(SessionAuthentication):
    def enforce_csrf(self, request):
        return


def _build_file_signature(path):
    try:
        stat = os.stat(path)
        return f"{int(stat.st_mtime_ns)}:{stat.st_size}"
    except (FileNotFoundError, OSError):
        return "missing"


def _build_excel_source_key(*, active_id, path):
    return f"active:{active_id}:{_build_file_signature(path)}"


def _get_excel_snapshot_path(cache_key):
    snapshot_dir = os.path.join(settings.BASE_DIR, "tmp", "excel_snapshots")
    os.makedirs(snapshot_dir, exist_ok=True)
    return os.path.join(snapshot_dir, f"{cache_key}.pkl")


def _load_persisted_excel_snapshot(cache_key):
    snapshot_path = _get_excel_snapshot_path(cache_key)
    if not os.path.exists(snapshot_path):
        return None

    try:
        snapshot = pd.read_pickle(snapshot_path)
    except Exception as exc:
        print(f"[SNAPSHOT] Failed to read snapshot for {cache_key}: {exc}")
        return None

    if not isinstance(snapshot, dict) or "df" not in snapshot:
        return None

    return snapshot


def _persist_excel_snapshot(cache_key, *, source_key, source_path, df):
    snapshot_path = _get_excel_snapshot_path(cache_key)
    payload = {
        "source_key": source_key,
        "source_path": source_path,
        "df": df.copy(deep=True) if df is not None else None,
        "saved_at": now().isoformat(),
    }
    try:
        pd.to_pickle(payload, snapshot_path)
    except Exception as exc:
        print(f"[SNAPSHOT] Failed to persist snapshot for {cache_key}: {exc}")


def _get_active_excel_source(master_model, *, fallback_filename, log_label):
    obj = master_model.objects.filter(is_active=True).first()
    if obj and getattr(obj, "file", None):
        print(f"[INFO] Active {log_label} object:", obj.display_name)
        file_path = obj.file.path
        file_sig = _build_file_signature(file_path)
        return {
            "path": file_path,
            "source_key": f"active:{obj.pk}:{file_sig}",
            "active_id": obj.pk,
        }

    fallback_path = os.path.join(
        settings.BASE_DIR,
        "AIDatabase",
        "management",
        "commands",
        fallback_filename,
    )

    print(f"[WARN] Using fallback {log_label} file:", fallback_path)
    fallback_sig = _build_file_signature(fallback_path)
    return {
        "path": fallback_path,
        "source_key": f"fallback:{fallback_path}:{fallback_sig}",
        "active_id": None,
    }


def _build_runtime_excel_source_key(*, active_id, path):
    file_sig = _build_file_signature(path)
    if active_id is not None:
        return f"active:{active_id}:{file_sig}"
    return f"fallback:{path}:{file_sig}"


def _get_active_excel_path(master_model, *, fallback_filename, log_label):
    return _get_active_excel_source(
        master_model,
        fallback_filename=fallback_filename,
        log_label=log_label,
    )["path"]


def get_active_excel_path():
    return _get_active_excel_path(
        ObservationImageExcelMaster,
        fallback_filename="Final_File_FDA_Observations_15_12_2025.xlsx",
        log_label="ExcelMaster",
    )


def get_active_excel_source():
    return _get_active_excel_source(
        ObservationImageExcelMaster,
        fallback_filename="Final_File_FDA_Observations_15_12_2025.xlsx",
        log_label="ExcelMaster",
    )


def _persist_excel_atomic(temp_path, final_path, retries=5, delay=0.5):
    if not os.path.exists(temp_path):
        raise FileNotFoundError(
            f"Temporary Excel file was not created: {temp_path}. "
            "Excel update aborted."
        )
    for attempt in range(retries):
        try:
            os.replace(temp_path, final_path)
            return
        except PermissionError as exc:
            if attempt == retries - 1:
                # Final fallback: try copy/remove so we don't leave the tmp file behind.
                try:
                    shutil.copy2(temp_path, final_path)
                    os.remove(temp_path)
                    return
                except Exception:
                    raise PermissionError(
                        f"Unable to update Excel file at {final_path}. "
                        "Please close any open copies and retry."
                    ) from exc
            time.sleep(delay)


def _get_preferred_sheet_name(sheet_name):
    if isinstance(sheet_name, (list, tuple)):
        for candidate in sheet_name:
            if candidate:
                return candidate
        return "Sheet1"
    return sheet_name or "Sheet1"


def _persist_dataframe_to_excel(path, df, *, sheet_name):
    temp_path = f"{path}.{uuid.uuid4().hex}.tmp.xlsx"
    df.to_excel(temp_path, index=False, sheet_name=_get_preferred_sheet_name(sheet_name))
    _persist_excel_atomic(temp_path, path)


def _normalize_summary_value(value):
    if pd.isna(value):
        return None
    normalized = str(value).strip()
    return normalized or None


def _summary_series_changed(before_series, after_series):
    after_values = [_normalize_summary_value(value) for value in after_series.tolist()]
    if before_series is None:
        before_values = [None] * len(after_values)
    else:
        before_values = [_normalize_summary_value(value) for value in before_series.tolist()]
    return before_values != after_values

EXCEL_DF_CACHE = {
    "observations": {"path": None, "source_key": None, "df": None},
    "warning_letter": {"path": None, "source_key": None, "df": None},
}
GMPC_EXCEL_DF_CACHE = {}
EXCEL_COMPARE_TRACKER = {
    "observations": None,
    "warning_letter": None,
}
OBSERVATION_SUMMARY_CACHE_VERSION = "summary-v2"
GMPC_EXCEL_CACHE_VERSION = "gmpc-v2"

SYSTEM_NORMALIZATION_MAP = {
    "quality system": "quality system",
    "laboratory control system": "laboratory control system",
    "material system": "material system",
    "packaging and labeling system": "packaging and labeling system",
    "packaging and labelling system": "packaging and labeling system",
    "production system": "production system",
    "facilities and equipment system": "facilities and equipment system",
    "facilities & equipment system": "facilities and equipment system",
    "facility & equipment system": "facilities and equipment system",
    "facilites & equipment system": "facilities and equipment system",
}


def _normalize_system_name(value):
    if value is None:
        return None
    normalized = str(value).strip().lower()
    return SYSTEM_NORMALIZATION_MAP.get(normalized, normalized)


def _decorate_cache_source_key(cache_key, source_key):
    if not source_key:
        return source_key
    if cache_key == "observations":
        suffix = f":{OBSERVATION_SUMMARY_CACHE_VERSION}"
        if str(source_key).endswith(suffix):
            return source_key
        return f"{source_key}{suffix}"
    return source_key


def _normalize_country_cache_value(country):
    return (country or "").strip()


def _gmpc_country_cache_key(country):
    normalized_country = _normalize_country_cache_value(country).lower()
    digest = hashlib.sha256(normalized_country.encode("utf-8")).hexdigest()[:16]
    return f"gmpc_{digest}"


def _get_gmpc_cache_bucket(country):
    cache_key = _gmpc_country_cache_key(country)
    return cache_key, GMPC_EXCEL_DF_CACHE.setdefault(
        cache_key,
        {
            "country": _normalize_country_cache_value(country),
            "path": None,
            "source_key": None,
            "df": None,
            "content_key": None,
            "filter_options_source_key": None,
            "filter_options": {},
        },
    )


def _build_dataframe_content_key(df):
    if df is None:
        return None

    normalized_df = df.copy()
    normalized_df = normalized_df.where(pd.notnull(normalized_df), "")
    normalized_df.columns = [str(col).strip() for col in normalized_df.columns]
    normalized_df = normalized_df.reindex(sorted(normalized_df.columns), axis=1)

    for col in normalized_df.columns:
        normalized_df[col] = normalized_df[col].map(
            lambda value: "" if value is None else _safe_cell_value(value) or ""
        )

    json_payload = normalized_df.to_json(orient="split", date_format="iso", force_ascii=False)
    return hashlib.sha256(json_payload.encode("utf-8")).hexdigest()

FORM483_NEW_DATA_COLUMNS = [
    "Sr. No.",
    "Company Name",
    "Organization Name",
    "FEI Number",
    "City, Country",
    "Type of establishment",
    "Month of Inspection",
    "FDA Investigator(s) name",
    "Year of Inspection",
    "System",
    "Form 483 Observation",
    "Observation Details",
]

FORM483_OBSERVATION_KEY_COLUMNS = [
    "Company Name",
    "Organization Name",
    "FEI Number",
    "City, Country",
    "Month of Inspection",
    "Year of Inspection",
    "System",
    "Form 483 Observation",
]

WARNING_LETTER_NEW_DATA_COLUMNS = [
    "Company Name",
    "Letter Issue Date",
    "Year",
    "Issuing Office",
    "Subject",
    "filename",
]


def _safe_cell_value(value):
    if pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            pass
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _row_fingerprint(row, key_columns):
    normalized = []
    for col in key_columns:
        val = _safe_cell_value(row.get(col))
        normalized.append("" if val is None else val)
    return hashlib.sha256("||".join(normalized).encode("utf-8")).hexdigest()


def _extract_new_rows(previous_df, current_df, key_columns):
    if previous_df is None:
        return []

    old_fingerprints = {
        _row_fingerprint(row, key_columns)
        for _, row in previous_df.iterrows()
    }

    new_rows = []
    seen_current = set()
    for _, row in current_df.iterrows():
        fp = _row_fingerprint(row, key_columns)
        if fp in seen_current:
            continue
        seen_current.add(fp)
        if fp not in old_fingerprints:
            new_rows.append((fp, row))

    return new_rows


def _extract_new_observation_groups(previous_df, current_df, key_columns):
    previous_keys = set()
    if previous_df is not None:
        for _, row in previous_df.iterrows():
            key_tuple = tuple(_safe_cell_value(row.get(col)) for col in key_columns)
            previous_keys.add(key_tuple)

    grouped_current = {}
    for _, row in current_df.iterrows():
        key_tuple = tuple(_safe_cell_value(row.get(col)) for col in key_columns)
        grouped_current.setdefault(key_tuple, []).append(row)

    new_groups = []
    for key_tuple, rows in grouped_current.items():
        if key_tuple in previous_keys:
            continue
        key_text = "||".join("" if v is None else str(v) for v in key_tuple)
        group_fingerprint = hashlib.sha256(key_text.encode("utf-8")).hexdigest()
        new_groups.append((group_fingerprint, key_tuple, rows))

    return new_groups


def _save_new_observation_rows(previous_df, current_df, source_excel_path):
    new_groups = _extract_new_observation_groups(
        previous_df,
        current_df,
        FORM483_OBSERVATION_KEY_COLUMNS,
    )
    if not new_groups:
        print("[NEW DATA][483] No new observations detected.")
        return

    reload_batch_id = uuid.uuid4().hex
    Form483ExcelNewData.objects.all().delete()
    UserCheckedUpdate.objects.all().update(checked_updates=False)

    objects = []
    for row_fingerprint, key_tuple, rows in new_groups:
        first_row = rows[0]
        payload = {col: _safe_cell_value(first_row.get(col)) for col in FORM483_NEW_DATA_COLUMNS}

        details_list = []
        for row in rows:
            detail = _safe_cell_value(row.get("Observation Details"))
            if detail and detail not in details_list:
                details_list.append(detail)

        payload["Observation Details"] = "\n\n".join(details_list) if details_list else None
        payload["observation_row_count"] = len(rows)
        payload["observation_key"] = {
            col: key_tuple[idx] for idx, col in enumerate(FORM483_OBSERVATION_KEY_COLUMNS)
        }

        objects.append(
            Form483ExcelNewData(
                reload_batch_id=reload_batch_id,
                source_excel_path=source_excel_path,
                sr_no=payload.get("Sr. No."),
                company_name=payload.get("Company Name"),
                organization_name=payload.get("Organization Name"),
                fei_number=payload.get("FEI Number"),
                city_country=payload.get("City, Country"),
                type_of_establishment=payload.get("Type of establishment"),
                month_of_inspection=payload.get("Month of Inspection"),
                investigator_name=payload.get("FDA Investigator(s) name"),
                year_of_inspection=payload.get("Year of Inspection"),
                system=payload.get("System"),
                form_483_observation=payload.get("Form 483 Observation"),
                observation_details=payload.get("Observation Details"),
                row_fingerprint=row_fingerprint,
                raw_row=payload,
            )
        )

    Form483ExcelNewData.objects.bulk_create(objects, ignore_conflicts=True)
    print(f"[NEW DATA][483] Saved {len(objects)} new observations (batch: {reload_batch_id}).")


def _save_new_warning_letter_rows(previous_df, current_df, source_excel_path):
    new_rows = _extract_new_rows(previous_df, current_df, WARNING_LETTER_NEW_DATA_COLUMNS)
    if not new_rows:
        print("[NEW DATA][WarningLetter] No new rows detected.")
        return

    reload_batch_id = uuid.uuid4().hex
    WarningLetterExcelNewData.objects.all().delete()
    UserCheckedUpdate.objects.all().update(checked_updates=False)
    objects = []
    for row_fingerprint, row in new_rows:
        payload = {col: _safe_cell_value(row.get(col)) for col in WARNING_LETTER_NEW_DATA_COLUMNS}
        objects.append(
            WarningLetterExcelNewData(
                reload_batch_id=reload_batch_id,
                source_excel_path=source_excel_path,
                company_name=payload.get("Company Name"),
                letter_issue_date=payload.get("Letter Issue Date"),
                year=payload.get("Year"),
                issuing_office=payload.get("Issuing Office"),
                subject=payload.get("Subject"),
                filename=payload.get("filename"),
                row_fingerprint=row_fingerprint,
                raw_row=payload,
            )
        )

    WarningLetterExcelNewData.objects.bulk_create(objects, ignore_conflicts=True)
    print(f"[NEW DATA][WarningLetter] Saved {len(objects)} new rows (batch: {reload_batch_id}).")


def _track_new_rows_on_reload(cache_key, previous_df, current_df, source_excel_path):
    if previous_df is None:
        return
    if cache_key == "observations":
        _save_new_observation_rows(previous_df, current_df, source_excel_path)
    elif cache_key == "warning_letter":
        _save_new_warning_letter_rows(previous_df, current_df, source_excel_path)


def _refresh_excel_cache_from_source_info(
    *,
    cache_key,
    source_path,
    source_key,
    active_id=None,
    sheet_name,
    log_label,
    baseline_df=None,
    baseline_source_key=None,
):
    cache = EXCEL_DF_CACHE[cache_key]
    source_key = _decorate_cache_source_key(cache_key, source_key)

    print(f"[RELOAD] {log_label}")
    print(f"[PATH]   {source_path}")

    current_df = _read_excel_with_sheet_fallback(
        source_path,
        sheet_name=sheet_name,
        log_label=log_label,
    )
    current_df = current_df.where(pd.notnull(current_df), None)
    original_summary_series = (
        current_df["Summary"].copy()
        if cache_key == "observations" and "Summary" in current_df.columns
        else None
    )

    effective_previous_df = baseline_df
    effective_previous_source_key = baseline_source_key

    if effective_previous_df is None and cache["df"] is not None:
        effective_previous_df = cache["df"]
        effective_previous_source_key = cache["source_key"]

    if effective_previous_df is None:
        snapshot = _load_persisted_excel_snapshot(cache_key)
        if snapshot:
            effective_previous_df = snapshot.get("df")
            effective_previous_source_key = snapshot.get("source_key")

    if cache_key == "observations":
        summary_baseline_df = (
            effective_previous_df
            if effective_previous_source_key == source_key
            else None
        )
        current_df = process_observation_summary(
            current_df,
            previous_df=summary_baseline_df,
        )
        current_df = current_df.where(pd.notnull(current_df), None)
        if _summary_series_changed(original_summary_series, current_df["Summary"]):
            _persist_dataframe_to_excel(
                source_path,
                current_df,
                sheet_name=sheet_name,
            )
            source_key = _build_runtime_excel_source_key(
                active_id=active_id,
                path=source_path,
            )
            source_key = _decorate_cache_source_key(cache_key, source_key)
            print(f"[SUMMARY] Excel updated with generated summaries: {source_path}")

    source_changed = (
        effective_previous_source_key is not None
        and effective_previous_source_key != source_key
    )

    if source_changed:
        if EXCEL_COMPARE_TRACKER.get(cache_key) != source_key:
            _track_new_rows_on_reload(
                cache_key=cache_key,
                previous_df=effective_previous_df,
                current_df=current_df,
                source_excel_path=source_path,
            )
            EXCEL_COMPARE_TRACKER[cache_key] = source_key
        else:
            print(f"[SKIP COMPARE] {log_label} already compared for {source_key}")
    elif effective_previous_source_key is None:
        print(f"[SNAPSHOT] Creating initial baseline for {log_label}")

    cache["df"] = current_df
    cache["path"] = source_path
    cache["source_key"] = source_key
    _persist_excel_snapshot(
        cache_key,
        source_key=source_key,
        source_path=source_path,
        df=current_df,
    )

    print(f"[CACHE]  {log_label} loaded and cached")
    return current_df


def _get_cached_excel_df(*, cache_key, source_getter, sheet_name, log_label):
    cache = EXCEL_DF_CACHE[cache_key]
    source_info = source_getter()
    current_path = source_info["path"]
    current_source_key = _decorate_cache_source_key(cache_key, source_info["source_key"])

    # Reload ONLY if file changed
    if cache["df"] is None or cache["source_key"] != current_source_key:
        _refresh_excel_cache_from_source_info(
            cache_key=cache_key,
            source_path=current_path,
            source_key=current_source_key,
            active_id=source_info.get("active_id"),
            sheet_name=sheet_name,
            log_label=log_label,
        )
    else:
        print(f"[CACHE HIT] Using cached {log_label}")

    return cache["df"]



def _read_excel_with_sheet_fallback(path, *, sheet_name, log_label):
    preferred = sheet_name
    if isinstance(preferred, (list, tuple)):
        preferred_sheets = [s for s in preferred if s]
    else:
        preferred_sheets = [preferred] if preferred else []

    if preferred_sheets:
        try:
            return pd.read_excel(path, sheet_name=preferred_sheets[0])
        except ValueError as exc:
            msg = str(exc)
            if "Worksheet named" not in msg or "not found" not in msg:
                raise
    else:
        exc = None

    xl = None
    try:
        xl = pd.ExcelFile(path)
        available = xl.sheet_names or []

        for candidate in preferred_sheets[1:]:
            if candidate in available:
                print(f"!! {log_label}: using fallback sheet '{candidate}' (configured sheet missing).")
                df = xl.parse(candidate)
                return df

        if available:
            chosen = available[0]
            if preferred_sheets:
                print(f"!! {log_label}: sheet '{preferred_sheets[0]}' not found; using '{chosen}'.")
            else:
                print(f"!! {log_label}: no sheet configured; using '{chosen}'.")
            df = xl.parse(chosen)
            return df

        if exc is not None:
            raise exc
        raise ValueError(f"{log_label}: no worksheets found in Excel file: {path}")
    finally:
        if xl is not None:
            try:
                xl.close()
            except Exception:
                pass


def _normalize_excel_dataframe(df):
    if df is None:
        return df
    normalized_df = df.where(pd.notnull(df), None).copy()
    normalized_df.columns = [str(col).strip() for col in normalized_df.columns]
    return normalized_df


def _read_excel_preferred_non_empty_sheet(path, *, sheet_name, log_label):
    df = _read_excel_with_sheet_fallback(
        path,
        sheet_name=sheet_name,
        log_label=log_label,
    )
    if not df.empty or len(df.columns) > 0:
        return df

    xl = None
    try:
        xl = pd.ExcelFile(path)
        preferred_sheets = []
        if isinstance(sheet_name, (list, tuple)):
            preferred_sheets = [s for s in sheet_name if s]
        elif sheet_name:
            preferred_sheets = [sheet_name]

        for candidate in xl.sheet_names or []:
            if candidate in preferred_sheets:
                continue
            candidate_df = xl.parse(candidate)
            if not candidate_df.empty or len(candidate_df.columns) > 0:
                print(
                    f"!! {log_label}: sheet '{preferred_sheets[0] if preferred_sheets else 'configured'}' "
                    f"is empty; using '{candidate}'."
                )
                return candidate_df

        return df
    finally:
        if xl is not None:
            try:
                xl.close()
            except Exception:
                pass


def get_cached_df():
    return _get_cached_excel_df(
        cache_key="observations",
        source_getter=get_active_excel_source,
        sheet_name="Sheet1",
        log_label="Excel",
    )


def get_active_warning_letter_excel_path():
    return _get_active_excel_path(
        WarningLetterExcelMaster,
        fallback_filename="Warning_Letters_Final_24_12_2025.xlsx",
        log_label="WarningLetterExcelMaster",
    )


def get_active_warning_letter_excel_source():
    return _get_active_excel_source(
        WarningLetterExcelMaster,
        fallback_filename="Warning_Letters_Final_24_12_2025.xlsx",
        log_label="WarningLetterExcelMaster",
    )


def get_cached_warning_letter_df():
    return _get_cached_excel_df(
        cache_key="warning_letter",
        source_getter=get_active_warning_letter_excel_source,
        sheet_name=[
            getattr(settings, "WARNING_LETTER_EXCEL_SHEET_NAME", None),
            "Final Files For Deploy",
            "Sheet1",
        ],
        log_label="Warning Letter Excel",
    )


def get_active_gmpc_excel(country):
    normalized_country = _normalize_country_cache_value(country)
    if not normalized_country:
        raise ValueError("Country is required for GMPC Excel cache lookup.")

    obj = (
        GMPCExcelMaster.objects
        .select_related("filters")
        .filter(is_active=True, active_excel_name__iexact=normalized_country)
        .order_by("-uploaded_at", "-pk")
        .first()
    )
    if not obj or not getattr(obj, "file", None):
        raise FileNotFoundError(f"No active GMPC found for country '{normalized_country}'.")

    return obj


def get_active_gmpc_excel_source(country, excel_obj=None):
    normalized_country = _normalize_country_cache_value(country)
    if not normalized_country:
        raise ValueError("Country is required for GMPC Excel cache lookup.")

    obj = excel_obj or get_active_gmpc_excel(normalized_country)
    print(f"[INFO] Active GMPC Excel object for {normalized_country}")
    file_path = obj.file.path
    file_sig = _build_file_signature(file_path)
    return {
        "path": file_path,
        "source_key": f"active:{obj.pk}:{file_sig}:{GMPC_EXCEL_CACHE_VERSION}",
        "active_id": obj.pk,
        "country": normalized_country,
    }


def build_card_url(key_url, key_value, url_type):
    if not key_value:
        return None

    if url_type == "mhra":
        val = key_value.lower()
        val = val.replace("[", "").replace("]", "")
        val = val.replace("/", "")
        val = re.sub(r"\s+", "-", val)
        val = re.sub(r"-+", "-", val)
        val = re.sub(r"[^a-z0-9\-]", "", val)

        return f"{key_url.rstrip('/')}/{val}"

    # default simple
    return f"{key_url}{key_value}"

def _normalize_gmpc_filter_config(filter_config):
    import json

    def parse_json_text(value, default):
        if value in (None, ""):
            return default
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return default
            try:
                return json.loads(stripped)
            except (TypeError, ValueError, json.JSONDecodeError):
                return default
        return value

    def normalize_string_list(value):
        parsed_value = parse_json_text(value, value)

        if isinstance(parsed_value, (list, tuple, set)):
            iterable = parsed_value
        elif parsed_value in (None, ""):
            iterable = []
        else:
            iterable = [parsed_value]

        return [
            str(item).strip()
            for item in iterable
            if str(item).strip()
        ]

    # ✅ RAW VALUES
    dynamic_filters = parse_json_text(
        filter_config.dynamic_filter if filter_config else [],
        [],
    )

    static_filters = parse_json_text(
        filter_config.static_filter if filter_config else {},
        {},
    )

    layout_config = parse_json_text(
        filter_config.layout_config if filter_config and filter_config.layout_config else {},
        {},
    )

    title_field_name = filter_config.title_field_name if filter_config and filter_config.title_field_name else None
    key_url = filter_config.key_url if filter_config and filter_config.key_url else None
    url_type = filter_config.url_type if filter_config and filter_config.url_type else None
    key_field_name = filter_config.key_field_name if filter_config and filter_config.key_field_name else None

    combined_fields = parse_json_text(
        filter_config.combined_fields if filter_config and filter_config.combined_fields else {},
        {},
    )

    # ✅ NORMALIZE
    dynamic_filters = normalize_string_list(dynamic_filters)

    static_filters = {
        str(key).strip(): value
        for key, value in static_filters.items()
        if str(key).strip()
    } if isinstance(static_filters, dict) else {}

    title_field_name = str(title_field_name).strip() if title_field_name else None
    key_url = str(key_url).strip() if key_url else None
    url_type = str(url_type).strip() if url_type else None
    key_field_name = str(key_field_name).strip() if key_field_name else None

    combined_fields = {
        str(key).strip(): normalize_string_list(value)
        for key, value in combined_fields.items()
        if str(key).strip()
    } if isinstance(combined_fields, dict) else {}

    # ✅ 🔥 NORMALIZE LAYOUT CONFIG (IMPORTANT)
    normalized_layout = {}

    if isinstance(layout_config, dict):
        rows = layout_config.get("rows", [])

        if isinstance(rows, list):
            clean_rows = []

            for row in rows:
                if isinstance(row, (list, tuple)):
                    clean_row = [
                        str(col).strip()
                        for col in row
                        if str(col).strip()
                    ]
                    if clean_row:
                        clean_rows.append(clean_row)

            if clean_rows:
                normalized_layout["rows"] = clean_rows

    # ✅ FINAL RETURN
    return (dynamic_filters, static_filters, title_field_name, normalized_layout,  key_url, url_type, key_field_name, combined_fields)

def _build_gmpc_card_fields(*, columns, row_values, key_column=None, title_column=None, combined_fields=None):
    def display_value(value):
        return value if str(value or "").strip() else "NA"

    combined_fields = combined_fields or {}
    column_positions = {column: index for index, column in enumerate(columns)}
    combined_by_first_column = {}
    hidden_columns = set()

    for label, source_columns in combined_fields.items():
        valid_columns = [column for column in source_columns if column in column_positions]
        if not valid_columns:
            continue

        first_column = min(valid_columns, key=lambda column: column_positions[column])
        combined_by_first_column.setdefault(first_column, []).append((label, valid_columns))
        hidden_columns.update(valid_columns)

    display_fields = {}

    for column in columns:
        if column in combined_by_first_column:
            for label, source_columns in combined_by_first_column[column]:
                combined_value = ", ".join(
                    value
                    for value in (row_values.get(source_column, "") for source_column in source_columns)
                    if value
                )
                display_fields[label] = display_value(combined_value)

        if column in hidden_columns or column == title_column:
            continue

        display_fields[column] = display_value(row_values.get(column, ""))

    return display_fields



def _parse_mhra_certificate_number(certificate_number):
    text = str(certificate_number or "").strip()

    result = {
        "auth_basis": "NA",
        "auth_no": "NA",
        "inspection_type": "NA",
        "product_variant": "NA",
        "variant_code": "NA",
        "inspection_ref": "NA",
        "sequence": "NA",
        "full_cert_no": text or "NA",
    }

    if not text or text.upper() == "NA":
        return result

    normalized_text = re.sub(r"\s+", " ", text)

    # ✅ FULL FORMAT MATCH (BEST CASE)
    match = re.match(
        r"^(?P<auth_basis>UK\s+[A-Za-z]+(?:\([A-Z]+\))?)\s+"
        r"(?P<auth_no>\d+)\s+Insp\s+"
        r"(?P<inspection_type>[A-Z]+(?:/[A-Z]+)*)\s+"
        r"(?P<tail>.+)$",
        normalized_text,
        flags=re.IGNORECASE,
    )

    if match:
        auth_basis = match.group("auth_basis").strip().upper()
        auth_no = match.group("auth_no").strip()
        inspection_type = match.group("inspection_type").strip().upper()
        tail = match.group("tail").strip()

    else:
        # 🔥 FALLBACK (handles "Insp GMP 17907/13988-0036")
        fallback = re.match(
            r"^Insp\s+(?P<inspection_type>[A-Z]+(?:/[A-Z]+)*)\s+(?P<tail>.+)$",
            normalized_text,
            flags=re.IGNORECASE,
        )

        if not fallback:
            return result

        auth_basis = "NA"
        auth_no = "NA"
        inspection_type = fallback.group("inspection_type").strip().upper()
        tail = fallback.group("tail").strip()

    # ✅ Extract Variant
    variant_match = re.search(r"\[([A-Za-z]+)\]\s*$", tail)
    variant_code = variant_match.group(1).upper() if variant_match else ""

    tail_without_variant = re.sub(r"\[[A-Za-z]+\]\s*$", "", tail).strip()

    # Defaults
    full_cert_no = tail_without_variant or "NA"
    inspection_ref = "NA"
    sequence = "NA"

    # ✅ Extract numbers
    cert_match = re.search(r"(\d+)/(\d+)-(\d+)", tail_without_variant)
    if cert_match:
        possible_auth = cert_match.group(1)
        inspection_ref = cert_match.group(2)
        sequence = cert_match.group(3)

        # 🔥 If auth_no missing → take from cert
        if auth_no == "NA":
            auth_no = possible_auth

    # ✅ Variant mapping
    variant_map = {
        "H": "Human[H]",
        "V": "Veterinary[V]",
        "I": "Investigational[I]",
    }

    result.update(
        {
            "auth_basis": auth_basis,
            "auth_no": auth_no,
            "inspection_type": inspection_type,
            "product_variant": variant_map.get(variant_code, "NA"),
            "variant_code": variant_code or "NA",
            "inspection_ref": inspection_ref,
            "sequence": sequence,
            "full_cert_no": (
                f"{full_cert_no}[{variant_code}]"
                if variant_code else full_cert_no
            ),
        }
    )

    return result

def _get_mhra_status_priority(value):
    normalized = str(value or "").strip().upper()
    if "NON" in normalized:
        return 2
    if normalized == "GMPC":
        return 1
    return 0


def _build_mhra_certificate_chip_label(breakdown):
    auth_basis = breakdown.get("auth_basis", "NA")
    auth_no = breakdown.get("auth_no", "NA")
    variant_code = breakdown.get("variant_code", "NA")
    chip_parts = [auth_basis]
    if auth_no != "NA":
        chip_parts.append(auth_no)
    label = " ".join(chip_parts).strip() or "NA"
    if variant_code != "NA":
        label = f"{label} [{variant_code}]"
    return label


def _clean_gmpc_title(title):
    if not title:
        return ""
    title_str = str(title)
    parts = re.split(r'(?i)\badditional\s+details\b', title_str, maxsplit=1)
    if parts:
        cleaned = parts[0].strip()
        cleaned = re.sub(r'[\s:,;-]+$', '', cleaned)
        return cleaned.strip()
    return title_str.strip()


def _build_mhra_grouped_cards(*, df, columns, key_column, title_column, combined_fields, key_url, url_type):
    grouped_cards = {}

    for row in df.itertuples(index=False, name=None):
        raw_row_dict = {}
        key_value = None
        title_value = None

        for col, val in zip(columns, row):
            clean_val = "" if _safe_cell_value(val) is None else _safe_cell_value(val)
            raw_row_dict[col] = clean_val

            if key_column and col == key_column:
                key_value = clean_val

            if title_column and col == title_column:
                title_value = clean_val

        # fallback title
        if not title_value:
            for col in columns:
                if col != key_column and raw_row_dict.get(col):
                    title_value = raw_row_dict[col]
                    break

        title_value = _clean_gmpc_title(title_value)

        row_dict = _build_gmpc_card_fields(
            columns=columns,
            row_values=raw_row_dict,
            key_column=key_column,
            title_column=title_column,
            combined_fields=combined_fields,
        )

        # ✅ Strong grouping key
        address_value = str(row_dict.get("Address", "NA") or "NA").strip()
        country_value = str(row_dict.get("Country", "NA") or "NA").strip()

        group_key = (
            str(title_value or "NA").strip().casefold(),
            address_value.casefold(),
            country_value.casefold(),
        )

        # ✅ Parse certificate (correct place ✔)
        certificate_number = row_dict.get("Certificate Number", "NA")
        breakdown = _parse_mhra_certificate_number(certificate_number)

        # ✅ Strong unique key (important)
        unique_cert_key = (
            breakdown.get("auth_no"),
            breakdown.get("inspection_ref"),
            breakdown.get("sequence"),
            breakdown.get("variant_code"),
        )

        certificate_entry = {
            "certificate_number": certificate_number,
            "detail_url": build_card_url(key_url, key_value, url_type),
            "chip_label": _build_mhra_certificate_chip_label(breakdown),
            **breakdown,
            "_unique_key": unique_cert_key,  # internal use
        }

        if group_key not in grouped_cards:
            grouped_cards[group_key] = {
                "title": title_value or "NA",
                "Address": address_value,
                "Country": country_value,
                "Inspection Date": row_dict.get("Inspection Date", "NA"),
                "GMPC or Non-compliance": row_dict.get("GMPC or Non-compliance", "NA"),
                "certificates": [],
                "_status_priority": _get_mhra_status_priority(
                    row_dict.get("GMPC or Non-compliance", "NA")
                ),
            }

        group = grouped_cards[group_key]

        # ✅ Update status priority
        current_priority = _get_mhra_status_priority(
            row_dict.get("GMPC or Non-compliance", "NA")
        )
        if current_priority > group["_status_priority"]:
            group["GMPC or Non-compliance"] = row_dict.get("GMPC or Non-compliance", "NA")
            group["_status_priority"] = current_priority

        # ✅ Proper deduplication
        existing_keys = {c["_unique_key"] for c in group["certificates"]}
        if unique_cert_key not in existing_keys:
            group["certificates"].append(certificate_entry)

    result_cards = []

    for group in grouped_cards.values():

        # ✅ Smart sorting (Human > Investigational > Others)
        def sort_priority(cert):
            code = cert.get("variant_code")
            if code == "H":
                return 1
            if code == "I":
                return 2
            return 3

        certificates = sorted(
            group["certificates"],
            key=lambda x: (sort_priority(x), x.get("chip_label", "")),
        )

        # remove internal key
        for cert in certificates:
            cert.pop("_unique_key", None)

        # ✅ Better selected certificate
        selected_certificate = certificates[0] if certificates else {
            "certificate_number": "NA",
            "detail_url": "",
            "chip_label": "NA",
            "auth_basis": "NA",
            "auth_no": "NA",
            "inspection_type": "NA",
            "product_variant": "NA",
            "variant_code": "NA",
            "inspection_ref": "NA",
            "sequence": "NA",
            "full_cert_no": "NA",
        }

        result_cards.append(
            {
                "title": group["title"],
                "Address": group["Address"],
                "Country": group["Country"],
                "Inspection Date": group["Inspection Date"],
                "GMPC or Non-compliance": group["GMPC or Non-compliance"],
                "certificates": certificates,
                "selected_certificate": selected_certificate,
                "certificate_count": len(certificates),
                "certificate_count_label": (
                    f"{len(certificates)} cert"
                    if len(certificates) == 1
                    else f"{len(certificates)} certs"
                ),
            }
        )

    return result_cards


def _build_gmpc_filter_config_key(*, source_key, dynamic_filters, static_filters):
    payload = {
        "source_key": source_key,
        "dynamic_filters": dynamic_filters,
        "static_filters": static_filters,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return f"{source_key}:{digest}"


def _build_gmpc_column_lookup(df):
    return {
        str(column).strip(): column
        for column in df.columns
        if str(column).strip()
    }


def _build_gmpc_filter_options_map(df, dynamic_filters, static_filters):
    def normalize_option(value):
        normalized_value = _safe_cell_value(value)
        return "" if normalized_value is None else normalized_value

    def build_filter_options(raw_options):
        return sorted(
            {
                normalized
                for normalized in (normalize_option(option) for option in raw_options)
                if normalized
            }
        )

    column_lookup = _build_gmpc_column_lookup(df)
    filter_options = {
        filter_name: build_filter_options(options)
        for filter_name, options in static_filters.items()
    }

    for column in dynamic_filters:
        actual_column = column_lookup.get(column)
        if column in filter_options or actual_column is None:
            continue
        filter_options[column] = build_filter_options(df[actual_column].tolist())

    return filter_options


def _build_gmpc_normalized_columns(df, filter_names):
    column_lookup = _build_gmpc_column_lookup(df)
    return {
        filter_name: df[actual_column].map(
            lambda value: "" if _safe_cell_value(value) is None else _safe_cell_value(value)
        )
        for filter_name in filter_names
        for actual_column in [column_lookup.get(filter_name)]
        if actual_column is not None
    }


def _resolve_gmpc_filter_options(*, df, filter_name, filter_options_map, selected_filters, normalized_columns):
    selected_values = selected_filters.get(filter_name, set())
    base_options = filter_options_map.get(filter_name, [])

    if selected_filters and filter_name in normalized_columns:
        mask = pd.Series(True, index=df.index)
        for other_filter, other_selected_values in selected_filters.items():
            if other_filter == filter_name:
                continue
            normalized_series = normalized_columns.get(other_filter)
            if normalized_series is None:
                continue
            mask &= normalized_series.isin(other_selected_values)

        available_values = set(normalized_columns[filter_name][mask].tolist())
        return [
            option
            for option in base_options
            if option in available_values or option in selected_values
        ]

    return base_options


def _build_gmpc_filter_definitions(*, filter_names, selected_filters):
    return [
        {
            "key": _get_gmpc_filter_param_key(filter_name),
            "name": filter_name,
            "options": [
                {
                    "value": option,
                    "selected": True,
                }
                for option in sorted(selected_filters.get(filter_name, set()))
            ],
        }
        for filter_name in filter_names
    ]


def _paginate_gmpc_filter_options(options, *, selected_values, page, page_size, query):
    query_text = str(query or "").strip().lower()

    filtered_options = [
        option
        for option in options
        if not query_text or query_text in option.lower() or option in selected_values
    ]

    selected_options = [option for option in filtered_options if option in selected_values]
    unselected_options = [option for option in filtered_options if option not in selected_values]
    ordered_options = selected_options + unselected_options

    paginator = Paginator(ordered_options, page_size)
    page_obj = paginator.get_page(page)
    page_items = list(page_obj.object_list) if paginator.count else []

    return {
        "options": [
            {
                "value": option,
                "selected": option in selected_values,
            }
            for option in page_items
        ],
        "page": page_obj.number if paginator.count else 1,
        "has_more": page_obj.has_next() if paginator.count else False,
        "total_options": paginator.count,
        "total_pages": paginator.num_pages if paginator.count else 0,
    }


def get_cached_gmpc_filter_options(*, country, source_key, df, dynamic_filters, static_filters):
    normalized_country = _normalize_country_cache_value(country)
    _, cache = _get_gmpc_cache_bucket(normalized_country)
    filter_options_source_key = _build_gmpc_filter_config_key(
        source_key=source_key,
        dynamic_filters=dynamic_filters,
        static_filters=static_filters,
    )

    if cache.get("filter_options_source_key") != filter_options_source_key:
        cache["filter_options"] = _build_gmpc_filter_options_map(
            df,
            dynamic_filters,
            static_filters,
        )
        cache["filter_options_source_key"] = filter_options_source_key
        print(f"[GMPC FILTER CACHE MISS] Rebuilt filter options for {normalized_country}")
    else:
        print(f"[GMPC FILTER CACHE HIT] Using cached filter options for {normalized_country}")

    return cache["filter_options"]

def _custom_gmpc_sort_key(item):
    site_name = str(item.get('site', '')).strip()
    if not site_name:
        return (3, "")
    first_char = site_name[0]
    if first_char.isalpha():
        group = 0
    elif first_char.isdigit():
        group = 1
    else:
        group = 2
    return (group, site_name.lower())

def get_gmpc_available_excel_names():
    return [
        {
            "value": (row["active_excel_name"] or "").strip().lower(),
            "label": (row["display_name"] or row["active_excel_name"] or "").strip(),
        }
        for row in (
            GMPCExcelMaster.objects
            .filter(is_active=True)
            .exclude(active_excel_name__isnull=True)
            .exclude(active_excel_name__exact="")
            .order_by("active_excel_name")
            .values("active_excel_name", "display_name")
            .distinct()
        )
    ]


def _get_selected_gmpc_active_excel_name(request):
    return _normalize_country_cache_value(
        request.GET.get("active_excel_name")
        or "eudra"
    ).lower()


def _get_gmpc_filter_param_key(filter_name):
    return f"filter_{slugify(filter_name)}"


def refresh_gmpc_excel_cache(*, country, baseline_path=None, baseline_source_key=None, source_info=None):
    normalized_country = _normalize_country_cache_value(country)
    cache_key, cache = _get_gmpc_cache_bucket(normalized_country)
    source_info = source_info or get_active_gmpc_excel_source(normalized_country)
    current_source_key = source_info["source_key"]

    baseline_df = None
    if baseline_path and os.path.exists(baseline_path):
        try:
            baseline_df = _read_excel_preferred_non_empty_sheet(
                baseline_path,
                sheet_name=[
                    getattr(settings, "GMPC_EXCEL_SHEET_NAME", None),
                    "Sheet1",
                ],
                log_label=f"GMPC Excel baseline [{normalized_country}]",
            )
            baseline_df = _normalize_excel_dataframe(baseline_df)
        except Exception as exc:
            print(f"[BASELINE][GMPC][{normalized_country}] Failed to read previous Excel: {exc}")

    current_df = _read_excel_preferred_non_empty_sheet(
        source_info["path"],
        sheet_name=[
            getattr(settings, "GMPC_EXCEL_SHEET_NAME", None),
            "Sheet1",
        ],
        log_label=f"GMPC Excel [{normalized_country}]",
    )
    current_df = _normalize_excel_dataframe(current_df)
    current_content_key = _build_dataframe_content_key(current_df)

    effective_previous_df = baseline_df
    effective_previous_source_key = baseline_source_key

    if effective_previous_df is None and cache["df"] is not None:
        effective_previous_df = cache["df"]
        effective_previous_source_key = cache["source_key"]

    if effective_previous_df is None:
        snapshot = _load_persisted_excel_snapshot(cache_key)
        if snapshot:
            effective_previous_df = snapshot.get("df")
            effective_previous_source_key = snapshot.get("source_key")

    previous_content_key = _build_dataframe_content_key(effective_previous_df)

    if effective_previous_df is not None and previous_content_key == current_content_key:
        print(f"[GMPC CACHE HIT] Reusing cached dataframe for {normalized_country}; Excel content unchanged.")
        cache["df"] = cache["df"] if cache["df"] is not None and cache.get("content_key") == current_content_key else effective_previous_df
        cache["path"] = source_info["path"]
        cache["source_key"] = current_source_key
        cache["content_key"] = current_content_key
        _persist_excel_snapshot(
            cache_key,
            source_key=current_source_key,
            source_path=source_info["path"],
            df=cache["df"],
        )
    else:
        print(f"[GMPC RELOAD] Loading new dataframe for {normalized_country}")
        cache["df"] = current_df
        cache["path"] = source_info["path"]
        cache["source_key"] = current_source_key
        cache["content_key"] = current_content_key
        _persist_excel_snapshot(
            cache_key,
            source_key=current_source_key,
            source_path=source_info["path"],
            df=current_df,
        )

    # Compute and save metrics in the DB
    try:
        from .models import GMPCExcelMaster
        excel_obj = GMPCExcelMaster.objects.filter(pk=source_info["active_id"]).first()
        if excel_obj:
            prev_df = None
            if baseline_path and os.path.exists(baseline_path):
                try:
                    prev_df = _get_gmpc_df_no_cache(baseline_path)
                except Exception as exc:
                    print(f"[CACHE] Failed to load baseline for metrics: {exc}")

            if prev_df is None:
                previous_excel = (
                    GMPCExcelMaster.objects
                    .filter(active_excel_name__iexact=normalized_country)
                    .exclude(pk=excel_obj.pk)
                    .order_by("-uploaded_at", "-pk")
                    .first()
                )
                if previous_excel and previous_excel.file:
                    try:
                        prev_df = _get_gmpc_df_no_cache(previous_excel.file.path)
                    except Exception as exc:
                        print(f"[CACHE] Failed to load previous db excel for metrics: {exc}")

            metrics = _calculate_gmpc_dashboard_metrics(cache["df"], prev_df, normalized_country)
            excel_obj.dashboard_metrics = metrics
            excel_obj.save(update_fields=["dashboard_metrics"])
            print(f"[CACHE] Calculated and saved dashboard metrics for {normalized_country} on GMPCExcelMaster pk={excel_obj.pk}")
    except Exception as e:
        print(f"[CACHE] Error saving metrics during cache refresh: {e}")
        import traceback
        traceback.print_exc()

    return cache["df"]


def get_cached_gmpc_df(country, source_info=None):
    normalized_country = _normalize_country_cache_value(country)
    _, cache = _get_gmpc_cache_bucket(normalized_country)
    source_info = source_info or get_active_gmpc_excel_source(normalized_country)

    if cache["df"] is None or cache["source_key"] != source_info["source_key"]:
        df = refresh_gmpc_excel_cache(
            country=normalized_country,
            source_info=source_info,
        )
    else:
        print(f"[GMPC CACHE HIT] Using cached GMPC Excel for {normalized_country}")
        df = cache["df"]

    if df is not None:
        try:
            excel = get_active_gmpc_excel(normalized_country)
            filter_config = getattr(excel, "filters", None)
            _, _, title_field_name, _, _, _, _, _ = _normalize_gmpc_filter_config(filter_config)
            if title_field_name:
                col_match = None
                for col in df.columns:
                    if str(col).strip().lower() == str(title_field_name).strip().lower():
                        col_match = col
                        break
                if col_match:
                    df[col_match] = df[col_match].apply(lambda x: _clean_gmpc_title(x) if x is not None else x)
        except Exception as exc:
            print(f"[GMPC DF CLEAN] Failed to clean title column: {exc}")

    return df


def refresh_form483_excel_cache(*, baseline_path=None, baseline_source_key=None):
    source_info = get_active_excel_source()
    baseline_df = None
    if baseline_path and os.path.exists(baseline_path):
        try:
            baseline_df = _read_excel_with_sheet_fallback(
                baseline_path,
                sheet_name="Sheet1",
                log_label="Excel baseline",
            )
            baseline_df = baseline_df.where(pd.notnull(baseline_df), None)
        except Exception as exc:
            print(f"[BASELINE][483] Failed to read previous Excel: {exc}")

    return _refresh_excel_cache_from_source_info(
        cache_key="observations",
        source_path=source_info["path"],
        source_key=_decorate_cache_source_key("observations", source_info["source_key"]),
        active_id=source_info.get("active_id"),
        sheet_name="Sheet1",
        log_label="Excel",
        baseline_df=baseline_df,
        baseline_source_key=_decorate_cache_source_key("observations", baseline_source_key)
        if baseline_source_key
        else None,
    )


def refresh_warning_letter_excel_cache(*, baseline_path=None, baseline_source_key=None):
    source_info = get_active_warning_letter_excel_source()
    baseline_df = None
    if baseline_path and os.path.exists(baseline_path):
        try:
            baseline_df = _read_excel_with_sheet_fallback(
                baseline_path,
                sheet_name=[
                    getattr(settings, "WARNING_LETTER_EXCEL_SHEET_NAME", None),
                    "Final Files For Deploy",
                    "Sheet1",
                ],
                log_label="Warning Letter Excel baseline",
            )
            baseline_df = baseline_df.where(pd.notnull(baseline_df), None)
        except Exception as exc:
            print(f"[BASELINE][WarningLetter] Failed to read previous Excel: {exc}")

    return _refresh_excel_cache_from_source_info(
        cache_key="warning_letter",
        source_path=source_info["path"],
        source_key=source_info["source_key"],
        active_id=source_info.get("active_id"),
        sheet_name=[
            getattr(settings, "WARNING_LETTER_EXCEL_SHEET_NAME", None),
            "Final Files For Deploy",
            "Sheet1",
        ],
        log_label="Warning Letter Excel",
        baseline_df=baseline_df,
        baseline_source_key=baseline_source_key,
    )

# AIMaster views
def homepage(request):
    return render(request, 'index.html')

# 483 views here
@login_required(login_url='/adminmaster/login/')
def show_form483_data(request):
    user = request.user


    # if not user.is_authenticated:
    #     return render(request, "483dashboard.html")
    report_name = "Form 483"
    # assignment = AssignChecker.objects.get(user=user)
    if True:
        queryset = Form483Master.objects.prefetch_related(
            'form483system_set__form483observation_set__form483obeservationcontent_set'
        )
        filter_set = Form483Filter(request.GET, queryset=queryset)
        paginator = Paginator(filter_set.qs, 10)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)
        show_flag = True
        context = {
            'filter': filter_set,
            'data': filter_set.qs,
            'data': page_obj,
            'page_obj': page_obj,
            'page_heading': 'Form 483 Observation Database - Drugs',
            "show_flag":show_flag,
        }
    else:
        show_flag = False
        context = {
            "show_flag":show_flag
        }
    # print("show_flag", show_flag)
    return render(request, '483homepage.html', context)

def get_unique_investigators_count(df):
    investigators = set()

    for raw_names in df['FDA Investigator(s) name'].dropna():
        names = [
            item.strip().lower()
            for item in str(raw_names)
                .replace("\r", ",")
                .replace("\n", ",")
                .split(",")
            if item.strip()
        ]
        investigators.update(names)

    return len(investigators)

def _get_investigator_observation_counts(df):
    investigator_stats = {}

    for _, row in df.iterrows():
        raw_names = row.get("FDA Investigator(s) name")
        if raw_names is None or pd.isna(raw_names):
            continue
        classification_value = str(row.get("Classification") or "").strip().upper()

        inspection_date = pd.to_datetime(
            row.get("Month of Inspection"),
            errors="coerce",
        )
        if pd.isna(inspection_date):
            inspection_year = pd.to_numeric(
                pd.Series([row.get("Year of Inspection")]),
                errors="coerce",
            ).iloc[0]
            if not pd.isna(inspection_year):
                inspection_date = pd.Timestamp(year=int(inspection_year), month=1, day=1)
        inspection_year_value = None
        if not pd.isna(inspection_date):
            inspection_year_value = int(inspection_date.year)
        else:
            parsed_year = pd.to_numeric(
                pd.Series([row.get("Year of Inspection")]),
                errors="coerce",
            ).iloc[0]
            if not pd.isna(parsed_year):
                inspection_year_value = int(parsed_year)

        inspection_key = row.get("FEI with Inspection End Date")
        if inspection_key is None or pd.isna(inspection_key) or str(inspection_key).strip() == "":
            company_name = str(row.get("Company Name") or "").strip()
            date_key = (
                inspection_date.strftime("%Y-%m-%d")
                if not pd.isna(inspection_date)
                else str(row.get("Month of Inspection") or "").strip()
            )
            inspection_key = f"{company_name}|{date_key}"

        investigator_names = [
            item.strip()
            for item in str(raw_names).replace("\r", ",").replace("\n", ",").split(",")
            if item.strip()
        ]

        for investigator_name in investigator_names:
            stat = investigator_stats.setdefault(
                investigator_name,
                {
                    "investigator_name": investigator_name,
                    "observation_count": 0,
                    "oai_observation_count": 0,
                    "vai_observation_count": 0,
                    "nai_observation_count": 0,
                    "_first_inspection": None,
                    "_last_inspection": None,
                    "_inspection_keys": set(),
                    "_resolved_inspection_keys": set(),
                    "_year_observation_counts": Counter(),
                },
            )
            stat["observation_count"] += 1
            if classification_value == "OAI":
                stat["oai_observation_count"] += 1
            elif classification_value == "VAI":
                stat["vai_observation_count"] += 1
            elif classification_value == "NAI":
                stat["nai_observation_count"] += 1
            stat["_inspection_keys"].add(str(inspection_key))
            if classification_value in {"OAI", "VAI", "NAI"}:
                stat["_resolved_inspection_keys"].add(str(inspection_key))

            if not pd.isna(inspection_date):
                if stat["_first_inspection"] is None or inspection_date < stat["_first_inspection"]:
                    stat["_first_inspection"] = inspection_date
                if stat["_last_inspection"] is None or inspection_date > stat["_last_inspection"]:
                    stat["_last_inspection"] = inspection_date
            if inspection_year_value is not None:
                stat["_year_observation_counts"][inspection_year_value] += 1

    investigator_rows = []
    for stat in investigator_stats.values():
        first_inspection = stat.pop("_first_inspection")
        last_inspection = stat.pop("_last_inspection")
        inspection_keys = stat.pop("_inspection_keys")
        resolved_inspection_keys = stat.pop("_resolved_inspection_keys")
        year_observation_counts = stat.pop("_year_observation_counts")

        unique_inspection_count = len(inspection_keys)
        stat["inspection_count"] = unique_inspection_count
        stat["resolved_inspection_count"] = len(resolved_inspection_keys)
        stat["oai_classification_rate"] = round(
            (stat["oai_observation_count"] / stat["observation_count"]) * 100,
            2,
        ) if stat["observation_count"] else 0
        stat["avg_483_observations_per_inspection"] = round(
            stat["observation_count"] / unique_inspection_count,
            2,
        ) if unique_inspection_count else 0

        if year_observation_counts:
            most_active_year, most_active_year_observations = max(
                year_observation_counts.items(),
                key=lambda item: (item[1], item[0]),
            )
            stat["most_active_year"] = int(most_active_year)
            stat["most_active_year_observation_count"] = int(most_active_year_observations)
        else:
            stat["most_active_year"] = None
            stat["most_active_year_observation_count"] = None

        if first_inspection is not None and last_inspection is not None:
            active_years = max(1, last_inspection.year - first_inspection.year + 1)
            active_years_text = "yr" if active_years == 1 else "yrs"
            stat["active_since"] = first_inspection.strftime("%b %Y")
            stat["last_inspection"] = last_inspection.strftime("%b %Y")
            stat["active_years"] = active_years
        else:
            stat["active_since"] = None
            stat["last_inspection"] = None
            stat["active_years"] = None

        oai = stat.get("oai_observation_count", 0)
        vai = stat.get("vai_observation_count", 0)
        nai = stat.get("nai_observation_count", 0)

        total = oai + vai + nai

        strictness = (
            (oai * 1.0) +
            (vai * 0.5) +
            (nai * 0.0)
        ) / total * 100 if total else 0

        stat["strictness_score"] = round(strictness, 2)

        if stat["strictness_score"] >= 80:
            stat["strictness_label"] = "Critical"
        elif stat["strictness_score"] >= 65:
            stat["strictness_label"] = "High"
        elif stat["strictness_score"] >= 50:
            stat["strictness_label"] = "Medium"
        else:
            stat["strictness_label"] = "Low"

        investigator_rows.append(stat)

    investigator_rows.sort(
        key=lambda row: (-row["inspection_count"], -row["strictness_score"], row["investigator_name"].lower())
    )
    return investigator_rows

def _get_auditiq_gmpc_total(country):
    try:
        excel = get_active_gmpc_excel(country)
        metrics = getattr(excel, "dashboard_metrics", None) or {}
        if metrics.get("total_certificates") is not None:
            return int(metrics.get("total_certificates") or 0)

        source_info = get_active_gmpc_excel_source(country, excel_obj=excel)
        df = get_cached_gmpc_df(country, source_info=source_info)
        return int(len(df)) if df is not None else 0
    except Exception as exc:
        print(f"[AUDITIQ][GMPC] Failed to load {country} total: {exc}")
        return 0


def _format_homepage_stat_count(value):
    try:
        return f"{int(value or 0):,}"
    except (TypeError, ValueError):
        return "0"


def _get_homepage_fda_observation_total():
    try:
        df = get_cached_df()
        return int(len(df)) if df is not None else 0
    except Exception as exc:
        print(f"[GMPC HOMEPAGE] Failed to load FDA 483 total from Excel: {exc}")
        try:
            return Form483Observation.objects.count()
        except Exception as db_exc:
            print(f"[GMPC HOMEPAGE] Failed to load FDA 483 total from database: {db_exc}")
            return 0


def auditiq_dashboard(request):
    context = {}
    try:
        df = get_cached_df()
        df = df.where(pd.notnull(df), None)
        df = df.rename(columns={"Year of Inspection": "Year"})
        df = df.dropna(subset=["Year", "System"])
        df["Year"] = df["Year"].astype(int)

        years = sorted(df["Year"].dropna().unique().tolist())

        context = {
            "Total_observations": len(df),
            "Total_Companies": df["Company Name"].nunique(),
            "Total_Investigators": get_unique_investigators_count(df),
            "Records_Indexed": 2400000,
            "min_year": min(years) if years else 2018,
            "max_year": max(years) if years else 2026,
        }
    except Exception as e:
        context["error"] = str(e)

    context.update({
        "usa_observations": context.get("Total_observations", 0),
        "eu_gmpc_records": _get_auditiq_gmpc_total("eudra"),
        "uk_gmpc_records": _get_auditiq_gmpc_total("mhra"),
    })

    return render(request, "auditiq.html", context)

def form483_dashboard(request):
    context = {}

    df = get_cached_df()
    df = df.where(pd.notnull(df), None)
    df = df.rename(columns={"Year of Inspection": "Year"})
    df = df.dropna(subset=["Year", "System"])
    df["Year"] = df["Year"].astype(int)

    context["Total_observations"] = len(df)
    context["Total_Companies"] = df["Company Name"].nunique()

    years = sorted(df["Year"].dropna().unique().tolist())
    context["chart1labels"] = years

    system_sequence = [
        "Quality System",
        "Laboratory Control System",
        "Material System",
        "Packaging and Labelling System",
        "Production System",
        "Facilites & Equipment System",
    ]
    context["system_sequence"] = system_sequence

    system_labels_map = {
        "quality system": "Quality System",
        "laboratory control system": "Laboratory Control System",
        "production system": "Production System",
        "material system": "Material System",
        "packaging and labeling system": "Packaging and Labelling System",
        "packaging and labelling system": "Packaging and Labelling System",
        "facilities and equipment system": "Facilites & Equipment System",
        "facilities & equipment system": "Facilites & Equipment System",
        "facility & equipment system": "Facilites & Equipment System",
    }

    df["System"] = df["System"].astype(str).str.strip().str.lower()
    df["System"] = df["System"].map(system_labels_map)
    df = df[df["System"].notna()]

    pivot = df.groupby(["System", "Year"]).size().unstack(fill_value=0)
    final_data = {}
    for system in system_sequence:
        final_data[system] = [
            int(pivot.at[system, y]) if (system in pivot.index and y in pivot.columns) else 0
            for y in years
        ]

    context["chart1data"] = final_data

    system_counts = df["System"].value_counts()
    context["system_labels"] = system_sequence
    context["system_data"] = [int(system_counts.get(system, 0)) for system in system_sequence]

    investigator_series = (
        df['FDA Investigator(s) name']
        .dropna()
        .astype(str)
        .str.rstrip(', ')
        .str.split(',')
        .explode()
        .str.strip()
        .str.lower()
        .replace('', pd.NA)
        .dropna()
    )
    investigator_counts = Counter(investigator_series)
    top_10 = investigator_counts.most_common(10)

    top_10_df = pd.DataFrame(top_10, columns=["Investigator", "Count"])

    context["top_investigators"] = [
        {"name": name, "count": int(count)}
        for name, count in top_10_df[["Investigator", "Count"]].itertuples(index=False, name=None)
    ]

    df["Type of establishment"] = df["Type of establishment"].str.strip()

    establishment_labels = [
        "API Manufacturer",
        "Contract Drug Manufacturer",
        "Prescription (Rx) Drug Manufacturer",
    ]

    establishment_data = [
        int(df[df["Type of establishment"] == label].shape[0])
        for label in establishment_labels
    ]

    context["establishment_labels"] = establishment_labels
    context["establishment_data"] = establishment_data

    user = request.user
    if request.user.is_authenticated:
        assignment = AssignChecker.objects.get(user=user)
        context["flag"] = "Form 483" in assignment.assigned_report
    else:
        context["flag"] = False
    context["Total_Investigators"] = get_unique_investigators_count(df)
    context["available_excel_names"] = get_gmpc_available_excel_names()
    context["selected_active_excel_name"] = "usa"

    return render(request, "483dashboard.html",context)

# ANDA views here
@login_required(login_url='/adminmaster/login/')
def anda_ectd_acceptance_deficiency(request):
    report_name = "ANDA ECTD"
    user = request.user
    assignment = AssignChecker.objects.get(user=user)
    if report_name in assignment.assigned_report:
        queryset = ANDAeCTD.objects.all().values('dosage', 'cmc_clinic', 'deficiency_type', 'deficiency')
        original_total_count = ANDAeCTD.objects.count()
        anda_filter = ANDAeCTDFilter(request.GET, queryset=queryset)
        paginator = Paginator(anda_filter.qs, 10)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)

        if request.GET.get("csrfmiddlewaretoken", False):
            columns = {
                'deficiency': 'Deficiency'
            }
            table_headers = ['Deficiency']
            is_filter = True
        else:
            columns = {
                    'dosage': 'Dosage',
                    # 'cmc_clinic': 'CMC/Clinic',
                    'deficiency_type': 'Deficiency Type',
                    'deficiency': 'Deficiency'
                }
            # table_headers = ['Dosage Form', 'CMC/Clinic', 'Deficiency Type', 'Deficiency']
            table_headers = ['Dosage Form', 'Deficiency Type', 'Deficiency']
            is_filter = False
        dosage = request.GET.get('dosage')
        cmc_clinic = request.GET.get('cmc_clinic')
        deficiency_type = request.GET.get('deficiency_type')
        context = {
                'dosage_form':dosage,
                'cmc_clinic':cmc_clinic,
                'deficiency_type':deficiency_type,
                'table_headers': table_headers,
                'page_heading': 'FDA - eCTD Acceptance Deficiency',
                'filter': anda_filter,
                'data': anda_filter.qs.values(
                *columns.keys()

            ),
                'full_data': anda_filter.qs.values(
                *columns.keys()

            ),
                'columns': columns,
                'ectd_acceptance_deficiency': True,
                'data': page_obj,
                'page_obj': page_obj,
                "is_filter":is_filter,
                "show_flag":True,
                "original_total_count": original_total_count,

            }
    else:
        context = {
            "show_flag":False
        }

    return render(request, 'AIDatabase/ANDA/ANDAeCTDBase.html', context)

@login_required(login_url='/adminmaster/login/')
def anda_technical_acceptance_deficiency(request):
    user = request.user
    report_name = "ANDA Technical Acceptance"
    if report_name in AssignChecker.objects.get(user=user).assigned_report:
        queryset = ANDATechnicalAcceptance.objects.all().values('dosage_form', 'type_of_dosage_form', 'deficiency_type', 'deficiency')
        original_total_count = ANDATechnicalAcceptance.objects.count()
        anda_filter = ANDATechnicalAcceptanceFilter(request.GET, queryset=queryset)
        paginator = Paginator(anda_filter.qs, 10)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)
        if request.GET.get("csrfmiddlewaretoken", False):
            columns = {
                'deficiency': 'Deficiency'
            }
            table_headers = ['Deficiency']
            is_filter = True

        else:
            columns = {
                    'dosage_form': 'Dosage Form',
                    # 'type_of_dosage_form': 'Type of Dosage Form',
                    'deficiency_type': 'Deficiency Type',
                    'deficiency': 'Deficiency'
                }
            table_headers = ['Dosage Form', 'Deficiency Type', 'Deficiency']
            is_filter = False
        dosage_form = request.GET.get('dosage_form')
        type_of_dosage_form = request.GET.get('type_of_dosage_form')
        deficiency_type = request.GET.get('deficiency_type')
        context = {
                'dosage_form':dosage_form,
                'type_of_dosage_form':type_of_dosage_form,
                'deficiency_type':deficiency_type,
                "is_filter":is_filter,
                'table_headers': table_headers,
                'page_heading': 'FDA - ANDA Acceptance Deficiency',
                'filter': anda_filter,
                'data': anda_filter.qs.values(
                *columns.keys()
            ),
                'full_data': anda_filter.qs.values(
                *columns.keys()
            ),
                'columns': columns,
                'data': page_obj,
                'page_obj': page_obj,
                'technical_acceptance_deficiency': True,
                'data': page_obj,
                'page_obj': page_obj,
                "show_flag":True,
                "original_total_count": original_total_count,
            }
    else:
        context = {
            "show_flag":False
        }
    return render(request, 'AIDatabase/ANDA/ANDATechnicalAcceptanceBase.html', context)


@login_required(login_url='/adminmaster/login/')
def anda_nasal_spray_deficiency(request):
    user = request.user
    report_name = "ANDA Nasal Spary-Deficiency"
    assignment = AssignChecker.objects.get(user=user)
    if report_name in assignment.assigned_report:
        data = ANDA.objects.filter(main_cateogry='Nasal Spray-Deficiency').values('dosage_form', 'cmc_section', 'deficiency_type', 'category_of_deficiency', 'deficiency')
        anda_filter = ANDAFilter(request.GET, queryset=data, main_category='Nasal Spray-Deficiency')
        original_total_count = data.count()

        paginator = Paginator(anda_filter.qs, 10)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)
        if request.GET.get("csrfmiddlewaretoken",False):
            columns = {
                'deficiency':'Deficiency'
            }
            table_headers = ['Deficiency']
            is_filter = True
        else:
            columns = {
                "dosage_form": "Dosage Form",
                "cmc_section": "CMC Section",
                "deficiency_type": "Deficiency Type",
                "category_of_deficiency": "Category of Deficiency'",
                "deficiency": "Deficiency",
            }
            table_headers = ['CMC Section', 'Deficiency Type', 'Category of Deficiency', 'Deficiency']
            is_filter = False
        cmc_section = request.GET.get('cmc_section')
        deficiency_type = request.GET.get('deficiency_type')
        category_of_deficiency = request.GET.get('category_of_deficiency')
        context = {
            'category_of_deficiency':category_of_deficiency,
            'cmc_section':cmc_section,
            'deficiency_type':deficiency_type,
            'is_filter':is_filter,
            'table_headers':table_headers,
            'page_heading': 'FDA - Nasal Spray Deficiency',
            "filter": anda_filter,
            "data": anda_filter.qs.values(
                *columns.keys()
            ),
            'nasal_spray_deficiency': True,
            "columns": columns,
            'data': page_obj,
            'full_data' : anda_filter.qs.values(
                *columns.keys()
            ),
            'page_obj': page_obj,
            "show_flag":True,
            "original_total_count": original_total_count,
        }
    else:
        context = {
            "show_flag":False
        }
    return render(request, 'AIDatabase/ANDA/ANDABase.html', context)


@login_required(login_url='/adminmaster/login/')
def anda_liquid_oral_deficiency(request):
    user = request.user
    report_name = "ANDA Liquid Oral-Deficiency"
    assignment = AssignChecker.objects.get(user=user)
    if report_name in assignment.assigned_report:
        data = ANDA.objects.filter(main_cateogry='Liquid Oral-Deficiency').values('dosage_form', 'cmc_section', 'deficiency_type', 'category_of_deficiency', 'deficiency')
        anda_filter = ANDAFilter(request.GET, queryset=data, main_category='Liquid Oral-Deficiency')
        original_total_count = data.count()

        paginator = Paginator(anda_filter.qs, 10)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)
        if request.GET.get("csrfmiddlewaretoken",False):
            columns = {
                'deficiency':'Deficiency'
            }
            table_headers = ['Deficiency']
            is_filter = True
        else:
            columns = {
                "dosage_form": "Dosage Form",
                "cmc_section": "CMC Section",
                "deficiency_type": "Deficiency Type",
                "category_of_deficiency": "Category of Deficiency'",
                "deficiency": "Deficiency",
            }
            table_headers = ['Dosage Type', 'CMC Section', 'Deficiency Type', 'Category of Deficiency', 'Deficiency']
            is_filter = False
        dosage_form = request.GET.get('dosage_form')
        cmc_section = request.GET.get('cmc_section')
        deficiency_type = request.GET.get('deficiency_type')
        category_of_deficiency = request.GET.get('category_of_deficiency')
        context = {
            'dosage_form':dosage_form,
            'category_of_deficiency':category_of_deficiency,
            'cmc_section':cmc_section,
            'deficiency_type':deficiency_type,
            'is_filter':is_filter,
            'table_headers':table_headers,
            'page_heading': 'FDA - Liquid Oral-Deficiency',
            'filter': anda_filter,
            'data': anda_filter.qs.values(
                *columns.keys()
            ),
            'full_data': anda_filter.qs.values(
                *columns.keys()
            ),
            'columns': columns,
            'liquid_oral_deficiency': True,
            'data': page_obj,
            'page_obj': page_obj,
            "show_flag":True,
            "original_total_count": original_total_count,

        }
    else:
        context = {
            "show_flag":False
        }
    return render(request, 'AIDatabase/ANDA/ANDABase.html', context)

@login_required(login_url='/adminmaster/login/')
def anda_iud_deficiency(request):
    user = request.user
    report_name = "ANDA IUD-Deficiency"
    assignment = AssignChecker.objects.get(user=user)
    if report_name in assignment.assigned_report:
        queryset = ANDA.objects.filter(main_cateogry='IUD-Deficiency')
        anda_filter = ANDAFilter(request.GET, queryset=queryset, main_category='IUD-Deficiency')
        original_total_count = queryset.count()

        paginator = Paginator(anda_filter.qs, 10)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)
        if request.GET.get("csrfmiddlewaretoken",False):
            columns = {
                'deficiency':'Deficiency'
            }
            table_headers = ['Deficiency']
            is_filter = True
        else:
            columns = {
                "dosage_form": "Dosage Form",
                "cmc_section": "CMC Section",
                "deficiency_type": "Deficiency Type",
                "category_of_deficiency": "Category of Deficiency'",
                "deficiency": "Deficiency",
            }
            table_headers = ['CMC Section', 'Deficiency Type', 'Category of Deficiency', 'Deficiency']
            is_filter = False
        cmc_section = request.GET.get('cmc_section')
        deficiency_type = request.GET.get('deficiency_type')
        category_of_deficiency = request.GET.get('category_of_deficiency')
        context = {
                'category_of_deficiency':category_of_deficiency,
                'cmc_section':cmc_section,
                'deficiency_type':deficiency_type,
                'is_filter':is_filter,
                'table_headers': table_headers,
                'page_heading': 'FDA - IUD-Deficiency',
                'filter': anda_filter,
                'data': anda_filter.qs.values(
                *columns.keys()
            ),
                'full_data': anda_filter.qs.values(
                *columns.keys()
            ),
                'columns': columns,
                'iud_deficiency': True,
                'data': page_obj,
                'page_obj': page_obj,
                "show_flag":True,
                "original_total_count": original_total_count,

        }
    else:
        context={
            "show_flag":False
        }
    return render(request, 'AIDatabase/ANDA/ANDABase.html', context)


@login_required(login_url='/adminmaster/login/')
def anda_tdds_deficiency(request):
    user = request.user
    report_name = "ANDA TDDS-Deficiency"
    assignment = AssignChecker.objects.get(user=user)
    if report_name in assignment.assigned_report:
        queryset = ANDA.objects.filter(main_cateogry='TDDS-Deficiency')
        anda_filter = ANDAFilter(request.GET, queryset=queryset, main_category='TDDS-Deficiency')
        original_total_count = queryset.count()

        paginator = Paginator(anda_filter.qs, 10)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)
        if request.GET.get("csrfmiddlewaretoken",False):
            columns = {
                'deficiency':'Deficiency'
            }
            table_headers = ['Deficiency']
            is_filter = True
        else:
            columns = {
                "dosage_form": "Dosage Form",
                "cmc_section": "CMC Section",
                "deficiency_type": "Deficiency Type",
                "category_of_deficiency": "Category of Deficiency'",
                "deficiency": "Deficiency",
            }
            table_headers = ['Dosage Type', 'CMC Section', 'Deficiency Type', 'Category of Deficiency', 'Deficiency']
            is_filter = False
        dosage_form = request.GET.get('dosage_form')
        cmc_section = request.GET.get('cmc_section')
        deficiency_type = request.GET.get('deficiency_type')
        category_of_deficiency = request.GET.get('category_of_deficiency')
        context = {
                'dosage_form':dosage_form,
                'category_of_deficiency':category_of_deficiency,
                'cmc_section':cmc_section,
                'deficiency_type':deficiency_type,
                'is_filter':is_filter,
                'table_headers': table_headers,
                'page_heading': 'FDA - TDDS-Deficiency',
                'filter': anda_filter,
                'data': anda_filter.qs.values(
                *columns.keys()
            ),
                'full_data': anda_filter.qs.values(
                *columns.keys()
            ),
                'columns': columns,
                'tdds_deficiency': True,
                'data': page_obj,
                'page_obj': page_obj,
                "show_flag":True,
                "original_total_count": original_total_count,

        }
    else:
        context={
            "show_flag":False
        }
    return render(request, 'AIDatabase/ANDA/ANDABase.html', context)


@login_required(login_url='/adminmaster/login/')
def anda_suppository_deficiency(request):
    user = request.user
    report_name = "ANDA Suppository-Deficiency"
    assignment = AssignChecker.objects.get(user=user)
    if report_name in assignment.assigned_report:
        queryset = ANDA.objects.filter(main_cateogry='Suppository-Deficiency')
        anda_filter = ANDAFilter(request.GET, queryset=queryset, main_category='Suppository-Deficiency')
        original_total_count = queryset.count()

        paginator = Paginator(anda_filter.qs, 10)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)
        if request.GET.get("csrfmiddlewaretoken",False):
            columns = {
                'deficiency':'Deficiency'
            }
            table_headers = ['Deficiency']
            is_filter = True
        else:
            columns = {
                "dosage_form": "Dosage Form",
                "cmc_section": "CMC Section",
                "deficiency_type": "Deficiency Type",
                "category_of_deficiency": "Category of Deficiency'",
                "deficiency": "Deficiency",
            }
            table_headers = ['CMC Section', 'Deficiency Type', 'Category of Deficiency', 'Deficiency']
            is_filter = False
        cmc_section = request.GET.get('cmc_section')
        deficiency_type = request.GET.get('deficiency_type')
        category_of_deficiency = request.GET.get('category_of_deficiency')
        context = {
                'category_of_deficiency':category_of_deficiency,
                'cmc_section':cmc_section,
                'deficiency_type':deficiency_type,
                'is_filter':is_filter,
                'table_headers':table_headers,
                'page_heading': 'FDA - Suppository-Deficiency',
                'filter': anda_filter,
                'data': anda_filter.qs.values(
                *columns.keys()
            ),
                'full_data': anda_filter.qs.values(
                *columns.keys()
            ),
                'columns': columns,
                'suppository_deficiency': True,
                'data': page_obj,
                'page_obj': page_obj,
                "show_flag":True,
                "original_total_count": original_total_count,

        }
    else:
        context = {
            "show_flag":False
        }
    return render(request, 'AIDatabase/ANDA/ANDABase.html', context)


@login_required(login_url='/adminmaster/login/')
def anda_topicals_deficiency(request):
    user = request.user
    report_name = "ANDA Topicals-Deficiency"
    assignment = AssignChecker.objects.get(user=user)
    if report_name in assignment.assigned_report:
        queryset = ANDA.objects.filter(main_cateogry='Topicals-Deficiency')
        anda_filter = ANDAFilter(request.GET, queryset=queryset, main_category='Topicals-Deficiency')
        original_total_count = queryset.count()

        paginator = Paginator(anda_filter.qs, 10)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)
        if request.GET.get("csrfmiddlewaretoken",False):
            columns = {
                'deficiency':'Deficiency'
            }
            table_headers = ['Deficiency']
            is_filter = True
        else:
            columns = {
                "dosage_form": "Dosage Form",
                "cmc_section": "CMC Section",
                "deficiency_type": "Deficiency Type",
                "category_of_deficiency": "Category of Deficiency'",
                "deficiency": "Deficiency",
            }
            table_headers = ['Dosage Type', 'CMC Section', 'Deficiency Type', 'Category of Deficiency', 'Deficiency']
            is_filter = False
        dosage_form = request.GET.get('dosage_form')
        cmc_section = request.GET.get('cmc_section')
        deficiency_type = request.GET.get('deficiency_type')
        category_of_deficiency = request.GET.get('category_of_deficiency')
        context = {
                'dosage_form':dosage_form,
                'category_of_deficiency':category_of_deficiency,
                'cmc_section':cmc_section,
                'deficiency_type':deficiency_type,
                'is_filter':is_filter,
                'table_headers':table_headers,
                'page_heading': 'FDA - Topicals-Deficiency',
                'filter': anda_filter,
                'data': anda_filter.qs.values(
                *columns.keys()
            ),
                'full_data': anda_filter.qs.values(
                *columns.keys()
            ),
                'columns': columns,
                'topicals_deficiency': True,
                'data': page_obj,
                'page_obj': page_obj,
                "show_flag":True,
                "original_total_count": original_total_count,

        }
    else:
        context = {
            "show_flag":False
        }
    return render(request, 'AIDatabase/ANDA/ANDABase.html', context)


@login_required(login_url='/adminmaster/login/')
def anda_solid_oral_deficiency(request):
    user = request.user
    report_name = "ANDA Solid Oral-Deficiency"
    assignment = AssignChecker.objects.get(user=user)
    if report_name in assignment.assigned_report:
        queryset = ANDA.objects.filter(main_cateogry='Solid Oral-Deficiency')
        anda_filter = ANDAFilter(request.GET, queryset=queryset, main_category='Solid Oral-Deficiency')
        original_total_count = queryset.count()

        paginator = Paginator(anda_filter.qs, 10)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)
        if request.GET.get("csrfmiddlewaretoken",False):
            columns = {
                'deficiency':'Deficiency'
            }
            table_headers = ['Deficiency']
            is_filter = True
        else:
            columns = {
                "dosage_form": "Dosage Form",
                "cmc_section": "CMC Section",
                "deficiency_type": "Deficiency Type",
                "category_of_deficiency": "Category of Deficiency'",
                "deficiency": "Deficiency",
            }
            table_headers = ['Dosage Type', 'CMC Section', 'Deficiency Type', 'Category of Deficiency', 'Deficiency']
            is_filter = False
        dosage_form = request.GET.get('dosage_form')
        cmc_section = request.GET.get('cmc_section')
        deficiency_type = request.GET.get('deficiency_type')
        category_of_deficiency = request.GET.get('category_of_deficiency')
        context = {
                'dosage_form':dosage_form,
                'category_of_deficiency':category_of_deficiency,
                'cmc_section':cmc_section,
                'deficiency_type':deficiency_type,
                'is_filter':is_filter,
                'table_headers':table_headers,
                'page_heading': 'FDA - Solid Oral-Deficiency',
                'filter': anda_filter,
                'data': anda_filter.qs.values(
                *columns.keys()
            ),
                'full_data': anda_filter.qs.values(
                *columns.keys()
            ),
                'columns': columns,
                'solid_oral_deficiency': True,
                'data': page_obj,
                'page_obj': page_obj,
                "show_flag":True,
                "original_total_count": original_total_count,

        }
    else:
        context = {
            "show_flag":False
        }
    return render(request, 'AIDatabase/ANDA/ANDABase.html', context)


@login_required(login_url='/adminmaster/login/')
def anda_otic_deficiency(request):
    user = request.user
    report_name = "ANDA Otic - Deficiency"
    assignment = AssignChecker.objects.get(user=user)
    if report_name in assignment.assigned_report:
        queryset = ANDA.objects.filter(main_cateogry='Otic - Deficiency')
        anda_filter = ANDAFilter(request.GET, queryset=queryset, main_category='Otic - Deficiency')
        original_total_count = queryset.count()

        paginator = Paginator(anda_filter.qs, 10)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)
        if request.GET.get("csrfmiddlewaretoken",False):
            columns = {
                'deficiency':'Deficiency'
            }
            table_headers = ['Deficiency']
            is_filter = True
        else:
            columns = {
                "dosage_form": "Dosage Form",
                "cmc_section": "CMC Section",
                "deficiency_type": "Deficiency Type",
                "category_of_deficiency": "Category of Deficiency'",
                "deficiency": "Deficiency",
            }
            table_headers = ['CMC Section', 'Deficiency Type', 'Category of Deficiency', 'Deficiency']
            is_filter = False
        cmc_section = request.GET.get('cmc_section')
        deficiency_type = request.GET.get('deficiency_type')
        category_of_deficiency = request.GET.get('category_of_deficiency')
        context = {
                'category_of_deficiency':category_of_deficiency,
                'cmc_section':cmc_section,
                'deficiency_type':deficiency_type,
                'is_filter':is_filter,
                'table_headers':table_headers,
                'page_heading': 'FDA - Otic - Deficiency',
                'filter': anda_filter,
                'data': anda_filter.qs.values(
                *columns.keys()
            ),
                'full_data': anda_filter.qs.values(
                *columns.keys()
            ),
                'columns': columns,
                'otic_deficiency': True,
                'data': page_obj,
                'page_obj': page_obj,
                "show_flag":True,
                "original_total_count": original_total_count,

            }
    else:
        context = {
            "show_flag":False
        }
    return render(request, 'AIDatabase/ANDA/ANDABase.html', context)


@login_required(login_url='/adminmaster/login/')
def anda_ophthalmic_deficiency(request):
    user = request.user
    report_name = "ANDA Ophthalmic - Deficiency"
    assignment = AssignChecker.objects.get(user=user)
    if report_name in assignment.assigned_report:
        queryset = ANDA.objects.filter(main_cateogry=' Ophthalmic - Deficiency')
        anda_filter = ANDAFilter(request.GET, queryset=queryset, main_category=' Ophthalmic - Deficiency')
        original_total_count = queryset.count()

        paginator = Paginator(anda_filter.qs, 10)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)
        if request.GET.get("csrfmiddlewaretoken",False):
            columns = {
                'deficiency':'Deficiency'
            }
            table_headers = ['Deficiency']
            is_filter = True
        else:
            columns = {
                "dosage_form": "Dosage Form",
                "cmc_section": "CMC Section",
                "deficiency_type": "Deficiency Type",
                "category_of_deficiency": "Category of Deficiency'",
                "deficiency": "Deficiency",
            }
            table_headers = ['Dosage Type', 'CMC Section', 'Deficiency Type', 'Category of Deficiency', 'Deficiency']
            is_filter = False
        dosage_form = request.GET.get('dosage_form')
        cmc_section = request.GET.get('cmc_section')
        deficiency_type = request.GET.get('deficiency_type')
        category_of_deficiency = request.GET.get('category_of_deficiency')
        context = {
                'dosage_form':dosage_form,
                'category_of_deficiency':category_of_deficiency,
                'cmc_section':cmc_section,
                'deficiency_type':deficiency_type,
                'is_filter':is_filter,
                'table_headers':table_headers,
                'page_heading': 'FDA - Ophthalmic - Deficiency',
                'filter': anda_filter,
                'data': anda_filter.qs.values(
                *columns.keys()
            ),
                'full_data': anda_filter.qs.values(
                *columns.keys()
            ),
                'columns': columns,
                'ophthalmic_deficiency': True,
                'data': page_obj,
                'page_obj': page_obj,
                "show_flag":True,
                "original_total_count": original_total_count,

            }
    else:
        context = {
            "show_flag":False
        }
    return render(request, 'AIDatabase/ANDA/ANDABase.html', context)



@login_required(login_url='/adminmaster/login/')
def anda_injectable_peptide_deficiency(request):
    user = request.user
    report_name = "ANDA Injectable - Peptide Deficiency"
    assignment = AssignChecker.objects.get(user=user)
    if report_name in assignment.assigned_report:
        queryset = ANDA.objects.filter(main_cateogry='Injectable - Peptide Deficiency')
        anda_filter = ANDAFilter(request.GET, queryset=queryset, main_category='Injectable - Peptide Deficiency')
        original_total_count = queryset.count()

        paginator = Paginator(anda_filter.qs, 10)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)
        if request.GET.get("csrfmiddlewaretoken",False):
            columns = {
                'deficiency':'Deficiency'
            }
            table_headers = ['Deficiency']
            is_filter = True
        else:
            columns = {
                "cmc_section": "CMC Section",
                "deficiency_type": "Deficiency Type",
                "category_of_deficiency": "Category of Deficiency'",
                "deficiency": "Deficiency",
            }
            table_headers = ['CMC Section', 'Deficiency Type', 'Category of Deficiency', 'Deficiency']
            is_filter = False
        cmc_section = request.GET.get('cmc_section')
        deficiency_type = request.GET.get('deficiency_type')
        category_of_deficiency = request.GET.get('category_of_deficiency')
        context = {
                'category_of_deficiency':category_of_deficiency,
                'cmc_section':cmc_section,
                'deficiency_type':deficiency_type,
                'is_filter':is_filter,
                'table_headers':table_headers,
                'page_heading': 'FDA - Injectable - Peptide Deficiency',
                'filter': anda_filter,
                'data': anda_filter.qs.values(
                *columns.keys()
            ),
                'full_data': anda_filter.qs.values(
                *columns.keys()
            ),
                'columns': columns,
                'injectable_peptide_deficiency': True,
                'data': page_obj,
                'page_obj': page_obj,
                "show_flag":True,
                "original_total_count": original_total_count,

        }
    else:
        context = {
            "show_flag":False
        }
    return render(request, 'AIDatabase/ANDA/ANDABase.html', context)



@login_required(login_url='/adminmaster/login/')
def anda_injectable_general_deficiency(request):
    user = request.user
    report_name = "ANDA Injectable - General Deficiency"
    assignment = AssignChecker.objects.get(user=user)
    if report_name in assignment.assigned_report:
        queryset = ANDA.objects.filter(main_cateogry='Injectable - General Deficiency')
        anda_filter = ANDAFilter(request.GET, queryset=queryset, main_category='Injectable - General Deficiency')
        original_total_count = queryset.count()

        paginator = Paginator(anda_filter.qs, 10)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)
        if request.GET.get("csrfmiddlewaretoken",False):
            columns = {
                'deficiency':'Deficiency'
            }
            table_headers = ['Deficiency']
            is_filter = True
        else:
            columns = {
                "dosage_form": "Dosage Form",
                "cmc_section": "CMC Section",
                "deficiency_type": "Deficiency Type",
                "category_of_deficiency": "Category of Deficiency'",
                "deficiency": "Deficiency",
            }
            table_headers = ['Dosage Type', 'CMC Section', 'Deficiency Type', 'Category of Deficiency', 'Deficiency']
            is_filter = False

        dosage_form = request.GET.get('dosage_form')
        cmc_section = request.GET.get('cmc_section')
        deficiency_type = request.GET.get('deficiency_type')
        category_of_deficiency = request.GET.get('category_of_deficiency')
        context = {
                'dosage_form':dosage_form,
                'category_of_deficiency':category_of_deficiency,
                'cmc_section':cmc_section,
                'deficiency_type':deficiency_type,
                'table_headers': table_headers,
                'is_filter':is_filter,
                'page_heading': 'FDA - Injectable - General Deficiency',
                'filter': anda_filter,
                'data': anda_filter.qs.values(
                *columns.keys()
            ),
                'full_data': anda_filter.qs.values(
                *columns.keys()
            ),
                'columns': columns,
                'injectable_general_deficiency': True,
                'data': page_obj,
                'page_obj': page_obj,
                "show_flag":True,
                "original_total_count": original_total_count,

        }
    else:
        context = {
            "show_flag":False
        }
    return render(request, 'AIDatabase/ANDA/ANDABase.html', context)



# Major CR views here
@login_required(login_url='/adminmaster/login/')
def show_major_cr(request):
    context = {'page_heading': 'Major CR AI Database'}
    return render(request, 'AIDatabase/MajorCR/MajorCRBase.html', context)

@login_required(login_url='/adminmaster/login/')
def majorcr_nasal_spray_deficiency(request):
    user = request.user
    report_name = "Major CR Nasal Spray-Deficiency"
    assignment = AssignChecker.objects.get(user=user)
    if report_name in assignment.assigned_report:
        queryset = MajorCR.objects.filter(main_cateogry='Nasal Spray-Deficiency')
        majorcr_filter = MajorCRFilter(request.GET, queryset=queryset, main_category='Nasal Spray-Deficiency')
        original_total_count = queryset.count()

        paginator = Paginator(majorcr_filter.qs, 10)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)
        if request.GET.get("csrfmiddlewaretoken",False):
            columns = {
                'deficiency':'Deficiency'
            }
            table_headers = ['Deficiency']
            is_filter = True
        else:
            columns = {
                "dosage_form": "Dosage Form",
                "cmc_section": "CMC Section",
                "deficiency_type": "Deficiency Type",
                "category_of_deficiency": "Category of Deficiency'",
                "deficiency": "Deficiency",
            }
            table_headers = ['CMC Section', 'Deficiency Type', 'Category of Deficiency', 'Deficiency']
            is_filter = False
        cmc_section = request.GET.get('cmc_section')
        deficiency_type = request.GET.get('deficiency_type')
        category_of_deficiency = request.GET.get('category_of_deficiency')
        context = {
                'category_of_deficiency':category_of_deficiency,
                'cmc_section':cmc_section,
                'deficiency_type':deficiency_type,
                'is_filter':is_filter,
                'table_headers': table_headers,
                'page_heading': 'Complete Response -  Nasal Spray Deficiency',
                'filter': majorcr_filter,
                'data': majorcr_filter.qs.values(
                *columns.keys()
            ),
                'full_data': majorcr_filter.qs.values(
                *columns.keys()
            ),
                'columns': columns,
                'nasal_spray_deficiency': True,
                'data': page_obj,
                'page_obj': page_obj,
                "show_flag":True,
                "original_total_count": original_total_count,
            }
    else:
        context={
            "show_flag":False
        }
    return render(request, 'AIDatabase/MajorCR/MajorCRBase.html', context)



@login_required(login_url='/adminmaster/login/')
def majorcr_liquid_oral_deficiency(request):
    user = request.user
    report_name = "Major CR Liquid Oral-Deficiency"
    assignment = AssignChecker.objects.get(user=user)
    if report_name in assignment.assigned_report:
        queryset = MajorCR.objects.filter(main_cateogry='Liquid Oral-Deficiency')
        majorcr_filter = MajorCRFilter(request.GET, queryset=queryset, main_category='Liquid Oral-Deficiency')
        original_total_count = queryset.count()
        paginator = Paginator(majorcr_filter.qs, 10)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)
        if request.GET.get("csrfmiddlewaretoken",False):
            columns = {
                'deficiency':'Deficiency'
            }
            table_headers = ['Deficiency']
            is_filter = True
        else:
            columns = {
                "dosage_form": "Dosage Form",
                "cmc_section": "CMC Section",
                "deficiency_type": "Deficiency Type",
                "category_of_deficiency": "Category of Deficiency'",
                "deficiency": "Deficiency",
            }
            table_headers = ['Dosage Type', 'CMC Section', 'Deficiency Type', 'Category of Deficiency', 'Deficiency']
            is_filter = False
        dosage_form = request.GET.get('dosage_form')
        cmc_section = request.GET.get('cmc_section')
        deficiency_type = request.GET.get('deficiency_type')
        category_of_deficiency = request.GET.get('category_of_deficiency')
        context = {
                'dosage_form': dosage_form,
                'category_of_deficiency':category_of_deficiency,
                'cmc_section':cmc_section,
                'deficiency_type':deficiency_type,
                'is_filter':is_filter,
                'table_headers':table_headers,
                'page_heading': 'Complete Response -  Liquid Oral-Deficiency',
                'filter': majorcr_filter,
                'data': majorcr_filter.qs.values(
                *columns.keys()
            ),
                'full_data': majorcr_filter.qs.values(
                *columns.keys()
            ),
                'columns': columns,
                'liquid_oral_deficiency': True,
                'data': page_obj,
                'page_obj': page_obj,
                "show_flag":True,
                "original_total_count": original_total_count,
        }
    else:
        context = {
            "show_flag":False
        }
    return render(request, 'AIDatabase/MajorCR/MajorCRBase.html', context)


@login_required(login_url='/adminmaster/login/')
def majorcr_iud_deficiency(request):
    user = request.user
    report_name = "Major CR IUD-Deficiency"
    assignment = AssignChecker.objects.get(user=user)
    if report_name in assignment.assigned_report:
        queryset = MajorCR.objects.filter(main_cateogry='IUD-Deficiency')
        majorcr_filter = MajorCRFilter(request.GET, queryset=queryset, main_category='IUD-Deficiency')
        original_total_count = queryset.count()
        paginator = Paginator(majorcr_filter.qs, 10)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)
        if request.GET.get("csrfmiddlewaretoken",False):
            columns = {
                'deficiency':'Deficiency'
            }
            table_headers = ['Deficiency']
            is_filter = True
        else:
            columns = {
                "dosage_form": "Dosage Form",
                "cmc_section": "CMC Section",
                "deficiency_type": "Deficiency Type",
                "category_of_deficiency": "Category of Deficiency'",
                "deficiency": "Deficiency",
            }
            table_headers = ['CMC Section', 'Deficiency Type', 'Category of Deficiency', 'Deficiency']
            is_filter = False
        cmc_section = request.GET.get('cmc_section')
        deficiency_type = request.GET.get('deficiency_type')
        category_of_deficiency = request.GET.get('category_of_deficiency')
        context = {
                'category_of_deficiency':category_of_deficiency,
                'cmc_section':cmc_section,
                'deficiency_type':deficiency_type,
            'is_filter':is_filter,
                'table_headers': table_headers,
                'page_heading': 'Complete Response -  IUD-Deficiency',
                'filter': majorcr_filter,
                'data': majorcr_filter.qs.values(
                *columns.keys()
            ),
            'full_data': majorcr_filter.qs.values(
                *columns.keys()
            ),
                'columns': columns,
                'iud_deficiency': True,
                'data': page_obj,
                'page_obj': page_obj,
                "show_flag":True,
                "original_total_count": original_total_count,
        }
    else:
        context = {
            "show_flag":False
        }
    return render(request, 'AIDatabase/MajorCR/MajorCRBase.html', context)



@login_required(login_url='/adminmaster/login/')
def majorcr_tdds_deficiency(request):
    user = request.user
    report_name = "Major CR TDDS-Deficiency"
    assignment = AssignChecker.objects.get(user=user)
    if report_name in assignment.assigned_report:
        queryset = MajorCR.objects.filter(main_cateogry='TDDS-Deficiency')
        majorcr_filter = MajorCRFilter(request.GET, queryset=queryset, main_category='TDDS-Deficiency')
        original_total_count = queryset.count()
        paginator = Paginator(majorcr_filter.qs, 10)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)

        if request.GET.get("csrfmiddlewaretoken",False):
            columns = {
                'deficiency':'Deficiency'
            }
            table_headers = ['Deficiency']
            is_filter = True
        else:
            columns = {
                "dosage_form": "Dosage Form",
                "cmc_section": "CMC Section",
                "deficiency_type": "Deficiency Type",
                "category_of_deficiency": "Category of Deficiency'",
                "deficiency": "Deficiency",
            }
            table_headers = ['Dosage Type', 'CMC Section', 'Deficiency Type', 'Category of Deficiency', 'Deficiency']
            is_filter = False
        dosage_form = request.GET.get('dosage_form')
        cmc_section = request.GET.get('cmc_section')
        deficiency_type = request.GET.get('deficiency_type')
        category_of_deficiency = request.GET.get('category_of_deficiency')
        context = {
            'dosage_form': dosage_form,
                'category_of_deficiency':category_of_deficiency,
                'cmc_section':cmc_section,
                'deficiency_type':deficiency_type,
                'is_filter':is_filter,
                'table_headers':table_headers,
                'page_heading': 'Complete Response -  TDDS-Deficiency',
                'filter': majorcr_filter,
                'data': majorcr_filter.qs.values(
                *columns.keys()
            ),
                'full_data': majorcr_filter.qs.values(
                *columns.keys()
            ),
                'columns': columns,
                'tdds_deficiency': True,
                'data': page_obj,
                'page_obj': page_obj,
                "show_flag":True,
                "original_total_count": original_total_count,
        }
    else:
        context = {
            "show_flag":False
        }
    return render(request, 'AIDatabase/MajorCR/MajorCRBase.html', context)



@login_required(login_url='/adminmaster/login/')
def majorcr_suppository_deficiency(request):
    user = request.user
    report_name = "Major CR Suppository-Deficiency"
    assignment = AssignChecker.objects.get(user=user)
    if report_name in assignment.assigned_report:
        queryset = MajorCR.objects.filter(main_cateogry='Suppository-Deficiency')
        majorcr_filter = MajorCRFilter(request.GET, queryset=queryset, main_category='Suppository-Deficiency')
        original_total_count = queryset.count()
        paginator = Paginator(majorcr_filter.qs, 10)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)

        if request.GET.get("csrfmiddlewaretoken",False):
            columns = {
                'deficiency':'Deficiency'
            }
            table_headers = ['Deficiency']
            is_filter = True
        else:
            columns = {
                "dosage_form": "Dosage Form",
                "cmc_section": "CMC Section",
                "deficiency_type": "Deficiency Type",
                "category_of_deficiency": "Category of Deficiency'",
                "deficiency": "Deficiency",
            }
            table_headers = ['CMC Section', 'Deficiency Type', 'Category of Deficiency', 'Deficiency']
            is_filter = False
        cmc_section = request.GET.get('cmc_section')
        deficiency_type = request.GET.get('deficiency_type')
        category_of_deficiency = request.GET.get('category_of_deficiency')
        context = {
                'category_of_deficiency':category_of_deficiency,
                'cmc_section':cmc_section,
                'deficiency_type':deficiency_type,
                'is_filter':is_filter,
                'table_headers':table_headers,
                'page_heading': 'Complete Response -  Suppository-Deficiency',
                'filter': majorcr_filter,
                'data': majorcr_filter.qs.values(
                *columns.keys()
            ),
                'full_data': majorcr_filter.qs.values(
                *columns.keys()
            ),
                'columns': columns,
                'suppository_deficiency': True,
                'data': page_obj,
                'page_obj': page_obj,
                "show_flag":True,
                "original_total_count": original_total_count,
            }
    else:
        context = {
            "show_flag":False
        }
    return render(request, 'AIDatabase/MajorCR/MajorCRBase.html', context)


@login_required(login_url='/adminmaster/login/')
def majorcr_topicals_deficiency(request):
    user = request.user
    report_name = "Major CR Topicals-Deficiency"
    assignment = AssignChecker.objects.get(user=user)
    if report_name in assignment.assigned_report:
        queryset = MajorCR.objects.filter(main_cateogry='Topicals-Deficiency')
        majorcr_filter = MajorCRFilter(request.GET, queryset=queryset, main_category='Topicals-Deficiency')
        original_total_count = queryset.count()
        paginator = Paginator(majorcr_filter.qs, 10)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)

        if request.GET.get("csrfmiddlewaretoken",False):
            columns = {
                'deficiency':'Deficiency'
            }
            table_headers = ['Deficiency']
            is_filter = True
        else:
            columns = {
                "dosage_form": "Dosage Form",
                "cmc_section": "CMC Section",
                "deficiency_type": "Deficiency Type",
                "category_of_deficiency": "Category of Deficiency'",
                "deficiency": "Deficiency",
            }
            table_headers = ['Dosage Type', 'CMC Section', 'Deficiency Type', 'Category of Deficiency', 'Deficiency']
            is_filter = False
        dosage_form = request.GET.get('dosage_form')
        cmc_section = request.GET.get('cmc_section')
        deficiency_type = request.GET.get('deficiency_type')
        category_of_deficiency = request.GET.get('category_of_deficiency')
        context = {
            'dosage_form': dosage_form,
                'category_of_deficiency':category_of_deficiency,
                'cmc_section':cmc_section,
                'deficiency_type':deficiency_type,
                'is_filter':is_filter,
                'table_headers':table_headers,
                'page_heading': 'Complete Response -  Topicals-Deficiency',
                'filter': majorcr_filter,
                'data': majorcr_filter.qs.values(
                *columns.keys()
            ),
                'full_data': majorcr_filter.qs.values(
                *columns.keys()
            ),
                'columns': columns,
                'topicals_deficiency': True,
                'data': page_obj,
                'page_obj': page_obj,
                "show_flag":True,
                "original_total_count": original_total_count,
        }
    else:
        context = {
            "show_flag":False
        }
    return render(request, 'AIDatabase/MajorCR/MajorCRBase.html', context)


@login_required(login_url='/adminmaster/login/')
def majorcr_solid_oral_deficiency(request):
    user = request.user
    report_name = "Major CR Solid Oral-Deficiency"
    assignment = AssignChecker.objects.get(user=user)
    if report_name in assignment.assigned_report:
        queryset = MajorCR.objects.filter(main_cateogry='Solid Oral-Deficiency')
        majorcr_filter = MajorCRFilter(request.GET, queryset=queryset, main_category='Solid Oral-Deficiency')
        original_total_count = queryset.count()
        paginator = Paginator(majorcr_filter.qs, 10)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)
        if request.GET.get("csrfmiddlewaretoken",False):
            columns = {
                'deficiency':'Deficiency'
            }
            table_headers = ['Deficiency']
            is_filter = True
        else:
            columns = {
                "dosage_form": "Dosage Form",
                "cmc_section": "CMC Section",
                "deficiency_type": "Deficiency Type",
                "category_of_deficiency": "Category of Deficiency'",
                "deficiency": "Deficiency",
            }
            table_headers = ['Dosage Type', 'CMC Section', 'Deficiency Type', 'Category of Deficiency', 'Deficiency']
            is_filter = False
        dosage_form = request.GET.get('dosage_form')
        cmc_section = request.GET.get('cmc_section')
        deficiency_type = request.GET.get('deficiency_type')
        category_of_deficiency = request.GET.get('category_of_deficiency')

        context = {
            'dosage_form': dosage_form,
                'category_of_deficiency':category_of_deficiency,
                'cmc_section':cmc_section,
                'deficiency_type':deficiency_type,
                'is_filter':is_filter,
                'table_headers': table_headers,
                'page_heading': 'Complete Response -  Solid Oral-Deficiency',
                'filter': majorcr_filter,
                'data': majorcr_filter.qs.values(
                *columns.keys()
            ),
                'full_data': majorcr_filter.qs.values(
                *columns.keys()
            ),
                'columns': columns,
                'solid_oral_deficiency': True,
                'data': page_obj,
                'page_obj': page_obj,
                "show_flag":True,
                "original_total_count": original_total_count,
            }
    else:
        context = {
            "show_flag":False
        }
    return render(request, 'AIDatabase/MajorCR/MajorCRBase.html', context)



@login_required(login_url='/adminmaster/login/')
def majorcr_otic_deficiency(request):
    user = request.user
    report_name = "Major CR Otic - Deficiency"
    assignment = AssignChecker.objects.get(user=user)
    if report_name in assignment.assigned_report:
        queryset = MajorCR.objects.filter(main_cateogry='Otic - Deficiency')
        majorcr_filter = MajorCRFilter(request.GET, queryset=queryset, main_category='Otic - Deficiency')
        original_total_count = queryset.count()
        paginator = Paginator(majorcr_filter.qs, 10)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)

        if request.GET.get("csrfmiddlewaretoken",False):
            columns = {
                'deficiency':'Deficiency'
            }
            table_headers = ['Deficiency']
            is_filter = True
        else:
            columns = {
                "dosage_form": "Dosage Form",
                "cmc_section": "CMC Section",
                "deficiency_type": "Deficiency Type",
                "category_of_deficiency": "Category of Deficiency'",
                "deficiency": "Deficiency",
            }
            table_headers = ['CMC Section', 'Deficiency Type', 'Category of Deficiency', 'Deficiency']
            is_filter = False
        cmc_section = request.GET.get('cmc_section')
        deficiency_type = request.GET.get('deficiency_type')
        category_of_deficiency = request.GET.get('category_of_deficiency')
        context = {
                'category_of_deficiency':category_of_deficiency,
                'cmc_section':cmc_section,
                'deficiency_type':deficiency_type,
                'is_filter':is_filter,
                'table_headers':table_headers,
                'page_heading': 'Complete Response -  Otic - Deficiency',
                'filter': majorcr_filter,
                'data': majorcr_filter.qs.values(
                *columns.keys()
            ),
                'full_data': majorcr_filter.qs.values(
                *columns.keys()
            ),
                'columns': columns,
                'otic_deficiency': True,
                'data': page_obj,
                'page_obj': page_obj,
                "show_flag":True,
                "original_total_count": original_total_count,
            }
    else:
        context = {
            "show_flag":False
        }
    return render(request, 'AIDatabase/MajorCR/MajorCRBase.html', context)



@login_required(login_url='/adminmaster/login/')
def majorcr_ophthalmic_deficiency(request):
    user = request.user
    report_name = "Major CR Ophthalmic - Deficiency"
    assignment = AssignChecker.objects.get(user=user)
    if report_name in assignment.assigned_report:
        queryset = MajorCR.objects.filter(main_cateogry=' Ophthalmic - Deficiency')
        majorcr_filter = MajorCRFilter(request.GET, queryset=queryset, main_category=' Ophthalmic - Deficiency')
        original_total_count = queryset.count()
        paginator = Paginator(majorcr_filter.qs, 10)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)

        if request.GET.get("csrfmiddlewaretoken",False):
            columns = {
                'deficiency':'Deficiency'
            }
            table_headers = ['Deficiency']
            is_filter = True
        else:
            columns = {
                "dosage_form": "Dosage Form",
                "cmc_section": "CMC Section",
                "deficiency_type": "Deficiency Type",
                "category_of_deficiency": "Category of Deficiency'",
                "deficiency": "Deficiency",
            }
            table_headers = ['Dosage Type', 'CMC Section', 'Deficiency Type', 'Category of Deficiency', 'Deficiency']
            is_filter = False
        dosage_form = request.GET.get('dosage_form')
        cmc_section = request.GET.get('cmc_section')
        deficiency_type = request.GET.get('deficiency_type')
        category_of_deficiency = request.GET.get('category_of_deficiency')
        context = {
            'dosage_form': dosage_form,
                'category_of_deficiency':category_of_deficiency,
                'cmc_section':cmc_section,
                'deficiency_type':deficiency_type,
                'is_filter':is_filter,
                'table_headers':table_headers,
                'page_heading': 'Complete Response -  Ophthalmic - Deficiency',
                'filter': majorcr_filter,
                'data': majorcr_filter.qs.values(
                *columns.keys()
            ),
                'full_data': majorcr_filter.qs.values(
                *columns.keys()
            ),
                'columns': columns,
                'ophthalmic_deficiency': True,
                'data': page_obj,
                'page_obj': page_obj,
                "show_flag":True,
                "original_total_count": original_total_count,
            }
    else:
        context = {
            "show_flag":False
        }
    return render(request, 'AIDatabase/MajorCR/MajorCRBase.html', context)



@login_required(login_url='/adminmaster/login/')
def majorcr_injectable_peptide_deficiency(request):
    user = request.user
    report_name = "Major CR Injectable - Peptide Deficiency"
    assignment = AssignChecker.objects.get(user=user)
    if report_name in assignment.assigned_report:
        queryset = MajorCR.objects.filter(main_cateogry='Injectable - Peptide Deficiency')
        majorcr_filter = MajorCRFilter(request.GET, queryset=queryset, main_category='Injectable - Peptide Deficiency')
        original_total_count = queryset.count()
        paginator = Paginator(majorcr_filter.qs, 10)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)
        if request.GET.get("csrfmiddlewaretoken",False):
            columns = {
                'deficiency':'Deficiency'
            }
            table_headers = ['Deficiency']
            is_filter = True
        else:
            columns = {
                "cmc_section": "CMC Section",
                "deficiency_type": "Deficiency Type",
                "category_of_deficiency": "Category of Deficiency'",
                "deficiency": "Deficiency",
            }
            table_headers = ['CMC Section', 'Deficiency Type', 'Category of Deficiency', 'Deficiency']
            is_filter = False
        cmc_section = request.GET.get('cmc_section')
        deficiency_type = request.GET.get('deficiency_type')
        category_of_deficiency = request.GET.get('category_of_deficiency')
        context = {
                'category_of_deficiency':category_of_deficiency,
                'cmc_section':cmc_section,
                'deficiency_type':deficiency_type,
                'is_filter':is_filter,
                'table_headers':table_headers,
                'page_heading': 'Complete Response -  Injectable - Peptide Deficiency',
                'filter': majorcr_filter,
                'data': majorcr_filter.qs.values(
                *columns.keys()
            ),
                'full_data': majorcr_filter.qs.values(
                *columns.keys()
            ),
                'columns': columns,
                'injectable_peptide_deficiency': True,
                'data': page_obj,
                'page_obj': page_obj,
                "show_flag":True,
                "original_total_count": original_total_count,
            }
    else:
        context = {
            "show_flag":False
        }
    return render(request, 'AIDatabase/MajorCR/MajorCRBase.html', context)


@login_required(login_url='/adminmaster/login/')
def majorcr_injectable_general_deficiency(request):
    user = request.user
    report_name = "Major CR Injectable - General Deficiency"
    assignment = AssignChecker.objects.get(user=user)
    if report_name in assignment.assigned_report:
        queryset = MajorCR.objects.filter(main_cateogry='Injectable - General Deficiency')
        majorcr_filter = MajorCRFilter(request.GET, queryset=queryset, main_category='Injectable - General Deficiency')
        original_total_count = queryset.count()
        paginator = Paginator(majorcr_filter.qs, 10)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)
        if request.GET.get("csrfmiddlewaretoken",False):
            columns = {
                'deficiency':'Deficiency'
            }
            table_headers = ['Deficiency']
            is_filter = True
        else:
            columns = {
                "dosage_form": "Dosage Form",
                "cmc_section": "CMC Section",
                "deficiency_type": "Deficiency Type",
                "category_of_deficiency": "Category of Deficiency'",
                "deficiency": "Deficiency",
            }
            table_headers = ['Dosage Type','CMC Section', 'Deficiency Type', 'Category of Deficiency', 'Deficiency']
            is_filter = False
        dosage_form = request.GET.get('dosage_form')
        cmc_section = request.GET.get('cmc_section')
        deficiency_type = request.GET.get('deficiency_type')
        category_of_deficiency = request.GET.get('category_of_deficiency')
        context = {
            'dosage_form': dosage_form,
                'category_of_deficiency':category_of_deficiency,
                'cmc_section':cmc_section,
                'deficiency_type':deficiency_type,
                'is_filter':is_filter,
                'table_headers':table_headers,
                'page_heading': 'Complete Response -  Injectable - General Deficiency',
                'filter': majorcr_filter,
                'data': majorcr_filter.qs.values(
                *columns.keys()
            ),
                'full_data': majorcr_filter.qs.values(
                *columns.keys()
            ),
                'columns': columns,
                'injectable_general_deficiency': True,
                'data': page_obj,
                'page_obj': page_obj,
                "show_flag":True,
                "original_total_count": original_total_count,
            }
    else:
        context = {
            "show_flag":False
        }
    return render(request, 'AIDatabase/MajorCR/MajorCRBase.html', context)

def get_anda_chart_data(request):
    chart_data = ANDA.objects.values('main_cateogry').annotate(
        dosage_count=Count('dosage_form', distinct=True),
        deficiency_count=Count('deficiency_type', distinct=True),
        category_count=Count('category_of_deficiency', distinct=True)
    ).order_by('main_cateogry')

    return JsonResponse({
        'labels': [item['main_cateogry'] for item in chart_data],
        'dosageCounts': [item['dosage_count'] for item in chart_data],
        'deficiencyCounts': [item['deficiency_count'] for item in chart_data],
        'categoryCounts': [item['category_count'] for item in chart_data]
    })

def anda_deficicency_count_pie(request):
    categories = ANDA.objects.values('main_cateogry').distinct()
    data = {
        'labels': [],
        'counts': []
    }
    for category in categories:
        cat_name = category['main_cateogry']
        count = ANDA.objects.filter(main_cateogry=cat_name).values('deficiency_type').distinct().count()
        data['labels'].append(f"{cat_name} ({count})")
        data['counts'].append(count)
    return JsonResponse(data)

def anda_category_deficicency_count_pie(request):
    categories = ANDA.objects.values('main_cateogry').distinct()
    data = {
        'labels': [],
        'counts': []
    }
    for category in categories:
        cat_name = category['main_cateogry']
        count = ANDA.objects.filter(main_cateogry=cat_name).values('category_of_deficiency').distinct().count()
        data['labels'].append(f"{cat_name} ({count})")
        data['counts'].append(count)
    return JsonResponse(data)

def anda_dosage_count_pie(request):
    categories = ANDA.objects.values('main_cateogry').distinct()
    data = {
        'labels': [],
        'counts': []
    }
    for category in categories:
        cat_name = category['main_cateogry']
        count = ANDA.objects.filter(main_cateogry=cat_name).values('dosage_form').distinct().count()
        data['labels'].append(f"{cat_name} ({count})")
        data['counts'].append(count)
    return JsonResponse(data)


def get_major_cr_chart_data(request):
    chart_data = MajorCR.objects.values('main_cateogry').annotate(
        dosage_count=Count('dosage_form', distinct=True),
        deficiency_count=Count('deficiency_type', distinct=True)
    ).order_by('main_cateogry')

    return JsonResponse({
        'labels': [item['main_cateogry'] for item in chart_data],
        'dosageCounts': [item['dosage_count'] for item in chart_data],
        'deficiencyCounts': [item['deficiency_count'] for item in chart_data]
    })

def major_cr_deficicency_count_pie(request):
    categories = MajorCR.objects.values('main_cateogry').distinct()
    data = {
        'labels': [],
        'counts': []
    }
    for category in categories:
        cat_name = category['main_cateogry']
        count = MajorCR.objects.filter(main_cateogry=cat_name).values('deficiency_type').distinct().count()
        data['labels'].append(f"{cat_name} ({count})")
        data['counts'].append(count)
    return JsonResponse(data)

def major_cr_category_deficicency_count_pie(request):
    categories = MajorCR.objects.values('main_cateogry').distinct()
    data = {
        'labels': [],
        'counts': []
    }
    for category in categories:
        cat_name = category['main_cateogry']
        count = MajorCR.objects.filter(main_cateogry=cat_name).values('category_of_deficiency').distinct().count()
        data['labels'].append(f"{cat_name} ({count})")
        data['counts'].append(count)
    return JsonResponse(data)

# @login_required(login_url='/adminmaster/login/')
def ai_master_base(request):
    total_deficiency_type = ANDA.objects.values('deficiency_type').distinct().count()
    total_records = ANDA.objects.all().count()
    total_dosage_type = ANDA.objects.values('dosage_form').distinct().count()
    total_dosage = ANDA.objects.values('main_cateogry').distinct().count()
    total_category = ANDA.objects.values('category_of_deficiency').distinct().count()
    total_cmc = ANDA.objects.values('cmc_section').distinct().count()
    data = {}
    for deficiency in ANDA.objects.values_list('deficiency_type', flat=True).distinct():
        count = ANDA.objects.filter(deficiency_type=deficiency).count()
        data[deficiency] = count

    # Sort the dictionary and convert it to a list of tuples
    deficiency_counts = sorted(data.items(), key=lambda item: item[1], reverse=True)
    return render(request,'AIDatabase/AIBase.html',{"total_deficiency_type":total_deficiency_type, "total_records":total_records,"total_dosage_type":total_dosage_type,"total_dosage":total_dosage,"total_category":total_category,"total_cmc":total_cmc,"deficiency_counts":deficiency_counts,})

# @login_required(login_url='/adminmaster/login/')
def major_cr_base(request):
    total_deficiency_type = MajorCR.objects.values('deficiency_type').distinct().count()
    total_records = MajorCR.objects.all().count()
    total_dosage_type = MajorCR.objects.exclude(dosage_form='').values('dosage_form').distinct().count()
    total_dosage = MajorCR.objects.values('main_cateogry').distinct().count()
    total_category = MajorCR.objects.values('category_of_deficiency').distinct().count()
    total_cmc = MajorCR.objects.values('cmc_section').distinct().count()
    data = {}
    for deficiency in MajorCR.objects.values_list('deficiency_type', flat=True).distinct():
        count = MajorCR.objects.filter(deficiency_type=deficiency).count()
        data[deficiency] = count

    # Sort the dictionary and convert it to a list of tuples
    deficiency_counts = sorted(data.items(), key=lambda item: item[1], reverse=True)
    return render(request,'AIDatabase/MajorCR.html',{"total_deficiency_type":total_deficiency_type, "total_records":total_records,"total_dosage_type":total_dosage_type,"total_dosage":total_dosage,"total_category":total_category,"total_cmc":total_cmc,"deficiency_counts":deficiency_counts,})

def get_anda_bubble_data(request):
    deficiency_data = (
        ANDA.objects.values('main_cateogry', 'dosage_form')
        .annotate(
            count=Count('deficiency_type')  # or Count('category_of_deficiency') if you want unique deficiency types
        )
    )

    bubbles = []
    for item in deficiency_data:
        bubbles.append({
            'category': item['main_cateogry'],
            'dosageForm': item['dosage_form'],
            'count': item['count']
        })
    # print("bubbles data",bubbles)
    return JsonResponse({'bubbles': bubbles})

def get_major_cr_bubble_data(request):
    deficiency_data = (
        ANDA.objects.values('main_cateogry', 'dosage_form')
        .annotate(
            total_deficiencies=Count('id'),
            unique_categories=Count('deficiency_type', distinct=True)
        )
    )

    bubbles = []
    for item in deficiency_data:
        categories = (
            ANDA.objects.filter(
                main_cateogry=item['main_cateogry'],
                dosage_form=item['dosage_form']
            )
            .values_list('deficiency_type', flat=True)
            .distinct()
        )

        bubbles.append({
            'x': item['main_cateogry'],
            'y': item['dosage_form'],
            'count': item['unique_categories'],  # Number of unique deficiency categories
            'total': item['total_deficiencies'],  # Total number of deficiencies
            'category': item['main_cateogry'],
            'dosageForm': item['dosage_form'],
            'deficiencyCategories': list(categories)  # List of all unique deficiency categories
        })

    return JsonResponse({'bubbles': bubbles})

def pie_chart_main_category(request):
    data = ANDA.objects.values('main_cateogry').annotate(total=Count('id'))
    labels = [entry['main_cateogry'] for entry in data]
    counts = [entry['total'] for entry in data]
    return JsonResponse({'labels': labels, 'counts': counts})

def major_cr_pie_chart_dosage_form(request):
    data = MajorCR.objects.values('dosage_form').annotate(total=Count('id'))
    labels = [entry['dosage_form'] for entry in data]
    counts = [entry['total'] for entry in data]
    return JsonResponse({'labels': labels, 'counts': counts})

def pie_chart_deficiency_type(request):
    data = ANDA.objects.values('deficiency_type').annotate(total=Count('id'))
    labels = [entry['deficiency_type'] for entry in data]
    counts = [entry['total'] for entry in data]
    return JsonResponse({'labels': labels, 'counts': counts})

def pie_chart_category_of_deficiency(request):
    data = ANDA.objects.values('category_of_deficiency').annotate(total=Count('id'))
    labels = [entry['category_of_deficiency'] for entry in data]
    counts = [entry['total'] for entry in data]
    return JsonResponse({'labels': labels, 'counts': counts})

def bar_chart_main_category(request):
    data = ANDA.objects.values('main_cateogry').annotate(total=Count('id'))
    labels = [entry['main_cateogry'] for entry in data]
    counts = [entry['total'] for entry in data]
    return JsonResponse({'labels': labels, 'counts': counts})

def bar_chart_cmc_section(request):
    data = ANDA.objects.values('cmc_section').annotate(total=Count('id'))
    labels = [entry['cmc_section'] for entry in data]
    counts = [entry['total'] for entry in data]
    return JsonResponse({'labels': labels, 'counts': counts})

def major_cr_bar_chart_cmc_section(request):
    data = MajorCR.objects.values('cmc_section').annotate(total=Count('id'))
    labels = [entry['cmc_section'] for entry in data]
    counts = [entry['total'] for entry in data]
    return JsonResponse({'labels': labels, 'counts': counts})

def bar_chart_category_vs_deficiency(request):
    data = ANDA.objects.values('category_of_deficiency').annotate(total=Count('id'))
    labels = [entry['category_of_deficiency'] for entry in data]
    counts = [entry['total'] for entry in data]
    return JsonResponse({'labels': labels, 'counts': counts})

def major_cr_bar_chart_category_vs_deficiency(request):
    data = MajorCR.objects.values('category_of_deficiency').annotate(total=Count('id'))
    labels = [entry['category_of_deficiency'] for entry in data]
    counts = [entry['total'] for entry in data]
    return JsonResponse({'labels': labels, 'counts': counts})


# @api_view(['GET'])
# def list_of_company(request):
#     company = Form483Master.objects.all()
#     companies = []
#     for i in company:
#         companies.append(i.company_name)
#     # companies = Form483Master.objects.values('company_name').distinct()
#     # companies = list(companies)
#     return JsonResponse({"companies":companies})


from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.core.exceptions import ObjectDoesNotExist
from rest_framework.decorators import api_view
import json
from collections import defaultdict

# @api_view(['GET', 'POST'])
# @csrf_exempt
# def company_object(request):
#     if request.method == "POST":
#         print("\n\n>>>>>>>yes>>>>",request.data)
#         company =  request.data.get('company_name')
#         system_Value = request.data.get('system_name')
#         fda_investigator_name = request.data.get('investigator_name')
#         year_of_inspection = request.data.get('year_of_inspection')
#         extra_company_search = request.data.get('extra_company_search')


#         try:
#             print("\n\n>>>>>>>try>>>>",year_of_inspection)
#             if system_Value != None:
#                 masters = []
#                 if extra_company_search != None:
#                     systems = Form483System.objects.filter(system__in = system_Value, master__company_name__in=extra_company_search).order_by('master__company_name')
#                 else:
#                     systems = Form483System.objects.filter(system__in = system_Value)
#                 for i in systems:
#                     masters.append(i.master)

#                 masters = list(set(masters))

#             elif fda_investigator_name != None:
#                 from django.db.models import Q
#                 q = Q()
#                 for i in fda_investigator_name:
#                     q |= Q(investigator_name__icontains=i)

#                 masters = Form483Master.objects.filter(q)
#                 # if extra_company_search != None:
#                 #     masters = Form483Master.objects.filter(investigator_name__icontains=fda_investigator_name, company_name__in=extra_company_search).order_by('company_name')
#                 # else:
#                 #     masters = Form483Master.objects.filter(investigator_name__icontains=fda_investigator_name).order_by('company_name')
#             elif year_of_inspection != None:
#                 if extra_company_search != None:
#                     print("\n\n>>>>>>>try>>>>",extra_company_search)
#                     masters = Form483Master.objects.filter(year_of_inspection__in=year_of_inspection, company_name__in=extra_company_search).order_by('company_name')
#                 else:
#                     masters = Form483Master.objects.filter(year_of_inspection__in=year_of_inspection).order_by('company_name')
#             else:
#                 print("\n\n>>>>>>>inside else>>>",year_of_inspection)
#                 masters = Form483Master.objects.filter(company_name__in=company).order_by('company_name')
#             # if not masters.exists():
#             #     return JsonResponse({"error": "No data found for the provided company name."}, status=404)



#             def nested_dict():
#                 return defaultdict(nested_dict)

#             # Initialize the main data structure
#             aggregated_data = defaultdict(lambda: {
#                 'company_name': "",
#                 'location': '',
#                 'type_of_establishment': set(),
#                 # 'total_observations':0,
#                 'total_fda_observation': 0,  # Total count for all observations
#                 'year_of_inspection': nested_dict()
#             })
#             location_counts = defaultdict(int)
#             for master in masters:
#                 location_key = f"{master.city}, {master.state}"
#                 location_counts[location_key] += Form483Observation.objects.filter(system__master=master).count()

#             # First pass: Count total observations for each location
#             # for master in masters:
#             #     location_key = f"{master.city}, {master.state}"
#             #     location_data = aggregated_data[location_key]
#             #     systems = Form483System.objects.filter(master=master)
#             #     for system in systems:
#             #         obs_count = Form483Observation.objects.filter(system=system).count()
#             #         location_data['total_observations'] += obs_count

#             # Second pass: Build the nested structure with system-level counts
#             for master in masters:
#                 location_key = f"{master.city}, {master.state}"
#                 location_data = aggregated_data[location_key]

#                 # Update basic location data
#                 location_data['location'] = location_key
#                 location_data['total_fda_observation'] = location_counts[location_key]
#                 location_data['type_of_establishment'].add(master.type_of_establishment)
#                 location_data['company_name'] = master.company_name

#                 # Get year and date
#                 year = str(master.year_of_inspection)
#                 date = str(master.date_of_inspection)

#                 # Add metadata
#                 if 'metadata' not in location_data['year_of_inspection'][year][date]:
#                     location_data['year_of_inspection'][year][date]['metadata'] = {
#                         'fda_investigators': master.investigator_name
#                     }

#                 # Process systems and their observations
#                 if system_Value != None:
#                     systems = Form483System.objects.filter(master=master, system__in = system_Value)
#                 else:
#                     systems = Form483System.objects.filter(master=master)
#                 for system in systems:
#                     # Get system observation count
#                     system_obs_count = Form483Observation.objects.filter(system=system).count()

#                     # Initialize system structure if not exists
#                     if 'systems' not in location_data['year_of_inspection'][year][date]:
#                         location_data['year_of_inspection'][year][date]['systems'] = {}

#                     if system.system not in location_data['year_of_inspection'][year][date]['systems']:
#                         location_data['year_of_inspection'][year][date]['systems'][system.system] = {
#                             'observation_count': system_obs_count,
#                             'observations': {}
#                         }

#                     system_data = location_data['year_of_inspection'][year][date]['systems'][system.system]

#                     # Process observations
#                     observations = Form483Observation.objects.filter(system=system)
#                     for observation in observations:
#                         contents = Form483ObeservationContent.objects.filter(observation=observation)
#                         content_data = []

#                         for content in contents:
#                             content_data.append({
#                                 'content_category': content.content_category,
#                                 'content': content.content,
#                                 'image': content.image.url if content.image else None
#                             })

#                         system_data['observations']["Observation"+" "+str(observation.observation_number)] = {
#                             'contents': content_data
#                         }

#             # Format the response
#             formatted_response = []
#             for location_key, location_data in aggregated_data.items():
#                 formatted_location = {
#                     'company_name': location_data['company_name'],
#                     'location': location_data['location'],
#                     'type_of_establishment': sorted(location_data['type_of_establishment']),
#                     'total_fda_observation': location_data['total_fda_observation'],
#                     # 'total_observations': location_data['total_observations'],
#                     'year_of_inspection': _convert_defaultdict_to_dict(location_data['year_of_inspection'])
#                 }
#                 formatted_response.append(formatted_location)
#                 print("formatted_response",formatted_response)


#             return JsonResponse({"data": formatted_response}, status=200)

#         except Exception as e:
#             return JsonResponse({"error": str(e)}, status=500)

#     return JsonResponse({"error": "Invalid request method."}, status=400)




# def get_image_filename(company, year, system, observation_num, detail_num, img_num):
#     safe_company = company.replace(" ", "_").replace("/", "_")
#     safe_system = system.replace(" ", "_").replace(",", "")

#     filename = f"{safe_company}_{year}_{safe_system}_Observation_{observation_num[-1]}_Detail_{detail_num}_img{img_num}.png"
#     # print("filename",filename)

#     media_url = f"{settings.MEDIA_URL}observation_images/{filename}"

#     media_url = media_url.replace("//", "/")

#     return media_url
import re
import urllib.parse

def get_image_filename(company, year, system, observation_num, detail_num, img_num):
    safe_company = company.strip().replace(" ", "_").replace("/", "_")
    safe_system = system.strip().replace(" ", "_").replace(",", "")

    # Extract the first number from observation_num string
    match = re.search(r'\d+', str(observation_num))
    observation_number_only = match.group() if match else "0"  # fallback to "0" if no number found

    filename = f"{safe_company}_{year}_{safe_system}_Observation_{observation_number_only}_Detail_{detail_num}_img{img_num}.png"

    media_url = f"{settings.MEDIA_URL}observation_images/{filename}"
    media_url = media_url.replace("//", "/")

    return media_url




observation_detail_mapping = {}
observation_detail_mapping_source_key = None
def initialize_detail_mapping(df):
    global observation_detail_mapping
    observation_detail_mapping.clear()

    groups = df.groupby(['Company Name', 'Year of Inspection', 'System', 'Form 483 Observation'])

    for name, group in groups:
        company, year, system, obs_num = name
        company = company.rstrip() if isinstance(company, str) else company

        # Sort the group if needed to ensure consistent ordering
        group = group.sort_index()

        # Assign detail numbers within each group
        for idx, (_, row) in enumerate(group.iterrows(), 1):
            details = row['Observation Details']
            # Create a unique key for this specific observation detail
            key = f"{company}::{year}::{system}::{obs_num}::{details}"
            observation_detail_mapping[key] = idx



# excel_file_path = os.path.join(settings.BASE_DIR, 'AIDatabase', 'management', 'commands', 'Final_File_FDA_Observations_8_12_2025.xlsx')
# df1 = pd.read_excel(excel_file_path, sheet_name="Sheet1")
# df1 = df1.where(pd.notnull(df1), None)

# print("--- Data with trailing space in 'Type of establishment' ---")
# problematic_data = df1[df1['Type of establishment'] == 'Prescription (Rx) Drug Manufacturer ']
# print(problematic_data)
# print("----------------------------------------------------------")

# df1['Type of establishment'] = df1['Type of establishment'].str.strip()
# print("Sheet 'Sheet1' Columns:", df1.columns.tolist())

# excel_file_path = get_active_excel_path()
# print("Using Excel file at:", excel_file_path)
# df1 = pd.read_excel(excel_file_path, sheet_name="Sheet1")
# df1 = df1.where(pd.notnull(df1), None)

@api_view(['GET', 'POST'])
@csrf_exempt
def company_object(request):
    # excel_file_path = get_active_excel_path()
    # df1 = pd.read_excel(excel_file_path, sheet_name="Sheet1")
    global observation_detail_mapping_source_key

    df1 = get_cached_df()
    current_source_key = get_active_excel_source()["source_key"]
    if request.method == "POST":
        # print("\n\n>>>>>>> Request Data >>>>", request.data)

        # Extract filters from request
        company = request.data.get('company_name')
        # print(">>",company)
        system_value = request.data.get('system_name')
        investigator_name = request.data.get('investigator_name')
        year_of_inspection = request.data.get('year_of_inspection')
        type_of_establishment = request.data.get('type_of_establishment')
        key_word_search = request.data.get('keyword_search')
        start_month_year = request.data.get("start_month_year")  # e.g., "2022-01"
        end_month_year = request.data.get("end_month_year")      # e.g., "2023-03"
        organization_name = request.data.get('organization_name')
        fei_number = request.data.get('fei_number')
        country = request.data.get('country')
        page = request.data.get('page', 1)  # Get page number from request
        page_size = request.data.get('page_size', 10)  # Default 10 items per page


        # print(year_of_inspection,'-----------------')

        # print("\n\n>>>>>>Key word search>>>>>>\n\n",key_word_search)

          # Make sure the detail mapping is initialized

        if not observation_detail_mapping or observation_detail_mapping_source_key != current_source_key:
            initialize_detail_mapping(df1)
            observation_detail_mapping_source_key = current_source_key
        # Apply filters dynamically
        # print("original DF: ",df1)
        filtered_df = df1[df1['Type of establishment'] != "OTC Drug Manufacturer"].copy()
        # print("Shape after excluding OTC:", filtered_df.shape)
        # print("Unique establishments after excluding OTC (raw from DF):", filtered_df['Type of establishment'].dropna().unique())

        if company:
            company = [comp.rstrip() for comp in company]
            filtered_df = filtered_df[filtered_df['Company Name'].str.strip().isin(company)]
            # filtered_df = filtered_df[filtered_df['Company Name'].isin(company)]
            # print("After filtering by company:", filtered_df.shape)
            # print("filtered_df>>>",filtered_df)

        if organization_name:
            filtered_df = filtered_df[
                filtered_df['Organization Name'].str.strip().isin(organization_name)
            ]

        if fei_number:
            filtered_df = filtered_df[
                filtered_df['FEI Number'].astype(str).isin([str(f) for f in fei_number])
            ]

        if country:
            if isinstance(country, list):
                pattern = '|'.join([re.escape(val.strip()) for val in country if str(val).strip()])
            else:
                pattern = re.escape(str(country).strip())
            if pattern:
                filtered_df = filtered_df[
                    filtered_df['Country'].fillna("").astype(str).str.contains(
                        pattern, case=False, na=False
                    )
                ]

        if type_of_establishment:
            # print("--- Debugging Type of Establishment Filter ---")
            # print("Raw Type of Establishment filter from request:", type_of_establishment)

            # Construct the regex pattern
            pattern_parts = [re.escape(val.strip()) for val in type_of_establishment]
            pattern = '|'.join(pattern_parts)
            # print("Regex pattern used:", pattern)

            # Apply the filter
            filtered_df_after_type_filter = filtered_df[filtered_df['Type of establishment'].str.contains(pattern, case=False, na=False)]
            filtered_df = filtered_df_after_type_filter # Update filtered_df for subsequent steps
            # print("--- End Debugging Type of Establishment Filter ---")

        # Parse 'Month of Inspection' as datetime for safe comparison
        filtered_df['Month of Inspection'] = pd.to_datetime(filtered_df['Month of Inspection'], errors='coerce')

        # Create filtered version for display/response (but include all in total_observations)
        filtered_df = filtered_df[
            ~(
                (filtered_df['Company Name'].str.strip() == 'Medefil Incorporated') &
                (filtered_df['Month of Inspection'] == pd.Timestamp('2024-01-01')) &
                (filtered_df['Sr. No.'] == 6)
            )
        ]



        if year_of_inspection:
            filtered_df = filtered_df[filtered_df['Year of Inspection'].isin(year_of_inspection)]

        if investigator_name:
            filtered_df = filtered_df[filtered_df['FDA Investigator(s) name'].str.contains('|'.join(investigator_name), na=False, case=False)]

        if system_value:
            normalized_selected_systems = {_normalize_system_name(s) for s in system_value if s is not None}
            filtered_df = filtered_df[
                filtered_df['System'].apply(_normalize_system_name).isin(normalized_selected_systems)
            ]

        # ----- Flexible Month-Year filtering -----
        df_with_dates = filtered_df.copy()
        df_with_dates['Inspection Date'] = pd.to_datetime(df_with_dates['Month of Inspection'], errors='coerce')

        start_date = pd.to_datetime(start_month_year, format="%Y-%m", errors='coerce') if start_month_year else None
        end_date = pd.to_datetime(end_month_year, format="%Y-%m", errors='coerce') if end_month_year else None

        if start_date and end_date:
            df_with_dates = df_with_dates[(df_with_dates['Inspection Date'] >= start_date) & (df_with_dates['Inspection Date'] <= end_date)]
        elif start_date:
            df_with_dates = df_with_dates[df_with_dates['Inspection Date'] >= start_date]
        elif end_date:
            df_with_dates = df_with_dates[df_with_dates['Inspection Date'] <= end_date]

        filtered_df = df_with_dates  # Use this for final processing

        pre_keyword_total_observations = filtered_df['Form 483 Observation'].count()
        # pre_keyword_total_observations = filtered_df.drop_duplicates(
        #     subset=['Company Name', 'Year of Inspection', 'System', 'Form 483 Observation']
        # )['Form 483 Observation'].count()
        # print("pre_keyword_total_observations",pre_keyword_total_observations)

        if key_word_search:
            if isinstance(key_word_search, list):
                pattern = '|'.join([re.escape(word) for word in key_word_search])
            else:
                pattern = re.escape(key_word_search)
            filtered_df = filtered_df[
                filtered_df['Observation Details'].str.contains(pattern, case=False, na=False)
            ]
            filtered_df = filtered_df.sort_values(
                by=['Year of Inspection'],
                ascending=[False],
                na_position='last'
            )
            post_keyword_total_observations = filtered_df.drop_duplicates(
                subset=['Company Name', 'Year of Inspection', 'System', 'Form 483 Observation']
            )['Form 483 Observation'].count()
        else:
            post_keyword_total_observations = 0

        # post_keyword_total_observations = []
        # if key_word_search:
        #     if isinstance(key_word_search, list):
        #         pattern = '|'.join([re.escape(word) for word in key_word_search])
        #     else:
        #         pattern = re.escape(key_word_search)
        #     filtered_df = filtered_df[
        #         filtered_df['Observation Details'].str.contains(pattern, case=False, na=False)
        #     ]
        #     post_keyword_total_observations = filtered_df['Form 483 Observation'].count()
            # print("post_keyword_total_observations",post_keyword_total_observations)
            # print("\n\nFilter Keyword Data>>>>>>",filtered_df['Observation Details'])
            # print("\n\nFilter Keyword Data count>>>>>",filtered_df['Observation Details'].count())




        # print("Filtered DF Shape:", filtered_df.shape)
        # print(filtered_df[['Company Name', 'Year of Inspection', 'System', 'Form 483 Observation']])
        # total_observations = filtered_df['Form 483 Observation'].count()
        # total_observations = filtered_df.drop_duplicates(
        #     subset=['Company Name', 'Year of Inspection', 'System', 'Form 483 Observation']
        # )['Form 483 Observation'].count()
        total_observations = filtered_df['Form 483 Observation'].count()

        # total_systems = filtered_df['System'].nunique()
        total_systems = filtered_df['System'].apply(_normalize_system_name).nunique()

        total_investigators = get_unique_investigators_count(filtered_df)

        total_companies = (
            filtered_df['Company Name']
            .dropna()
            .astype(str)
            .str.strip()
            .str.lower()
            .nunique()
        )

        establishment_values = (
            filtered_df['Type of establishment']
            .dropna()
            .astype(str)
            .str.strip()
            .str.lower()
        )
        allowed_establishments = [
            'api manufacturer',
            'prescription (rx) drug manufacturer',
            'contract drug manufacturer',
        ]
        total_establishments = establishment_values[establishment_values.isin(allowed_establishments)].nunique()

        # Get unique names/values
        # system_names = filtered_df['System'].unique()
        establishment_names = filtered_df['Type of establishment'].unique()

    #     # Step 1: split investigators into separate rows
    #     investigator_df = (
    #         filtered_df[['FDA Investigator(s) name', 'Form 483 Observation']]
    #         .dropna(subset=['FDA Investigator(s) name'])
    #         .assign(investigator=lambda df: df['FDA Investigator(s) name']
    #                 .astype(str)
    #                 .str.rstrip(', ')
    #                 .str.split(','))
    #         .explode('investigator')
    #     )

    #     # Step 2: clean names
    #     investigator_df['investigator'] = investigator_df['investigator'].str.strip()

    #     # Step 3: count observations per investigator
    #     ind_investigator_counts = (
    #         investigator_df
    #         .groupby('investigator')['Form 483 Observation']
    #         .count()   # or .nunique() if you want unique observations
    #         .sort_values(ascending=False)
    #         .to_dict()
    #     )

    #     system_counts = (
    #     filtered_df['System']
    #     .apply(_normalize_system_name)
    #     .str.title()
    #     .value_counts()
    #     .to_dict()
    # )
    #     establishment_counts = (
    #     filtered_df['Type of establishment']
    #     .dropna()
    #     .astype(str)
    #     .str.strip()
    #     .value_counts()
    #     .to_dict()
    # )



        # Step 1: keep original (no split)
        investigator_df = (
            filtered_df[['FDA Investigator(s) name', 'Form 483 Observation']]
            .dropna(subset=['FDA Investigator(s) name'])
            .copy()
        )

        # Step 2: normalize names (important)
        investigator_df['investigator'] = (
            investigator_df['FDA Investigator(s) name']
            .astype(str)
            .str.replace(r'\s*,\s*', ', ', regex=True)  # normalize spacing
            .str.strip()
        )

        # Step 3: count observations per investigator (combined)
        ind_investigator_counts = (
            investigator_df
            .groupby('investigator')['Form 483 Observation']
            .count()   # or .nunique()
            .sort_values(ascending=False)
            .to_dict()
        )
        system_counts = (
        filtered_df['System']
        .apply(_normalize_system_name)
        .str.title()
        .value_counts()
        .to_dict()
        )
        establishment_counts = (
            filtered_df['Type of establishment']
            .dropna()
            .astype(str)
            .str.strip()
            .value_counts()
            .to_dict()
        )

        # print(filtered_df,'---------------------')``````````````````````````````````````````````````````````````
        # print("System Names:", system_names)

        # print("Establishment Names:", establishment_names)
        # print("total_observations",total_observations)
        # print("total_systems",total_systems)
        # # print("total_investigators",total_investigators)
        # print("total_companies",total_companies)
        # print("total_establishments",total_establishments)
        summary_data = {
            "total_observations": int(total_observations),
            "total_systems": int(total_systems),
            "total_investigators": int(total_investigators),
            "total_companies": int(total_companies),
            "total_establishments" : int(total_establishments),
            "investigator_details": ind_investigator_counts,
            "system_details": system_counts,
            "establishment_details": establishment_counts,
            "pre_keyword_total_observations": pre_keyword_total_observations,
            "post_keyword_total_observations" : post_keyword_total_observations,
        }
        # print("summary_data", summary_data)
        # Aggregating data
        # Clean FEI numbers safely
        def clean_fei(val):
            if pd.isna(val) or val is None:
                return ""
            s = str(val).strip()
            if s.endswith('.0'):
                s = s[:-2]
            return s

        filtered_df['__fei_clean'] = filtered_df['FEI Number'].apply(clean_fei)
        filtered_df['__group_key'] = filtered_df.apply(
            lambda r: r['__fei_clean'] if r['__fei_clean'] else f"NO_FEI::{str(r.get('Company Name', '') or '').strip()}::{str(r.get('City, Country', '') or '').strip()}",
            axis=1
        )

        group_counts = filtered_df.groupby('__group_key')['Form 483 Observation'].nunique().to_dict()

        grouped_meta = (
            filtered_df.assign(
                __year_key=pd.to_numeric(filtered_df['Year of Inspection'], errors='coerce')
            )
            .groupby(['__group_key'], as_index=False)
            .agg(
                latest_year=('__year_key', 'max'),
                earliest_year=('__year_key', 'min'),
                company_name_sort=('Company Name', 'first')
            )
        )

        grouped_meta['__name_sort'] = grouped_meta['company_name_sort'].fillna("").astype(str).str.lower()
        if key_word_search:
            grouped_meta = grouped_meta.sort_values(
                by=['latest_year', '__name_sort'],
                ascending=[False, True],
                na_position='last',
            )
            ordered_keys = grouped_meta['__group_key'].tolist()
            paginated_data = None
        else:
            grouped_meta = grouped_meta.sort_values(
                by=['earliest_year', '__name_sort'],
                ascending=[True, True],
                na_position='last',
            )
            key_series = grouped_meta['__group_key']
            paginator = Paginator(key_series.tolist(), page_size)
            try:
                paginated_data = paginator.page(page)
            except PageNotAnInteger:
                paginated_data = paginator.page(1)
            except EmptyPage:
                paginated_data = paginator.page(paginator.num_pages)
            ordered_keys = list(paginated_data.object_list)

        selected_key_set = set(ordered_keys)
        page_df = filtered_df[filtered_df['__group_key'].isin(selected_key_set)] if selected_key_set else filtered_df.iloc[0:0]

        aggregated_data = defaultdict(lambda: {
            'company_name': "",
            'organization_name': "",
            'fei_number': "",
            'classification': "",
            'location': '',
            'type_of_establishment': set(),
            'obs_primary_type': {},
            'year_of_inspection': defaultdict(lambda: defaultdict(dict)),
            'year_classification': {},  # Store classification per year
            'inspections_raw': []
        })
        MIGRATED_IMAGE_FILENAMES = config("MIGRATE_FLAG", cast=bool, default=False)  # run only once, then turn False

        def split_establishment_types(value):
            if not value or str(value).lower() == 'nan':
                return ["Not Specified"]
            return [
                item.strip()
                for item in re.split(r"\s*&\s*|,", str(value))
                if item and item.strip()
            ]

        def prepare_observation_details(row_index, row, persist_excel_markup=False):
            details = row['Observation Details']
            company_value = row['Company Name'].strip() if row['Company Name'] else ""
            year_value = str(row['Year of Inspection'])
            system_value_local = row['System']
            observation_num_value = row['Form 483 Observation']

            details_text = str(details) if details is not None else ""
            has_image_markup = (
                "<image" in details_text
                or "<img:" in details_text
                or "/new_observation_images/" in details_text
            )

            if not has_image_markup:
                return details, details

            lookup_key = f"{company_value}::{year_value}::{system_value_local}::{observation_num_value}::{details}"
            if lookup_key in observation_detail_mapping:
                detail_num_value = observation_detail_mapping[lookup_key]
            else:
                detail_num_value = 1

            image_tags = OLD_IMAGE_TAG_REGEX.findall(details_text)
            excel_ready_details = normalize_image_markup(details)

            if MIGRATED_IMAGE_FILENAMES:
                for img_idx, img_num in enumerate(image_tags, start=1):
                    filename = get_image_filename(
                        company=company_value,
                        year=year_value,
                        system=system_value_local,
                        observation_num=observation_num_value,
                        detail_num=detail_num_value,
                        img_num=img_idx
                    ).split("/")[-1]

                    ensure_image_object_exists(filename=filename)
                    excel_ready_details = excel_ready_details.replace(
                        f"<image{img_num}>",
                        f"<img:{filename}>"
                    )

                current_image_names = [
                    name.strip()
                    for name in re.findall(IMG_TAG_REGEX, str(excel_ready_details))
                    if isinstance(name, str) and name.strip()
                ]
                for filename in dict.fromkeys(current_image_names):
                    ensure_image_object_exists(filename=filename)

            rendered_details = replace_image_tags(excel_ready_details)

            if persist_excel_markup and df1.loc[row_index, "Observation Details"] != excel_ready_details:
                df1.loc[row_index, "Observation Details"] = excel_ready_details

            return excel_ready_details, rendered_details

        if MIGRATED_IMAGE_FILENAMES:
            for row_index, row in filtered_df.iterrows():
                prepare_observation_details(row_index, row, persist_excel_markup=True)

        for row_index, row in page_df.iterrows():
            company = row['Company Name'].strip() if row['Company Name'] else ""
            location_key = row['City, Country'].strip() if row['City, Country'] else ""
            fei_clean = clean_fei(row['FEI Number'])
            group_key = fei_clean if fei_clean else f"NO_FEI::{company}::{location_key}"

            location_data = aggregated_data[group_key]

            location_data['organization_name'] = (row['Organization Name'] or "").strip()
            location_data['fei_number'] = fei_clean if fei_clean else "N/A"
            location_data['classification'] = (row['Classification'] or "").strip() if 'Classification' in row else ""
            location_data['total_fda_observation'] = group_counts.get(group_key, 0)
            location_data['type_of_establishment'].add(row['Type of establishment'])

            # Save raw inspection metadata to determine latest company name & address later
            year = str(int(float(row['Year of Inspection']))) if pd.notna(row['Year of Inspection']) else "0"
            date_value = pd.to_datetime(row['Month of Inspection'], errors='coerce')
            date = date_value.strftime('%Y %B') if pd.notna(date_value) else None

            location_data['inspections_raw'].append({
                'year': int(row['Year of Inspection']) if pd.notna(row['Year of Inspection']) else 0,
                'date_val': date_value if pd.notna(date_value) else pd.Timestamp.min,
                'company_name': company,
                'address': location_key
            })

            year = str(int(float(row['Year of Inspection']))) if pd.notna(row['Year of Inspection']) else "0"
            date_value = pd.to_datetime(row['Month of Inspection'], errors='coerce')
            date = date_value.strftime('%Y %B') if pd.notna(date_value) else None

            # Store classification for each year
            if year not in location_data['year_classification']:
                location_data['year_classification'][year] = (row['Classification'] or "").strip() if 'Classification' in row else ""

            # Ensure dictionary structure exists
            if date not in location_data['year_of_inspection'][year]:
                location_data['year_of_inspection'][year][date] = {'metadata': {}, 'systems': {}}

            # Add metadata if not already present

            location_data['year_of_inspection'][year][date]['metadata'] = {
                    'fda_investigators': "" if row['FDA Investigator(s) name'] == None else row['FDA Investigator(s) name']
                }

            system = row['System']
            if system not in location_data['year_of_inspection'][year][date]['systems']:
                location_data['year_of_inspection'][year][date]['systems'][system] = {
                    'observation_count': 0,
                    'observations': {}
                }

            observation_num = row['Form 483 Observation']
            obs_key = f"{observation_num}"
            # Include type_of_establishment in unique_obs_key so that the same
            # observation number from different establishment types is NOT collapsed.
            raw_type_for_key = str(row['Type of establishment']).strip() if row['Type of establishment'] else 'Not Specified'
            if not raw_type_for_key or raw_type_for_key.lower() in ('nan', 'none'):
                raw_type_for_key = 'Not Specified'
            unique_obs_key = f"{year}::{date}::{system}::{raw_type_for_key}::{obs_key}"

            # Count each observation exactly ONCE per system (first content row wins).
            is_new_obs = obs_key not in location_data['year_of_inspection'][year][date]['systems'][system]['observations']
            if is_new_obs:
                location_data['year_of_inspection'][year][date]['systems'][system]['observation_count'] += 1

            # Assign a single canonical type to each unique observation (first-row wins).
            # Splitting combined types and picking the first ensures no double-counting:
            # sum(type_counts) == len(obs_primary_type) == total_fda_observation.
            if unique_obs_key not in location_data['obs_primary_type']:
                raw_type_str = str(row['Type of establishment']).strip() if row['Type of establishment'] else ''
                if raw_type_str and raw_type_str.lower() not in ('nan', 'none', 'not specified', ''):
                    # Split combined types (e.g. "A & B") and take the first canonical type
                    parts = [p.strip() for p in re.split(r'\s*&\s*|,', raw_type_str) if p.strip()]
                    primary_type = parts[0] if parts else 'Not Specified'
                else:
                    primary_type = 'Not Specified'
                location_data['obs_primary_type'][unique_obs_key] = primary_type

            if obs_key not in location_data['year_of_inspection'][year][date]['systems'][system]['observations']:
                location_data['year_of_inspection'][year][date]['systems'][system]['observations'][obs_key] = {
                    'contents': [],
                    'summaries': [],
                    'type_of_establishment': [],
                }

            details = row['Observation Details']
            lookup_key = f"{company}::{year}::{system}::{observation_num}::{details}"
            if lookup_key in observation_detail_mapping:
                detail_num = observation_detail_mapping[lookup_key]
            else:
                # Fallback to position in filtered results if mapping not found
                detail_num = len(location_data['year_of_inspection'][year][date]['systems'][system]['observations'][obs_key]['contents']) + 1

            # detail_num = len(location_data['year_of_inspection'][year][date]['systems'][system]['observations'][obs_key]['contents']) + 1
            excel_ready_details, rendered_details = prepare_observation_details(
                row_index,
                row,
                persist_excel_markup=MIGRATED_IMAGE_FILENAMES
            )
            observation_entry = location_data['year_of_inspection'][year][date]['systems'][system]['observations'][obs_key]
            row_type_of_establishment = str(row['Type of establishment']).strip() if row['Type of establishment'] else 'Not Specified'
            if not row_type_of_establishment or row_type_of_establishment.lower() in ('nan', 'none'):
                row_type_of_establishment = 'Not Specified'
            if row_type_of_establishment not in observation_entry['type_of_establishment']:
                observation_entry['type_of_establishment'].append(row_type_of_establishment)
            observation_entry['contents'].append({
                'content': rendered_details,
                'type_of_establishment': row_type_of_establishment
            })
            summary_value = row.get('Summary') if 'Summary' in row.index else None
            if pd.notna(summary_value):
                normalized_summary = str(summary_value).strip()
                if normalized_summary and normalized_summary not in observation_entry['summaries']:
                    observation_entry['summaries'].append(normalized_summary)
        if MIGRATED_IMAGE_FILENAMES:
            active_excel_path = get_active_excel_path()
            import uuid
            temp_path = f"{active_excel_path}.{uuid.uuid4().hex}.tmp.xlsx"
            df1.to_excel(temp_path, index=False)
            _persist_excel_atomic(temp_path, active_excel_path)
            print("[INFO] Updated Excel saved:", active_excel_path)

        # Convert data into the required format for the frontend
        def sort_key(entry):
            name = entry['company_name'].strip()

            try:
                years = [int(y) for y in entry['year_of_inspection'].keys()]
                latest_year = max(years)
                earliest_year = min(years)
            except ValueError:
                latest_year = 0
                earliest_year = 9999

            # Keyword search -> NEW to OLD
            if key_word_search:
                return (-latest_year, name.lower())

            # Default (non-keyword) → OLD to NEW
            return (earliest_year, name.lower())
        formatted_by_key = {}
        for group_key, data in aggregated_data.items():
            type_counts = defaultdict(int)
            for obs_id, ptype in data['obs_primary_type'].items():
                type_counts[ptype] += 1

            total_obs_count = len(data['obs_primary_type'])

            # Determine latest company name, address, and histories
            sorted_inspections = sorted(
                data['inspections_raw'],
                key=lambda x: (x['year'], x['date_val']),
                reverse=True
            )

            latest_company = sorted_inspections[0]['company_name'] if sorted_inspections else ""
            latest_address = sorted_inspections[0]['address'] if sorted_inspections else ""

            address_history = []
            seen_addresses = set()
            for insp in sorted_inspections:
                addr = insp['address']
                if addr and addr not in seen_addresses:
                    seen_addresses.add(addr)
                    address_history.append({
                        'year': insp['year'],
                        'address': addr,
                    })

            company_history = []
            seen_companies = set()
            for insp in sorted_inspections:
                comp = insp['company_name']
                if comp and comp not in seen_companies:
                    seen_companies.add(comp)
                    company_history.append({
                        'year': insp['year'],
                        'company_name': comp,
                    })

            for idx, addr_item in enumerate(address_history):
                if idx == 0:
                    addr_item['label'] = f"{addr_item['year']} · Latest"
                else:
                    addr_item['label'] = f"{addr_item['year']} · Relocated"

            for idx, comp_item in enumerate(company_history):
                if idx == 0:
                    comp_item['label'] = f"{comp_item['year']} · Current"
                else:
                    comp_item['label'] = f"{comp_item['year']} · Previous"

            formatted_by_key[group_key] = {
                'company_name': latest_company,
                'organization_name': data['organization_name'],
                'fei_number': data['fei_number'],
                'classification': data['classification'],
                'year_classification': data['year_classification'],
                'location': latest_address,
                'type_of_establishment': sorted(list(data['type_of_establishment'])),
                'type_observation_counts': dict(sorted(type_counts.items())),
                'total_fda_observation': total_obs_count,
                'year_of_inspection': dict(sorted(data['year_of_inspection'].items(), key=lambda kv: int(kv[0]), reverse=True)),
                'obs_primary_type': data['obs_primary_type'],
                'address_history': address_history,
                'company_history': company_history
            }

        formatted_response = [formatted_by_key[k] for k in ordered_keys if k in formatted_by_key]
        if key_word_search:
            formatted_response = sorted(formatted_response, key=sort_key)

        if key_word_search:
            return Response({
                "data": formatted_response,   # full data
                "summary": summary_data,
                "pagination": {
                    "current_page": 1,
                    "total_pages": 1,
                    "total_count": len(formatted_response),
                    "has_next": False,
                    "has_previous": False,
                    "page_size": len(formatted_response)
                }
            })

        return Response({
            "data": formatted_response,
            "summary": summary_data,
            "pagination": {
                "current_page": paginated_data.number,
                "total_pages": paginator.num_pages,
                "total_count": paginator.count,
                "has_next": paginated_data.has_next(),
                "has_previous": paginated_data.has_previous(),
                "page_size": page_size
            }
        })
    return Response({"error": "Only POST method allowed"}, status=405)

@api_view(['GET'])
def list_of_organization_names(request):
    try:
        # excel_file_path = get_active_excel_path()
        # df1 = pd.read_excel(excel_file_path, sheet_name="Sheet1")
        # df1 = pd.read_excel(excel_file_path, engine='openpyxl')
        df1 = get_cached_df()
        df1 = df1.where(pd.notnull(df1), None)
        filtered_df = df1[df1['Type of establishment'] != 'OTC Drug Manufacturer']
        organizations = filtered_df['Organization Name'].dropna().astype(str).str.strip().unique().tolist()

        organizations = sorted(organizations)
        return JsonResponse({"organization_names": organizations}, status=200)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

@api_view(['GET'])

def list_of_fei_numbers(request):
    try:
        df1 = get_cached_df()
        df1 = df1.where(pd.notnull(df1), None)
        filtered_df = df1[df1['Type of establishment'] != 'OTC Drug Manufacturer']
        feis = (
            filtered_df['FEI Number']
            .dropna()
            .astype(str)
            .str.strip()     # remove spaces before and after
            .unique()
            .tolist()
        )
        feis = sorted(feis)
        return JsonResponse({"fei_numbers": feis}, status=200)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

@api_view(['GET'])
def list_of_country(request):
    try:
        df1 = get_cached_df()
        df1 = df1.where(pd.notnull(df1), None)
        filtered_df = df1[df1['Type of establishment'] != 'OTC Drug Manufacturer']
        countries = (
            filtered_df['Country']
            .dropna()
            .astype(str)
            .str.strip()
            .map(lambda value: value.split(',')[-1].strip() if ',' in value else value.strip())
            .map(lambda value: re.sub(r'\s*\([^)]+\)$', '', value).strip())
        )
        countries = sorted({country for country in countries if country})
        return JsonResponse({"countries": countries}, status=200)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@api_view(['GET'])
def list_of_company(request):
    try:
        # excel_file_path = get_active_excel_path()
        # df1 = pd.read_excel(excel_file_path, sheet_name="Sheet1")
        # df1 = pd.read_excel(excel_file_path, engine='openpyxl')
        df1 = get_cached_df()
        df1 = df1.where(pd.notnull(df1), None)
        filtered_df = df1[df1['Type of establishment'] != 'OTC Drug Manufacturer']
        companies = filtered_df['Company Name'].dropna().astype(str).str.strip().unique().tolist()

        companies = sorted(companies)
        return JsonResponse({"companies": companies}, status=200)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

@api_view(['GET'])
def list_of_investigators(request):
    try:
        # excel_file_path = get_active_excel_path()
        # df1 = pd.read_excel(excel_file_path, sheet_name="Sheet1")
        # df1 = pd.read_excel(excel_file_path, engine='openpyxl')
        df1 = get_cached_df()
        df1 = df1.where(pd.notnull(df1), None)
        filtered_df = df1[df1['Type of establishment'] != 'OTC Drug Manufacturer']

        investigators = filtered_df['FDA Investigator(s) name'].dropna()
        investigators = investigators.astype(str).str.replace(r'\n', ',', regex=True)
        investigators = investigators.str.split(',').explode().str.strip()

        investigators = investigators[investigators != ""].unique().tolist()
        investigators = sorted(investigators)
        return JsonResponse({"investigators": investigators}, status=200)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

@api_view(['GET'])
def list_of_establishments(request):
    try:
        df1 = get_cached_df()
        df1 = df1.where(pd.notnull(df1), None)
        filtered_df = df1[df1['Type of establishment'] != 'OTC Drug Manufacturer']

        establishments = filtered_df['Type of establishment'].dropna()
        establishments = establishments.astype(str).str.strip()
        establishments = establishments[establishments != ""].unique().tolist()
        establishments = sorted(establishments)
        return JsonResponse({"establishments": establishments}, status=200)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

@api_view(['GET'])
def list_of_systems(request):
    try:
        df1 = get_cached_df()
        df1 = df1.where(pd.notnull(df1), None)
        filtered_df = df1[df1['Type of establishment'] != 'OTC Drug Manufacturer']

        systems = filtered_df['System'].dropna().astype(str).str.strip().unique().tolist()
        systems = sorted(systems)
        return JsonResponse({"systems": systems}, status=200)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

@api_view(['GET'])
def list_of_years(request):
    try:
        df1 = get_cached_df()
        df1 = df1.where(pd.notnull(df1), None)
        filtered_df = df1[df1['Type of establishment'] != 'OTC Drug Manufacturer']

        years = (
                filtered_df['Year of Inspection']
                .dropna()
                .astype(float)
                .astype(int)
                .astype(str)
                .unique()
                .tolist()
            )


        print("years", years)
        years = sorted(years)
        return JsonResponse({"years": years}, status=200)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

# Warning Letter
def warning_letter(request):
    user = request.user

    data = get_cached_warning_letter_df()

    total_letters = int(len(data))
    total_companies = (
        int(data["Company Name"].nunique()) if "Company Name" in data.columns else 0
    )

    yearwise_labels = []
    yearwise_values = []
    if {"Year", "Company Name"}.issubset(set(data.columns)):
        year_series = pd.to_numeric(data["Year"], errors="coerce").dropna().astype(int)
        grouped = (
            data.loc[year_series.index]
            .assign(Year=year_series)
            .groupby("Year")["Company Name"]
            .nunique()
            .sort_index()
        )
        yearwise_labels = grouped.index.astype(int).tolist()
        yearwise_values = grouped.astype(int).tolist()

    flag = False
    if request.user.is_authenticated:
        try:
            assignment = AssignChecker.objects.get(user=user)
            flag = "Warning Latter" in (assignment.assigned_report or "")
        except AssignChecker.DoesNotExist:
            flag = False

    context = {
        "flag": flag,
        "total_companies": total_companies,
        "total_letters": total_letters,
        "yearwise_labels": yearwise_labels,
        "yearwise_values": yearwise_values,
    }

    return render(request, "warningletterdashboard.html", context)

def render_warning_letter(request):
    return render(request,'warningletter.html')

def inspection_hub(request):
    return render(request, 'Inspection_hub.html')

def usfda_guideline(request):
    return render(request, 'UsfdaGuidline.html')

def section_inspection(request):
    return render(request, 'Section_inspection.html')

def playbook(request):
    return render(request, 'Playbook.html')




@api_view(['GET'])
def warning_letter_company(request):
    try:
        df_warning_letter = get_cached_warning_letter_df()
        companies = df_warning_letter['Company Name'].dropna().unique().tolist()
        companies = sorted(companies)

        return JsonResponse({"companies": companies }, status=200)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)



def normalize_key(company, letter_date_str, year):
    company = company.strip().replace('/', '_')

    # Handle None letter_date_str
    if letter_date_str is None:
        letter_date_str = ''

    try:
        from datetime import datetime as dt
        if letter_date_str.strip():  # Only parse if not empty
            date_obj = dt.strptime(letter_date_str.strip(), '%B %d, %Y')
            letter_date_str = date_obj.strftime('%B %d, %Y')  # Forces same formatting
    except (ValueError, AttributeError):
        pass  # Leave date as-is if parsing fails
    return (company, letter_date_str, int(year) if year else 0)


def _migrate_warning_letter_pdfs_from_static_to_media():
    pdf_dir = os.path.join(settings.BASE_DIR, "static", "pdfs")
    if not os.path.exists(pdf_dir):
        return 0

    existing_names = set(
        WarningLetterPdf.objects.values_list("pdf_name", flat=True)
    )

    migrated = 0
    for filename in os.listdir(pdf_dir):
        if not filename.lower().endswith(".pdf"):
            continue

        # Keep the same format the UI expects: "Company - Month DD, YYYY.pdf"
        if " - " not in filename:
            continue

        if filename in existing_names:
            continue

        src_path = os.path.join(pdf_dir, filename)
        if not os.path.isfile(src_path):
            continue

        obj = WarningLetterPdf(pdf_name=filename)
        with open(src_path, "rb") as fp:
            obj.pdf_file.save(filename, File(fp), save=False)
        obj.save()
        existing_names.add(filename)
        migrated += 1

    return migrated


def build_pdf_mapping():
    pdf_mapping = {}

    migrate_flag = getattr(settings, "MIGRATE_FLAG_WARNING_LETTER", None)
    if migrate_flag is None:
        migrate_flag = config("MIGRATE_FLAG_WARNING_LETTER", cast=bool, default=False)

    if migrate_flag:
        migrated = _migrate_warning_letter_pdfs_from_static_to_media()
        if migrated:
            print(f"[INFO] Migrated {migrated} warning-letter PDFs into media + WarningLetterPdf.")

    # Serving logic: prefer DB/media whenever objects exist (flag only controls the one-time migration step).
    if WarningLetterPdf.objects.exists():
        for obj in WarningLetterPdf.objects.all().only("pdf_name", "pdf_file"):
            filename = obj.pdf_name
            if not filename or " - " not in filename or not filename.lower().endswith(".pdf"):
                continue

            name_part, date_part = filename.rsplit(" - ", 1)
            name = name_part.strip()
            date_str_raw = date_part.replace(".pdf", "").strip()
            date_str_raw = re.sub(r"\s*\(.*\)$", "", date_str_raw)  # remove trailing brackets

            if re.match(r"^[A-Za-z]+\s\d{1,2},\s\d{4}$", date_str_raw, re.IGNORECASE):
                try:
                    from datetime import datetime as dt
                    date_obj = dt.strptime(date_str_raw, "%B %d, %Y")
                    year = date_obj.year
                    date_str = date_obj.strftime("%B %d, %Y")
                    key = normalize_key(name, date_str, year)
                    pdf_mapping[key] = obj.pdf_file.url
                except ValueError:
                    continue

        return pdf_mapping

    pdf_dir = os.path.join(settings.BASE_DIR, 'static', 'pdfs')

    if not os.path.exists(pdf_dir):
        return pdf_mapping

    for filename in os.listdir(pdf_dir):
        if filename.lower().endswith('.pdf') and ' - ' in filename:
            name_part, date_part = filename.rsplit(' - ', 1)
            name = name_part.strip()
            date_str_raw = date_part.replace('.pdf', '').strip()
            date_str_raw = re.sub(r'\s*\(.*\)$', '', date_str_raw)  # remove trailing brackets

            if re.match(r'^[A-Za-z]+\s\d{1,2},\s\d{4}$', date_str_raw, re.IGNORECASE):
                try:
                    from datetime import datetime as dt
                    date_obj = dt.strptime(date_str_raw, '%B %d, %Y')
                    year = date_obj.year
                    date_str = date_obj.strftime('%B %d, %Y')
                    key = normalize_key(name, date_str, year)
                    pdf_mapping[key] = f"/static/pdfs/{filename}"
                except ValueError:
                    continue

    return pdf_mapping


@csrf_exempt
@api_view(['GET', 'POST'])
def warning_letter_data(request):
    if request.method == "POST":
        company_name = request.data.get('company_name')
        issuing_office = request.data.get('issuing_office')
        year = request.data.get('posted_year')

        df_warning_letter = get_cached_warning_letter_df()
        updated_excel = False
        excel_saved = False
        excel_save_error = None
        if "filename" not in df_warning_letter.columns:
            df_warning_letter["filename"] = None
            updated_excel = True

        # Build mapping (also performs PDF->model migration when enabled)
        pdf_mapping = build_pdf_mapping()
        pdf_url_by_name = {
            obj.pdf_name: obj.pdf_file.url
            for obj in WarningLetterPdf.objects.all().only("pdf_name", "pdf_file")
            if obj.pdf_name and obj.pdf_file
        }

        migrate_flag = getattr(settings, "MIGRATE_FLAG_WARNING_LETTER", None)
        if migrate_flag is None:
            migrate_flag = config("MIGRATE_FLAG_WARNING_LETTER", cast=bool, default=False)

        # Backfill filename for the whole sheet once (so blanks don't persist just because of filters)
        if migrate_flag:
            needs_backfill = False
            if df_warning_letter["filename"].isna().any():
                needs_backfill = True
            else:
                # Handle previously-saved URL-encoded values (e.g. %20)
                try:
                    if df_warning_letter["filename"].astype(str).str.contains("%", na=False).any():
                        needs_backfill = True
                except Exception:
                    pass

            if needs_backfill:
                filled_count = 0
                for row_index, row in df_warning_letter.iterrows():
                    company_val = row.get("Company Name")
                    if not isinstance(company_val, str) or not company_val.strip():
                        continue

                    letter_date = None
                    if pd.notna(row.get("Letter Issue Date")):
                        try:
                            letter_date = pd.to_datetime(row.get("Letter Issue Date")).strftime('%B %d, %Y').strip()
                        except Exception:
                            letter_date = None

                    if not letter_date:
                        continue

                    company_clean = company_val.strip().replace("/", "_")
                    try:
                        yr = int(pd.to_datetime(letter_date).year)
                    except Exception:
                        yr = row.get("Year")

                    lookup_key = normalize_key(company_clean, letter_date, yr)
                    pdf_path = pdf_mapping.get(lookup_key)

                    expected_pdf_name = f"{company_clean} - {letter_date}.pdf"
                    if pdf_path:
                        from urllib.parse import unquote, urlparse
                        stored_filename = unquote(os.path.basename(urlparse(pdf_path).path))
                    else:
                        stored_filename = expected_pdf_name

                    if df_warning_letter.at[row_index, "filename"] != stored_filename:
                        df_warning_letter.at[row_index, "filename"] = stored_filename
                        updated_excel = True
                        filled_count += 1

                if filled_count:
                    print(f"[INFO] Backfilled {filled_count} warning-letter filenames in Excel dataframe.")

        filtered_df = df_warning_letter.copy()

        # Ensure 'Year' column exists (extract from 'Letter Issue Date' if needed)
        if 'Year' not in filtered_df.columns and 'Letter Issue Date' in filtered_df.columns:
            try:
                filtered_df['Year'] = pd.to_datetime(filtered_df['Letter Issue Date'], errors='coerce').dt.year
            except Exception as e:
                print(f"[WARNING] Could not extract Year from Letter Issue Date: {e}")

        # Filter by company name
        if company_name and 'Company Name' in filtered_df.columns:
            if isinstance(company_name, list):
                company_name = [c.replace('/', '_') for c in company_name]
            else:
                company_name = company_name.replace('/', '_')

            filtered_df['Company Name'] = filtered_df['Company Name'].apply(
                lambda x: x.replace('/', '_') if isinstance(x, str) else x
            )
            filtered_df = filtered_df[filtered_df['Company Name'].isin(company_name)]

        # Filter by issuing office
        if issuing_office and 'Issuing Office' in filtered_df.columns:
            filtered_df = filtered_df[filtered_df['Issuing Office'].isin(issuing_office)]

        # Filter by year
        if year and 'Year' in filtered_df.columns:
            filtered_df = filtered_df[filtered_df['Year'].isin(year)]

        # Sort company names alphabetically so UI shows A-Z order
        filtered_df = filtered_df.sort_values(
            by='Company Name',
            key=lambda col: col.str.lower() if col.dtype == object else col,
            na_position='last'
        )

        result_data = []

        # Process each row
        for row_index, row in filtered_df.iterrows():
            letter_date = None
            # Check if 'Letter Issue Date' column exists before accessing it
            if 'Letter Issue Date' in filtered_df.columns and pd.notna(row.get('Letter Issue Date')):
                try:
                    letter_date = pd.to_datetime(row['Letter Issue Date']).strftime('%B %d, %Y').strip()
                except Exception as e:
                    print(f"Date parse error: {e}")
                    letter_date = None

            # Get Company Name with fallback
            company = row.get('Company Name')
            if not isinstance(company, str):
                print(f"[WARNING] Row {row_index}: Company Name is not a string: {company}")
                continue
            company = company.strip().replace('/', '_')

            # Use letter's actual year for lookup
            yr = None
            if letter_date:
                try:
                    yr = int(pd.to_datetime(letter_date).year)
                except Exception as e:
                    print(f"Year extract error: {e}")
                    if 'Year' in row and pd.notna(row['Year']):
                        try:
                            yr = int(row['Year'])
                        except Exception:
                            pass

            # Expected PDF filename format
            expected_pdf_name = f"{company} - {letter_date}.pdf"

            # **Single concise debug print**
            # print(f"EXCEL: '{row['Company Name']}' ({letter_date})  →  Expected PDF: '{expected_pdf_name}'")

            lookup_key = normalize_key(company, letter_date, yr)

            excel_filename = row.get("filename")
            excel_filename = excel_filename.strip() if isinstance(excel_filename, str) else None
            excel_filename = excel_filename or None

            # 1) If Excel explicitly provides a filename, use that as the source of truth (manual uploads).
            if excel_filename:
                pdf_path = pdf_url_by_name.get(excel_filename)
            else:
                # 2) Try exact expected filename against DB (handles duplicates like "(2).pdf").
                pdf_path = pdf_url_by_name.get(expected_pdf_name)
                # 3) Fallback to company/date key mapping (DB or static, depending on what's available).
                if not pdf_path:
                    pdf_path = pdf_mapping.get(lookup_key)

            # Only auto-write/overwrite Excel filenames during the one-time migration flow.
            if migrate_flag:
                if pdf_path:
                    from urllib.parse import unquote, urlparse
                    stored_filename = unquote(os.path.basename(urlparse(pdf_path).path))
                else:
                    stored_filename = expected_pdf_name

                if df_warning_letter.at[row_index, "filename"] != stored_filename:
                    df_warning_letter.at[row_index, "filename"] = stored_filename
                    updated_excel = True

            letter_info = {
                'company_name': company,
                'posted_date': yr,
                'letter_issue_date': letter_date,
                'issuing_office': row.get('Issuing Office', ' ') if 'Issuing Office' in filtered_df.columns and pd.notna(row.get('Issuing Office')) else ' ',
                'subject': row.get('Subject', ''),
                'pdf_path': pdf_path,
            }
            result_data.append(letter_info)

        if updated_excel:
            import uuid
            active_excel_path = get_active_warning_letter_excel_path()
            temp_path = f"{active_excel_path}.{uuid.uuid4().hex}.tmp.xlsx"
            df_warning_letter.to_excel(temp_path, index=False)
            try:
                _persist_excel_atomic(temp_path, active_excel_path)
                print("[INFO] Updated Warning Letter Excel saved:", active_excel_path)
                excel_saved = True
            except (PermissionError, FileNotFoundError) as exc:
                excel_save_error = str(exc)
                print(f"[WARN] Could not update Warning Letter Excel ({active_excel_path}): {excel_save_error}")
                try:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                except Exception:
                    pass

        return JsonResponse(
            {
                "data": result_data,
                "meta": {
                    "excel_updated": updated_excel,
                    "excel_saved": excel_saved,
                    "excel_save_error": excel_save_error,
                },
            },
            status=200,
            json_dumps_params={'default': str},
        )

    return JsonResponse({"error": "Invalid request method."}, status=400)



@api_view(['GET'])
def issuing_office_list(request):
    try:

        df_warning_letter = get_cached_warning_letter_df()

        issuing_offices = df_warning_letter['Issuing Office'].dropna().unique().tolist()
        issuing_offices = issuing_offices

        return JsonResponse({"issuing_offices": issuing_offices}, status=200)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

def _convert_defaultdict_to_dict(d):
    """Helper function to convert nested defaultdict to regular dict"""
    if isinstance(d, defaultdict):
        d = {k: _convert_defaultdict_to_dict(v) for k, v in d.items()}
    return d



@api_view(['POST','GET'])
def get_table_483_data(request):
    if request.method == 'POST':
        # print("in the post")
        data = json.loads(request.body)
    return JsonResponse()

def render_company_name(request):
    return render(request,'companypage.html')
def render_investigator(request):
    return render(request,'investigator.html')
def new_investigator(request):
    return render(request,'New_investigatorcard.html')
def particular_investigator(request):
    return render(request,'Particular_investigator_design.html')

def render_yearofinspection(request):
    context = {
        "available_excel_names": get_gmpc_available_excel_names(),
        "selected_active_excel_name": "usa",
    }
    return render(request, 'newyearofinspection.html', context)
def render_systempage(request):
    return render(request,'systempage.html')
def render_system_checklist(request):
    return render(request, 'system_checklist.html')


'''ChatGPT Bot'''
# file_path = os.path.join(settings.BASE_DIR, 'AIDatabase', 'management', 'commands', 'FDA_Final_Cleaned_Data.xlsx')
# df = pd.read_excel(file_path, sheet_name="Sheet1")


# # df["Year of Inspection"] = df["Year of Inspection"].astype(str)
# df.columns = ['Sr. No.', 'Company Name', 'City, Country', 'Type of establishment',
#               'Month of Inspection', 'FDA Investigator(s) name',
#               'Year of Inspection', 'System', 'Form 483 Observation',
#               'Observation Details']

# # client = openai.OpenAI(api_key="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")
# client = openai.OpenAI(api_key="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")  # Replace with your actual OpenAI API key

# def extract_keywords_and_filters(query):
#     response = client.chat.completions.create(
#         model="gpt-4o-mini",
#         messages=[
#             {"role": "system", "content": "You are an expert keyword extractor. Extract key filters and detect if the user wants graphical analysis."},
#             {"role": "user", "content": f"""Extract key filters and corresponding column names as ['Sr. No.', 'Company Name', 'City, Country', 'Type of establishment', 'Month of Inspection', 'FDA Investigator(s) name', 'Year of Inspection', 'System'] from the given query in JSON Format.

#             Also, detect if the user is asking for analysis in graphical format such as charts or graphs.

#             Return JSON as below:
#             {{
#             "filters": {{
#                 "Sr. No.": null,
#                 "Company Name": "company name",
#                 "City, Country": "city and state",
#                 "Type of establishment": null,
#                 "Month of Inspection": null,
#                 "FDA Investigator(s) name": "name of investigators",
#                 "Year of Inspection": null,
#                 "System": null
#                 }},
#             "analysis_flag": false,
#             "chart_type": null
#             }}

#             Query: {query}"""}
#         ]
#     )
#     extracted_text = response.choices[0].message.content.strip()
#     return json.loads(extracted_text.replace("```json\n", "").replace("```", ""))

# def correct_spelling(json_data):
#     response = client.chat.completions.create(
#         model="gpt-4o-mini",
#         messages=[
#             {"role": "system", "content": "You are a spelling correction assistant. Correct spelling mistakes in JSON values without changing keys."},
#             {"role": "user", "content": f"Correct any spelling or grammatical mistakes only in the values of this JSON:\n{json.dumps(json_data)}"}
#         ]
#     )
#     corrected_text = response.choices[0].message.content.strip()
#     return json.loads(corrected_text.replace("```json\n", "").replace("```", ""))

# def generate_graph(df, chart_type="bar", filename="graph.png"):
#     """Generate a chart and save as an image."""
#     file_path = os.path.join("/tmp", filename)  # Change as needed

#     plt.figure(figsize=(10, 6))
#     if chart_type == "bar":
#         sns.countplot(data=df, x="Year of Inspection", palette="coolwarm")  # Example column
#         plt.title("Inspection Count by Year")
#     elif chart_type == "pie":
#         df['Observation Details'].value_counts().plot(kind='pie', autopct='%1.1f%%')
#         plt.title("Observation Distribution")
#     plt.xticks(rotation=45)
#     plt.savefig(file_path)  # Save the graph
#     plt.close()

#     return file_path

# def get_matching_row(query):
#     extracted_data = extract_keywords_and_filters(query)
#     filters = extracted_data.get("filters", {})
#     graphical_analysis = extracted_data.get("analysis_flag", False)
#     chart_type = extracted_data.get("chart_type", "bar")
#     filtered_df = df.copy()
#     file_link = "https://docs.google.com/spreadsheets/d/16uKs6_NYr3Z5InFtnu-YTPFXQwn-nvA2/edit?usp=sharing&ouid=109538213086217519689&rtpof=true&sd=true"

#     # General Search with Fuzzy Matching
#     for column, value in filters.items():
#         if value is not None:  # Only apply filtering if value is not null
#             matches = process.extract(value, df[column].astype(str), limit=5)
#             matched_values = [match[0] for match in matches]
#             filtered_df = filtered_df[filtered_df[column].astype(str).isin(matched_values)]

#     # If no results, check spelling and try refined extraction
#     if filtered_df.empty:
#         extracted_data = extract_keywords_and_filters(query)
#         extracted_data = correct_spelling(extracted_data)
#         filters = extracted_data.get("filters", {})
#         graphical_analysis = extracted_data.get("analysis_flag", False)
#         chart_type = extracted_data.get("chart_type", "bar")
#         filtered_df = df.copy()
#         for column, value in filters.items():
#             if value is not None:
#                 matches = process.extract(value, df[column].astype(str), limit=5)
#                 matched_values = [match[0] for match in matches]
#                 filtered_df = filtered_df[filtered_df[column].astype(str).isin(matched_values)]

#     # If still no results, pass full dataset to model for direct search
#     if filtered_df.empty:
#         if graphical_analysis:
#             graph_path = generate_graph(df, chart_type)  # Generate graph
#             graph_html = f'<img src="{graph_path}" alt="Graphical Analysis">'
#             content = "Behave as FDA Investigator and provide relevant information & graphical analysis for the given dataset along with all the information mentioned in the query. Keep statistical information unchanged and make it easy for high-level executives and managers to understand. Provide the output in Rich Text format as HTML (only body tags) and make it look like a professional document."
#         else:
#             content = "Behave as FDA Investigator and provide relevant information for the given dataset along with all the information mentioned in the query. Keep statistical information unchanged and make it easy for high-level executives and managers to understand. Provide the output in Rich Text format as HTML (only body tags) and make it look like a professional document."
#         response = client.chat.completions.create(
#             model="gpt-4o-mini",
#             messages=[
#                 {"role": "system", "content": content},
#                 {"role": "user", "content": f"The dataset is saved at {file_link}. Please analyze it accordingly.\nQuery: {query}"}
#             ]
#         )
#         extracted_text = response.choices[0].message.content.strip()
#         return filters, extracted_text, graphical_analysis

#     return filters, filtered_df.to_dict(orient="records"), graphical_analysis

# def summarize_row_data(query, graphical_analysis):
#     if graphical_analysis:
#         content = "Provide a summary and graphical analysis for the given rows. Keep statistical information unchanged and make it easy for high-level executives and managers to understand. Provide the output in Rich Text format as HTML (only body tags) and make it look like a professional document."
#     else:
#         content = "Summarize the given rows. Keep statistical information unchanged and make it easy for high-level executives and managers to understand. Provide the output in Rich Text format as HTML (only body tags) and make it look like a professional document."
#     response = client.chat.completions.create(
#         model="gpt-4o-mini",
#         messages=[
#             {"role": "system", "content": content},
#             {"role": "user", "content": str(query)}
#         ]
#     )
#     extracted_text = response.choices[0].message.content.strip()
#     return extracted_text

# file_path = os.path.join(settings.BASE_DIR, 'AIDatabase', 'management', 'commands', 'FDA_DATA.xlsx')

# df = pd.read_excel(file_path, sheet_name="Sheet1")  # Skip title row

# df.columns = ['Sr. No.', 'Company Name', 'City, Country', 'Type of establishment',
#        'Month of Inspection', 'FDA Investigator(s) name',
#        'Year of Inspection', 'System', 'Form 483 Observation',
#        'Observation Details']

# OpenAI API setup
# client = openai.OpenAI(api_key="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")  # Replace with your actual OpenAI API key
# openai.api_key = "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"

# def extract_keywords_and_filters(query):
#     response = openai.ChatCompletion.create(

#         model="gpt-4o-mini",
#         messages=[
#             {"role": "system", "content": "You have to behave as expert keyword extractor from the query"},
#             {"role": "user", "content": """Extract key filters and corresponding column names as ['Sr. No.', 'Company Name', 'City, Country', 'Type of establishment', 'Month of Inspection', 'FDA Investigator(s) name', 'Year of Inspection', 'System'] from the given query in JSON Format as below:
#               {
#               "filters": {
#                   "Sr. No.": null,
#                   "Company Name": null,
#                   "City, Country": null,
#                   "Type of establishment": null,
#                   "Month of Inspection": null,
#                   "FDA Investigator(s) name": null,
#                   "Year of Inspection": null,
#                   "System": null
#                   }
#               }
#             Now i am giving my list of company name list and FDA investigator as array here, company names: ["""+str(df["Company Name"].unique())+"""].
#             FDA Investigator(s) name: ["""+str(df["FDA Investigator(s) name"].unique())+"""].
#              If user have spelling mistake then kindly give correct one if it matches 90%.
#             Query : """+query}
#         ]
#     )
#     # print(response)
#     extracted_text = response.choices[0].message.content.strip()
#     return json.loads(extracted_text.replace("```json\n", "").replace("```", ""))

# def get_matching_row(query):
#     extracted_data = extract_keywords_and_filters(query)
#     # extracted_data = json.loads(json_string)
#     filters = extracted_data.get("filters", {})
#     filtered_df = df.copy()

#     for column, value in filters.items():
#         if value is not None:  # Only apply filtering if value is not null
#             # print("column name: ", column)
#             filtered_df = filtered_df[filtered_df[column].astype(str).str.contains(str(value), case=False, na=False)]
#             # print(filtered_df)

#     return filters, filtered_df.to_dict(orient="records")

# # # Example query
# # # query = "What are the type of establishment for COLONIAL DAMES CO LTD"
# # query = "Give me observations as table of rajiv srivastv investigator"
# # filters, result = get_matching_row(query)
# # print("Extracted Filters:", filters)
# # print("Matching Rows:", result)


# def summarize_row_data(query, user_query):
#     response = openai.ChatCompletion.create(
#         model="gpt-4o-mini",
#         messages=[
#             {"role": "system", "content": "Summarize the given data based on user query. If the output is exceeding limit, than you can more summarize the observations. Make sure to give the output in as HTML starting from body tage."},
#             {"role": "user", "content": f"data : {query} \n user query : {user_query} \n provide the output for all the rows, summarized observations."}
#         ]
#     )
#     extracted_text = response.choices[0].message.content.strip()
#     return extracted_text

# def extract_chart_details(query):
#     response = client.chat.completions.create(
#         model="gpt-4o-mini",
#         messages=[
#             {"role": "system", "content": "Extract chart details (x-axis, y-axis, title, graph_type) in JSON format if the query is relevant for a chart.Only allow graph_type values: 'bar', 'pie', or 'line'."},
#             {"role": "user", "content": f"""
#                 Given the user query, extract chart details in JSON format if applicable:
#                 {{
#                     "x_axis": "",
#                     "y_axis": "",
#                     "title": "",
#                     "graph_type": ""
#                 }}
#                 Ensure that 'graph_type' is only one of the following: "bar", "pie", or "line".
#                 Query: {query}
#             """}
#         ]
#     )

#     extracted_text = response.choices[0].message.content.strip()
#     extracted_text = extracted_text.replace("```json\n", "").replace("```", "")
#     return json.loads(extracted_text)

# def generate_graph(df, query):
#     chart_details = extract_chart_details(query)
#     x_axis = chart_details.get("x_axis")
#     y_axis = chart_details.get("y_axis")
#     title = chart_details.get("title", "Chart")
#     graph_type = chart_details.get("graph_type")

#     if not x_axis or not y_axis or x_axis not in df.columns or y_axis not in df.columns:
#         return None

#     graph_folder = os.path.join(settings.MEDIA_ROOT, 'img', 'creating_graph')
#     os.makedirs(graph_folder, exist_ok=True)
#     sanitized_query = re.sub(r'[^a-zA-Z0-9 ]', '', query).strip().replace(" ", "_")

#     # Shorten to first 6 words for clarity
#     short_query = "_".join(sanitized_query.split("_")[:6])

#     # Generate a unique hash from the query
#     hash_part = hashlib.md5(query.encode()).hexdigest()[:6]

#     filename = f"{short_query}_{hash_part}.png"
#     # filename = "generated_chart.png"
#     file_path = os.path.join(graph_folder, filename)

#     plt.figure(figsize=(10, 6))

#     if graph_type == "bar":
#         counts = df[x_axis].value_counts().nlargest(10)
#         counts.plot(kind="bar", color="lightblue")
#         plt.xlabel(x_axis)
#         plt.ylabel(y_axis)
#         plt.title(title)
#         plt.xticks(rotation=45)

#     elif graph_type == "pie":
#         counts = df[y_axis].value_counts()
#         top = counts.nlargest(6)
#         others = pd.Series({"Others": counts.iloc[6:].sum()})
#         counts = pd.concat([top, others])
#         counts.plot(kind='pie', autopct='%1.1f%%')
#         plt.title(title)
#         plt.axis('equal')

#     elif graph_type == "line":
#         counts = df.groupby(x_axis)[y_axis].sum()
#         counts.plot(kind="line", marker="o", color="green")
#         plt.xlabel(x_axis)
#         plt.ylabel(y_axis)
#         plt.title(title)
#         plt.grid(True)

#     plt.tight_layout()
#     plt.savefig(file_path)
#     plt.close()

#     return f'<br><img src="/media/img/creating_graph/{filename}" alt="Generated Graph">'

# @login_required(login_url='/adminmaster/login/')
# def chat_ui_view(request):
#     """ Renders the chatbot UI """
#     return render(request, 'AIDatabase/Chatbot/ChatUiwithHtmlReponse.html')


# @csrf_exempt
# @api_view(["POST"])
# @permission_classes([AllowAny])
# def chat_with_bot(request):
#     """ Handles chatbot queries and integrates FDA data lookup """
#     if True:
#         # user = CustomUser.objects.get(username="devin")
#         user = request.user
#         user_input = request.data.get("prompt", "").strip()
#         # chat_id = request.data.get(5)
#         chat_id = request.data.get("chat_id")


#         if not user_input:
#             return JsonResponse({"error": "Prompt is required"}, status=400)


#         filters, result = get_matching_row(user_input)
#         if result:
#             final_output = summarize_row_data(result, user_input)
#         else:
#             final_output = "<p>No matching records found.</p>"

#         # graph_html = generate_graph(df, user_input)
#         # if graph_html:
#         #         final_output += graph_html

#         ChatMessage.objects.create(
#             user=user,
#             chat_id= chat_id,
#             user_message=user_input,
#             bot_response=final_output
#         )

#     return JsonResponse({"chat_id": chat_id, "response": final_output}, json_dumps_params={"ensure_ascii": False})


# @csrf_exempt
# @api_view(["POST"])
# @permission_classes([AllowAny])
# def clear_chat(request):
#     try:
#         ChatMessage.objects.filter(user=request.user).delete()
#         return JsonResponse({"message": "Chat cleared successfully"})
#     except Exception as e:
#         return JsonResponse({"error": str(e)}, status=500)


# @csrf_exempt
# @api_view(["POST"])
# @permission_classes([AllowAny])
# def new_chat(request):
#     # user = CustomUser.objects.get(username="devin")
#     user = request.user
#     last_chat = ChatMessage.objects.filter(user=user).order_by("-chat_id").first()
#     new_chat_id = last_chat.chat_id + 1 if last_chat else 1
#     # print("new_chat_id",new_chat_id)

#     return JsonResponse({"chat_id": new_chat_id, "message": "New chat started successfully."})



# @api_view(["GET"])
# @permission_classes([AllowAny])
# def get_all_chat_histories(request):
#     # user = CustomUser.objects.get(username="devin")
#     user = request.user
#     chat_sessions = (
#         ChatMessage.objects.filter(user=user)
#         .values("chat_id")
#         .annotate(last_activity=Max("created_at"))
#         .order_by("-last_activity")
#     )

#     chat_messages = []
#     for session in chat_sessions:
#         latest_message = ChatMessage.objects.filter(
#             chat_id=session["chat_id"], created_at=session["last_activity"]
#         ).first()
#         if latest_message:
#             chat_messages.append({
#                 "chat_id": session["chat_id"],
#                 "message": latest_message.user_message,
#                 "last_activity": session["last_activity"]
#             })

#     return Response(chat_messages)

# @api_view(["GET"])
# @permission_classes([AllowAny])
# def get_all_chat_by_specific_id(request, chat_id):
#     # user = CustomUser.objects.get(username="devin")
#     user = request.user
#     messages = ChatMessage.objects.filter(user=user, chat_id=chat_id).order_by("created_at")
#     serializer = ChatMessageSerializer(messages, many=True)
#     return Response(serializer.data)


# @api_view(["DELETE"])
# @permission_classes([AllowAny])
# def delete_chat_by_id(request, chat_id):
#     # user = CustomUser.objects.get(username="devin")
#     user = request.user
#     messages = ChatMessage.objects.filter(user=user, chat_id=chat_id)
#     messages.delete()
#     return Response({"message": "Chat deleted"})

IMG_TAG_REGEX = r'<img:([^>]+)>'
OBSERVATION_IMAGE_URL_MAP = None


def _get_observation_image_url_map():
    global OBSERVATION_IMAGE_URL_MAP
    if OBSERVATION_IMAGE_URL_MAP is None:
        OBSERVATION_IMAGE_URL_MAP = {
            obj.image_name: obj.image.url
            for obj in ObservationImage.objects.only("image_name", "image")
        }
    return OBSERVATION_IMAGE_URL_MAP

def replace_image_tags(details_text):
    if not details_text:
        return details_text

    image_url_map = _get_observation_image_url_map()

    def repl(match):
        image_name = match.group(1).strip()
        image_url = image_url_map.get(image_name)
        if image_url:
            return image_url

        # The process-level cache can be stale after admin/manual DB updates.
        global OBSERVATION_IMAGE_URL_MAP
        OBSERVATION_IMAGE_URL_MAP = None
        refreshed_map = _get_observation_image_url_map()
        return refreshed_map.get(image_name, f"[MISSING IMAGE: {image_name}]")

    return re.sub(IMG_TAG_REGEX, repl, str(details_text))

LEGACY_PATH_REGEX = re.compile(r"/new_observation_images/([^<>\s\"']+)")
OLD_IMAGE_TAG_REGEX = re.compile(r"<image(\d+)>")

def normalize_image_markup(details_text):
    """
    Ensure we always store <img:filename> tags in Excel, even if legacy /new_observation_images/
    paths or URL-encoded filenames slip in.
    """
    if not details_text:
        return details_text

    def path_repl(match):
        filename = urllib.parse.unquote(match.group(1))
        return f"<img:{filename}>"

    return LEGACY_PATH_REGEX.sub(path_repl, str(details_text))


def ensure_image_object_exists(filename):
    global OBSERVATION_IMAGE_URL_MAP
    old_dir = os.path.join(settings.MEDIA_ROOT, "observation_images")
    new_dir = os.path.join(settings.MEDIA_ROOT, "new_observation_images")

    old_path = os.path.join(old_dir, filename)
    new_path = os.path.join(new_dir, filename)

    if ObservationImage.objects.filter(image_name=filename).exists():
        print("? DB object already exists:", filename)
        return True

    source_path = None
    if os.path.exists(new_path):
        source_path = new_path
    elif os.path.exists(old_path):
        source_path = old_path
    else:
        print("??  FILE NOT FOUND:", old_path)
        return False

    os.makedirs(new_dir, exist_ok=True)

    if source_path == old_path and not os.path.exists(new_path):
        shutil.copy2(old_path, new_path)
        print("?? Copied image:", filename)
        source_path = new_path

    obj = ObservationImage(image_name=filename)
    with open(source_path, "rb") as f:
        file_data = f.read()
    obj.image.save(filename, ContentFile(file_data), save=True)
    OBSERVATION_IMAGE_URL_MAP = None

    print("? CREATED DB object:", filename)
    return True

@api_view(['GET'])
def updates_data(request):
    try:
        unique_updates = {}
        active_updates_form484 = Form483ExcelNewData.objects.all()

        for update in active_updates_form484:
            company_name = (update.company_name or "").strip()
            if not company_name:
                continue
            company_key = company_name.lower()
            if company_key not in unique_updates:
                unique_updates[company_key] = {
                "update_type": "Form 483",
                "company_name": company_name,
                "fei_number": update.fei_number,
                "city_country": update.city_country,
                }

        active_updates_warning_letter = WarningLetterExcelNewData.objects.all()

        for update in active_updates_warning_letter:
            company_name = (update.company_name or "").strip()
            if not company_name:
                continue
            company_key = company_name.lower()
            if company_key in unique_updates:
                existing_type = unique_updates[company_key]["update_type"]
                if "Warning Letter" not in existing_type:
                    unique_updates[company_key]["update_type"] = f"{existing_type}, Warning Letter"
                continue

            unique_updates[company_key] = {
                "update_type": "Warning Letter",
                "company_name": company_name,
            }

        active_updates_list = list(unique_updates.values())
        return JsonResponse({"updates_list": active_updates_list}, status=200)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@api_view(['GET', 'POST'])
@authentication_classes([CsrfExemptSessionAuthentication])
def checked_updates(request):
    try:
        user = request.user
        print("User in checked_updates:", user)
        if not user or not user.is_authenticated:
            return JsonResponse(
                {
                    "error": "Authentication required",
                    "checked_updates": False,
                },
                status=401,
            )

        obj, created = UserCheckedUpdate.objects.get_or_create(user=user)

        if request.method == 'POST':
            data = request.data
            checked = data.get('checked_updates', False)
            obj.checked_updates = checked
            obj.save()

            return JsonResponse({"message": "Updated successfully","checked_updates": obj.checked_updates}, status=200)
        return JsonResponse({"checked_updates": obj.checked_updates}, status=200)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


# @api_view(['GET'])
# def active_announcements(request):
#     today = now().date()

#     announcements = Announcement.objects.filter(
#         active=True,
#         till_date__gte=today
#     ).order_by('-created_at').values(
#         'id', 'title', 'content', 'till_date'
#     )

#     return Response(list(announcements))


@api_view(['GET'])
def system_checklists(request):
    try:
        checklists_qs = SystemChecklist.objects.filter(is_active=True)
        checklists_data = []
        for item in checklists_qs:
            checklists_data.append({
                'system_name': item.system_name,
                'description': item.description,
                'icon': item.icon.url if item.icon else None,
                'file': item.file.url if item.file else None,
                'filename': os.path.basename(item.file.name) if item.file else None,
                'file_type': item.file_type if item.file_type else None,
                'page_len': item.page_len if hasattr(item, 'page_len') else None
            })
        return JsonResponse({"checklists": checklists_data}, status=200)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
def india_manufacturer(request):
    return render(request,'top20recurring.html')

def render_top20recurring_detail(request):
    return render(request,'top20recurring_detail.html')

@api_view(['GET'])
def investigator_insights(request):
    try:
        df = get_cached_df()
        # df = pd.read_excel("media//excel_files//Updated_Recent_Final_updated_file_22_06_2026_stagging_version3.xlsx")
        df = df.where(pd.notnull(df), None)

        investigator_rows = _get_investigator_observation_counts(df)

        page_number = request.GET.get('page', 1)
        page_size = request.GET.get('page_size', 10)
        paginator = Paginator(investigator_rows, page_size)

        try:
            page_obj = paginator.page(page_number)
        except PageNotAnInteger:
            page_obj = paginator.page(1)
        except EmptyPage:
            page_obj = paginator.page(paginator.num_pages)

        return JsonResponse(
            {
                "investigator_insights": list(page_obj.object_list),
                "total_investigators": paginator.count,
                "total_pages": paginator.num_pages,
                "current_page": page_obj.number,
                "has_next": page_obj.has_next(),
                "has_previous": page_obj.has_previous(),
            },
            status=200,
        )
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@api_view(['GET'])
def investigator_detail_insights(request):
    try:
        investigator_name = request.GET.get("investigator") or request.data.get("investigator")

        if not investigator_name:
            return JsonResponse({"error": "investigator parameter is required"}, status=400)

        df = get_cached_df()
        df = df.where(pd.notnull(df), None)

        filtered_rows = []

        for _, row in df.iterrows():
            raw_names = row.get("FDA Investigator(s) name")

            if raw_names is None or pd.isna(raw_names):
                continue

            names = [
                item.strip()
                for item in str(raw_names).replace("\r", ",").replace("\n", ",").split(",")
                if item.strip()
            ]

            if investigator_name in names:
                filtered_rows.append(row)

        if not filtered_rows:
            return JsonResponse({
                "investigator": investigator_name,
                "message": "No data found"
            }, status=200)

        temp_df = pd.DataFrame(filtered_rows)

        classification_col = "Classification"

        if classification_col not in temp_df.columns:
            return JsonResponse({"error": "Classification column not found"}, status=400)

        # 🧠 Calculate both Observation and Inspection Counts
        inspection_class_map = {}
        obs_class_counts = Counter()

        for _, row in temp_df.iterrows():
            classification_val = str(row.get(classification_col) or "").strip().upper()
            obs_class_counts[classification_val] += 1

            inspection_date = pd.to_datetime(row.get("Month of Inspection"), errors="coerce")
            inspection_key = row.get("FEI with Inspection End Date")
            if not inspection_key or str(inspection_key).strip() == "":
                company_name = str(row.get("Company Name") or "").strip()
                date_key = (
                    inspection_date.strftime("%Y-%m-%d")
                    if not pd.isna(inspection_date)
                    else str(row.get("Month of Inspection") or "").strip()
                )
                inspection_key = f"{company_name}|{date_key}"

            if inspection_key not in inspection_class_map:
                inspection_class_map[inspection_key] = classification_val

        unique_class_counts = Counter(inspection_class_map.values())
        total = len(temp_df) # Total observations

        classification_data = {
            "OAI (Official Action)": {
                "count": int(unique_class_counts.get("OAI", 0)),
                "percentage": round((obs_class_counts.get("OAI", 0) / total) * 100, 2) if total else 0
            },
            "VAI (Voluntary Action)": {
                "count": int(unique_class_counts.get("VAI", 0)),
                "percentage": round((obs_class_counts.get("VAI", 0) / total) * 100, 2) if total else 0
            },
            "NAI (No Action)": {
                "count": int(unique_class_counts.get("NAI", 0)),
                "percentage": round((obs_class_counts.get("NAI", 0) / total) * 100, 2) if total else 0
            }
        }

        if "System" not in temp_df.columns:
            return JsonResponse({"error": "System column not found"}, status=400)

        systems_counter = Counter(
            temp_df["System"]
            .dropna()
            .apply(_normalize_system_name)
            .dropna()
        )

        system_mapping = {
            "quality system": "Quality System",
            "facilities and equipment system": "Facilities & Equipment System",
            "laboratory control system": "Laboratory Control System",
            "production system": "Production System",
            "material system": "Material System",
            "packaging and labeling system": "Labelling & Packaging System"
        }

        system_data = {
            display_name: systems_counter.get(internal_key, 0)
            for internal_key, display_name in system_mapping.items()
        }

        year_inspection_map = defaultdict(set)

        for _, row in temp_df.iterrows():

            inspection_date = pd.to_datetime(
                row.get("Month of Inspection"),
                errors="coerce"
            )

            if pd.isna(inspection_date):
                year_val = pd.to_numeric(
                    pd.Series([row.get("Year of Inspection")]),
                    errors="coerce"
                ).iloc[0]

                if not pd.isna(year_val):
                    inspection_year = int(year_val)
                else:
                    continue
            else:
                inspection_year = inspection_date.year

            inspection_key = row.get("FEI with Inspection End Date")

            if not inspection_key or str(inspection_key).strip() == "":
                company_name = str(row.get("Company Name") or "").strip()

                date_key = (
                    inspection_date.strftime("%Y-%m-%d")
                    if not pd.isna(inspection_date)
                    else str(row.get("Month of Inspection") or "").strip()
                )

                inspection_key = f"{company_name}|{date_key}"

            year_inspection_map[inspection_year].add(str(inspection_key))

        yearly_inspections = {
            str(year): len(keys)
            for year, keys in sorted(year_inspection_map.items())
        }

        country_inspection_map = defaultdict(set)

        for _, row in temp_df.iterrows():

            country = str(row.get("Country") or "").strip()

            if not country:
                country = "Unknown"

            inspection_date = pd.to_datetime(
                row.get("Month of Inspection"),
                errors="coerce"
            )

            inspection_key = row.get("FEI with Inspection End Date")

            if not inspection_key or str(inspection_key).strip() == "":
                company_name = str(row.get("Company Name") or "").strip()

                date_key = (
                    inspection_date.strftime("%Y-%m-%d")
                    if not pd.isna(inspection_date)
                    else str(row.get("Month of Inspection") or "").strip()
                )

                inspection_key = f"{company_name}|{date_key}"

            country_inspection_map[country].add(str(inspection_key))

        country_inspections = {
            country: len(keys)
            for country, keys in sorted(
                country_inspection_map.items(),
                key=lambda x: -len(x[1])
            )
        }

        est_col = next(
            (col for col in temp_df.columns if "establishment" in col.lower()),
            None
        )

        if not est_col:
            return JsonResponse({"error": "Type of Establishment column not found"}, status=400)

        temp_df[est_col] = (
            temp_df[est_col]
            .astype(str)
            .str.strip()
        )
        temp_df[est_col] = temp_df[est_col].str.title()

        establishment_counts = temp_df[est_col].value_counts()

        expected_establishment_types = [
            "Prescription (Rx) Drug Manufacturer",
            "Api Manufacturer",
            "Prescription (Rx) Drug Manufacturer & Api Manufacturer",

        ]

        type_of_establishment = {
            est: int(establishment_counts.get(est, 0))
            for est in expected_establishment_types
        }

        for est, count in establishment_counts.items():
            if est not in type_of_establishment:
                type_of_establishment[est] = int(count)

        inspection_map = {}

        for _, row in temp_df.iterrows():

            inspection_date = pd.to_datetime(
                row.get("Month of Inspection"),
                errors="coerce"
            )

            if pd.isna(inspection_date):
                continue

            inspection_key = row.get("FEI with Inspection End Date")

            if not inspection_key or str(inspection_key).strip() == "":
                company_name = str(row.get("Company Name") or "").strip()
                inspection_key = f"{company_name}|{inspection_date.strftime('%Y-%m-%d')}"

            # 🧠 Initialize inspection
            if inspection_key not in inspection_map:
                inspection_map[inspection_key] = {
                    "Company Name": str(row.get("Company Name") or "").strip(),
                    "Country": str(row.get("Country") or "").strip(),
                    "FEI Number": str(row.get("FEI Number") or "").strip(),
                    "Date": inspection_date.strftime("%Y-%m-%d"),
                    "Classification": str(row.get("Classification") or "").strip().upper(),
                    "Number of 483 Observations": 0,
                    "_date_obj": inspection_date  # for sorting
                }

            inspection_map[inspection_key]["Number of 483 Observations"] += 1

        inspection_list = list(inspection_map.values())

        inspection_list.sort(key=lambda x: x["_date_obj"], reverse=True)

        for item in inspection_list:
            item.pop("_date_obj", None)

        recent_inspections = inspection_list[:8]

        theme_keywords = defaultdict(list)

        qs = InvestigatorThemedKeywords.objects.all().values("system_name", "keyword")
        for row in qs:
            theme_keywords[row["system_name"]].append(row["keyword"])

        THEME_KEYWORDS = dict(theme_keywords)

        theme_keyword_counter = defaultdict(Counter)

        for text in temp_df["Observation Details"].dropna():
            text_normalized = str(text).casefold()

            for theme, keywords in THEME_KEYWORDS.items():
                for keyword in keywords:
                    if keyword.casefold() in text_normalized:
                        theme_keyword_counter[theme][keyword] += 1

        top_keywords_per_system = {}

        for theme, counter in theme_keyword_counter.items():
            top_keywords = counter.most_common(5)

            top_keywords_per_system[theme] = [
                {keyword : count}
                for keyword, count in top_keywords
            ]



        return JsonResponse({
            "investigator": investigator_name,
            "total_observations": int(total),
            "classification_breakdown": classification_data,
            "system_breakdown": system_data,
            "yearly_inspections": yearly_inspections,
            "country_inspections": country_inspections,
            "type_of_establishment": type_of_establishment,
            "recent_inspections": recent_inspections,
            "frequent_observation_themes": top_keywords_per_system
        }, status=200)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


def gmpc_active_country_excels(request):
    try:
        active_excels = (
            GMPCExcelMaster.objects
            .filter(is_active=True)
            .exclude(active_excel_name__isnull=True)
            .exclude(active_excel_name__exact="")
            .order_by("active_excel_name", "-uploaded_at", "-pk")
        )

        seen_countries = set()
        payload = []

        for obj in active_excels:
            country = _normalize_country_cache_value(obj.active_excel_name)
            country_key = country.lower()
            if country_key in seen_countries:
                continue
            seen_countries.add(country_key)

            df = get_cached_gmpc_df(country)
            records = df.where(pd.notnull(df), None).to_dict(orient="records") if df is not None else []

            payload.append({
                "id": obj.pk,
                "country": country,
                "uploaded_at": obj.uploaded_at.isoformat() if obj.uploaded_at else None,
                "file_name": os.path.basename(obj.file.name) if obj.file else None,
                "rows": records,
                "row_count": len(records),
            })

        return JsonResponse(
            {
                "count": len(payload),
                "active_country_excels": payload,
            },
            status=200,
        )
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=500)


def gmpc_filter_options_api(request):
    selected_active_excel_name = _get_selected_gmpc_active_excel_name(request)

    try:
        excel = get_active_gmpc_excel(selected_active_excel_name)
        source_info = get_active_gmpc_excel_source(selected_active_excel_name, excel_obj=excel)
        filter_config = getattr(excel, "filters", None)
        dynamic_filters, static_filters, title_field_name, layout_config, key_url, url_type, key_field_name, combined_fields = _normalize_gmpc_filter_config(filter_config)

        df = get_cached_gmpc_df(selected_active_excel_name, source_info=source_info)
        filter_options_map = get_cached_gmpc_filter_options(
            country=selected_active_excel_name,
            source_key=source_info["source_key"],
            df=df,
            dynamic_filters=dynamic_filters,
            static_filters=static_filters,
        )

        filter_names = list(filter_options_map.keys())
        filter_key_map = {
            _get_gmpc_filter_param_key(filter_name): filter_name
            for filter_name in filter_names
        }

        requested_filter_key = str(request.GET.get("filter_key", "")).strip()
        filter_name = filter_key_map.get(requested_filter_key)

        if not filter_name:
            return JsonResponse({"error": "Invalid filter key."}, status=400)

        selected_filters = {}
        for current_filter_name in filter_names:
            current_filter_key = _get_gmpc_filter_param_key(current_filter_name)
            selected_values = {
                str(value).strip()
                for value in request.GET.getlist(current_filter_key)
                if str(value).strip()
            }
            if selected_values:
                selected_filters[current_filter_name] = selected_values

        normalized_columns = _build_gmpc_normalized_columns(df, filter_names)
        resolved_options = _resolve_gmpc_filter_options(
            df=df,
            filter_name=filter_name,
            filter_options_map=filter_options_map,
            selected_filters=selected_filters,
            normalized_columns=normalized_columns,
        )

        option_page = _paginate_gmpc_filter_options(
            resolved_options,
            selected_values=selected_filters.get(filter_name, set()),
            page=request.GET.get("options_page", 1),
            page_size=50,
            query=request.GET.get("q", ""),
        )

        return JsonResponse(
            {
                "filter_key": requested_filter_key,
                "filter_name": filter_name,
                **option_page,
            },
            status=200,
        )
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=500)

def _get_gmpc_df_no_cache(path):
    df = _read_excel_preferred_non_empty_sheet(
        path,
        sheet_name=[
            getattr(settings, "GMPC_EXCEL_SHEET_NAME", None),
            "Sheet1",
        ],
        log_label="GMPC Excel (No Cache)",
    )
    df = _normalize_excel_dataframe(df)
    return df

def _calculate_gmpc_dashboard_metrics(df, prev_df, country):
    import datetime
    import pandas as pd

    normalized_country = (country or "").strip().lower()

    # 1. Total records (certificates)
    total_certificates = len(df) if df is not None else 0

    # 2. Total unique sites
    total_sites = 0
    if df is not None:
        site_col = None
        for col in df.columns:
            if str(col).strip().lower() in ("site name", "site details"):
                site_col = col
                break
        if site_col:
            total_sites = df[site_col].dropna().astype(str).str.strip().nunique()

    # 3. Compliance vs Non-compliance
    compliance_count = 0
    non_compliance_count = 0
    other_count = 0
    status_breakdown = {}

    if df is not None:
        if normalized_country == "eudra":
            if "Document Type" in df.columns:
                counts = df["Document Type"].value_counts(dropna=True).to_dict()
                compliance_count = counts.get("GMPC", 0)
                other_count = counts.get("GMPDA", 0)
                non_compliance_count = counts.get("GMPNC", 0)
                status_breakdown = {
                    "GMP Certificate (GMPC)": int(compliance_count),
                    "GMP Document/Auth (GMPDA)": int(other_count),
                    "GMP Non-Compliance (GMPNC)": int(non_compliance_count)
                }
        else:  # mhra or others
            status_col = None
            for col in df.columns:
                if str(col).strip().lower() in ("gmpc or non-compliance", "document type"):
                    status_col = col
                    break
            if status_col and status_col in df.columns:
                counts = df[status_col].value_counts(dropna=True).to_dict()
                compliance_count = counts.get("GMPC", 0)
                non_compliance_count = counts.get("Non Compliant", 0)
                status_breakdown = {
                    "GMPC Compliant": int(compliance_count),
                    "Non Compliant": int(non_compliance_count)
                }

    # Percentages
    compliance_pct = round((compliance_count / total_certificates * 100), 1) if total_certificates else 0.0
    other_pct = round((other_count / total_certificates * 100), 1) if total_certificates else 0.0
    non_compliance_pct = round((non_compliance_count / total_certificates * 100), 1) if total_certificates else 0.0

    # 4. Top 10 Countries
    country_labels = []
    country_values = []
    if df is not None and "Country" in df.columns:
        temp_countries = df["Country"].dropna().astype(str).str.strip().str.upper()
        country_counts = temp_countries.value_counts().head(10).to_dict()
        country_labels = list(country_counts.keys())
        country_values = [int(v) for v in country_counts.values()]

    # 5. Yearly Trends
    year_labels = []
    year_values = []
    if df is not None:
        date_col = None
        for col in df.columns:
            if str(col).strip().lower() in ("inspection end date", "inspection date"):
                date_col = col
                break

        if date_col:
            if normalized_country == "mhra":
                parsed_years = pd.to_datetime(df[date_col], format="%d/%m/%Y", errors="coerce").dt.year
            else:
                parsed_years = pd.to_datetime(df[date_col], errors="coerce").dt.year

            # fallback to Issue Date
            if parsed_years.isna().any() and "Issue Date" in df.columns:
                issue_years = pd.to_datetime(df["Issue Date"], errors="coerce").dt.year
                parsed_years = parsed_years.fillna(issue_years)

            # filter valid years
            current_yr = datetime.datetime.now().year
            valid_years = parsed_years[(parsed_years >= 2000) & (parsed_years <= current_yr + 1)].dropna().astype(int)
            year_counts = valid_years.value_counts().sort_index().to_dict()

            year_labels = [str(y) for y in year_counts.keys()]
            year_values = [int(v) for v in year_counts.values()]

    max_country_count = max(country_values) if country_values else 1
    country_data = [
        {
            "country": label,
            "count": val,
            "width": round((val / max_country_count) * 100, 1)
        }
        for label, val in zip(country_labels, country_values)
    ]

    # 6. Eudra Metadata (Inspection last 12m, MIA count, Coverage range)
    inspections_last_12m = 0
    sites_with_mia = 0
    coverage_range = "2015 - 2026"
    active_countries_labels = []
    active_countries_values = []
    active_countries_data = []

    uk_domestic_count = 0
    international_count = 0
    current_year_inspections = 0
    inspection_types = {}

    if df is not None:
        df_copy = df.copy()
        date_col = None
        for col in df_copy.columns:
            if str(col).strip().lower() in ("inspection end date", "inspection date"):
                date_col = col
                break

        if date_col:
            if normalized_country == "mhra":
                df_copy['parsed_date'] = pd.to_datetime(df_copy[date_col], format="%d/%m/%Y", errors='coerce')
            else:
                df_copy['parsed_date'] = pd.to_datetime(df_copy[date_col], errors='coerce')
        else:
            df_copy['parsed_date'] = pd.NaT

        max_date = df_copy['parsed_date'].max()
        if pd.isna(max_date):
            max_date = datetime.datetime.now()
        one_year_ago = max_date - pd.Timedelta(days=365)
        two_years_ago = max_date - pd.Timedelta(days=2*365)

        inspections_last_12m = int(df_copy[df_copy['parsed_date'] >= one_year_ago].shape[0])

        # Site Name column dynamically
        site_col = 'Site Name'
        for col in df_copy.columns:
            if str(col).strip().lower() in ("site name", "site details"):
                site_col = col
                break

        if normalized_country == 'mhra':
            # Check if Certificate Number contains "UK MIA" case-insensitively
            if 'Certificate Number' in df_copy.columns:
                sites_with_mia = int(df_copy[
                    df_copy['Certificate Number'].astype(str).str.upper().str.contains("UK MIA", na=False)
                ][site_col].nunique())

            # UK Domestic vs International
            if 'Country' in df_copy.columns:
                country_series = df_copy['Country'].dropna().astype(str).str.strip().str.upper()
                uk_domestic_count = int((country_series == 'UNITED KINGDOM').sum())
                international_count = int((country_series != 'UNITED KINGDOM').sum())

            # Current year 2026 Inspections
            current_year_inspections = int((df_copy['parsed_date'].dt.year == 2026).sum())

            # Inspection Type Breakdown
            if 'Certificate Number' in df_copy.columns:
                for cert in df_copy['Certificate Number'].dropna():
                    parsed = _parse_mhra_certificate_number(cert)
                    insp_type = (parsed.get("inspection_type") or "NA").strip().upper()
                    if insp_type == "IMP":
                        insp_type = "IMP ONLY"

                    if insp_type != "NA" and insp_type != "":
                        inspection_types[insp_type] = inspection_types.get(insp_type, 0) + 1
        else:
            if 'MIA Number' in df_copy.columns:
                sites_with_mia = int(df_copy[df_copy['MIA Number'].notna() & (df_copy['MIA Number'].astype(str).str.strip() != '')][site_col].nunique())

        min_yr = df_copy['parsed_date'].min().year if not pd.isna(df_copy['parsed_date'].min()) else 2015
        max_yr = df_copy['parsed_date'].max().year if not pd.isna(df_copy['parsed_date'].max()) else 2026
        coverage_range = f"{min_yr} - {max_yr}"

        # Active countries in last 2 years
        active_df = df_copy[df_copy['parsed_date'] >= two_years_ago]
        if 'Country' in active_df.columns:
            ac_counts = active_df['Country'].dropna().astype(str).str.strip().str.upper().value_counts().head(10).to_dict()
            active_countries_labels = list(ac_counts.keys())
            active_countries_values = [int(v) for v in ac_counts.values()]
            max_ac_count = max(active_countries_values) if active_countries_values else 1
            active_countries_data = [
                {
                    "country": label,
                    "count": val,
                    "width": round((val / max_ac_count) * 100, 1)
                }
                for label, val in zip(active_countries_labels, active_countries_values)
            ]

    # 7. Audit log calculations
    from datetime import datetime
    change_detected_date = datetime.now().strftime('%d %b %Y')

    status_changes_list = []
    newly_added_list = []
    removed_list = []
    field_updates_count = 0
    all_changes_list = []
    unchanged_count = 0

    if df is not None and prev_df is not None:
        # Determine columns dynamically for comparison
        if normalized_country == 'mhra':
            site_col = 'Site Details ' if 'Site Details ' in df.columns else ('Site Details' if 'Site Details' in df.columns else 'Site Name')
            date_col = 'Inspection Date'
            status_col = 'GMPC or Non-compliance'
            cert_col = 'Certificate Number'
        else:
            site_col = 'Site Name'
            date_col = 'Inspection End Date'
            status_col = 'Document Type'
            cert_col = 'Certificate Number' if 'Certificate Number' in df.columns else 'EudraGMDP Document Reference Number'

        df_sorted = df.copy()
        prev_df_sorted = prev_df.copy()

        import re
        df_sorted[site_col] = df_sorted[site_col].fillna('').astype(str).apply(lambda x: re.sub(r"\s+", " ", x).strip())
        prev_df_sorted[site_col] = prev_df_sorted[site_col].fillna('').astype(str).apply(lambda x: re.sub(r"\s+", " ", x).strip())

        if normalized_country == 'mhra':
            df_sorted['parsed_date'] = pd.to_datetime(df_sorted[date_col], format="%d/%m/%Y", errors='coerce')
            prev_df_sorted['parsed_date'] = pd.to_datetime(prev_df_sorted[date_col], format="%d/%m/%Y", errors='coerce')
        else:
            df_sorted['parsed_date'] = pd.to_datetime(df_sorted[date_col], errors='coerce')
            prev_df_sorted['parsed_date'] = pd.to_datetime(prev_df_sorted[date_col], errors='coerce')

        df_sorted = df_sorted.sort_values('parsed_date')
        prev_df_sorted = prev_df_sorted.sort_values('parsed_date')

        curr_sites = set(df_sorted[site_col].dropna().astype(str).str.lower().unique())
        prev_sites = set(prev_df_sorted[site_col].dropna().astype(str).str.lower().unique())

        newly_added_site_names = curr_sites - prev_sites
        removed_site_names = prev_sites - curr_sites

        curr_latest = df_sorted.groupby([site_col, 'Country']).last()
        prev_latest = prev_df_sorted.groupby([site_col, 'Country']).last()

        common_index = prev_latest.index.intersection(curr_latest.index)

        # Status changes comparison
        status_changes_mask = prev_latest.loc[common_index, status_col] != curr_latest.loc[common_index, status_col]
        changed_sites = common_index[status_changes_mask]

        for site_key in changed_sites:
            site_name, country_val = site_key
            row_latest = curr_latest.loc[site_key]
            row_prev = prev_latest.loc[site_key]

            updated_dt = ''
            if normalized_country == 'mhra':
                if not pd.isna(row_latest.get(date_col)):
                    try:
                        updated_dt = pd.to_datetime(row_latest[date_col], format="%d/%m/%Y").strftime('%d %b %Y')
                    except Exception:
                        updated_dt = str(row_latest[date_col])
            else:
                if 'Issue Date' in curr_latest.columns and not pd.isna(row_latest.get('Issue Date')):
                    try:
                        updated_dt = pd.to_datetime(row_latest['Issue Date']).strftime('%d %b %Y')
                    except Exception:
                        updated_dt = str(row_latest['Issue Date'])
                elif not pd.isna(row_latest.get(date_col)):
                    try:
                        updated_dt = pd.to_datetime(row_latest[date_col]).strftime('%d %b %Y')
                    except Exception:
                        updated_dt = str(row_latest[date_col])

            status_changes_list.append({
                'site': str(site_name),
                'prev_status': str(row_prev.get(status_col) or ''),
                'curr_status': str(row_latest.get(status_col) or ''),
                'country': str(country_val),
                'updated_date': str(updated_dt),
                'cert_no': str(row_latest.get(cert_col) or ''),
                'change_detected': change_detected_date

            })

        # Newly added list
        for site_key in curr_latest.index:
            site_name, country_val = site_key
            if site_name.strip().lower() in newly_added_site_names:
                row_latest = curr_latest.loc[site_key]
                issued_dt = ''
                if normalized_country == 'mhra':
                    if not pd.isna(row_latest.get(date_col)):
                        try:
                            issued_dt = pd.to_datetime(row_latest[date_col], format="%d/%m/%Y").strftime('%d %b %Y')
                        except Exception:
                            issued_dt = str(row_latest[date_col])
                else:
                    if 'Issue Date' in curr_latest.columns and not pd.isna(row_latest.get('Issue Date')):
                        try:
                            issued_dt = pd.to_datetime(row_latest['Issue Date']).strftime('%d %b %Y')
                        except Exception:
                            issued_dt = str(row_latest['Issue Date'])
                    elif not pd.isna(row_latest.get(date_col)):
                        try:
                            issued_dt = pd.to_datetime(row_latest[date_col]).strftime('%d %b %Y')
                        except Exception:
                            issued_dt = str(row_latest[date_col])

                newly_added_list.append({
                    'site': str(site_name),
                    'doc_type': str(row_latest.get(status_col) or ''),
                    'cert_no': str(row_latest.get(cert_col) or ''),
                    'country': str(country_val),
                    'issued_date': str(issued_dt),
                    'change_detected': change_detected_date

                })

        # Removed list
        for site_key in prev_latest.index:
            site_name, country_val = site_key
            if site_name.strip().lower() in removed_site_names:
                row_latest = prev_latest.loc[site_key]
                seen_dt = ''
                if normalized_country == 'mhra':
                    if not pd.isna(row_latest.get(date_col)):
                        try:
                            seen_dt = pd.to_datetime(row_latest[date_col], format="%d/%m/%Y").strftime('%d %b %Y')
                        except Exception:
                            seen_dt = str(row_latest[date_col])
                else:
                    if not pd.isna(row_latest.get(date_col)):
                        try:
                            seen_dt = pd.to_datetime(row_latest[date_col]).strftime('%d %b %Y')
                        except Exception:
                            seen_dt = str(row_latest[date_col])
                    elif 'Issue Date' in prev_latest.columns and not pd.isna(row_latest.get('Issue Date')):
                        try:
                            seen_dt = pd.to_datetime(row_latest['Issue Date']).strftime('%d %b %Y')
                        except Exception:
                            seen_dt = str(row_latest['Issue Date'])

                removed_list.append({
                    'site': str(site_name),
                    'last_status': str(row_latest.get(status_col) or ''),
                    'last_cert': str(row_latest.get(cert_col) or ''),
                    'country': str(country_val),
                    'last_seen': str(seen_dt),
                    'change_detected': change_detected_date

                })

        # Field updates comparison
        field_updates_mask = pd.Series(False, index=common_index)
        for col in ['Address 1', 'City', 'DUNS Number', 'Site NCA Reference', 'MIA Number', 'Address ']:
            if col in prev_latest.columns and col in curr_latest.columns:
                field_updates_mask |= (prev_latest.loc[common_index, col].fillna('').astype(str).str.strip() !=
                                       curr_latest.loc[common_index, col].fillna('').astype(str).str.strip())
        updated_sites = common_index[field_updates_mask]
        field_updates_count = len(updated_sites)

    if df is not None:
        # Compute unchanged_count and all_changes_list
        unchanged_count = max(0, total_sites - len(status_changes_list) - len(newly_added_list))

        # Add changed
        for item in status_changes_list:
            all_changes_list.append({
                'type': 'Changed',
                'site': item['site'],
                'cert_no': item['cert_no'],
                'country': item['country'],
                'status': f"{item['prev_status']} → {item['curr_status']}",
                'date_str': item['updated_date'],
                'parsed_date': pd.to_datetime(item['updated_date'], errors='coerce'),
                'change_detected': item['change_detected']

            })

        # Add new
        for item in newly_added_list:
            all_changes_list.append({
                'type': 'New',
                'site': item['site'],
                'cert_no': item['cert_no'],
                'country': item['country'],
                'status': item['doc_type'],
                'date_str': item['issued_date'],
                'parsed_date': pd.to_datetime(item['issued_date'], errors='coerce'),
                'change_detected': item['change_detected']

            })

        # Add revoked
        for item in removed_list:
            all_changes_list.append({
                'type': 'Revoked',
                'site': item['site'],
                'cert_no': item['last_cert'],
                'country': item['country'],
                'status': 'Certificate removed',
                'date_str': item['last_seen'],
                'parsed_date': pd.to_datetime(item['last_seen'], errors='coerce'),
                'change_detected': item['change_detected']

            })

        # Sort by parsed_date descending
        all_changes_list = sorted(all_changes_list, key=_custom_gmpc_sort_key)
        status_changes_list = sorted(status_changes_list, key=_custom_gmpc_sort_key)
        newly_added_list = sorted(newly_added_list, key=_custom_gmpc_sort_key)
        removed_list = sorted(removed_list, key=_custom_gmpc_sort_key)

        for item in all_changes_list:
            item.pop('parsed_date', None)

        # Custom sort: letters (A-Z) first, then numbers, then remaining
        def _label_sort_key(lbl):
            s = str(lbl or "").strip()
            if not s:
                return (3, "")
            first = s[0]
            if re.match(r"[A-Za-z]", first):
                return (0, s.lower())
            if re.match(r"\d", first):
                m = re.match(r"^(\d+)", s)
                if m:
                    try:
                        return (1, int(m.group(1)))
                    except Exception:
                        return (1, s)
                return (1, s)
            return (2, s.lower())

        def _sort_labels_values_data(labels, values=None, data_list=None):
            if not labels:
                return labels, values, data_list
            indices = list(range(len(labels)))
            indices.sort(key=lambda i: _label_sort_key(labels[i]))
            sorted_labels = [labels[i] for i in indices]
            sorted_values = [values[i] for i in indices] if (values and len(values) == len(labels)) else values
            sorted_data = [data_list[i] for i in indices] if (data_list and len(data_list) == len(labels)) else data_list
            return sorted_labels, sorted_values, sorted_data

        # Apply sorting to textual label/value lists (preserve corresponding values/data)
        country_labels, country_values, country_data = _sort_labels_values_data(country_labels, country_values, country_data)
        active_countries_labels, active_countries_values, active_countries_data = _sort_labels_values_data(active_countries_labels, active_countries_values, active_countries_data)
        inspection_type_labels, inspection_type_values, _ = _sort_labels_values_data(list(inspection_types.keys()) if isinstance(inspection_types, dict) else inspection_type_labels, inspection_type_values, None)

        # Status breakdown comes from a dict; sort its keys/values into lists
        if isinstance(status_breakdown, dict) and status_breakdown:
            st_labels = list(status_breakdown.keys())
            st_values = list(status_breakdown.values())
            st_labels, st_values, _ = _sort_labels_values_data(st_labels, st_values, None)
            status_labels = st_labels
            status_values = st_values
        else:
            status_labels = list(status_breakdown.keys())
            status_values = list(status_breakdown.values())

        # Ensure inspection_type labels variable exists (from earlier logic)
        if isinstance(inspection_type_labels, list):
            inspection_type_labels = list(inspection_type_labels)

        # Re-sort change lists by `site` using label ordering (A-Z, numbers, then others)
        def _site_item_key(item):
            return _label_sort_key(item.get('site') if isinstance(item, dict) else item)

        try:
            status_changes_list = sorted(status_changes_list, key=lambda x: _site_item_key(x)) if status_changes_list else status_changes_list
            newly_added_list = sorted(newly_added_list, key=lambda x: _site_item_key(x)) if newly_added_list else newly_added_list
            removed_list = sorted(removed_list, key=lambda x: _site_item_key(x)) if removed_list else removed_list
            all_changes_list = sorted(all_changes_list, key=lambda x: _site_item_key(x)) if all_changes_list else all_changes_list
        except Exception:
            # Fallback: leave original ordering on any unexpected error
            pass

        # Store metrics
    metrics = {
        "total_certificates": int(total_certificates),
        "total_sites": int(total_sites),
        "compliance_count": int(compliance_count),
        "compliance_pct": float(compliance_pct),
        "other_count": int(other_count),
        "other_pct": float(other_pct),
        "non_compliance_count": int(non_compliance_count),
        "non_compliance_pct": float(non_compliance_pct),
        "inspections_last_12m": int(inspections_last_12m),
        "sites_with_mia": int(sites_with_mia),
        "coverage_range": str(coverage_range),
        "status_changes_count": int(len(status_changes_list)),
        "newly_added_count": int(len(newly_added_list)),
        "removed_count": int(len(removed_list)),
        "field_updates_count": int(field_updates_count),
        "status_changes_list": status_changes_list,
        "newly_added_list": newly_added_list,
        "removed_list": removed_list,
        "year_labels": [str(x) for x in year_labels],
        "year_values": [int(x) for x in year_values],
        "country_labels": [str(x) for x in country_labels],
        "country_values": [int(x) for x in country_values],
        "country_data": country_data,
        "active_countries_labels": [str(x) for x in active_countries_labels],
        "active_countries_values": [int(x) for x in active_countries_values],
        "active_countries_data": active_countries_data,
        "status_labels": list(status_breakdown.keys()),
        "status_values": list(status_breakdown.values()),

        # MHRA additions
        "uk_domestic_count": int(uk_domestic_count),
        "international_count": int(international_count),
        "current_year_inspections": int(current_year_inspections),
        "inspection_type_labels": list(inspection_types.keys()),
        "inspection_type_values": list(inspection_types.values()),
        "all_changes_list": all_changes_list,
        "unchanged_count": int(unchanged_count),
    }
    return metrics

def gmpc_homepage(request):
    fda_483_total = _get_homepage_fda_observation_total()
    eudra_total = _get_auditiq_gmpc_total("eudra")
    mhra_total = _get_auditiq_gmpc_total("mhra")

    context = {
        "fda_483_observations_count": _format_homepage_stat_count(fda_483_total),
        "eudra_records_count": _format_homepage_stat_count(eudra_total),
        "mhra_records_count": _format_homepage_stat_count(mhra_total),
        "fda_483_observations_total": fda_483_total,
        "eudra_records_total": eudra_total,
        "mhra_records_total": mhra_total,
    }
    return render(request, "GmpcHomepage.html", context=context)
def gmpc_dashboard(request):
    import datetime
    selected_active_excel_name = _get_selected_gmpc_active_excel_name(request)

    try:
        excel = get_active_gmpc_excel(selected_active_excel_name)
        source_info = get_active_gmpc_excel_source(selected_active_excel_name, excel_obj=excel)
        df = get_cached_gmpc_df(selected_active_excel_name, source_info=source_info)

        # Check for AJAX requests first!
        if request.GET.get('ajax') == '1':
            action = request.GET.get('action')
            site_col = 'Site Name'
            if df is not None:
                for col in df.columns:
                    if str(col).strip().lower() in ("site name", "site details"):
                        site_col = col
                        break

            if action == 'search_sites':
                query = request.GET.get('q', '').strip().lower()
                if df is not None and query:
                    matching_sites = df[df[site_col].astype(str).str.lower().str.contains(query, na=False)][site_col].unique()[:15].tolist()
                else:
                    matching_sites = []
                return JsonResponse({'sites': matching_sites})

            elif action == 'get_site_history':
                site_name = request.GET.get('site_name', '').strip()
                if df is not None and site_name:
                    site_df = df[df[site_col].astype(str).str.strip().str.lower() == site_name.lower()].copy()

                    date_col = 'Inspection End Date'
                    for col in df.columns:
                        if str(col).strip().lower() in ("inspection end date", "inspection date"):
                            date_col = col
                            break

                    if selected_active_excel_name == 'mhra':
                        site_df['parsed_date'] = pd.to_datetime(site_df[date_col], format="%d/%m/%Y", errors='coerce')
                    else:
                        site_df['parsed_date'] = pd.to_datetime(site_df[date_col], errors='coerce')
                    site_df = site_df.sort_values('parsed_date', ascending=False)
                    # Get URL and filter configs for building report link dynamically
                    filter_config = getattr(excel, "filters", None)
                    _, _, _, _, key_url, url_type, key_field_name, _ = _normalize_gmpc_filter_config(filter_config)

                    history = []
                    for row in site_df.itertuples(index=False):
                        row_dict = dict(zip(df.columns, row))
                        # format date nicely
                        issue_dt_str = ''
                        if row_dict.get('Issue Date') and not pd.isna(row_dict['Issue Date']):
                            try:
                                issue_dt_str = pd.to_datetime(row_dict['Issue Date']).strftime('%b %d, %Y')
                            except Exception:
                                issue_dt_str = str(row_dict['Issue Date'])

                        inspect_dt_str = ''
                        if row_dict.get(date_col) and not pd.isna(row_dict[date_col]):
                            try:
                                if selected_active_excel_name == 'mhra':
                                    inspect_dt_str = pd.to_datetime(row_dict[date_col], format="%d/%m/%Y").strftime('%b %d, %Y')
                                else:
                                    inspect_dt_str = pd.to_datetime(row_dict[date_col]).strftime('%b %d, %Y')
                            except Exception:
                                inspect_dt_str = str(row_dict[date_col])

                        cert_col = 'Certificate Number'
                        for col in df.columns:
                            if str(col).strip().lower() in ('certificate number', 'eudragmdp document reference number'):
                                cert_col = col
                                break

                        doc_type_col = 'Document Type'
                        for col in df.columns:
                            if str(col).strip().lower() in ('document type', 'gmpc or non-compliance'):
                                doc_type_col = col
                                break
                        # Resolve the key column for building the URL
                        normalized_key_field = None
                        if key_field_name:
                            for col in df.columns:
                                if str(col).strip().lower() == str(key_field_name).strip().lower():
                                    normalized_key_field = col
                                    break
                        if not normalized_key_field:
                            normalized_key_field = cert_col

                        key_value = row_dict.get(normalized_key_field) or ''
                        report_link = build_card_url(key_url, key_value, url_type) if key_url and key_value else ''


                        history.append({
                            'cert_no': row_dict.get(cert_col) or '',
                            'doc_type': row_dict.get(doc_type_col) or '',
                            'issue_date': issue_dt_str,
                            'inspection_end_date': inspect_dt_str,
                            'report_link': report_link,
                        })

                    # General site info
                    latest_row = site_df.iloc[0] if not site_df.empty else {}
                    site_info = {
                        'site_name': latest_row.get(site_col, site_name) if not site_df.empty else site_name,
                        'current_status': latest_row.get(doc_type_col) or '' if not site_df.empty else '',
                        'country': latest_row.get('Country') or '' if not site_df.empty else '',
                        'oms_id': latest_row.get('OMS Organisation Identifier') or '' if not site_df.empty else '',
                        'nca_ref': latest_row.get('Site NCA Reference') or '' if not site_df.empty else '',
                        'history': history
                    }
                    return JsonResponse(site_info)
                return JsonResponse({'error': 'Site not found.'}, status=400)

        # Check DB cached dashboard metrics
        metrics = getattr(excel, 'dashboard_metrics', None)
        if metrics and "total_certificates" in metrics:
            print(f"[DASHBOARD] Using DB cached metrics for GMPCExcelMaster pk={excel.pk}")
            # Ensure lists are sorted using our new logic on the fly
            for list_key in ("all_changes_list", "status_changes_list", "newly_added_list", "removed_list"):
                if list_key in metrics and isinstance(metrics[list_key], list):
                    metrics[list_key] = sorted(metrics[list_key], key=_custom_gmpc_sort_key)

        else:
            print(f"[DASHBOARD] Metrics not cached in DB for pk={excel.pk}; calculating now...")
            # Find the previous active GMPC Excel for this country/display area
            previous_excel = (
                GMPCExcelMaster.objects
                .filter(active_excel_name__iexact=selected_active_excel_name)
                .exclude(pk=excel.pk)
                .order_by("-uploaded_at", "-pk")
                .first()
            )

            prev_df = None
            if previous_excel and getattr(previous_excel, 'file', None):
                try:
                    prev_df = _get_gmpc_df_no_cache(previous_excel.file.path)
                except Exception as exc:
                    print(f"[COMPARE] Failed to load previous excel: {exc}")

            metrics = _calculate_gmpc_dashboard_metrics(df, prev_df, selected_active_excel_name)

            # Save metrics to DB
            excel.dashboard_metrics = metrics
            excel.save(update_fields=["dashboard_metrics"])
            print(f"[DASHBOARD] Saved newly calculated metrics to GMPCExcelMaster pk={excel.pk}")

        context = {
            "available_excel_names": get_gmpc_available_excel_names(),
            "selected_active_excel_name": selected_active_excel_name,
            **metrics
        }
        return render(request, "gmpcdashboard.html", context)

    except Exception as e:
        import traceback
        print(f"GMPC Dashboard Error: {e}")
        traceback.print_exc()
        return render(request, "gmpcdashboard.html", {
            "available_excel_names": get_gmpc_available_excel_names(),
            "selected_active_excel_name": selected_active_excel_name,
            "total_certificates": 0,
            "total_sites": 0,
            "compliance_count": 0,
            "non_compliance_count": 0,
            "year_labels": [],
            "year_values": [],
            "country_labels": [],
            "country_values": [],
            "country_data": [],
            "status_labels": [],
            "status_values": [],
            "error": str(e),
        })

import datetime

def gmpc_module(request):
    selected_active_excel_name = _get_selected_gmpc_active_excel_name(request)

    try:
        start_time = datetime.datetime.now()

        excel = get_active_gmpc_excel(selected_active_excel_name)
        source_info = get_active_gmpc_excel_source(selected_active_excel_name, excel_obj=excel)
        filter_config = getattr(excel, "filters", None)
        dynamic_filters, static_filters, title_field_name, layout_config, key_url, url_type, key_field_name, combined_fields = _normalize_gmpc_filter_config(filter_config)
        # ✅ Load DF once
        df = get_cached_gmpc_df(selected_active_excel_name, source_info=source_info)

        # ✅ Normalize columns
        normalized_cols = {str(col).strip(): str(col).strip() for col in df.columns}

        key_column = normalized_cols.get(str(key_field_name).strip()) if key_field_name else None
        title_column = normalized_cols.get(str(title_field_name).strip()) if title_field_name else None

        searched = request.GET.get("search") == "1"

        filter_names = list(static_filters.keys())
        filter_names.extend(
            filter_name
            for filter_name in dynamic_filters
            if filter_name not in static_filters
        )
        selected_filters = {}

        for filter_name in filter_names:
            filter_key = _get_gmpc_filter_param_key(filter_name)
            selected_values = {
                str(v).strip()
                for v in request.GET.getlist(filter_key)
                if str(v).strip()
            }
            if selected_values:
                selected_filters[filter_name] = selected_values

        response_filters = _build_gmpc_filter_definitions(
            filter_names=filter_names,
            selected_filters=selected_filters,
        )
        normalized_columns = _build_gmpc_normalized_columns(df, filter_names)

        # ✅ Apply filters
        filtered_df = df
        for column_name, selected_values in selected_filters.items():
            normalized_series = normalized_columns.get(column_name)
            if normalized_series is None:
                continue

            filtered_df = filtered_df[
                normalized_series.reindex(filtered_df.index).isin(selected_values)
            ]
         # ✅ Sort by Site Name / Site Details (falling back to Certificate Number) alphabetically ascending
        sort_col = None
        for candidate in ['site name', 'site details', 'site details ']:
            for col in filtered_df.columns:
                if str(col).strip().lower() == candidate:
                    sort_col = col
                    break
            if sort_col:
                break
        if not sort_col:
            # Fallback
            for col in filtered_df.columns:
                if str(col).strip().lower() in ('certificate number', 'certificate-number'):
                    sort_col = col
                    break
        if sort_col:
            filtered_df = filtered_df.sort_values(
                by=sort_col,
                key=lambda col: col.astype(str).str.lower(),
                ascending=True,
                na_position='last'
            )
        # ✅ PAGINATION + CARD BUILD
        page_size = 12
        requested_page = request.GET.get("page", 1)
        cards = []

        if searched:
            columns = [str(col).strip() for col in df.columns]

            if selected_active_excel_name == "mhra":
                grouped_cards = _build_mhra_grouped_cards(
                    df=filtered_df,
                    columns=columns,
                    key_column=key_column,
                    title_column=title_column,
                    combined_fields=combined_fields,
                    key_url=key_url,
                    url_type=url_type,
                )
                total_rows = len(grouped_cards)
                paginator = Paginator(grouped_cards, page_size)
                page_obj = paginator.get_page(requested_page)
                cards = list(page_obj.object_list) if total_rows else []
                loaded_rows = min(page_obj.number * page_size, total_rows) if total_rows else 0
            else:
                total_rows = int(len(filtered_df.index))
                paginator = Paginator(range(total_rows), page_size)
                page_obj = paginator.get_page(requested_page)

                if total_rows:
                    start = page_obj.start_index() - 1
                    end = page_obj.end_index()
                    paginated_df = filtered_df.iloc[start:end]
                    loaded_rows = end
                else:
                    paginated_df = filtered_df.iloc[0:0]
                    loaded_rows = 0

                for row in paginated_df.itertuples(index=False, name=None):

                    raw_row_dict = {}
                    key_value = None
                    title_value = None

                    for col, val in zip(columns, row):
                        clean_val = "" if _safe_cell_value(val) is None else _safe_cell_value(val)
                        raw_row_dict[col] = clean_val

                        if key_column and col == key_column:
                            key_value = clean_val

                        if title_column and col == title_column:
                            title_value = clean_val

                    if not title_value:
                        for col in columns:
                            if col != key_column and raw_row_dict.get(col):
                                title_value = raw_row_dict[col]
                                break

                    title_value = _clean_gmpc_title(title_value)

                    row_dict = _build_gmpc_card_fields(
                        columns=columns,
                        row_values=raw_row_dict,
                        key_column=key_column,
                        title_column=title_column,
                        combined_fields=combined_fields,
                    )

                    detail_url = build_card_url(key_url, key_value, url_type)
                    row_dict["key_value"] = key_value
                    row_dict["title"] = title_value
                    row_dict["detail_url"] = detail_url

                    cards.append(row_dict)
        else:
            total_rows = 0
            paginator = Paginator([], page_size)
            page_obj = paginator.get_page(requested_page)
            loaded_rows = 0

        current_page = page_obj.number if total_rows else 1
        total_pages = paginator.num_pages if total_rows else 0
        has_more = page_obj.has_next() if total_rows else False

        end_time = datetime.datetime.now()
        elapsed_time = (end_time - start_time).total_seconds()
        print(f"Elapsed time for gmpc_module: {elapsed_time:.2f} seconds")
        # ✅ AJAX response (for scroll)
        is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"
        initial_data = {
            "cards": cards,
            "has_more": has_more,
            "current_page": current_page,
            "next_page": page_obj.next_page_number() if has_more else None,
            "loaded_rows": loaded_rows,
            "total_rows": total_rows,
            "total_pages": total_pages,
        }
        if is_ajax:
            return JsonResponse(initial_data)

        # ✅ Normal render (first load)
        return render(request, "gmpc_module.html", {
            "initial_cards_json": json.dumps(initial_data),
            "available_excel_names": get_gmpc_available_excel_names(),
            "selected_active_excel_name": selected_active_excel_name,
            "filters": response_filters,
            "searched": searched,
            "cards": cards,
            "title_column": title_column,
            "layout_config": layout_config,
            "result_count": loaded_rows if searched else 0,
            "total_rows": total_rows if searched else 0,
            "selected_filter_count": len(selected_filters),
            "has_more": has_more,
            "current_page": current_page,
            "total_pages": total_pages,
            "page_size": page_size,
        })

    except Exception as e:
        return render(request, "gmpc_module.html", {
            "initial_cards_json": json.dumps({}),
            "available_excel_names": get_gmpc_available_excel_names(),
            "selected_active_excel_name": selected_active_excel_name,
            "filters": [],
            "error": str(e),
            "searched": False,
            "cards": [],
            "title_column": "",
            "layout_config": {},
            "result_count": 0,
            "total_rows": 0,
            "selected_filter_count": 0,
            "has_more": False,
            "current_page": 1,
            "total_pages": 0,
            "page_size": 12,
        })


def top10_investigators(request):
    return render(request, 'top10_investigators.html')


def top10_companies(request):
    return render(request, 'top10_companies.html')
