import hashlib
import json
import logging
import os
import re
import time

import pandas as pd
from decouple import config
from django.conf import settings

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - compatibility fallback
    OpenAI = None

import openai


logger = logging.getLogger(__name__)

SUMMARY_COLUMN = "Summary"
OBSERVATION_COLUMN = "Form 483 Observation"
DETAILS_COLUMN = "Observation Details"
SUMMARY_GROUP_CONTEXT_COLUMNS = [
    "Company Name",
    "Organization Name",
    "FEI Number",
    "City, Country",
    "Month of Inspection",
    "Year of Inspection",
    "System",
    OBSERVATION_COLUMN,
]
SUMMARY_MODEL = "gpt-4.1-mini"
SUMMARY_TEMPERATURE = 0.7
SUMMARY_MAX_INPUT_CHARS = 15000
SUMMARY_MIN_RATIO = 0.20
SUMMARY_TARGET_RATIO = 0.30
SUMMARY_MAX_RATIO = 0.35
SUMMARY_MIN_COMPLETION_TOKENS = 32
SUMMARY_MAX_COMPLETION_TOKENS = 2000
SUMMARY_MAX_ATTEMPTS = 3
SUMMARY_RETRY_DELAY_SECONDS = 1

SUMMARY_SYSTEM_PROMPT = (
    "You are an expert FDA GMP compliance summarizer specializing in FDA 483 observations.\n"
    "STRICT RULES:\n"
    "1. Use ONLY the provided text.\n"
    "2. DO NOT add assumptions, interpretations, or external information.\n"
    "3. Preserve critical regulatory terminology exactly as written whenever important.\n"
    "4. Retain key factual evidence, examples, systems, process names, counts, years, and operational failures when they are important to understanding the observation.\n"
    "5. Clearly describe what failed, where it failed, and why it is a GMP/compliance risk.\n"
    "6. Keep important data integrity, contamination, documentation, validation, and procedural control issues.\n"
    "7. Remove only repetitive wording and unnecessary background, but preserve important examples, counts, years, systems, SOP references, and factual evidence supporting the observation.\n"
    "8. Write in concise FDA/regulatory language suitable for audit and CAPA review.\n"
    "9. Keep the summary fact-based, precise, and traceable to the original observation.\n"
    "10. Output one concise paragraph with meaningful compliance detail.\n"
    "11. Keep the summary BETWEEN 20% AND 35% of the original word count.\n"
    "12. Prefer completeness of critical compliance details over excessive shortening.\n"
    "13. Preserve important numerical details, years, counts, examples, and documented evidence whenever they support the compliance concern.\n"
    )

SUMMARY_USER_PROMPT_TEMPLATE = (
    "Summarize the following FDA observation.\n"
    "Original length: {original_words} words.\n"
    "Required summary length: {min_words}-{max_words} words.\n"
    "Target length: about {target_words} words.\n"
    "Hard limit: do not exceed {max_words} words.\n\n"
    "{prepared_text}"
    )



# --- Checkpoint / Resume ---
# Summaries are written here immediately after generation so that if the
# process is interrupted the already-completed work is not lost.
SUMMARY_CHECKPOINT_DIR = None  # resolved lazily from Django settings
SUMMARY_CHECKPOINT_FILENAME = "summary_checkpoint.json"

_openai_client = None
_openai_client_initialized = False
_checkpoint_cache = None  # in-memory mirror of checkpoint file


# ---------------------------------------------------------------------------
# Checkpoint helpers
# ---------------------------------------------------------------------------

def _get_checkpoint_path():
    """Return the absolute path to the checkpoint JSON file."""
    global SUMMARY_CHECKPOINT_DIR
    if SUMMARY_CHECKPOINT_DIR is None:
        try:
            base = settings.BASE_DIR
        except Exception:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        SUMMARY_CHECKPOINT_DIR = os.path.join(base, "tmp", "summaries")
    os.makedirs(SUMMARY_CHECKPOINT_DIR, exist_ok=True)
    return os.path.join(SUMMARY_CHECKPOINT_DIR, SUMMARY_CHECKPOINT_FILENAME)


