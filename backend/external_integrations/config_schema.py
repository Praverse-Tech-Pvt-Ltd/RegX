"""Per-type connector configuration, validated on the way in and again on use.

A connector's configuration is JSON because different connector types need
different fields. That is the only reason. It is **not** a place to put whatever
the caller sends: every key is named here, every value is typed and bounded, and
an unknown key is an error rather than something quietly carried along.

VALIDATED TWICE, DELIBERATELY
-----------------------------
`validate_configuration` runs when a connector is written, and again in
`transport` before a request is built. The second pass is not redundant. The
first proves the API refused a bad configuration; the second proves the row is
still good at the moment it is used, which covers a row written by a raw cursor,
a migration, or a code path that did not exist when this was written. The whole
app assumes rows can be wrong; that is why `0002` exists.

WHAT IS DELIBERATELY NOT CONFIGURABLE
-------------------------------------
No shell command, no filesystem path, no proxy, no template, no expression, no
importable dotted path, no `Authorization` header. A connector describes *where*
to talk and nothing about *how this process behaves*. Anything that turns
configuration into code is out of scope for an integration framework, and there
is no version of "just this one field" that stays small.
"""

from __future__ import annotations

from .netpolicy import DestinationRefused, normalize_path_prefix, validate_url


class ConfigurationError(Exception):
    """Invalid connector configuration, with a safe enumerated code."""

    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(detail)


class ConfigErrorCode:
    UNKNOWN_FIELD = "CONFIG_UNKNOWN_FIELD"
    MISSING_FIELD = "CONFIG_MISSING_FIELD"
    INVALID_VALUE = "CONFIG_INVALID_VALUE"
    HEADER_REJECTED = "CONFIG_HEADER_REJECTED"
    TLS_REQUIRED = "CONFIG_TLS_REQUIRED"
    UNSUPPORTED_TYPE = "CONFIG_UNSUPPORTED_TYPE"


#: Bounds. Conservative on purpose: a connector that needs three minutes to
#: answer a health check is a connector that will hold a worker for three
#: minutes, and the failure mode of "too short" is a retry.
MIN_TIMEOUT_SECONDS = 1
MAX_CONNECT_TIMEOUT_SECONDS = 15
MAX_READ_TIMEOUT_SECONDS = 120
DEFAULT_CONNECT_TIMEOUT_SECONDS = 5
DEFAULT_READ_TIMEOUT_SECONDS = 30

#: A ceiling on anything this deployment will read from a remote endpoint, and
#: separately on what it will accept as an imported document. Both are bounded
#: reads, never "read it and see how big it was".
DEFAULT_MAX_RESPONSE_BYTES = 32 * 1024 * 1024
MAX_MAX_RESPONSE_BYTES = 512 * 1024 * 1024

MAX_STATIC_HEADERS = 8
MAX_HEADER_VALUE_LENGTH = 256

#: Static headers a tenant may set. Nothing here can change *who* the request is
#: from or *where* it goes.
ALLOWED_STATIC_HEADERS = frozenset({"accept", "accept-language", "x-client-id", "x-request-source"})

#: Named so the refusal is specific. `Authorization` is absent because the
#: credential adapter owns it -- a configurable auth header is a plaintext
#: secret in a JSON column with extra steps.
REJECTED_STATIC_HEADERS = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "set-cookie",
        "host",
        "content-length",
        "transfer-encoding",
        "connection",
        "upgrade",
        "expect",
        "te",
        "trailer",
    }
)


def _require_bool(config: dict, key: str, *, default=None) -> bool:
    value = config.get(key, default)
    if not isinstance(value, bool):
        raise ConfigurationError(ConfigErrorCode.INVALID_VALUE, f"'{key}' must be true or false.")
    return value


def _require_int(config: dict, key: str, *, default: int, low: int, high: int) -> int:
    value = config.get(key, default)
    # bool is an int in Python and would sail through the range check.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigurationError(ConfigErrorCode.INVALID_VALUE, f"'{key}' must be a whole number.")
    if not low <= value <= high:
        raise ConfigurationError(
            ConfigErrorCode.INVALID_VALUE, f"'{key}' must be between {low} and {high}."
        )
    return value


def _validate_static_headers(raw) -> dict:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigurationError(
            ConfigErrorCode.INVALID_VALUE, "'static_headers' must be an object."
        )
    if len(raw) > MAX_STATIC_HEADERS:
        raise ConfigurationError(ConfigErrorCode.INVALID_VALUE, "Too many static headers.")

    cleaned: dict[str, str] = {}
    for name, value in raw.items():
        if not isinstance(name, str) or not isinstance(value, str):
            raise ConfigurationError(
                ConfigErrorCode.HEADER_REJECTED, "Header names and values must be text."
            )
        lowered = name.strip().lower()
        if lowered in REJECTED_STATIC_HEADERS or lowered not in ALLOWED_STATIC_HEADERS:
            # One message for "explicitly forbidden" and "not on the list": the
            # allow-list is the rule, and naming which branch fired would tell
            # the caller what the forbidden list contains.
            raise ConfigurationError(
                ConfigErrorCode.HEADER_REJECTED, f"The header '{name}' may not be configured."
            )
        if len(value) > MAX_HEADER_VALUE_LENGTH:
            raise ConfigurationError(ConfigErrorCode.HEADER_REJECTED, "Header value is too long.")
        if any(ch in value or ch in name for ch in ("\r", "\n", "\x00")):
            # Response splitting. The client library would probably refuse too;
            # "probably" is not a control.
            raise ConfigurationError(
                ConfigErrorCode.HEADER_REJECTED, "Headers may not contain control characters."
            )
        cleaned[lowered] = value
    return cleaned


