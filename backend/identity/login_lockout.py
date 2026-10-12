"""Per-account lockout for password login.

Keyed on the normalised email, not the client IP. Behind nginx every browser
login reaches Django from the nginx container's address, and every
company_site delegation (`AdminMaster.regx_auth`) arrives from the
company_site container's address, so an IP key would treat all users as one
client: one attacker could lock everyone out, including every legacy login at
once. An account key behaves the same on both paths, and delegation cannot be
used to sidestep it.

Only failures count. After LOGIN_LOCKOUT_THRESHOLD failures within
LOGIN_LOCKOUT_SECONDS the account is refused for LOGIN_LOCKOUT_SECONDS, even
with the correct password, so a lock never reveals whether a guess was right.
A successful login clears the counter.

State lives in the default cache (Redis in production, which already holds the
sessions). The lock stores its expiry and is compared against the clock, so it
ends on time regardless of the cache backend's own expiry.
"""

import hashlib
import logging

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from rest_framework.exceptions import Throttled

logger = logging.getLogger(__name__)

_PREFIX = "identity:login-lockout"


def _key(kind: str, email: str) -> str:
    # Hash so a raw address never appears in a cache key.
    digest = hashlib.sha256(email.strip().lower().encode()).hexdigest()
    return f"{_PREFIX}:{kind}:{digest}"


def check(email: str) -> None:
    """Raise Throttled (HTTP 429, Retry-After) if the account is locked."""
    if not email:
        return
    locked_until = cache.get(_key("until", email))
    if locked_until is None:
        return
    remaining = locked_until - timezone.now().timestamp()
    if remaining > 0:
        raise Throttled(wait=remaining)


def record_failure(email: str) -> None:
    if not email:
        return
    window = settings.LOGIN_LOCKOUT_SECONDS
    count_key = _key("count", email)
    cache.add(count_key, 0, timeout=window)
    try:
        count = cache.incr(count_key)
    except ValueError:  # expired between add() and incr()
        cache.set(count_key, 1, timeout=window)
        count = 1
    if count >= settings.LOGIN_LOCKOUT_THRESHOLD:
        cache.set(_key("until", email), timezone.now().timestamp() + window, timeout=window)
        cache.delete(count_key)
        logger.warning(
            "login locked after repeated failures (account_key=%s, lock_seconds=%s)",
            count_key.rsplit(":", 1)[-1][:16],
            window,
        )


def clear(email: str) -> None:
    cache.delete_many([_key("count", email), _key("until", email)])