def _load_checkpoint():
    """Load the checkpoint from disk into the in-memory cache."""
    global _checkpoint_cache
    if _checkpoint_cache is not None:
        return _checkpoint_cache

    path = _get_checkpoint_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                _checkpoint_cache = json.load(fh)
            logger.info("[CHECKPOINT] Loaded %d saved summaries from %s", len(_checkpoint_cache), path)
        except Exception as exc:
            logger.warning("[CHECKPOINT] Could not read checkpoint file: %s", exc)
            _checkpoint_cache = {}
    else:
        _checkpoint_cache = {}

    return _checkpoint_cache


def _save_checkpoint(key, summary):
    """Persist a single key→summary entry to disk immediately."""
    checkpoint = _load_checkpoint()
    checkpoint[key] = summary
    path = _get_checkpoint_path()
    try:
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(checkpoint, fh, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception as exc:
        logger.warning("[CHECKPOINT] Could not save checkpoint: %s", exc)


def _checkpoint_key(merged_text):
    """Stable content-based key for a block of observation detail text."""
    return hashlib.sha256(merged_text.encode("utf-8")).hexdigest()


def clear_summary_checkpoint():
    """Delete the checkpoint file and reset the in-memory cache.
    Call this when you start a completely fresh generation run."""
    global _checkpoint_cache
    _checkpoint_cache = {}
    path = _get_checkpoint_path()
    if os.path.exists(path):
        try:
            os.remove(path)
            logger.info("[CHECKPOINT] Checkpoint file cleared: %s", path)
        except Exception as exc:
            logger.warning("[CHECKPOINT] Could not clear checkpoint file: %s", exc)


# ---------------------------------------------------------------------------

def _is_blank(value):
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except Exception:
        pass
    return not str(value).strip()


def _normalize_text(value):
    if _is_blank(value):
        return None
    return str(value).strip()


def _normalize_observation_key(value):
    normalized = _normalize_text(value)
    return normalized if normalized else None


def _build_summary_group_key(row):
    parts = []
    for column in SUMMARY_GROUP_CONTEXT_COLUMNS:
        if column not in row.index:
            continue
        parts.append(_normalize_text(row.get(column)) or "")

    normalized_key = "||".join(parts).strip("|")
    return normalized_key or None


def _truncate_text(text, limit=SUMMARY_MAX_INPUT_CHARS):
    normalized = _normalize_text(text)
    if not normalized or len(normalized) <= limit:
        return normalized

    truncated = normalized[:limit]
    for separator in ("\n\n", "\n", ". ", "; ", ", ", " "):
        boundary = truncated.rfind(separator)
        if boundary > int(limit * 0.7):
            truncated = truncated[:boundary].strip()
            break

    return truncated.strip()


def _count_words(text):
    normalized = _normalize_text(text)
    if not normalized:
        return 0
    return len(re.findall(r"\S+", normalized))


def _build_summary_word_limits(text):
    original_words = _count_words(text)
    if not original_words:
        return {
            "original_words": 0,
            "min_words": 0,
            "target_words": 0,
            "max_words": 0,
            "max_tokens": SUMMARY_MIN_COMPLETION_TOKENS,
        }

    min_words = max(1, int(original_words * SUMMARY_MIN_RATIO))
    max_words = max(min_words, int(original_words * SUMMARY_MAX_RATIO))
    target_words = min(max_words, max(min_words, round(original_words * SUMMARY_TARGET_RATIO)))
    # Approximate 2 tokens per word with a larger safety margin to avoid truncation.
    max_tokens = max(
        SUMMARY_MIN_COMPLETION_TOKENS,
        min(SUMMARY_MAX_COMPLETION_TOKENS, int(max_words * 2.0) + 50),
    )
    return {
        "original_words": original_words,
        "min_words": min_words,
        "target_words": target_words,
        "max_words": max_words,
        "max_tokens": max_tokens,
    }


def _normalize_summary_output(text):
    normalized = _normalize_text(text)
    if not normalized:
        return None

    normalized = re.sub(r"\s+", " ", normalized).strip()
    normalized = normalized.replace("•", " ")
    normalized = re.sub(r"\s*-\s*", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip(" ,;")

    return normalized


def _trim_summary_to_word_limit(text, min_words, max_words):
    return _normalize_summary_output(text)


def _summary_fits_target(summary, source_text):
    normalized_summary = _normalize_summary_output(summary)
    normalized_source = _normalize_text(source_text)
    if not normalized_summary or not normalized_source:
        return False

    word_limits = _build_summary_word_limits(normalized_source)
    summary_words = _count_words(normalized_summary)
    return word_limits["min_words"] <= summary_words <= word_limits["max_words"]


def _extract_message_content(response):
    if not response or not getattr(response, "choices", None):
        return None

    message = response.choices[0].message
    content = getattr(message, "content", None)

    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        parts = []
        for item in content:
            text_value = getattr(item, "text", None)
            if text_value:
                parts.append(text_value)
            elif isinstance(item, dict) and item.get("text"):
                parts.append(item["text"])
        return "\n".join(parts).strip() if parts else None

    return None


def _get_openai_api_key():
    return (
        config("OPENAI_API_KEY", default=None)
        or getattr(settings, "OPENAI_API_KEY", None)
        or getattr(openai, "api_key", None)
    )


def _get_openai_client():
    global _openai_client, _openai_client_initialized

    if _openai_client_initialized:
        return _openai_client

    _openai_client_initialized = True
    api_key = _get_openai_api_key()
    if not api_key:
        logger.warning("[SUMMARY] OPENAI_API_KEY is not configured. Summary generation skipped.")
        return None

    if OpenAI is not None:
        _openai_client = OpenAI(api_key=api_key)
        return _openai_client

    openai.api_key = api_key
    _openai_client = False
    return _openai_client


def generate_summary(text):
    prepared_text = _truncate_text(text)
    if not prepared_text:
        return None

    word_limits = _build_summary_word_limits(prepared_text)
    system_prompt = SUMMARY_SYSTEM_PROMPT
    user_prompt = SUMMARY_USER_PROMPT_TEMPLATE.format(
        original_words=word_limits["original_words"],
        min_words=word_limits["min_words"],
        max_words=word_limits["max_words"],
        target_words=word_limits["target_words"],
        prepared_text=prepared_text,
    )
    for attempt in range(1, SUMMARY_MAX_ATTEMPTS + 1):
        try:
            client = _get_openai_client()
            if client is None:
                return None

            if client is False:  # pragma: no cover - legacy SDK fallback
                response = openai.ChatCompletion.create(
                    model=SUMMARY_MODEL,
                    temperature=SUMMARY_TEMPERATURE,
                    max_completion_tokens=word_limits["max_tokens"],
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                )
                message = response["choices"][0]["message"]["content"]
                summary = _trim_summary_to_word_limit(
                    message,
                    word_limits["min_words"],
                    word_limits["max_words"],
                )
                print("[SUMMARY] Generated summary using legacy OpenAI SDK", summary)
            else:
                logger.warning("[SUMMARY] Calling OpenAI API (Attempt %s/%s) for observation...", attempt, SUMMARY_MAX_ATTEMPTS)
                response = client.chat.completions.create(
                    model=SUMMARY_MODEL,
                    temperature=SUMMARY_TEMPERATURE,
                    max_completion_tokens=word_limits["max_tokens"],
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                )
                summary = _trim_summary_to_word_limit(
                    _extract_message_content(response),
                    word_limits["min_words"],
                    word_limits["max_words"],
                )

            if summary:
                logger.warning("[SUMMARY] Generated summary successfully: %s words.", _count_words(summary))
                return summary

            raise ValueError("OpenAI returned an empty summary.")
        except Exception as exc:
            logger.warning(
                "[SUMMARY] OpenAI summary generation failed on attempt %s/%s: %s",
                attempt,
                SUMMARY_MAX_ATTEMPTS,
                exc,
            )
            if attempt == SUMMARY_MAX_ATTEMPTS:
                logger.exception("[SUMMARY] Exhausted retries for summary generation.")
                return None
            time.sleep(SUMMARY_RETRY_DELAY_SECONDS)

    return None

def process_observation_summary(df, previous_df=None):
    if df is None or df.empty:
        return df

    if OBSERVATION_COLUMN not in df.columns or DETAILS_COLUMN not in df.columns:
        logger.warning("[SUMMARY] Required columns missing. Found columns: %s", list(df.columns))
        return df

    df = df.copy()
    if SUMMARY_COLUMN not in df.columns:
        df[SUMMARY_COLUMN] = None

    # Refreshing the Excel cache reaches here on an ordinary page view, and any
    # block without a summary costs one OpenAI call -- ~8k blocks in the bundled
    # workbook. Off by default so nothing bills unattended; summaries already
    # present in the sheet are still read and served either way.
    if not getattr(settings, "ENABLE_OBSERVATION_SUMMARIES", False):
        logger.info(
            "[SUMMARY] ENABLE_OBSERVATION_SUMMARIES is off; serving existing "
            "summaries without generating new ones."
        )
        return df

    generated_count, skipped_count, failed_count = 0, 0, 0

    # --- Pass 1: Count total blocks only (no text stored, very low memory) ---
    total_blocks = 0
    _prev_obs, _prev_comp, _has_block = None, None, False
    for _idx, _row in df.iterrows():
        _obs = _normalize_observation_key(_row[OBSERVATION_COLUMN])
        _comp = _normalize_text(_row.get("Company Name", ""))
        if _has_block and (_obs != _prev_obs or _comp != _prev_comp):
            total_blocks += 1
            _has_block = False
        if not _has_block:
            _prev_obs, _prev_comp, _has_block = _obs, _comp, True
    if _has_block:
        total_blocks += 1

    print(f"[SUMMARY] Starting summary generation for {total_blocks} observation blocks.")
    _start_time = time.time()

    # --- Pass 2: Stream one block at a time (low memory) ---
    block_num = 0
    current_obs, current_company = None, None
    current_indices, current_details = [], []

    def _flush_block(block_indices, block_obs, block_company, block_details):
        nonlocal generated_count, skipped_count, failed_count, block_num
        if not block_indices or not block_obs:
            return

        block_num += 1
        elapsed = time.time() - _start_time
        if block_num > 1 and elapsed > 0:
            avg = elapsed / (block_num - 1)
            remaining = avg * (total_blocks - block_num + 1)
            eta_str = f"ETA {int(remaining // 60)}m {int(remaining % 60)}s"
        else:
            eta_str = "ETA --"

        progress = (
            f"[SUMMARY] {block_num}/{total_blocks} | "
            f"{(block_company or '')[:40]} | {block_obs} | "
            f"gen={generated_count} skip={skipped_count} fail={failed_count} | {eta_str}"
        )

        # Skip if already has summary
        existing = [s for s in df.loc[block_indices, SUMMARY_COLUMN].tolist() if _normalize_text(s)]
        if existing:
            df.loc[block_indices, SUMMARY_COLUMN] = existing[0]
            skipped_count += 1
            print(f"{progress} --> SKIPPED (already has summary)")
            return

        # Clean + deduplicate details
        details_list, seen = [], set()
        for value in block_details:
            d = _normalize_text(value)
            if d and d not in seen:
                seen.add(d)
                details_list.append(d)
        if not details_list:
            skipped_count += 1
            print(f"{progress} --> SKIPPED (no details)")
            return

        merged_text = "\n\n".join(details_list)
        details_list = None  # free immediately

        # Checkpoint restore
        ck_key = _checkpoint_key(merged_text)
        checkpoint = _load_checkpoint()
        if ck_key in checkpoint:
            df.loc[block_indices, SUMMARY_COLUMN] = checkpoint[ck_key]
            skipped_count += 1
            print(f"{progress} --> CHECKPOINT (restored)")
            return

        # Call OpenAI
        print(f"{progress} --> GENERATING...")
        summary = generate_summary(merged_text)
        merged_text = None  # free immediately after API call
        if summary:
            _save_checkpoint(ck_key, summary)
            df.loc[block_indices, SUMMARY_COLUMN] = summary
            generated_count += 1
            print(f"{progress} --> DONE")
        else:
            failed_count += 1
            print(f"{progress} --> FAILED")

    for idx, row in df.iterrows():
        obs_no = _normalize_observation_key(row[OBSERVATION_COLUMN])
        company = _normalize_text(row.get("Company Name", ""))
        detail = _normalize_text(row[DETAILS_COLUMN])

        if current_indices and (obs_no != current_obs or company != current_company):
            _flush_block(current_indices, current_obs, current_company, current_details)
            current_indices, current_details = [], []

        if not current_indices:
            current_obs, current_company = obs_no, company

        current_indices.append(idx)
        if detail:
            current_details.append(detail)

    # Flush last block
    _flush_block(current_indices, current_obs, current_company, current_details)

    total_elapsed = time.time() - _start_time
    print(
        f"[SUMMARY] ALL DONE in {int(total_elapsed // 60)}m {int(total_elapsed % 60)}s | "
        f"generated={generated_count} skipped={skipped_count} failed={failed_count} "
        f"total={total_blocks}"
    )
    logger.info(
        "[SUMMARY] Completed. generated=%s skipped=%s failed=%s",
        generated_count, skipped_count, failed_count,
    )
    return df
