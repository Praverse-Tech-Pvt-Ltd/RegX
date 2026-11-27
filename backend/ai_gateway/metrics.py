"""Admin-readable call metrics, computed from `AICallRecord` rows.

Latency percentiles count only calls that reached the provider (answered or
failed there); refusals before the network (off, not configured, no tenant,
breaker open) have no meaningful latency and are counted by outcome instead.
"""

from __future__ import annotations

import math
from datetime import timedelta

from django.db.models import Count, Sum
from django.utils import timezone

from .models import AICallRecord, CallOutcome

#: Upper bound on rows read for the percentiles, so the endpoint stays cheap.
MAX_LATENCY_SAMPLE = 10_000


def percentile(sorted_values: list[int], fraction: float) -> int | None:
    """Nearest-rank percentile. None for an empty list."""
    if not sorted_values:
        return None
    rank = max(1, math.ceil(fraction * len(sorted_values)))
    return sorted_values[rank - 1]


def summarise(days: int = 7) -> dict:
    since = timezone.now() - timedelta(days=days)
    rows = AICallRecord.objects.filter(created_at__gte=since)

    by_outcome = dict.fromkeys(CallOutcome.values, 0)
    for item in rows.values("outcome").annotate(n=Count("id")):
        by_outcome[item["outcome"]] = item["n"]
    total = sum(by_outcome.values())
    reached = by_outcome[CallOutcome.OK] + by_outcome[CallOutcome.PROVIDER_ERROR]

    latencies = sorted(
        rows.filter(
            outcome__in=[CallOutcome.OK, CallOutcome.PROVIDER_ERROR], latency_ms__isnull=False
        )
        .order_by("-created_at")
        .values_list("latency_ms", flat=True)[:MAX_LATENCY_SAMPLE]
    )
    tokens = rows.aggregate(input=Sum("input_tokens"), output=Sum("output_tokens"))
    errors_by_reason = {
        item["reason_code"]: item["n"]
        for item in rows.filter(outcome=CallOutcome.PROVIDER_ERROR)
        .values("reason_code")
        .annotate(n=Count("id"))
        .order_by("reason_code")
    }
    by_prompt = [
        {"prompt_id": i["prompt_id"], "prompt_version": i["prompt_version"], "calls": i["n"]}
        for i in rows.values("prompt_id", "prompt_version")
        .annotate(n=Count("id"))
        .order_by("prompt_id", "prompt_version")
    ]
    return {
        "window_days": days,
        "calls": total,
        "by_outcome": by_outcome,
        "provider_calls": reached,
        "provider_error_rate": round(by_outcome[CallOutcome.PROVIDER_ERROR] / reached, 4)
        if reached
        else None,
        "provider_errors_by_reason": errors_by_reason,
        "latency_ms": {
            "sample": len(latencies),
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "max": latencies[-1] if latencies else None,
        },
        "tokens": {"input": tokens["input"] or 0, "output": tokens["output"] or 0},
        "by_prompt": by_prompt,
    }