def _validate_generic_https(config: dict) -> dict:
    allowed = {
        "base_url",
        "allowed_path_prefix",
        "health_path",
        "connect_timeout_seconds",
        "read_timeout_seconds",
        "max_response_bytes",
        "verify_tls",
        "static_headers",
    }
    unknown = sorted(set(config) - allowed)
    if unknown:
        raise ConfigurationError(
            ConfigErrorCode.UNKNOWN_FIELD, f"Unsupported configuration field: {unknown[0]}"
        )

    base_url = config.get("base_url")
    if not isinstance(base_url, str) or not base_url:
        raise ConfigurationError(ConfigErrorCode.MISSING_FIELD, "'base_url' is required.")
    try:
        # Text-level only here. The destination is resolved and classified at
        # request time, because a name that is public today may not be tomorrow
        # and configuration is not the moment that matters.
        validate_url(base_url)
        prefix = normalize_path_prefix(config.get("allowed_path_prefix") or "/")
    except DestinationRefused as exc:
        raise ConfigurationError(ConfigErrorCode.INVALID_VALUE, str(exc)) from exc

    verify_tls = _require_bool(config, "verify_tls", default=True)
    if verify_tls is not True:
        # There is no environment flag that turns this off. A connector carries
        # tenant documents and a bearer token; unverified TLS means handing both
        # to whoever answers.
        raise ConfigurationError(
            ConfigErrorCode.TLS_REQUIRED, "TLS verification cannot be disabled."
        )

    health_path = config.get("health_path", "")
    if health_path is None:
        health_path = ""
    if not isinstance(health_path, str) or len(health_path) > 512:
        raise ConfigurationError(ConfigErrorCode.INVALID_VALUE, "'health_path' must be short text.")

    return {
        "base_url": base_url,
        "allowed_path_prefix": prefix,
        "health_path": health_path.lstrip("/"),
        "connect_timeout_seconds": _require_int(
            config,
            "connect_timeout_seconds",
            default=DEFAULT_CONNECT_TIMEOUT_SECONDS,
            low=MIN_TIMEOUT_SECONDS,
            high=MAX_CONNECT_TIMEOUT_SECONDS,
        ),
        "read_timeout_seconds": _require_int(
            config,
            "read_timeout_seconds",
            default=DEFAULT_READ_TIMEOUT_SECONDS,
            low=MIN_TIMEOUT_SECONDS,
            high=MAX_READ_TIMEOUT_SECONDS,
        ),
        "max_response_bytes": _require_int(
            config,
            "max_response_bytes",
            default=DEFAULT_MAX_RESPONSE_BYTES,
            low=1024,
            high=MAX_MAX_RESPONSE_BYTES,
        ),
        "verify_tls": True,
        "static_headers": _validate_static_headers(config.get("static_headers")),
    }


#: Connector types this milestone actually implements.
#:
#: **HTTPS only.** SFTP was scoped and dropped: doing it properly needs pinned
#: host keys, an explicit known-hosts policy, no agent forwarding and no
#: ProxyCommand, and doing it improperly means `AutoAddPolicy` and a connector
#: that trusts whatever answers on port 22. One connector type with a defensible
#: security model beats two where the second is a placeholder wearing a
#: vendor's name. The enum is open for a later milestone to extend.
_VALIDATORS = {"generic_https": _validate_generic_https}


def validate_configuration(connector_type: str, config) -> dict:
    """Return a normalised configuration, or raise `ConfigurationError`.

    The return value -- not the input -- is what gets stored and used. Defaults
    are materialised here so a stored row never depends on what this module's
    defaults happened to be on the day it was written.
    """
    if not isinstance(config, dict):
        raise ConfigurationError(ConfigErrorCode.INVALID_VALUE, "Configuration must be an object.")
    validator = _VALIDATORS.get(connector_type)
    if validator is None:
        raise ConfigurationError(
            ConfigErrorCode.UNSUPPORTED_TYPE, "That connector type is not supported."
        )
    return validator(config)


def public_configuration(config: dict) -> dict:
    """The configuration as it may be shown to a caller.

    Identical to the stored configuration today, and a separate function anyway:
    the day a connector type needs a field that must not be displayed, this is
    where it gets dropped, and every serialiser already goes through here.
    """
    return dict(config or {})
