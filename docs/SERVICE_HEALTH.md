# Service Health

**Scope: per-container health signals.** Docker asks each service a question it
can only answer if it is actually working, and records the answer.

This is **not** monitoring, **not** alerting, and **not** SLA enforcement.
Nothing here pages anyone, retains history beyond the last few probes, or
promises availability. It is a local signal that `docker compose ps`, an
operator, and CI can read.

Verified against `regx-main` `d0e443d85ecf9eeba0d9018e1046f9c18181da4a`.

---

## 1. Coverage

| Service | Healthcheck | Probe asks |
|---|:-:|---|
| postgres | pre-existing | `pg_isready -U regx` — the server accepts connections |
| redis | pre-existing | `redis-cli ping` — the server answers |
| backend | pre-existing | HTTP 200 from `/api/regx/v1/health/` |
| company_site | pre-existing | HTTP 200 from `/termsofuse/` |
| nginx | pre-existing | HTTP 200 from `/healthz` on `127.0.0.1:8080` |
| **celery** | **added** | the worker replies to a Celery control ping |
| **frontend** | **added** | the Next.js server returns 200 for `/signin` |

Five of seven services were covered. The two that were not are the two whose
failure is hardest to see from outside: a Celery worker that has stopped
consuming looks identical to a working one from the process table, and a
frontend that is not serving still reports `Up`.

---

## 2. What "healthy" means here

**A running process is not a working service.** That is the whole reason these
two probes exist, and it is not hypothetical — it was reproduced:

> `SIGSTOP` the Celery worker and `docker compose ps` still reports `Up`,
> `.State.Status` is still `running`, and the `celery@... ready.` line is still
> in the log. All three of the signals CI previously relied on still passed
> while the worker consumed nothing at all.

So each probe asks for work, not for existence.

---

## 3. Celery

```
celery -A regx inspect ping -d celery@$(hostname) --timeout 5
```

| Setting | Value |
|---|---|
| interval | 20s |
| timeout | 10s |
| retries | 3 |
| start_period | 30s |

**Healthy** means the worker's main process received a control message over the
broker and replied. That implies the broker is reachable, the worker is
connected to it, and its control loop is running.

Three details are load-bearing:

- **`-d celery@...` targets this worker by nodename.** A bare `inspect ping` is
  a broadcast that succeeds if *any* worker replies — so the moment a second
  worker exists, a dead one would report healthy. Targeting is also far faster,
  because it returns on the first reply instead of waiting out the timeout:
  **0.5s targeted vs 5.8s broadcast**, measured.
- **`$(hostname)`, not `$HOSTNAME`.** `HOSTNAME` is not in this container's
  `Config.Env` — it is injected on the `docker exec` path, not declared — so a
  healthcheck could see it empty, target the node `celery@`, never get a reply,
  and pin the service unhealthy for a reason that has nothing to do with the
  worker. `hostname` reads the UTS namespace, which is what Celery uses to build
  its nodename. In `compose.yaml` it is written `$$(hostname)` so compose passes
  it through instead of expanding it from the host environment.
- **Output is discarded** and replaced with one fixed line. The failure path is
  a ~120-line Python traceback. It was tested with a password embedded in the
  broker URL and the password did not appear anywhere in it, but keeping
  arbitrary library text out of `docker inspect` health logs is the safer
  default.

A worker busy running a long task still replies — the control loop lives in the
main process and tasks run in child processes — so a loaded worker is not
falsely marked unhealthy.

---

## 4. Frontend

```
wget -q -O /dev/null http://127.0.0.1:3000/signin
```

| Setting | Value |
|---|---|
| interval | 10s |
| timeout | 5s |
| retries | 3 |
| start_period | 15s |

**Healthy** means the Node server accepted a connection and returned a 2xx for a
real application route. `wget` exits non-zero on any HTTP error status, so a 404
or a 500 fails the probe — it is not merely a port check.

- **`127.0.0.1`, not `localhost`.** `node:22-alpine` resolves `localhost` to
  `::1` first and Next binds `0.0.0.0` (IPv4 only), so a `localhost` probe is
  refused outright. Verified in this image. It is the same trap that once had
  nginx reporting unhealthy while it was serving every request correctly.
- **`/signin`, not `/`.** nginx routes `/` to the company site, so the
  frontend's own `/` is a page no user ever reaches; `/signin` is its real entry
  route. It needs no session, and it is a client component, so rendering it
  makes no backend call.

**The frontend probe deliberately does not depend on the backend.** A
per-service signal should say something about that service. Cross-service
routing is already covered by nginx's own `/healthz` and by the origin checks.

