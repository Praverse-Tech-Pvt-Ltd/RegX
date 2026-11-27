"""Benchmark the configured AI provider against the SOW latency targets.

    python manage.py ai_benchmark --tenant <slug> [--concurrency 1,5,10] [--repeats 3]

Runs the fixed synthetic prompt set (ai_gateway/benchmark_prompts.py) through
the real gateway path -- tenant check, off switch, breaker, retries, records --
at each concurrency level, then reports p50/p95 end-to-end latency, error rate
and tokens per mode, and whether p95 meets the target (Fast < 5 s, Think < 10 s).
Consistency: each prompt is sent `--repeats` times one after another and the
answers compared (by hash; no answer text is printed or stored).

It sends nothing unless a real provider is configured and AI is enabled: with
the default empty REGX_AI_* values it stops with "not configured".
"""

from __future__ import annotations

import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.models import Sum

from ai_gateway import service
from ai_gateway.benchmark_prompts import BENCHMARK_PROMPTS, TARGET_P95_SECONDS
from ai_gateway.config import config_problem, load_config
from ai_gateway.metrics import percentile
from ai_gateway.models import AICallRecord

PROMPT_ID = "benchmark.answer"


def _levels(raw: str) -> list[int]:
    try:
        levels = [int(x) for x in raw.split(",") if x.strip()]
    except ValueError:
        raise CommandError("--concurrency must be a comma-separated list of integers") from None
    if not levels or any(n < 1 or n > 50 for n in levels):
        raise CommandError("--concurrency levels must be between 1 and 50")
    return levels


class Command(BaseCommand):
    help = "Benchmark the configured AI provider (synthetic prompts only)."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", required=True, help="Tenant slug the calls are made in.")
        parser.add_argument("--concurrency", default="1,5,10")
        parser.add_argument(
            "--repeats", type=int, default=3, help="Consistency repeats per prompt."
        )
        parser.add_argument("--fast-target", type=float, default=TARGET_P95_SECONDS["fast"])
        parser.add_argument("--think-target", type=float, default=TARGET_P95_SECONDS["think"])
        parser.add_argument("--json-out", default="", help="Also write the report as JSON here.")

    def handle(self, *args, **opts):
        config = load_config()
        problem = config_problem(config)
        if config.provider == "stub":
            problem = problem or "PROVIDER_IS_OFFLINE_STUB"
        if problem:
            raise CommandError(f"AI is not configured ({problem}). Nothing was sent.")
        if not service.is_enabled():
            raise CommandError(
                "AI is disabled: REGX_AI_ENABLED and the platform switch must both be on. "
                "Nothing was sent."
            )
        levels = _levels(opts["concurrency"])
        if opts["repeats"] < 2:
            raise CommandError("--repeats must be at least 2")

        from tenancy.models import Tenant

        tenant = Tenant.objects.filter(slug=opts["tenant"]).first()
        if tenant is None:
            raise CommandError("No tenant with that slug. Nothing was sent.")

        targets = {"fast": opts["fast_target"], "think": opts["think_target"]}
        report = {
            "provider": config.provider,
            "model": config.model,
            "prompt_id": PROMPT_ID,
            "targets_p95_seconds": targets,
            "levels": [],
            "consistency": {},
        }
        self.stdout.write(f"Provider {config.provider}, model {config.model}")

        for level in levels:
            jobs = [p for p in BENCHMARK_PROMPTS for _ in range(level)]
            with ThreadPoolExecutor(max_workers=level) as pool:
                results = list(pool.map(lambda p: self._one(tenant, p), jobs))
            entry = {"concurrency": level, "modes": {}}
            for mode in ("fast", "think"):
                rows = [r for r in results if r["mode"] == mode]
                entry["modes"][mode] = self._summarise(rows, targets[mode])
            report["levels"].append(entry)
            self._print_level(entry)

        report["consistency"] = self._consistency(tenant, opts["repeats"])
        c = report["consistency"]
        self.stdout.write(
            f"Consistency: {c['identical']}/{c['prompts']} prompts gave identical answers "
            f"across {c['repeats']} runs ({c['failed_runs']} runs failed)"
        )
        if opts["json_out"]:
            with open(opts["json_out"], "w", encoding="utf-8") as fh:
                json.dump(report, fh, indent=2)
        return None

    # -- helpers -------------------------------------------------------------

    def _call(self, tenant, prompt):
        from tenancy.context import clear_current_tenant, set_current_tenant

        set_current_tenant(tenant)  # thread-local: set in every worker thread
        try:
            started = time.monotonic()
            result = service.generate(PROMPT_ID, fields={"request": prompt.request})
            return result, time.monotonic() - started
        finally:
            clear_current_tenant()
            connection.close()  # each worker thread has its own connection

    def _one(self, tenant, prompt):
        result, seconds = self._call(tenant, prompt)
        return {"mode": prompt.mode, "ok": result.ok, "seconds": seconds, "call_id": result.call_id}

    def _summarise(self, rows, target):
        times = sorted(int(r["seconds"] * 1000) for r in rows)
        p95 = percentile(times, 0.95)
        tokens = AICallRecord.objects.filter(
            public_id__in=[r["call_id"] for r in rows if r["call_id"]]
        ).aggregate(input=Sum("input_tokens"), output=Sum("output_tokens"))
        errors = sum(1 for r in rows if not r["ok"])
        return {
            "requests": len(rows),
            "errors": errors,
            "error_rate": round(errors / len(rows), 4) if rows else None,
            "p50_ms": percentile(times, 0.50),
            "p95_ms": p95,
            "input_tokens": tokens["input"] or 0,
            "output_tokens": tokens["output"] or 0,
            "target_p95_ms": int(target * 1000),
            "meets_target": p95 is not None and p95 < target * 1000 and errors == 0,
        }

    def _print_level(self, entry):
        self.stdout.write(f"Concurrency {entry['concurrency']}:")
        for mode, m in entry["modes"].items():
            verdict = "MEETS" if m["meets_target"] else "MISSES"
            self.stdout.write(
                f"  {mode:<5} requests={m['requests']} errors={m['errors']} "
                f"p50={m['p50_ms']}ms p95={m['p95_ms']}ms "
                f"tokens in/out={m['input_tokens']}/{m['output_tokens']} "
                f"target p95<{m['target_p95_ms']}ms {verdict}"
            )

    def _consistency(self, tenant, repeats):
        identical = failed = 0
        for prompt in BENCHMARK_PROMPTS:
            hashes = set()
            for _ in range(repeats):
                result, _seconds = self._call(tenant, prompt)
                if not result.ok:
                    failed += 1
                    continue
                hashes.add(hashlib.sha256(result.text.encode("utf-8")).hexdigest())
            if len(hashes) == 1:
                identical += 1
        return {
            "prompts": len(BENCHMARK_PROMPTS),
            "repeats": repeats,
            "identical": identical,
            "failed_runs": failed,
        }
