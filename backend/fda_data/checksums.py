"""Deterministic checksums for FDA source files and extracted rows."""

import hashlib
import json


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def sha256_payload(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _normalised_value(value):
    """A field value with line endings unified and trailing whitespace removed
    (per line and at the end), so a copy of a file saved with CRLF line
    endings, or with trailing spaces, normalises to the same content."""
    if not isinstance(value, str):
        return value
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in text.split("\n")).rstrip()


def row_content_hash(fields: dict) -> str:
    """The hash of one row's normalised content."""
    return sha256_payload({k: _normalised_value(v) for k, v in fields.items()})


def content_fingerprint(rows_fields: list[dict]) -> str:
    """The fingerprint of a whole release's content: the per-row hashes,
    sorted, hashed together. Independent of row order, line endings and
    trailing whitespace; any change to any value of any row changes it.
    Used to refuse importing the same data twice (owner decision 2026-11-18)."""
    hashes = sorted(row_content_hash(fields) for fields in rows_fields)
    return hashlib.sha256("\n".join(hashes).encode("ascii")).hexdigest()