---

## 5. Measured behaviour

Local stack. Failure induced with `SIGSTOP`, which leaves the process alive and
the container `running` — the case that motivated the work.

| Service | Cold start → healthy | Healthy → unhealthy | Unhealthy → healthy |
|---|---|---|---|
| celery | ~6s | **70s** | **5s** |
| frontend | ~1s | **45s** | **<2s** |

Both matched the configured arithmetic: three failed probes at the configured
interval, plus probe duration. Celery's failing probe takes ~5.8s because it
waits out `--timeout 5`; the frontend's fails by hitting the 5s Docker timeout
(`Health check exceeded timeout (5s)`).

Throughout the failure window both containers reported `running` and `Up`. Only
the health status changed — which is the point.

---

## 6. `depends_on` was not changed

Deliberately.

- **Nothing starts after celery.** No service needs a worker to be ready.
- **nginx already depends on frontend** with the default `service_started`.
  Promoting it to `service_healthy` would delay the origin without fixing
  anything: nginx needs the upstream *name* to resolve at startup, which a
  created container already satisfies. A brief 502 while Next finishes booting
  is self-healing; a later origin is not an improvement.

A healthcheck is worth having for operator visibility and for CI to wait on,
even when no startup ordering depends on it.

---

## 7. nginx upstreams after recreation — unchanged behaviour

Applying this change recreates `celery` and `frontend`, which is exactly the
condition that surfaces a known behaviour:

**nginx resolves its upstream hostnames once at startup and holds the addresses
for the life of the process.** A recreated upstream gets a new address on the
compose network and nginx keeps proxying to the old one.

Reproduced again here: after `docker compose up -d` recreated the frontend,
`/signin` and `/documents` returned **502** through the origin while the
frontend itself was healthy, and `/` and `/ratools/` — company site, not
recreated — still returned 200.

The symptom differs from the restore case in `BACKUP_RESTORE_DR.md` §4, which
produced a **404**. The difference is whether the stale address has since been
reused: if another container holds it, that container answers and simply lacks
the route (404); if nothing holds it, the connection fails (502). Same cause,
two faces.

```bash
docker compose restart nginx
```

That restored every route to 200. It is a restart-to-re-resolve fix and **not** a
claim that nginx tracks Docker DNS — it does not, which is why the restart is
needed. It applies to any container recreation, not only to this change. No
nginx redesign was undertaken as part of this work.

---

## 8. Operator commands

```bash
docker compose ps
```

Shows `(healthy)`, `(unhealthy)` or `(health: starting)` per service.

```bash
docker inspect --format='{{.State.Health.Status}}' regx-celery-1
```

One service's current status.

```bash
docker inspect --format='{{range .State.Health.Log}}{{.ExitCode}} {{.Output}}{{end}}' regx-celery-1
```

The last few probe results with their exit codes. Because celery's probe output
is suppressed, run the probe by hand when you need the detail:

```bash
docker compose exec celery sh -c 'celery -A regx inspect ping -d celery@$(hostname)'
```

---

## 9. Limitations

- **Health is per container.** All seven green does not mean the integrated
  application works end to end; nothing here exercises a user journey. Check the
  origin at `http://localhost:8080` for that.
- **`start_period` hides failures during startup**, by design — probes failing
  in the first 30s (celery) or 15s (frontend) do not count against retries.
- **Detection is not instant**: roughly 70s for celery, 45s for the frontend.
  Faster probing would trade false negatives for latency, a bad trade for a
  signal nothing pages on.
- **A healthy Celery worker is not a drained queue.** The probe says the worker
  answers, not that tasks succeed or that the backlog is small.
- **No history, no alerting, no thresholds, no SLA.** Docker keeps only the last
  few probe results.
- **The Redis and Postgres probes are liveness, not correctness.**
  `redis-cli ping` says the server answers; it says nothing about the data.

---

## 10. CI

`.github/workflows/docker-integration.yml` now waits on both new healthchecks
instead of inferring readiness.

The celery step previously slept 3 seconds, grepped the log for `ready.`, and
asserted `.State.Status` was `running`. A `SIGSTOP`ed worker passes all three.
It now waits for the health status, which the worker can only reach by replying.

The frontend previously had **no wait at all** — the route checks passed because
earlier steps happened to take long enough. That was a race, not a guarantee. It
now waits on the health status.

Run locally against a cold `regx-ci` project, both new waits succeeded on their
first poll — 1 of 45 and 1 of 30 iterations — so the added waits introduce no CI
race and leave substantial headroom for a slower runner.
