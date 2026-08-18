"""Structured operational logging for REGX.

OPERATIONAL LOGGING IS NOT THE AUDIT TRAIL.

The regulated audit trail is ``audit.models.AuditEvent`` -- immutable database
rows written deliberately by application code. It is the authoritative record
for regulated user actions, approvals, checklist decisions, signatures and
regulatory evidence, and it does not depend on anything in this module.

What is emitted here is operational telemetry: did a request arrive, did it
finish, how long did it take, did something raise. It is for diagnosing a
running system. It must never be relied on as regulatory evidence, and audit
payloads are deliberately not duplicated into it.

The primary confidentiality control is simple: **sensitive values are never
passed to the logger.** No handler here reads request bodies, response bodies,
headers, cookies or query strings. :func:`redact` exists underneath that as
defence in depth for strings that arrive from elsewhere -- it is not permission
to log a request.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from contextvars import ContextVar

# ---------------------------------------------------------------------------
# Request correlation
# ---------------------------------------------------------------------------
# A ContextVar, not a thread-local and not a module global: it is correct under
# threads AND under async, and each context gets an independent copy, so two
# requests in flight cannot see each other's identifier.
#
# Named request_id, NOT correlation_id, on purpose. `correlation_id` is already
# taken in this codebase as a *domain* field -- documents.DocumentJob and the
# FDA import models each carry one to tie a processing chain together. Reusing
# the name for an HTTP concern would collide with an existing regulated concept
# in exactly the place people go looking.
_request_id: ContextVar[str | None] = ContextVar("regx_request_id", default=None)

#: Response and request header carrying the identifier.
REQUEST_ID_HEADER = "X-Request-ID"


def get_request_id() -> str | None:
    """The current request's identifier, or None outside a request."""
    return _request_id.get()


def set_request_id(value: str):
    """Bind an identifier to this context. Returns a token for :func:`reset_request_id`."""
    return _request_id.set(value)


def reset_request_id(token) -> None:
    """Restore the previous identifier. Always call this in a finally block."""
    _request_id.reset(token)


def new_request_id() -> str:
    return str(uuid.uuid4())


def coerce_incoming_request_id(raw: str | None) -> str:
    """Accept a caller-supplied request id only if it is a well-formed UUID.

    Anything else is discarded and replaced. An inbound header is attacker
    controlled: without this, a caller could inject newlines and forge whole log
    lines, or push a megabyte of text into every record for a request. Requiring
    a UUID makes the value structurally incapable of either.
    """
    if not raw:
        return new_request_id()
    candidate = raw.strip()
    try:
        return str(uuid.UUID(candidate))
    except (ValueError, AttributeError, TypeError):
        return new_request_id()


_record_factory_installed = False


def install_request_id_record_factory() -> None:
    """Stamp ``request_id`` onto every LogRecord as it is created.

    Not at format time. A formatter runs whenever its handler gets round to it,
    which for a queued, buffered or test-captured handler is after the request
    finished and the ContextVar was reset -- so a format-time lookup silently
    loses the correlation on exactly the records that matter most, the error
    ones. Binding at creation captures the value while the context is
    unambiguously still live.

    Doing it here rather than in the middleware also covers records this project
    does not emit: django.request, django.security and Celery's own loggers all
    become correlatable without being touched.

    Chains to any previously installed factory, and is idempotent.
    """
    global _record_factory_installed
    if _record_factory_installed:
        return

    previous = logging.getLogRecordFactory()

    def factory(*args, **kwargs):
        record = previous(*args, **kwargs)
        if getattr(record, "request_id", None) is None:
            current = _request_id.get()
            if current:
                record.request_id = current
        return record

    logging.setLogRecordFactory(factory)
    _record_factory_installed = True


# ---------------------------------------------------------------------------
# Redaction -- defence in depth only
# ---------------------------------------------------------------------------
_SENSITIVE_KEY = (
    r"password|passwd|pwd|secret|api[_-]?key|access[_-]?key|"
    r"access[_-]?token|refresh[_-]?token|id[_-]?token|token|"
    r"authorization|cookie|set[_-]?cookie|csrf[_-]?token|csrfmiddlewaretoken|"
    r"mfa[_-]?secret|recovery[_-]?code|otp|private[_-]?key|encryption[_-]?key"
)

