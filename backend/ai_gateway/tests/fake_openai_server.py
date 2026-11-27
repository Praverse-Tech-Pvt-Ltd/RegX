"""A local fake of an OpenAI-compatible chat endpoint, for tests and the benchmark proof.

Runs inside the test process on 127.0.0.1 with an OS-chosen port, so it is never
reachable from outside the machine. Stdlib only.

Each request is answered according to the next planned behaviour (`plan(...)`),
or the default behaviour when the plan is empty:

* "ok"          canned JSON reply, content derived from the prompt (deterministic)
* "slow"        "ok" after `delay` seconds
* "hang"        sleeps `delay` seconds before sending anything (client times out)
* "429" / "500" / "401" / "400"   that status with a JSON error body
* "malformed"   200 with a body that is not JSON
* "bad_shape"   200 with JSON that has no choices
* "long"        200 with `size` bytes of content (for the response-size cap)
* "drip"        200 headers, then the body a few bytes at a time, `delay` apart

Every request is recorded (path, headers, parsed JSON body) for assertions.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

#: Never sent anywhere real. A recognisable marker so tests can prove the key
#: does not leak into logs or records.
FAKE_API_KEY = "fake-key-for-local-tests-only-0000"
FAKE_MODEL = "fake-model-1"

#: Content the fake puts in every answer, so tests can prove response text
#: never reaches a log line or a database row.
REPLY_MARKER = "FAKE-REPLY-MARKER"


def canned_text(prompt: str) -> str:
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:10]
    return f"{REPLY_MARKER} {digest}"


class _Handler(BaseHTTPRequestHandler):
    server: FakeOpenAIServer
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # keep test output quiet
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw)
        except ValueError:
            body = None
        self.server.record(
            {"method": "POST", "path": self.path, "headers": dict(self.headers), "json": body}
        )
        behaviour = self.server.next_behaviour()
        kind = behaviour["kind"]
        delay = behaviour.get("delay", 0)
        prompt = ""
        if isinstance(body, dict):
            try:
                prompt = body["messages"][-1]["content"]
            except (KeyError, IndexError, TypeError):
                prompt = ""

        if kind in ("slow", "hang"):
            time.sleep(delay)
            if kind == "hang":
                return
        if kind in ("429", "500", "401", "400"):
            return self._send(int(kind), json.dumps({"error": {"message": "echo: " + prompt}}))
        if kind == "malformed":
            return self._send(200, "this is not json {")
        if kind == "bad_shape":
            return self._send(200, json.dumps({"id": "x", "object": "chat.completion"}))
        if kind == "long":
            text = "x" * behaviour.get("size", 2_000_000)
            return self._send(200, self._reply(text, prompt))
        if kind == "drip":
            payload = self._reply(canned_text(prompt), prompt).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            try:
                for i in range(0, len(payload), 8):
                    self.wfile.write(payload[i : i + 8])
                    self.wfile.flush()
                    time.sleep(delay)
            except (BrokenPipeError, ConnectionResetError):
                pass  # the client gave up, which is what the test wanted
            return
        self._send(200, self._reply(canned_text(prompt), prompt))

    def _reply(self, text: str, prompt: str) -> str:
        return json.dumps(
            {
                "id": "chatcmpl-fake",
                "object": "chat.completion",
                "model": FAKE_MODEL,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": text},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": len(prompt.split()),
                    "completion_tokens": len(text.split()),
                    "total_tokens": len(prompt.split()) + len(text.split()),
                },
            }
        )

    def _send(self, status: int, text: str):
        payload = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass


class FakeOpenAIServer(ThreadingHTTPServer):
    daemon_threads = True
    # Do not wait for a deliberately slow handler when the test is over.
    block_on_close = False

    def __init__(self):
        super().__init__(("127.0.0.1", 0), _Handler)
        self._lock = threading.Lock()
        self._plan: deque[dict] = deque()
        self.default = {"kind": "ok"}
        self.requests: list[dict] = []
        self._thread: threading.Thread | None = None
        self._stopped = False

    @property
    def url(self) -> str:
        host, port = self.server_address[:2]
        return f"http://{host}:{port}/v1"

    def plan(self, *behaviours: dict) -> None:
        with self._lock:
            self._plan.extend(behaviours)

    def next_behaviour(self) -> dict:
        with self._lock:
            return self._plan.popleft() if self._plan else dict(self.default)

    def record(self, entry: dict) -> None:
        with self._lock:
            self.requests.append(entry)

    def start(self) -> FakeOpenAIServer:
        self._thread = threading.Thread(target=self.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self.shutdown()
        self.server_close()
