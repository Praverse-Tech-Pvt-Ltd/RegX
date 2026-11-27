"""`generate()`: the single entry point for an AI call.

Order of checks, each one cheaper than the next and each one able to stop the
call before anything leaves the process:

1. tenant: a current tenant is required, and a named user must be an active
   member of it;
2. off switch: the REGX_AI_ENABLED setting AND the platform switch;
3. configuration: provider known, URL / key / model present;
4. prompt: template exists and the caller's fields match it;
5. circuit breaker: refused at once while the provider is paused;
6. the provider call, with an overall time budget and limited retries.

It never raises for an AI problem. Every path returns an `AIResult` the caller
can show ("AI unavailable") while the rest of the page carries on.

**Safe logging.** One log line and one `AICallRecord` per call, carrying tenant,
user, provider, model, prompt id/version, latency, tokens and outcome. Never the
prompt, the fields, the response, the error body or the key.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from django.conf import settings

from common.exceptions import TenantScopeMissing

from . import breaker
from .config import config_problem, load_config
from .models import AICallRecord, AISwitch, CallOutcome
from .prompts import get_prompt
from .providers import ProviderError, ProviderReply, ProviderRequest, provider_factory

logger = logging.getLogger("regx.ai_gateway")

UNAVAILABLE_MESSAGE = "AI unavailable. The rest of this page works as normal."
DISABLED_MESSAGE = "AI is disabled."
NOT_CONFIGURED_MESSAGE = "AI is not configured."
REFUSED_MESSAGE = "AI is available only inside a workspace you belong to."


class ResultStatus:
    OK = "ok"
    DISABLED = "disabled"
    NOT_CONFIGURED = "not_configured"
    REFUSED = "refused"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class AIResult:
    status: str
    message: str
    reason_code: str = ""
    text: str | None = None
    prompt_id: str = ""
    prompt_version: int = 0
    call_id: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == ResultStatus.OK


def is_enabled() -> bool:
    """Both gates: the deployment setting and the platform switch."""
    return bool(settings.REGX_AI_ENABLED) and AISwitch.is_on()


def _tenant_problem(user):
    from tenancy.context import current_tenant
    from tenancy.models import TenantMembership

    try:
        tenant = current_tenant()
    except TenantScopeMissing:
        return None, "TENANT_REQUIRED"
    if user is not None:
        if not getattr(user, "is_authenticated", False):
            return tenant, "USER_NOT_AUTHENTICATED"
        if not TenantMembership.objects.filter(tenant=tenant, user=user, is_active=True).exists():
            return tenant, "NOT_A_MEMBER"
    return tenant, None


def _call_with_retries(
    provider, request: ProviderRequest, config
) -> tuple[ProviderReply | None, str, int]:
    """(reply, error_code, attempts). Retries only retryable errors, within the budget."""
    deadline = time.monotonic() + config.timeout_seconds
    attempts = 0
    error_code = ""
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None, error_code or "TIMEOUT", attempts
        attempts += 1
        try:
            reply = provider.complete(
                ProviderRequest(
                    prompt=request.prompt,
                    max_output_tokens=request.max_output_tokens,
                    timeout_seconds=remaining,
                )
            )
            return reply, "", attempts
        except ProviderError as exc:
            error_code = exc.code
            if not exc.retryable or attempts > config.max_retries:
                return None, error_code, attempts
        except Exception:  # a provider bug must not take the page down
            return None, "PROVIDER_FAILED", attempts
        pause = config.retry_backoff_seconds * attempts
        if pause and time.monotonic() + pause < deadline:
            time.sleep(pause)


def _finish(
    *,
    tenant,
    user,
    provider_name: str,
    model: str,
    prompt_id: str,
    prompt_version: int,
    outcome: str,
    reason_code: str = "",
    started: float | None = None,
    attempts: int = 0,
    reply: ProviderReply | None = None,
) -> AICallRecord:
    latency_ms = int((time.monotonic() - started) * 1000) if started is not None else None
    record = AICallRecord.objects.create(
        tenant=tenant,
        user=user if getattr(user, "pk", None) else None,
        provider=provider_name[:32],
        model=model[:128],
        prompt_id=prompt_id[:64],
        prompt_version=prompt_version,
        outcome=outcome,
        reason_code=reason_code,
        latency_ms=latency_ms,
        attempts=attempts,
        input_tokens=reply.input_tokens if reply else None,
        output_tokens=reply.output_tokens if reply else None,
    )
    logger.info(
        "ai call finished",
        extra={
            "outcome": outcome,
            "reason_code": reason_code or None,
            "tenant": getattr(tenant, "slug", None),
            "user": str(user.public_id) if getattr(user, "public_id", None) else None,
            "ai_provider": provider_name,
            "ai_model": model or None,
            "prompt_id": prompt_id,
            "prompt_version": prompt_version,
            "duration_ms": latency_ms,
            "attempts": attempts,
            "input_tokens": record.input_tokens,
            "output_tokens": record.output_tokens,
            "ai_call_id": str(record.public_id),
        },
    )
    return record


def generate(
    prompt_id: str, *, fields: dict[str, str] | None = None, user=None, version: int | None = None
) -> AIResult:
    fields = fields or {}
    config = load_config()
    common = {"user": user, "provider_name": config.provider or "none", "model": config.model}

    # An unknown template or wrong fields is a programming error, not an AI
    # outage: it raises (PromptNotFound / PromptFieldsInvalid) instead of
    # returning a result.
    template = get_prompt(prompt_id, version)
    prompt_text = template.render(fields)
    prompt_ref = {"prompt_id": template.id, "prompt_version": template.version}

    def result(status, message, outcome, reason="", **kw):
        record = _finish(
            tenant=tenant, outcome=outcome, reason_code=reason, **common, **prompt_ref, **kw
        )
        return AIResult(
            status=status,
            message=message,
            reason_code=reason,
            text=kw["reply"].text if kw.get("reply") else None,
            call_id=str(record.public_id),
            **prompt_ref,
        )

    tenant, problem = _tenant_problem(user)
    if problem:
        return result(ResultStatus.REFUSED, REFUSED_MESSAGE, CallOutcome.TENANT_REFUSED, problem)

    if not is_enabled():
        return result(ResultStatus.DISABLED, DISABLED_MESSAGE, CallOutcome.DISABLED, "AI_DISABLED")

    problem = config_problem(config)
    if problem:
        return result(
            ResultStatus.NOT_CONFIGURED, NOT_CONFIGURED_MESSAGE, CallOutcome.NOT_CONFIGURED, problem
        )

    if breaker.is_open(config.provider):
        return result(
            ResultStatus.UNAVAILABLE, UNAVAILABLE_MESSAGE, CallOutcome.CIRCUIT_OPEN, "CIRCUIT_OPEN"
        )

    try:
        provider = provider_factory(config.provider)(config)
    except ValueError:  # e.g. a base URL the adapter refuses (plain http to a remote host)
        return result(
            ResultStatus.NOT_CONFIGURED,
            NOT_CONFIGURED_MESSAGE,
            CallOutcome.NOT_CONFIGURED,
            "ENDPOINT_INVALID",
        )
    started = time.monotonic()
    reply, error_code, attempts = _call_with_retries(
        provider,
        ProviderRequest(
            prompt=prompt_text,
            max_output_tokens=template.max_output_tokens,
            timeout_seconds=config.timeout_seconds,
        ),
        config,
    )
    if reply is None:
        breaker.record_failure(config.provider)
        return result(
            ResultStatus.UNAVAILABLE,
            UNAVAILABLE_MESSAGE,
            CallOutcome.PROVIDER_ERROR,
            error_code,
            started=started,
            attempts=attempts,
        )
    breaker.record_success(config.provider)
    common["model"] = reply.model or config.model
    return result(
        ResultStatus.OK, "", CallOutcome.OK, started=started, attempts=attempts, reply=reply
    )
