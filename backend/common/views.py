"""Health, readiness, and version endpoints.

LIVENESS AND READINESS ARE DIFFERENT QUESTIONS
----------------------------------------------
`health` answers "is this process running": no dependency is consulted, because
a liveness probe that fails when the database is down asks the orchestrator to
restart a process that has nothing wrong with it. Restarting will not bring the
database back, and it turns one outage into a crash loop.

`readiness` answers "can this process serve traffic": the dependencies a request
actually needs. A failure here removes the instance from rotation, which is the
correct response and is reversible without a restart.

NEITHER PROVES A WORKER IS ALIVE
--------------------------------
These endpoints are served by the web process. A green readiness check says
nothing about whether any Celery worker is consuming the queue -- documents
would be uploaded and never scanned, transfers queued and never run, with every
probe green throughout. Worker health is a separate signal; see
`docs/TASK_RELIABILITY.md` for how stale work is found.

WHAT A PROBE MAY SAY
--------------------
These endpoints are `AllowAny`. They report *which* dependency is unavailable
and never why: an exception message from the database driver names the host, the
port and the database, and publishing that to an unauthenticated caller at
exactly the moment something is wrong is the opposite of useful. The detail goes
to the log.

A PROBE MUST BE ABLE TO FAIL
----------------------------
Both checks are bounded, because an unbounded one does not fail -- it hangs, and
a hung probe is worse than a failing one: the orchestrator cannot tell "not
ready" from "still thinking", and each probe holds a web worker for the whole
time, so an outage in a dependency starves this process through its own health
checks. The database is bounded by `connect_timeout`; the cache by
`socket_connect_timeout` and `socket_timeout`, which had to be added because
Django's Redis backend sets neither. Both live in `regx.settings.base` and are
asserted by `common/tests/test_dependency_timeouts.py`.

Each check is exactly one operation. redis-py is configured with no retries, so
the worst case for the cache probe is the two socket bounds added together
rather than some multiple of them.
"""

import logging

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

logger = logging.getLogger("regx.health")


@extend_schema(tags=["health"], responses={200: {"type": "object"}})
@api_view(["GET"])
@permission_classes([AllowAny])
def health_view(request):
    """Liveness. Deliberately checks nothing."""
    return Response({"status": "ok"})


@extend_schema(tags=["health"], responses={200: {"type": "object"}, 503: {"type": "object"}})
@api_view(["GET"])
@permission_classes([AllowAny])
def readiness_view(request):
    """Readiness. Reports which dependency is unavailable, never why."""
    checks = {}

    try:
        connection.ensure_connection()
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "unavailable"
        # `exc_info` rather than the message in the response: the log is
        # access-controlled and passes through the redaction filter.
        logger.error("readiness: database unavailable", exc_info=True)

    try:
        cache.set("regx_readiness_probe", "1", timeout=5)
        checks["cache"] = "ok"
    except Exception:
        checks["cache"] = "unavailable"
        logger.error("readiness: cache unavailable", exc_info=True)

    all_ok = all(value == "ok" for value in checks.values())
    return Response(
        {
            "status": "ready" if all_ok else "degraded",
            "checks": checks,
            # Stated in the payload so nobody reads a green probe as proof that
            # queued work is being consumed.
            "note": "Web process only. This does not indicate Celery worker health.",
        },
        status=200 if all_ok else 503,
    )


@extend_schema(tags=["health"], responses={200: {"type": "object"}})
@api_view(["GET"])
@permission_classes([AllowAny])
def version_view(request):
    return Response(
        {
            "version": getattr(settings, "APP_VERSION", "unknown"),
            "environment": getattr(settings, "APP_ENVIRONMENT", "unknown"),
        }
    )
