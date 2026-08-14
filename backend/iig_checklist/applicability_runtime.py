"""`5A-DEC-004` -- governed runtime applicability evaluation and persistence.

4D-1 gave applicability rules a validator; nothing ever evaluated them. A
question governed by an approved rule was therefore presented as applicable to
every product, whatever the rule said. 5A-DEC-004 makes that insufficient for
production, and this module is the governed writer that closes it.

Three responsibilities, deliberately separated:

* **context assembly** (M4D3-APP-006/007) -- read the six registry-version-1
  fields into an in-memory dict, once per pass, never persisted;
* **evaluation** -- delegated wholly to the pure evaluator in
  ``applicability.py``; no branching logic is reimplemented here;
* **persistence** (M4D3-PST-002..006) -- write the outcome onto the response
  through the single governed writer, honouring the APP-009 ownership boundary.

**APP-009 is preserved exactly.** ``is_not_applicable`` and
``not_applicable_reason`` remain server-owned for a rule-governed response, and
the client-facing update service still refuses to write either. This module is
the *only* writer of the ``REVIEW_REQUIRED:`` marker, which is why the reserved
prefix is refused on every client path (M4D3-APP-011).

**No live recomputation after review starts.** PST-007/008: applicability is
computed for `draft` and `returned` executions only. Once an execution is
submitted, the persisted state is authoritative and is never recomputed from
live product or FDA data -- otherwise a source change years later would silently
rewrite what an approved execution asserted.
"""

from __future__ import annotations

from dataclasses import dataclass

from .applicability import ApplicabilityEvaluationError, evaluate_applicability
from .enums import ApplicabilityOutcome, ExecutionStatus
from .field_registry import FIELD_REGISTRY_VERSION
from .governed_vocabularies import RESERVED_REASON_PREFIX

#: PST-007 -- the only statuses in which applicability may be (re)computed.
RECOMPUTABLE_EXECUTION_STATUSES = frozenset({ExecutionStatus.DRAFT, ExecutionStatus.RETURNED})

#: The six field names of registry version 1, split by the source that owns
#: them. Kept as data rather than inline lookups so that "which source feeds
#: which field" is auditable in one place.
_PRODUCT_FIELDS = ("product.route", "product.dosage_form", "product.release_type")
_IID_FIELDS = ("iid.match_status", "iid.has_mde", "iid.has_potency")

#: Governed reason code used when a rule cannot be evaluated because its source
#: group is not resolvable for this execution. Uppercase, colon-free and
#: `REVIEW_REQUIRED`-free, matching the M4D3-RFV-001 reason-code grammar.
UNRESOLVED_SOURCE_REASON_CODE = "APPLICABILITY_SOURCE_UNRESOLVED"

#: Governed reason code for a rule whose stored condition tree the evaluator
#: refuses. Reachable only for content that bypassed `validate_condition_json()`
#: -- but reachable, so it needs a governed outcome rather than an exception.
MALFORMED_RULE_REASON_CODE = "APPLICABILITY_RULE_MALFORMED"


@dataclass(frozen=True, slots=True)
class ApplicabilityContext:
    """One assembled evaluation context plus what could not be resolved.

    ``unresolved_groups`` is what makes fail-closed possible: a rule that reads
    a field group we could not resolve must not quietly take its false branch,
    because "we could not find out" is not the same answer as "no".
    """

    values: dict
    unresolved_groups: frozenset[str]
    field_registry_version: int = FIELD_REGISTRY_VERSION


def _product_record(execution):
    """The ProductDevelopmentRecord behind an execution, or None."""
    formulation_version = getattr(execution, "formulation_version", None)
    return getattr(formulation_version, "product", None)


