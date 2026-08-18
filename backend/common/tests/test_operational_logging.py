"""Tests for structured operational logging.

The point of most of these is negative: proving that things which must never
reach a log do not reach it. Every secret used here is a synthetic sentinel --
never a real credential -- and each test asserts the sentinel is absent from the
formatted output, not merely that the code "looks safe".
"""

import json
import logging
import threading
import uuid

import pytest
from django.test import RequestFactory

from common.middleware import RequestIDMiddleware
from common.structured_logging import (
    REQUEST_ID_HEADER,
    JSONFormatter,
    RedactionFilter,
    coerce_incoming_request_id,
    get_request_id,
    redact,
)

# Synthetic markers. These are not credentials; they exist so a test can prove
# a specific string never appears in output.
PASSWORD_SENTINEL = "TEST_DO_NOT_LOG_PASSWORD_123"
TOKEN_SENTINEL = "TEST_DO_NOT_LOG_TOKEN_456"
COOKIE_SENTINEL = "TEST_DO_NOT_LOG_COOKIE_789"
BODY_SENTINEL = "TEST_DO_NOT_LOG_BODY_012"


def format_records(records) -> str:
    """Render captured records exactly as a handler would, and join them."""
    formatter = JSONFormatter(service="test")
    redactor = RedactionFilter()
    out = []
    for record in records:
        redactor.filter(record)
        out.append(formatter.format(record))
    return "\n".join(out)


def make_middleware(get_response):
    return RequestIDMiddleware(get_response)


def ok_response(_request):
    from django.http import HttpResponse

    return HttpResponse("ok")


# ---------------------------------------------------------------------------
# A / B -- identity on the request and on the response
# ---------------------------------------------------------------------------
class TestRequestIdentity:
    def test_request_gets_an_id(self):
        """A: every request carries a request_id, generated when none is supplied."""
        seen = {}

        def capture(request):
            seen["ctx"] = get_request_id()
            seen["attr"] = request.request_id
            return ok_response(request)

        make_middleware(capture)(RequestFactory().get("/x/"))

        assert seen["ctx"], "no request id bound to the context"
        assert seen["attr"] == seen["ctx"]
        uuid.UUID(seen["ctx"])  # raises if it is not a well-formed UUID

    def test_response_returns_the_id(self):
        """B: the id comes back to the caller on the response header."""
        response = make_middleware(ok_response)(RequestFactory().get("/x/"))
        assert response[REQUEST_ID_HEADER]
        uuid.UUID(response[REQUEST_ID_HEADER])

    def test_valid_incoming_id_is_honoured(self):
        supplied = str(uuid.uuid4())
        request = RequestFactory().get("/x/", headers={"x-request-id": supplied})
        response = make_middleware(ok_response)(request)
        assert response[REQUEST_ID_HEADER] == supplied

    @pytest.mark.parametrize(
        "hostile",
        [
            "not-a-uuid",
            "../../etc/passwd",
            'x" injected="1',
            "line1\nline2 forged log entry",
            "A" * 5000,
            "",
        ],
    )
    def test_hostile_incoming_id_is_discarded(self, hostile):
        """An inbound header is attacker controlled; only a real UUID is accepted."""
        request = RequestFactory().get("/x/", headers={"x-request-id": hostile})
        response = make_middleware(ok_response)(request)
        returned = response[REQUEST_ID_HEADER]
        assert returned != hostile
        uuid.UUID(returned)

    def test_coerce_helper_always_returns_a_uuid(self):
        for raw in (None, "", "garbage", "\n\n", "12345"):
            uuid.UUID(coerce_incoming_request_id(raw))


