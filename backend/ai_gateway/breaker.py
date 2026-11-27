"""A simple circuit breaker, shared across processes through the Django cache.

After AI_BREAKER_FAILURE_THRESHOLD consecutive failed calls the breaker opens
and calls are refused at once (no network) for AI_BREAKER_COOLDOWN_SECONDS.
After the cool-down one call is let through; success closes the breaker,
failure opens it again.

Best effort by design: two processes can race on the counter and let one extra
call through. That is acceptable for a breaker whose job is to stop hammering a
provider that is down, not to count exactly.
"""

from __future__ import annotations

import time

from django.conf import settings
from django.core.cache import cache

_KEY = "ai_gateway:breaker:{provider}"


def _state(provider: str) -> dict:
    return cache.get(_KEY.format(provider=provider)) or {"failures": 0, "open_until": 0.0}


def _save(provider: str, state: dict) -> None:
    cache.set(_KEY.format(provider=provider), state, timeout=None)


def is_open(provider: str) -> bool:
    return _state(provider)["open_until"] > time.time()


def record_success(provider: str) -> None:
    _save(provider, {"failures": 0, "open_until": 0.0})


def record_failure(provider: str) -> None:
    state = _state(provider)
    state["failures"] += 1
    if state["failures"] >= settings.AI_BREAKER_FAILURE_THRESHOLD:
        state["open_until"] = time.time() + settings.AI_BREAKER_COOLDOWN_SECONDS
        # The next call after the cool-down is the trial call; one more failure
        # reopens the breaker straight away.
        state["failures"] = settings.AI_BREAKER_FAILURE_THRESHOLD - 1
    _save(provider, state)


def reset(provider: str) -> None:
    cache.delete(_KEY.format(provider=provider))
