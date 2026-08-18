"""Request correlation and request-completion logging.

Operational only. Nothing here writes to the regulated audit trail, and the
audit trail does not read anything from here -- see ``common.structured_logging``.
"""

from __future__ import annotations

import logging
import time

from .structured_logging import (
    REQUEST_ID_HEADER,
    coerce_incoming_request_id,
    reset_request_id,
    set_request_id,
)

logger = logging.getLogger("regx.request")

#: Probe endpoints. Docker polls these every few seconds per service; at INFO
#: they would be most of the log volume and would bury real traffic. Successful
#: probes drop to DEBUG. Failing ones do not -- a health endpoint returning 500
#: is exactly what someone reading these logs needs to see.
HEALTH_PATHS = frozenset(
    {
        "/api/regx/v1/health/",
        "/api/regx/v1/readiness/",
    }
)


class RequestIDMiddleware:
    """Binds a request id, logs one completion event, sets the response header.

    What is deliberately never touched: the request body, the response body,
    request headers, cookies, and the query string. Only ``request.path`` is
    recorded -- never ``request.get_full_path()`` -- so a query parameter can
    never reach the log, including ones added long after this was written.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = coerce_incoming_request_id(request.headers.get(REQUEST_ID_HEADER))
        token = set_request_id(request_id)
        # Attached so views and DRF handlers can correlate without importing
        # the contextvar machinery.
        request.request_id = request_id
        started = time.perf_counter()

        # One try/finally around everything, so the request id stays bound for
        # the whole request -- including the completion log below. Resetting
        # earlier would leave that record, and anything else logged during
        # response handling, uncorrelated.
        try:
            try:
                response = self.get_response(request)
            except Exception:
                # Unhandled: log it, then re-raise untouched so Django's own
                # handling is unchanged. No body, no headers, no locals -- the
                # exception class and traceback are the diagnostic payload.
                #
                # request_id is NOT passed in extra: the record factory already
                # stamps it, and logging raises KeyError on a key that already
                # exists on the record.
                logger.exception(
                    "unhandled exception",
                    extra={
                        "method": request.method,
                        "path": request.path,
                        "duration_ms": self._elapsed_ms(started),
                    },
                )
                raise

            duration_ms = self._elapsed_ms(started)
            try:
                response[REQUEST_ID_HEADER] = request_id
            except Exception:  # noqa: S110  pragma: no cover
                # Some streaming/file responses reject item assignment. Failing
                # to set a diagnostic header must not fail the request.
                pass

            status_code = getattr(response, "status_code", 0)
            level = logging.INFO
            if status_code >= 500:
                level = logging.ERROR
            elif status_code >= 400:
                level = logging.WARNING
            elif request.path in HEALTH_PATHS:
                level = logging.DEBUG

            logger.log(
                level,
                "request completed",
                extra={
                    "method": request.method,
                    "path": request.path,
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                },
            )
            return response
        finally:
            reset_request_id(token)

    @staticmethod
    def _elapsed_ms(started: float) -> float:
        return round((time.perf_counter() - started) * 1000, 2)