# ---------------------------------------------------------------------------
# C -- request completion event
# ---------------------------------------------------------------------------
class TestRequestCompletionLogging:
    def test_completion_event_has_the_expected_fields(self, caplog):
        with caplog.at_level(logging.DEBUG, logger="regx.request"):
            response = make_middleware(ok_response)(RequestFactory().get("/some/path/"))

        records = [r for r in caplog.records if r.name == "regx.request"]
        assert len(records) == 1

        payload = json.loads(format_records(records))
        assert payload["event"] == "request completed"
        assert payload["method"] == "GET"
        assert payload["path"] == "/some/path/"
        assert payload["status_code"] == 200
        assert payload["request_id"] == response[REQUEST_ID_HEADER]
        assert isinstance(payload["duration_ms"], int | float)
        assert payload["level"] == "INFO"
        assert payload["logger"] == "regx.request"

    def test_query_string_is_never_recorded(self, caplog):
        """Only request.path is logged, never the full path with its query."""
        with caplog.at_level(logging.DEBUG, logger="regx.request"):
            make_middleware(ok_response)(
                RequestFactory().get(f"/search/?q=hello&leak={TOKEN_SENTINEL}")
            )
        output = format_records(caplog.records)
        assert TOKEN_SENTINEL not in output
        assert "q=hello" not in output
        assert json.loads(output)["path"] == "/search/"

    def test_server_error_logs_at_error_level(self, caplog):
        from django.http import HttpResponse

        with caplog.at_level(logging.DEBUG, logger="regx.request"):
            make_middleware(lambda r: HttpResponse(status=500))(RequestFactory().get("/x/"))
        assert json.loads(format_records(caplog.records))["level"] == "ERROR"


