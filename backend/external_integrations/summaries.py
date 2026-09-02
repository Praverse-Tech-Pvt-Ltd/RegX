"""What may be written into an execution's request and response summaries.

Two allow-lists and a size cap, for the same reason the audit module has one: a
summary column is durable storage that is rarely re-read carefully, and half of
what could go in it comes from a system nobody in RegX controls.

**No raw response is ever stored.** Not the body, not the headers, not the URL,
not an exception string. A remote endpoint's error page can contain another
tenant's data, an internal hostname, a stack trace, or markup that will one day
be rendered somewhere. Storing it "for debugging" means storing all of that
permanently, on the assumption nobody looks. The enumerated `error_code` is what
a person actually needs to act, and it is bounded by construction.
"""

from __future__ import annotations

_REQUEST_KEYS = frozenset(
    {
        "operation",
        "resource_type",
        "resource_public_id",
        "snapshot_public_id",
        "manifest_checksum",
        "entry_count",
        "external_object_id",
        "relative_path",
        "method",
        "title",
        "document_type",
        "declared_mime",
    }
)

_RESPONSE_KEYS = frozenset(
    {
        "http_status",
        "bytes_transferred",
        "latency_ms",
        "external_reference",
        "remote_checksum",
        "remote_checksum_verified",
        "document_public_id",
        "document_version_public_id",
        "external_object_id",
        "attempt",
    }
)

MAX_STRING = 255


def _clean(payload: dict | None, allowed: frozenset) -> dict:
    if not payload:
        return {}
    cleaned: dict = {}
    for key, value in payload.items():
        if key not in allowed:
            continue
        if isinstance(value, str):
            # Bounded, and stripped of anything unprintable: these values reach
            # a database column and, later, a browser.
            value = "".join(ch for ch in value if ch.isprintable())[:MAX_STRING]
        elif isinstance(value, bool) or isinstance(value, int) or value is None:
            pass
        else:
            # Lists, dicts and everything else are dropped rather than coerced.
            # A nested structure is how "just a small summary" becomes a copy of
            # the remote payload.
            continue
        cleaned[key] = value
    return cleaned


def request_summary(payload: dict | None) -> dict:
    return _clean(payload, _REQUEST_KEYS)


def response_summary(payload: dict | None) -> dict:
    return _clean(payload, _RESPONSE_KEYS)