def build_context(execution) -> ApplicabilityContext:
    """M4D3-APP-006/007 -- assemble exactly the six registry-version-1 fields.

    In-memory only, assembled once per governed pass and never persisted: a
    stored context would become a second, silently-diverging copy of product
    state.

    ``product.*`` resolves from the execution's own
    ``FormulationVersion -> ProductDevelopmentRecord``, which is already
    tenant-scoped by the execution, so no cross-tenant read is possible here.

    ``iid.*`` is **deliberately left unresolved.** Those three fields describe a
    *matched IID precedent*, and an ``AssessmentSnapshot`` is scoped to one
    formulation **component**, while applicability is a property of the
    execution. Which component's snapshot governs an execution-level rule -- or
    whether one must be created during an applicability pass at all -- is not
    settled by any approved specification, and choosing one here would be
    engineering inventing regulatory meaning. It is registered as an open
    governance question (5A-P1 OQ-8); until it is answered, a rule that reads
    these fields fails closed to ``review_required`` rather than guessing.
    """
    values: dict = {}
    product = _product_record(execution)
    if product is not None:
        # Blank is treated as absent, per APP-005: an unset route is not the
        # empty-string route, and matching a rule against "" would be a false
        # positive on real data.
        if product.route:
            values["product.route"] = product.route
        if product.dosage_form:
            values["product.dosage_form"] = product.dosage_form
        if product.release_type:
            values["product.release_type"] = product.release_type

    # `iid` is always unresolved today -- see the docstring and 5A-P1 OQ-8.
    unresolved = {"iid"}
    if product is None:
        unresolved.add("product")
    return ApplicabilityContext(values=values, unresolved_groups=frozenset(unresolved))


def referenced_field_groups(condition_json) -> frozenset[str]:
    """The source groups a rule reads (``product`` / ``iid``).

    Walks the same two node shapes the validator accepts. A malformed node is
    ignored rather than raised on: this is a pre-flight question about which
    sources a rule needs, and the evaluator is what refuses malformed trees.
    """
    groups: set[str] = set()

    def _walk(node, depth: int) -> None:
        if depth > 16 or not isinstance(node, dict):
            return
        if "operator" in node and "conditions" in node:
            children = node.get("conditions")
            if isinstance(children, list):
                for child in children:
                    _walk(child, depth + 1)
            return
        field = node.get("field")
        if isinstance(field, str) and "." in field:
            groups.add(field.split(".", 1)[0])

    _walk(condition_json, 1)
    return frozenset(groups)


def outcome_for_rule(rule, context: ApplicabilityContext) -> str:
    """The governed outcome for one rule, failing closed on unresolved sources.

    A rule whose source group could not be assembled returns
    ``review_required`` rather than its false branch. That is the conservative
    reading and the one 5A-DEC-004 asks for: an unanswerable rule becomes a
    human decision, never an automatic "this question does not apply".
    """
    needed = referenced_field_groups(rule.condition_json)
    if needed & context.unresolved_groups:
        return ApplicabilityOutcome.REVIEW_REQUIRED
    try:
        return evaluate_applicability(rule, context.values)
    except ApplicabilityEvaluationError:
        # A stored tree the evaluator refuses is a content defect: it can only
        # exist if `validate_condition_json()` was bypassed. It is contained
        # here rather than propagated, because one malformed rule must not make
        # an entire execution uncreatable -- but it fails **closed**, to
        # `review_required`, so the question is never silently treated as
        # applicable or as not applicable on the strength of a rule nobody can
        # evaluate. The evaluator itself still raises (M4D3-APP-003); this is
        # the governed service deciding what to do about that.
        return ApplicabilityOutcome.REVIEW_REQUIRED


