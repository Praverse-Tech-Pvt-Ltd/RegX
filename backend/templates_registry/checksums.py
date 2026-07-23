"""Checksum helpers for source packages, source records, and normalized content."""

import hashlib
import json


def sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def sha256_payload(payload: dict) -> str:
    """Deterministic checksum of a JSON-serializable payload (stable key order)."""
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str)
    return sha256_text(canonical)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
