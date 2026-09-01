"""Running real threads against real PostgreSQL, for concurrency tests.

Lives in `common` because every domain needs it and none owns it -- and it
imports **nothing from any domain**, which is what makes that placement legal
rather than convenient. `common` is the innermost layer; a helper here that
reached for a model would invert the architecture, and `import-linter` would
say so.

Sequential calls with a comment claiming concurrency prove nothing. These are
threads on separate connections, released together by a barrier.
"""

from __future__ import annotations

import threading

from django.db import connections


def race(targets, timeout: int = 60):
    """Run callables on real threads, released together, and collect outcomes.

    Returns `(results, errors)` rather than raising: in a race, "one of them
    failed" is frequently the correct outcome, and the test decides which
    outcomes are acceptable.

    Every thread closes its connection afterwards. Without that the test
    database keeps an idle transaction open and the next test blocks behind it,
    which shows up as an unrelated timeout much later.
    """
    results: list = []
    errors: list = []
    barrier = threading.Barrier(len(targets))

    def wrapped(fn):
        def run():
            try:
                barrier.wait(timeout=20)
                results.append(fn())
            except Exception as exc:
                errors.append(exc)
            finally:
                connections.close_all()

        return run

    threads = [threading.Thread(target=wrapped(fn)) for fn in targets]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=timeout)
    return results, errors