def _review_reason_code(rule, context: ApplicabilityContext) -> str:
    """Which governed reason code a REVIEW_REQUIRED marker should carry.

    The rule's own ``reason_code`` is used when the rule genuinely evaluated to
    its review branch -- that is the author's approved explanation. When review
    was forced by something the rule did not ask for (an unresolvable source, or
    a tree the evaluator refuses), a dedicated code is used instead, because
    attributing an engineering-side failure to the author's reason text would
    misdescribe why a human is being asked to look.
    """
    if referenced_field_groups(rule.condition_json) & context.unresolved_groups:
        return UNRESOLVED_SOURCE_REASON_CODE
    try:
        evaluate_applicability(rule, context.values)
    except ApplicabilityEvaluationError:
        return MALFORMED_RULE_REASON_CODE
    return rule.reason_code or UNRESOLVED_SOURCE_REASON_CODE


def review_required_marker(reason_code: str) -> str:
    """M4D3-PST-002 -- the reserved persisted form of a REVIEW_REQUIRED outcome.

    ``REVIEW_REQUIRED:<reason_code>``, with ``is_not_applicable`` staying false
    and ``raw_value`` untouched: the question still needs answering, it just
    needs a human to decide whether it applies first.
    """
    return f"{RESERVED_REASON_PREFIX}{reason_code}"


def derive_applicability_outcome(response) -> str:
    """M4D3-PST-009 -- the read-only outcome derived from persisted state only.

    Never recomputed from live data, so a historical execution keeps reporting
    what it was assessed against. The order matters: ``not_applicable`` is
    checked first because a response that is N/A cannot simultaneously be
    awaiting a review decision.
    """
    if response.is_not_applicable:
        return ApplicabilityOutcome.NOT_APPLICABLE
    reason = response.not_applicable_reason or ""
    if reason.startswith(RESERVED_REASON_PREFIX):
        return ApplicabilityOutcome.REVIEW_REQUIRED
    if response.question.applicability_rule_id:
        return ApplicabilityOutcome.APPLICABLE
    return "no_rule"


def evaluate_execution_applicability(*, execution, actor=None) -> dict:
    """Evaluate and persist applicability for every rule-governed response.

    Returns ``{response_public_id: outcome}`` for the responses this pass
    actually changed, so a caller can audit the delta rather than re-deriving it.

    Governed constraints honoured here:

    * PST-007/008 -- runs only for `draft` / `returned` executions; any other
      status returns ``{}`` without touching a row, so a submitted or approved
      execution can never be silently re-assessed.
    * M4D3-APP-012 -- a user-declared N/A on a **non**-rule-governed response is
      never overwritten; this pass only ever writes rule-governed responses.
    * M4D3-PST-005 -- ``full_clean()`` before every save.
    * The context is assembled once for the whole pass (APP-007), so every
      question in one execution is assessed against exactly the same product
      state -- assembling per response could otherwise straddle a concurrent
      product edit and produce a self-inconsistent execution.
    """
    del actor  # evaluation is actor-independent; provenance is the caller's

    if execution.status not in RECOMPUTABLE_EXECUTION_STATUSES:
        return {}

    from .models import ChecklistResponse

    context = build_context(execution)
    changed: dict[str, str] = {}

    responses = (
        ChecklistResponse.objects.filter(execution=execution)
        .select_related("question", "question__applicability_rule")
        .order_by("question__display_order", "question__code", "public_id")
    )

    for response in responses:
        rule = response.question.applicability_rule
        if rule is None:
            continue

        outcome = outcome_for_rule(rule, context)

        if outcome == ApplicabilityOutcome.NOT_APPLICABLE:
            new_flag, new_reason = True, rule.reason_code
        elif outcome == ApplicabilityOutcome.REVIEW_REQUIRED:
            new_flag, new_reason = False, review_required_marker(_review_reason_code(rule, context))
        else:
            new_flag, new_reason = False, None

        if (
            response.is_not_applicable == new_flag
            and (response.not_applicable_reason or None) == new_reason
        ):
            continue

        response.is_not_applicable = new_flag
        response.not_applicable_reason = new_reason
        response.full_clean()
        response.save(update_fields=["is_not_applicable", "not_applicable_reason"])
        changed[str(response.public_id)] = str(outcome)

    return changed