# ---------------------------------------------------------------------------
# D -- concurrency
# ---------------------------------------------------------------------------
class TestConcurrentIsolation:
    def test_ids_do_not_leak_between_concurrent_requests(self):
        """D: each in-flight request sees only its own id.

        A module global or a carelessly shared value would fail here; a
        ContextVar gives every thread its own copy.
        """
        results = {}
        barrier = threading.Barrier(8)

        def run(index):
            supplied = str(uuid.UUID(int=index))

            def inner(request):
                # Every thread parks here until all eight are inside a request,
                # so the contexts genuinely overlap rather than running serially.
                barrier.wait(timeout=10)
                results[index] = get_request_id()
                return ok_response(request)

            make_middleware(inner)(RequestFactory().get("/x/", headers={"x-request-id": supplied}))

        threads = [threading.Thread(target=run, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        assert len(results) == 8
        for index, seen in results.items():
            assert seen == str(uuid.UUID(int=index)), f"thread {index} saw {seen}"
        assert len(set(results.values())) == 8

    def test_context_is_cleared_after_the_request(self):
        make_middleware(ok_response)(RequestFactory().get("/x/"))
        assert get_request_id() is None


# ---------------------------------------------------------------------------
# E / F / G / H -- nothing sensitive reaches the log
# ---------------------------------------------------------------------------
class TestSensitiveDataNeverLogged:
    def _request_with_everything(self):
        return RequestFactory().post(
            f"/api/regx/v1/auth/login/?token={TOKEN_SENTINEL}",
            data=json.dumps({"email": "a@b.c", "password": PASSWORD_SENTINEL}),
            content_type="application/json",
            headers={
                "authorization": f"Bearer {TOKEN_SENTINEL}",
                "cookie": f"sessionid={COOKIE_SENTINEL}",
                "x-csrftoken": TOKEN_SENTINEL,
            },
        )

    def test_no_sensitive_value_survives_a_full_request(self, caplog):
        """E, F, G, H together: headers, cookies, body and query all stay out."""
        with caplog.at_level(logging.DEBUG):
            make_middleware(ok_response)(self._request_with_everything())

        output = format_records(caplog.records)
        for sentinel in (PASSWORD_SENTINEL, TOKEN_SENTINEL, COOKIE_SENTINEL):
            assert sentinel not in output, f"{sentinel} leaked into the log"
        assert "Bearer" not in output
        assert "sessionid" not in output

    def test_request_body_is_not_logged(self, caplog):
        """H: bodies are never read by the logging path."""
        request = RequestFactory().post(
            "/x/",
            data=json.dumps({"note": BODY_SENTINEL}),
            content_type="application/json",
        )
        with caplog.at_level(logging.DEBUG):
            make_middleware(ok_response)(request)
        assert BODY_SENTINEL not in format_records(caplog.records)

    def test_exception_path_does_not_leak_the_request(self, caplog):
        """An unhandled error must be diagnosable without dumping the request."""

        def boom(_request):
            raise ValueError("upstream refused")

        with caplog.at_level(logging.DEBUG), pytest.raises(ValueError):
            make_middleware(boom)(self._request_with_everything())

        output = format_records(caplog.records)
        for sentinel in (PASSWORD_SENTINEL, TOKEN_SENTINEL, COOKIE_SENTINEL):
            assert sentinel not in output


# ---------------------------------------------------------------------------
# I -- exception correlation
# ---------------------------------------------------------------------------
class TestExceptionLogging:
    def test_exception_is_correlated_and_typed(self, caplog):
        """I: the error record carries the same request_id, the class and a trace."""

        def boom(_request):
            raise KeyError("missing thing")

        request = RequestFactory().get("/explodes/")
        with caplog.at_level(logging.DEBUG, logger="regx.request"), pytest.raises(KeyError):
            make_middleware(boom)(request)

        records = [r for r in caplog.records if r.name == "regx.request"]
        assert len(records) == 1
        payload = json.loads(format_records(records))

        assert payload["level"] == "ERROR"
        assert payload["event"] == "unhandled exception"
        assert payload["exception_class"] == "KeyError"
        assert payload["path"] == "/explodes/"
        assert payload["request_id"]
        assert "Traceback" in payload["stack"]

    def test_the_exception_is_re_raised_unchanged(self):
        """Logging must observe, never swallow."""

        def boom(_request):
            raise RuntimeError("original")

        with pytest.raises(RuntimeError, match="original"):
            make_middleware(boom)(RequestFactory().get("/x/"))


# ---------------------------------------------------------------------------
# J -- health-probe noise
# ---------------------------------------------------------------------------
class TestHealthProbeNoise:
    def test_successful_probe_drops_to_debug(self, caplog):
        """J: Docker polls these constantly; at INFO they would bury real traffic."""
        with caplog.at_level(logging.DEBUG, logger="regx.request"):
            make_middleware(ok_response)(RequestFactory().get("/api/regx/v1/health/"))
        assert json.loads(format_records(caplog.records))["level"] == "DEBUG"

    def test_a_failing_probe_is_not_quietened(self, caplog):
        """A health endpoint returning 500 is exactly what must stay visible."""
        from django.http import HttpResponse

        with caplog.at_level(logging.DEBUG, logger="regx.request"):
            make_middleware(lambda r: HttpResponse(status=500))(
                RequestFactory().get("/api/regx/v1/health/")
            )
        assert json.loads(format_records(caplog.records))["level"] == "ERROR"


# ---------------------------------------------------------------------------
# K -- Celery task arguments
# ---------------------------------------------------------------------------
class TestCeleryTaskArguments:
    def test_task_args_attached_as_extra_are_not_emitted(self):
        """K: Celery puts args/kwargs on the record; the allow-list drops them.

        celery.worker.strategy logs "Task <name>[<id>] received" and attaches
        ``extra={'data': {..., 'args': ..., 'kwargs': ...}}``. The stock text
        formatter never renders that, but a JSON formatter that serialised
        record.__dict__ or every extra would silently begin logging task
        arguments -- which here can be document identifiers and governed
        payloads. This proves the formatter does not.
        """
        record = logging.LogRecord(
            name="celery.worker.strategy",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="Task documents.process[abc-123] received",
            args=(),
            exc_info=None,
        )
        record.data = {
            "id": "abc-123",
            "name": "documents.process",
            "args": f"('{PASSWORD_SENTINEL}',)",
            "kwargs": f"{{'token': '{TOKEN_SENTINEL}'}}",
        }

        payload = json.loads(JSONFormatter(service="test").format(record))

        assert PASSWORD_SENTINEL not in json.dumps(payload)
        assert TOKEN_SENTINEL not in json.dumps(payload)
        assert "data" not in payload
        assert "args" not in payload
        assert "kwargs" not in payload
        # The useful part still survives.
        assert payload["event"] == "Task documents.process[abc-123] received"

    def test_an_exception_message_can_still_echo_its_input(self):
        """KNOWN LIMITATION, pinned deliberately so it cannot regress silently.

        The allow-list keeps task args out of the "received" record, but an
        exception *message* is free-form text and libraries routinely
        interpolate the offending value into it. Observed for real:

            ValueError("Field 'id' expected a number but got 'X'.")

        raised by Django when a task argument reached a FK lookup. Celery's
        LOG_FAILURE includes %(exc)s, so the value travels in the message.

        This is inherent to exceptions in Python, not something the formatter
        introduces, and it predates structured logging -- the same text was
        emitted before, unstructured. Redaction cannot help: the value does not
        look like a secret. It is documented in OPERATIONAL_LOGGING.md rather
        than papered over, because suppressing exception messages entirely would
        remove most of the diagnostic value of an error log.

        The test asserts the CURRENT behaviour. If a future change starts
        stripping exception text, this test should be updated deliberately.
        """
        try:
            raise ValueError(f"expected a number but got {PASSWORD_SENTINEL!r}")
        except ValueError:
            import sys

            record = logging.LogRecord(
                name="celery.app.trace",
                level=logging.ERROR,
                pathname=__file__,
                lineno=1,
                msg="Task t[1] raised unexpected: "
                f"ValueError(\"expected a number but got '{PASSWORD_SENTINEL}'\")",
                args=(),
                exc_info=sys.exc_info(),
            )

        out = JSONFormatter(service="test").format(record)
        assert PASSWORD_SENTINEL in out, (
            "behaviour changed: exception messages no longer echo their input. "
            "Update this test and OPERATIONAL_LOGGING.md section 13."
        )

    def test_arbitrary_extras_are_not_emitted(self):
        record = logging.LogRecord(
            name="x",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="hello",
            args=(),
            exc_info=None,
        )
        record.some_unexpected_field = PASSWORD_SENTINEL
        assert PASSWORD_SENTINEL not in JSONFormatter(service="test").format(record)


# ---------------------------------------------------------------------------
# Redaction -- defence in depth
# ---------------------------------------------------------------------------
class TestRedaction:
    @pytest.mark.parametrize(
        "text",
        [
            f"password={PASSWORD_SENTINEL}",
            f'"password": "{PASSWORD_SENTINEL}"',
            f"api_key={PASSWORD_SENTINEL}",
            f"api-key: {PASSWORD_SENTINEL}",
            f"secret={PASSWORD_SENTINEL}",
            f"access_token={PASSWORD_SENTINEL}",
            f"refresh_token={PASSWORD_SENTINEL}",
            f"authorization: {PASSWORD_SENTINEL}",
            f"cookie={PASSWORD_SENTINEL}",
            f"csrf_token={PASSWORD_SENTINEL}",
            f"mfa_secret={PASSWORD_SENTINEL}",
            f"Bearer {PASSWORD_SENTINEL}",
            f"redis://user:{PASSWORD_SENTINEL}@redis:6379/0",
        ],
    )
    def test_secret_bearing_patterns_are_blanked(self, text):
        result = redact(text)
        assert PASSWORD_SENTINEL not in result, f"not redacted: {text!r}"
        assert "[REDACTED]" in result

    def test_the_key_survives_so_the_line_stays_diagnosable(self):
        assert "password" in redact(f"password={PASSWORD_SENTINEL}")

    def test_ordinary_text_is_left_alone(self):
        for benign in (
            "request completed",
            "user signed in",
            "status_code=200 duration_ms=12.5",
            "processing document 3f1a-99",
        ):
            assert redact(benign) == benign

    def test_redaction_never_raises(self):
        for odd in ("", "\x00\x01", "a" * 100000, "🔑 password=x"):
            redact(odd)


# ---------------------------------------------------------------------------
# Formatter robustness -- logging must not be able to break a request
# ---------------------------------------------------------------------------
class TestFormatterRobustness:
    def test_output_is_one_json_object_per_line(self):
        record = logging.LogRecord(
            name="x",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="line one\nline two",
            args=(),
            exc_info=None,
        )
        out = JSONFormatter(service="test").format(record)
        assert "\n" not in out
        assert json.loads(out)["event"] == "line one\nline two"

    def test_a_bad_message_does_not_raise(self):
        class Explodes:
            def __str__(self):
                raise ValueError("cannot render")

        record = logging.LogRecord(
            name="x",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg=Explodes(),
            args=(),
            exc_info=None,
        )
        out = JSONFormatter(service="test").format(record)
        json.loads(out)  # still parseable rather than an exception in logging

    def test_absent_fields_are_omitted_not_nulled(self):
        record = logging.LogRecord(
            name="x",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="plain",
            args=(),
            exc_info=None,
        )
        payload = json.loads(JSONFormatter(service="test").format(record))
        for field in ("method", "path", "status_code", "duration_ms", "stack"):
            assert field not in payload
        assert set(payload) == {"timestamp", "level", "logger", "service", "event"}
