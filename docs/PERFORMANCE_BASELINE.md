# Performance baseline

Measurements, before and after. Every number here came from a test that can be
re-run; nothing is estimated.

## How these are measured

**Structural, never timing.** A wall-clock assertion is a promise about the
machine rather than the code: it passes on a laptop, fails on a loaded runner,
gets marked flaky, and is deleted. What is measured instead is query count, rows
the database returned, objects built, and bytes read — properties of the
program.

**Compared across sizes, not pinned.** `assert queries == 13` breaks on every
harmless refactor and still misses what matters. The question is whether a
page's cost depends on how much data the tenant has.

Helpers live in `common/query_budget.py`.

## Attention queue — the defect this milestone found

`submission_operations.attention_rows` caps its scan at
`ATTENTION_SCAN_LIMIT = 500`. The cap was applied **after** the work.

`add()` was handed an already-evaluated list comprehension, so the database
returned every candidate row and Python built a row dict for each one before the
slice. The cap bounded what was *displayed* and nothing else.

| Sections | Kept | Dicts built (before) | Dicts built (after) | Queries | Queries with an outer LIMIT (before → after) |
|---|---|---|---|---|---|
| 10 | 10 | 10 | 10 | 9 | 1 of 9 → 9 of 9 |
| 100 | 100 | 100 | 100 | 9 | 1 of 9 → 9 of 9 |
| 600 | 500 | **600** | **500** | 9 | 1 of 9 → 9 of 9 |
| 1200 | 500 | **1200** | **500** | 9 | 1 of 9 → 9 of 9 |

**The query count was flat at 9 the entire time, before and after.** That is the
point worth keeping: a query-count test would have shown this path as healthy at
every size. The cost was in rows fetched and objects allocated, and only a
measurement of *work* rather than *statements* could see it.

Regression test: `submission_operations/tests/test_scan_cap_reaches_sql.py`.

### A test that was fooled

The first version of "every scan query carries a LIMIT" searched each statement
for the substring and passed against a completely unbounded branch. An
`Exists()` annotation compiles to a subquery ending `LIMIT 1`, so the word was
present in SQL that read the whole table. The assertion now matches an outer
limit at the end of the statement. The mutation that removes the upgrade
branch's bound turned nothing red until that was fixed.

## Connector list and execution history

Measured after Milestone 14's per-row permission fix, confirmed unchanged here.

```
connector list       10 / 100 / 500 rows -> 13 / 13 / 13 queries
execution history    10 / 100 / 500 rows ->  6 /  6 /  6 queries
```

Flat. The connector list was 85 / 485 queries at 10 / 60 rows before Milestone 14
hoisted the advisory permission lookup out of the row loop.

## Paths measured and found already bounded

These were measured during discovery and **not changed**, because the
measurement did not justify it. Optimising them would have been change without
evidence.

| Path | Finding |
|---|---|
| Dashboard case rows | Aggregates over exactly the page the view paginated; one grouped query per dimension |
| Dashboard dossier rows | Same shape |
| Activity feed | `[:limit]` on the queryset — the slice reaches SQL |
| Document list | `select_related` on version and creator; paginated |
| Package detail / manifest | Measured flat in Milestone 13 across 10 / 50 / 120 entries |

## What was deliberately not done

* **No caching.** Every read path here is authorization-sensitive. A cache keyed
  on anything less than (tenant, user, permission set) risks serving one
  tenant's rows to another, and that trade is not worth a query.
* **No new indexes.** No measured query plan justified one. Adding an index
  costs every write to that table forever, and speculative indexes are how a
  write path gets slower for a read that was never slow.
* **No connection pooler.** Nothing measured showed connection pressure.
