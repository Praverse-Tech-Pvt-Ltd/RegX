"""Versioned prompt templates.

Each template has an id and a version, and every call records both, so any
stored answer can be traced to the exact wording that produced it. Changing a
template's text means adding a new version; a test pins each published
(id, version) to a fingerprint of its text so an in-place edit fails the build.

All templates here are synthetic and written for this codebase. None contains
client data.
"""

from __future__ import annotations

import hashlib
import string
from dataclasses import dataclass


@dataclass(frozen=True)
class PromptTemplate:
    id: str
    version: int
    text: str
    max_output_tokens: int

    @property
    def fields(self) -> frozenset[str]:
        return frozenset(
            name for _, name, _, _ in string.Formatter().parse(self.text) if name is not None
        )

    def fingerprint(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()

    def render(self, values: dict[str, str]) -> str:
        missing = self.fields - set(values)
        extra = set(values) - self.fields
        if missing or extra:
            raise PromptFieldsInvalid(self.id, self.version)
        return self.text.format(**values)


class PromptNotFound(LookupError):
    pass


class PromptFieldsInvalid(ValueError):
    """The caller's fields do not match the template. Names only, never values."""

    def __init__(self, template_id: str, version: int):
        super().__init__(f"fields do not match prompt {template_id} v{version}")


_TEMPLATES: tuple[PromptTemplate, ...] = (
    PromptTemplate(
        id="gateway.health_check",
        version=1,
        text="Reply with the single word: ready.",
        max_output_tokens=8,
    ),
    PromptTemplate(
        id="benchmark.answer",
        version=1,
        text=(
            "You are assisting a pharmaceutical quality team. Answer the request "
            "below in plain English. If the request cannot be answered from the "
            "text given, say so.\n\n{request}"
        ),
        max_output_tokens=400,
    ),
)

PROMPTS: dict[tuple[str, int], PromptTemplate] = {(t.id, t.version): t for t in _TEMPLATES}


def get_prompt(template_id: str, version: int | None = None) -> PromptTemplate:
    """A specific version, or the latest one when `version` is None."""
    if version is not None:
        try:
            return PROMPTS[(template_id, version)]
        except KeyError:
            raise PromptNotFound(f"{template_id} v{version}") from None
    versions = [t for (tid, _), t in PROMPTS.items() if tid == template_id]
    if not versions:
        raise PromptNotFound(template_id)
    return max(versions, key=lambda t: t.version)
