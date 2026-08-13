"""`5A-DEC-001` -- governed resolvers for `FDA_DERIVED_DEFAULT` answers.

The module the 4D-3 specification named (M4D3-SVC-007/008) and which was then
held out of scope by instruction. Until it existed, `prefill_source` and
`default_value_binding` were stored, cloned and returned by the API while being
read by nothing at all: an `FDA_DERIVED_DEFAULT` question started empty, stayed
empty, and could only be filled by a reviewer override. 5A-DEC-001 refuses to
let regulatory personnel approve production bindings against that, so this is
the real mechanism.

**Allow-list, never executable content.** A question binds a resolver by
*identifier*; the identifier is looked up in an immutable registry of
module-level functions declared here. There is no dynamic import, no
`getattr` on a client string, no `eval`, no `exec`. An identifier that is not in
the registry is refused at question-authoring time and again at resolution time,
so an unknown or hostile identifier can never reach a call site.

**Pure and deterministic.** A resolver receives an already-selected, governed
source object and returns a value plus its provenance. It performs no lookup of
its own, opens no transaction, writes nothing and emits no audit. The same
inputs must always produce the same output -- that is what makes an approved
execution reproducible.

**No fabrication.** A resolver that cannot produce a value returns an explicit
failure. It never substitutes zero, empty string or a "sensible" default: a
fabricated regulated value is far worse than a visibly missing one, because
nothing downstream can tell it apart from a real answer.

**Provenance is mandatory.** Every resolution records which source release it
came from, by UUID and governed version, and which field of it. Without that an
approved execution cannot be defended later, and 5A-DEC-001 requires source
identity and version to survive approval.

Scope note: the resolvers here are **infrastructure plus synthetic bindings**.
No production regulatory mapping is declared, because which FDA field answers
which regulatory question is content, decided by the regulatory authority
through the 5A package -- not by engineering. Production content remains 0/20.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType

#: Resolution succeeded and produced a value.
STATUS_RESOLVED = "resolved"
#: The governed source exists but holds no usable value for this binding.
STATUS_VALUE_UNAVAILABLE = "value_unavailable"
#: No governed source could be selected at all.
STATUS_SOURCE_UNAVAILABLE = "source_unavailable"
#: The binding names an identifier that is not in the registry.
STATUS_UNKNOWN_RESOLVER = "unknown_resolver"

#: Source kinds a resolver may declare. Closed set: provenance that names an
#: unrecognised source kind cannot be interpreted by an auditor.
SOURCE_KIND_IID_RELEASE = "fda_iid_release"
SOURCE_KIND_IID_PRECEDENT = "fda_iid_precedent_record"

ALLOWED_SOURCE_KINDS = frozenset({SOURCE_KIND_IID_RELEASE, SOURCE_KIND_IID_PRECEDENT})


@dataclass(frozen=True, slots=True)
class ResolvedAnswer:
    """One resolver outcome: a value, or an explicit reason there is none.

    ``value`` is ``None`` for every non-resolved status, and callers must key
    off ``status`` rather than off ``value is None`` -- a resolver is allowed to
    resolve successfully to a JSON null only if a future binding says so, and
    conflating the two would make "no data" indistinguishable from "no answer".
    """

    status: str
    value: object = None
    source_kind: str = ""
    source_public_id: str = ""
    source_version: str = ""
    source_field: str = ""
    failure_detail: str = ""

    @property
    def resolved(self) -> bool:
        return self.status == STATUS_RESOLVED

    def provenance(self, identifier: str, resolver_version: str) -> dict:
        """The governed provenance record persisted alongside the answer.

        UUID-only external identity: no database primary key appears here, in
        line with the rest of the app's public payload rules. Emitted for
        failures too -- "we looked and the source had nothing" is itself
        provenance an auditor needs.
        """
        record = {
            "resolver_identifier": identifier,
            "resolver_version": resolver_version,
            "status": self.status,
        }
        if self.source_kind:
            record["source_kind"] = self.source_kind
        if self.source_public_id:
            record["source_public_id"] = self.source_public_id
        if self.source_version:
            record["source_version"] = self.source_version
        if self.source_field:
            record["source_field"] = self.source_field
        if self.failure_detail:
            record["failure_detail"] = self.failure_detail
        return record


def _decimal_string(value) -> str | None:
    """Render a Decimal without scientific notation or precision loss.

    Regulated quantities travel as strings for the same reason they do
    everywhere else in this codebase: a JSON float silently rounds a value a
    reviewer approved.
    """
    if value is None:
        return None
    if not isinstance(value, Decimal):
        return None
    return format(value, "f")


# ---------------------------------------------------------------------------
# Resolvers.
#
# Signature is fixed: resolve(source) -> ResolvedAnswer, where `source` is a
# governed object the *caller* selected and locked. A resolver never queries.
# ---------------------------------------------------------------------------


def _resolve_iid_potency_amount(source) -> ResolvedAnswer:
    """Potency amount from a governed IID precedent record."""
    if source is None:
        return ResolvedAnswer(
            status=STATUS_SOURCE_UNAVAILABLE,
            failure_detail="No governed IID precedent record was selected.",
        )
    rendered = _decimal_string(getattr(source, "potency_amount", None))
    if rendered is None:
        return ResolvedAnswer(
            status=STATUS_VALUE_UNAVAILABLE,
            source_kind=SOURCE_KIND_IID_PRECEDENT,
            source_public_id=str(source.public_id),
            source_version=_release_version(source),
            source_field="potency_amount",
            failure_detail="The precedent record holds no usable potency amount.",
        )
    return ResolvedAnswer(
        status=STATUS_RESOLVED,
        value={"value": rendered},
        source_kind=SOURCE_KIND_IID_PRECEDENT,
        source_public_id=str(source.public_id),
        source_version=_release_version(source),
        source_field="potency_amount",
    )


def _resolve_iid_maximum_daily_exposure(source) -> ResolvedAnswer:
    """Maximum daily exposure from a governed IID precedent record."""
    if source is None:
        return ResolvedAnswer(
            status=STATUS_SOURCE_UNAVAILABLE,
            failure_detail="No governed IID precedent record was selected.",
        )
    rendered = _decimal_string(getattr(source, "maximum_daily_exposure", None))
    if rendered is None:
        return ResolvedAnswer(
            status=STATUS_VALUE_UNAVAILABLE,
            source_kind=SOURCE_KIND_IID_PRECEDENT,
            source_public_id=str(source.public_id),
            source_version=_release_version(source),
            source_field="maximum_daily_exposure",
            failure_detail="The precedent record holds no usable maximum daily exposure.",
        )
    return ResolvedAnswer(
        status=STATUS_RESOLVED,
        value={"value": rendered},
        source_kind=SOURCE_KIND_IID_PRECEDENT,
        source_public_id=str(source.public_id),
        source_version=_release_version(source),
        source_field="maximum_daily_exposure",
    )


def _resolve_iid_route(source) -> ResolvedAnswer:
    """The raw route string as published in the governed IID release."""
    if source is None:
        return ResolvedAnswer(
            status=STATUS_SOURCE_UNAVAILABLE,
            failure_detail="No governed IID precedent record was selected.",
        )
    raw = getattr(source, "route_raw", "") or ""
    if not raw.strip():
        return ResolvedAnswer(
            status=STATUS_VALUE_UNAVAILABLE,
            source_kind=SOURCE_KIND_IID_PRECEDENT,
            source_public_id=str(source.public_id),
            source_version=_release_version(source),
            source_field="route_raw",
            failure_detail="The precedent record holds no route value.",
        )
    return ResolvedAnswer(
        status=STATUS_RESOLVED,
        value={"value": raw},
        source_kind=SOURCE_KIND_IID_PRECEDENT,
        source_public_id=str(source.public_id),
        source_version=_release_version(source),
        source_field="route_raw",
    )


def _release_version(precedent) -> str:
    """The governed identity of the release a precedent row came from.

    Both the release UUID and its checksum are part of what makes an execution
    reproducible: the UUID says which release, the checksum says which exact
    bytes of it. A release identifier alone would not detect a re-ingested file.
    """
    release = getattr(precedent, "release", None)
    if release is None:
        return ""
    return f"{release.public_id}:{release.source_checksum_sha256}"


@dataclass(frozen=True, slots=True)
class ResolverEntry:
    """One approved binding identifier."""

    function: object
    resolver_version: str
    source_kind: str
    description: str


#: The complete allow-list. Immutable at import; adding an entry is a code
#: change that goes through review, never configuration and never client input.
#:
#: These three are **synthetic infrastructure bindings**, present so the
#: mechanism is real, exercised and testable. They assert nothing about which
#: FDA field answers which regulatory question -- that mapping is content the
#: regulatory authority approves through the 5A package (register item 12).
ANSWER_SOURCE_REGISTRY: MappingProxyType[str, ResolverEntry] = MappingProxyType(
    {
        "iid.potency_amount": ResolverEntry(
            function=_resolve_iid_potency_amount,
            resolver_version="1.0.0",
            source_kind=SOURCE_KIND_IID_PRECEDENT,
            description="Potency amount as published in the governed IID release.",
        ),
        "iid.maximum_daily_exposure": ResolverEntry(
            function=_resolve_iid_maximum_daily_exposure,
            resolver_version="1.0.0",
            source_kind=SOURCE_KIND_IID_PRECEDENT,
            description="Maximum daily exposure as published in the governed IID release.",
        ),
        "iid.route": ResolverEntry(
            function=_resolve_iid_route,
            resolver_version="1.0.0",
            source_kind=SOURCE_KIND_IID_PRECEDENT,
            description="Route string as published in the governed IID release.",
        ),
    }
)


def is_known_resolver(identifier: str) -> bool:
    """Allow-list membership. The single authority; never re-implemented."""
    return identifier in ANSWER_SOURCE_REGISTRY


def get_resolver(identifier: str) -> ResolverEntry | None:
    return ANSWER_SOURCE_REGISTRY.get(identifier)


def resolve(identifier: str, source) -> tuple[ResolvedAnswer, str]:
    """Resolve one binding. Returns ``(outcome, resolver_version)``.

    An unknown identifier is a refusal, not an exception: it is reported as a
    governed ``unknown_resolver`` outcome so the response records *why* it has
    no value, rather than the whole execution failing to be created. Authoring
    validation already rejects unknown identifiers, so reaching this branch
    means content changed underneath a stored binding -- exactly the case where
    a silent empty answer would be dangerous.
    """
    entry = get_resolver(identifier)
    if entry is None:
        return (
            ResolvedAnswer(
                status=STATUS_UNKNOWN_RESOLVER,
                failure_detail=f"{identifier!r} is not an approved resolver identifier.",
            ),
            "",
        )
    outcome = entry.function(source)
    return outcome, entry.resolver_version


def _validate_registry() -> None:
    """Import-time invariants -- the registry is wrong loudly, or not at all."""
    for identifier, entry in ANSWER_SOURCE_REGISTRY.items():
        if not identifier or not isinstance(identifier, str):
            raise RuntimeError(f"Invalid resolver identifier: {identifier!r}")
        if entry.source_kind not in ALLOWED_SOURCE_KINDS:
            raise RuntimeError(
                f"{identifier}: unknown source_kind {entry.source_kind!r}"
            )
        if not callable(entry.function):
            raise RuntimeError(f"{identifier}: resolver is not callable")


_validate_registry()