#: key=value / key: value / "key": "value"
_KV_RE = re.compile(
    rf"(?i)(['\"]?\b(?:{_SENSITIVE_KEY})\b['\"]?\s*[:=]\s*)(['\"]?)([^'\"\s,;&}}\]]+)\2"
)
#: Authorization: Bearer <token>, and bare bearer/basic credentials.
_BEARER_RE = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}")
#: Connection URLs carrying credentials: scheme://user:password@host
_URL_CRED_RE = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)([^\s:/@]*):([^\s@]+)@")

REDACTED = "[REDACTED]"


def redact(text: str) -> str:
    """Blank out obvious secret-bearing patterns in a string.

    This is a safety net, not a guarantee, and it is explicitly not a licence to
    log untrusted input. It cannot recognise a secret that does not look like
    one. Do not log the thing in the first place.
    """
    if not text:
        return text
    try:
        text = _KV_RE.sub(rf"\1\2{REDACTED}\2", text)
        text = _BEARER_RE.sub(rf"\1 {REDACTED}", text)
        text = _URL_CRED_RE.sub(rf"\1\2:{REDACTED}@", text)
    except Exception:  # pragma: no cover - redaction must never break logging
        return REDACTED
    return text


class RequestIDRecoveryFilter(logging.Filter):
    """Recover ``request_id`` for records logged outside the middleware stack.

    Django logs every 4xx/5xx response through ``django.request`` from
    ``BaseHandler.get_response`` -- which runs *after* the middleware chain has
    returned, so RequestIDMiddleware has already reset the ContextVar and the
    record factory finds nothing to stamp. Those records arrive carrying
    ``extra={"request": <HttpRequest>}``, and the middleware puts ``request_id``
    on the request object, so the identifier can be recovered from there.

    Only that one attribute is read. The request object is never serialised --
    the formatter's allow-list still keeps its headers, cookies and body out.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if getattr(record, "request_id", None) is None:
            request = getattr(record, "request", None)
            recovered = getattr(request, "request_id", None)
            if isinstance(recovered, str):
                record.request_id = recovered
        return True


class RedactionFilter(logging.Filter):
    """Applies :func:`redact` to the formatted message of every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = redact(str(record.getMessage()))
            record.args = ()
        except Exception:  # noqa: S110  pragma: no cover
            # Deliberately swallowed: logging from inside a logging filter risks
            # recursion, and a redaction failure must never drop the record.
            pass
        return True


# ---------------------------------------------------------------------------
# JSON formatter
# ---------------------------------------------------------------------------
# Deliberately an ALLOW-LIST. Serialising record.__dict__, or everything passed
# through `extra`, would be actively dangerous here: Celery attaches the task's
# args and kwargs to the "Task ... received" record as extra["data"], where the
# stock text formatter never renders them. A formatter that dumped extras would
# silently start logging task arguments -- which for this system can be document
# identifiers and governed payloads. So only these names are ever emitted.
_ALLOWED_EXTRA_FIELDS = (
    "method",
    "path",
    "status_code",
    "duration_ms",
    "task_name",
    "task_id",
    "outcome",
)

_SERVICE = os.environ.get("REGX_SERVICE_NAME", "backend")


class JSONFormatter(logging.Formatter):
    """One JSON object per line, stable field names, no null padding.

    Fields absent for a given record are omitted rather than emitted as null;
    a schema-shaped blob of nulls on every line is noise, not structure.
    """

    def __init__(self, service: str | None = None):
        super().__init__()
        self.service = service or _SERVICE

    def format(self, record: logging.LogRecord) -> str:
        try:
            return self._format(record)
        except Exception:  # pragma: no cover - a formatter must not break a request
            # Last resort: still emit something parseable rather than raising
            # inside logging and taking the caller down with it.
            return json.dumps(
                {
                    "level": "ERROR",
                    "logger": "regx.logging",
                    "event": "log record could not be formatted",
                    "service": self.service,
                }
            )

    def _format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S")
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "service": self.service,
            "event": redact(record.getMessage()),
        }

        request_id = getattr(record, "request_id", None) or get_request_id()
        if request_id:
            payload["request_id"] = request_id

        for field in _ALLOWED_EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value

        if record.exc_info and record.exc_info[0] is not None:
            payload["exception_class"] = record.exc_info[0].__name__
            # The traceback is the diagnostic value of an error record. It is
            # frames and source lines, not locals -- Python does not include
            # variable values in a standard traceback, so credentials held in a
            # local do not travel with it.
            payload["stack"] = redact(self.formatException(record.exc_info))

        return json.dumps(payload, default=str, ensure_ascii=False)
