"""Every dependency the web process talks to is bounded by a timeout.

WHY THIS EXISTS

`readiness` is an `AllowAny` endpoint served by the web process, and it writes
to the cache. Django's built-in `RedisCache` sets no socket timeout of its own,
so against a Redis that accepts the connection and then never answers -- a
black-holed host, a frozen box, a route that went away -- `cache.set` blocks
until the operating system gives up, which is minutes. The probe does not fail;
it hangs. An orchestrator cannot tell "not ready" from "still thinking", and
because the probe holds a web worker for the whole time, each probe interval
takes another one. A cache outage then starves the web process through its own
health checks.

An unbounded socket is invisible to an ordinary suite. It never shows up as a
slow test, because nothing here talks to a black hole. So what is asserted is
structural: the option is present, it reaches the client redis-py actually
builds, and readiness turns the resulting error into a coarse 503 instead of
propagating it.

THE SPELLING IS THE TRAP

Django's built-in backend passes `OPTIONS` straight into
`redis.ConnectionPool.from_url`, so these keys are redis-py's own, in lower
case. The upper-case `SOCKET_TIMEOUT` spelling belongs to the third-party
`django-redis` package, which is not what is installed here. That is why the
test below asserts on the connection pool the client actually builds rather
than on the settings dictionary alone -- a dictionary test passes just as
happily with a key that does nothing.

WHAT IS DELIBERATELY NOT BOUNDED

The Celery broker uses the same Redis URL and deliberately gets no read
timeout. A worker waiting for a job holds a blocking pop open on purpose, so a
socket read timeout there would tear down an idle worker's connection as a
matter of routine. Bounding the cache and bounding the broker are different
problems with different right answers.
"""

import json
import logging

import pytest

READINESS = "/api/regx/v1/readiness/"

#: Not a latency target -- a ceiling on hanging. Sessions are cache-backed, so
#: a bound tight enough to trip under ordinary load would log users out.
CEILING_SECONDS = 30

TIMEOUT_OPTIONS = ("socket_connect_timeout", "socket_timeout")


def _authoritative_cache():
    """The real cache configuration, not the test override.

    `regx.settings.test` replaces `CACHES` with a local-memory backend so the
    suite does not need a Redis running. That override is precisely what makes
    these options invisible to every other test, which is why this reads the
    authoritative module instead of `django.conf.settings`.

    There is still one source of truth: `regx.settings.base`. Nothing here
    restates a value, it only reads the one the application ships.
    """
    from regx.settings import base

    return base.CACHES["default"]


class TestTheCacheConfigurationCarriesSocketTimeouts:
    def test_both_socket_timeouts_are_configured(self):
        options = _authoritative_cache().get("OPTIONS", {})

        for key in TIMEOUT_OPTIONS:
            assert key in options, (
                f"the cache configuration has no {key}; a Redis that stops "
                "answering will hang the readiness probe instead of failing it"
            )
            value = options[key]
            assert isinstance(value, int | float) and not isinstance(value, bool), (
                f"{key} must be a number, got {value!r}"
            )
            assert value > 0, f"{key} of {value} disables the bound"
            assert value <= CEILING_SECONDS, (
                f"{key} of {value}s is long enough that a probe still looks hung"
            )

    def test_the_timeouts_reach_the_pool_the_client_builds(self):
        """THE regression test.

        Asserted on the connection pool rather than on the settings dict,
        because the failure this guards against is a key that is present and
        ignored. `from_url` builds the pool without connecting, so this runs
        with no Redis anywhere.
        """
        from django.core.cache import CacheHandler

        backend = CacheHandler({"default": _authoritative_cache()})["default"]
        pool = backend._cache._get_connection_pool(write=True)

        for key in TIMEOUT_OPTIONS:
            assert pool.connection_kwargs.get(key), (
                f"{key} never reached redis-py; it is set in OPTIONS but the "
                "client did not receive it, so the socket is still unbounded"
            )

    def test_one_cache_operation_is_bounded_by_the_sum_of_the_two(self):
        """The bound is a real number, and this records what it is.

        redis-py does not retry here -- `retry_on_timeout` is false and the
        default `Retry` allows zero attempts -- so one `cache.set` is one
        connect plus one command, and the worst case is the two timeouts added
        together. That is what makes "bounded" a fact rather than a hope.
        """
        options = _authoritative_cache()["OPTIONS"]
        worst_case = options["socket_connect_timeout"] + options["socket_timeout"]
        assert worst_case <= CEILING_SECONDS

    def test_the_database_check_is_bounded_too(self):
        """The other half of what readiness touches."""
        from regx.settings import base

        connect_timeout = base.DATABASES["default"]["OPTIONS"]["connect_timeout"]
        assert 0 < connect_timeout <= CEILING_SECONDS


