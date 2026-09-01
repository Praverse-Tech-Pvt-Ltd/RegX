"""Measuring what a read path costs, and asserting it does not grow.

The rule this exists to enforce: **a page's cost must not depend on how much
data the tenant has.** A list that issues one extra query per row is fine at
ten rows and unusable at ten thousand, and nothing in a normal test suite
notices the difference -- every fixture is small.

WHY COUNTS ARE COMPARED, NOT PINNED
-----------------------------------
`assert queries == 13` breaks on every harmless refactor and still would not
catch the thing that matters. What matters is the *shape*: the same page of
results should cost the same number of queries whether the tenant has ten rows
or a thousand. So these helpers measure at two or more sizes and compare.

WHY NOT TIMING
--------------
A wall-clock assertion is a promise about the machine, not about the code. It
passes on a fast laptop, fails on a loaded CI runner, and gets marked flaky and
deleted. Everything here is structural: query counts, rows fetched, objects
built, bytes read. Those are properties of the program.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.db import connection
from django.test.utils import CaptureQueriesContext


@dataclass
class Measurement:
    """What one run of a path cost."""

    size: int
    queries: int
    sql: list[str] = field(default_factory=list)

    @property
    def limited(self) -> int:
        """How many of the queries carried a LIMIT.

        A scan that means to cap its work has to do it in SQL. Counting this
        separates "we asked the database for a bounded set" from "we read
        everything and threw most of it away", which is invisible in the query
        count alone -- both are one query.
        """
        return sum(1 for statement in self.sql if "LIMIT" in statement.upper())


def measure(callable_, /) -> Measurement:
    """Run something once and report what it cost."""
    with CaptureQueriesContext(connection) as ctx:
        callable_()
    return Measurement(
        size=0,
        queries=len(ctx.captured_queries),
        sql=[q["sql"] for q in ctx.captured_queries],
    )


def measure_across(sizes, grow, run) -> list[Measurement]:
    """Grow the data, measure at each size, and return the measurements.

    `grow(target)` must bring the dataset up to `target` rows -- it is called
    with increasing targets and should add only the difference, so a run at
    [10, 100, 500] builds 500 rows in total rather than 610.
    """
    out = []
    for size in sizes:
        grow(size)
        measurement = measure(run)
        measurement.size = size
        out.append(measurement)
    return out


def assert_constant_queries(measurements, *, label: str) -> None:
    """The count must not move as the data grows.

    Reported with every size, because "13 vs 485" is a diagnosis and
    "not equal" is not.
    """
    counts = {m.size: m.queries for m in measurements}
    distinct = set(counts.values())
    assert len(distinct) == 1, f"{label} query count grows with the data: " + ", ".join(
        f"{size} rows -> {q} queries" for size, q in sorted(counts.items())
    )


def assert_bounded_work(measurements, *, label: str, cap: int, actual) -> None:
    """Work done must stop growing once the data passes a cap.

    `actual` maps a measurement to the amount of work observed -- rows built,
    objects created, bytes read. A cap that is applied after the work is done
    bounds the *output* and nothing else, which is the failure this catches.
    """
    over_cap = [m for m in measurements if m.size > cap]
    assert over_cap, f"{label}: no measurement exceeded the cap, so nothing was proved"
    for m in over_cap:
        observed = actual(m)
        assert observed <= cap, (
            f"{label}: {m.size} rows produced {observed} units of work for a cap of {cap}; "
            "the cap is being applied after the work rather than before it"
        )