class _StalledCache:
    """Stands in for a Redis that has stopped answering.

    Raises what redis-py raises when the socket bound above fires, and counts
    the calls, because "bounded" also requires that readiness makes exactly one
    of them.
    """

    def __init__(self, exc):
        self._exc = exc
        self.calls = 0

    def set(self, *args, **kwargs):
        self.calls += 1
        raise self._exc


@pytest.mark.django_db
class TestReadinessSurvivesARedisStall:
    """What the socket bound actually buys.

    The configuration tests above establish that a stalled Redis raises within
    a few seconds instead of blocking for minutes. These establish the other
    half: when it does raise, readiness answers. A probe that returns a 500 and
    a traceback is the same operational problem as one that hangs -- the
    orchestrator still cannot act on it.
    """

    def test_a_read_stall_becomes_a_coarse_503(self, client, monkeypatch, caplog):
        import redis

        stalled = _StalledCache(
            redis.exceptions.TimeoutError("Timeout reading from redis-cache.internal:6379")
        )
        monkeypatch.setattr("common.views.cache", stalled)

        with caplog.at_level(logging.ERROR, logger="regx.health"):
            response = client.get(READINESS)

        assert response.status_code == 503
        assert response.json()["checks"]["cache"] == "unavailable"
        assert stalled.calls == 1, (
            f"readiness made {stalled.calls} cache calls; the response is only "
            "bounded by the socket timeout if it makes exactly one"
        )

    def test_a_connect_stall_becomes_a_coarse_503(self, client, monkeypatch):
        """The other way a black-holed host presents: the connect never lands."""
        import redis

        stalled = _StalledCache(
            redis.exceptions.ConnectionError(
                "Error connecting to redis-cache.internal:6379. Connection timed out."
            )
        )
        monkeypatch.setattr("common.views.cache", stalled)

        response = client.get(READINESS)

        assert response.status_code == 503
        assert response.json()["checks"]["cache"] == "unavailable"

    def test_the_stall_message_never_reaches_the_caller(self, client, monkeypatch):
        """`readiness` is `AllowAny`.

        A redis-py error names the host and the port, and publishing internal
        topology to an unauthenticated caller at the moment something is wrong
        is the opposite of useful. Same rule the database check already
        follows.
        """
        import redis

        monkeypatch.setattr(
            "common.views.cache",
            _StalledCache(
                redis.exceptions.TimeoutError("Timeout reading from redis-cache.internal:6379")
            ),
        )

        response = client.get(READINESS)
        body = json.dumps(response.json())

        for secret in ("redis-cache.internal", "6379", "Timeout reading", "redis"):
            assert secret not in body.lower(), f"readiness leaked {secret!r}"

    def test_the_detail_is_kept_server_side(self, client, monkeypatch, caplog):
        """Coarse outward, complete inward. Losing the cause entirely would
        trade one operational problem for another."""
        import redis

        monkeypatch.setattr(
            "common.views.cache",
            _StalledCache(redis.exceptions.TimeoutError("Timeout reading from redis")),
        )

        with caplog.at_level(logging.ERROR, logger="regx.health"):
            client.get(READINESS)

        assert any("cache unavailable" in record.getMessage() for record in caplog.records), (
            "the cache failure was hidden from the caller and never logged"
        )
        assert any(record.exc_info for record in caplog.records), (
            "the log records the failure but not the exception behind it"
        )

    def test_a_stalled_cache_does_not_take_the_database_check_with_it(self, client, monkeypatch):
        """Each dependency is reported on its own.

        A single `checks` verdict would tell an operator that something is
        wrong and not which thing, which is the entire value of the endpoint.
        """
        import redis

        monkeypatch.setattr(
            "common.views.cache", _StalledCache(redis.exceptions.TimeoutError("stalled"))
        )

        response = client.get(READINESS)
        checks = response.json()["checks"]

        assert checks["cache"] == "unavailable"
        assert checks["database"] == "ok"

    def test_liveness_is_unaffected_by_a_stalled_cache(self, client, monkeypatch):
        """Restarting the web process does not fix Redis."""
        import redis

        monkeypatch.setattr(
            "common.views.cache", _StalledCache(redis.exceptions.TimeoutError("stalled"))
        )

        response = client.get("/api/regx/v1/health/")

        assert response.status_code == 200
        assert response.json()["status"] == "ok"
