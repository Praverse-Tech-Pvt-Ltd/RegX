"""`5A-DEC-002` -- governed select-option value/label semantics.

Before 5A, a `single_select` / `multi_select` question carried its closed
vocabulary as a bare list of code strings in `validation_rule["options"]`, and
there was **no place at all** to record what a code means to a human. A reviewer
answering a regulated question would have been shown `EXCIPIENT_FN_3` rather
than the approved wording for it.

5A-DEC-002 forbids all three of the shortcuts that would otherwise be reached
for: displaying the raw code, folding the option wording into the question
prose, and deriving a label in the frontend by prettifying the code. So the
label becomes explicit, approved, governed content that travels with the option.

**Two accepted shapes, one governed form.**

    legacy    ["CODE_A", "CODE_B"]
    governed  [{"value": "CODE_A", "label": "…"}, {"value": "CODE_B", "label": "…"}]

The legacy shape is still parsed because pre-5A synthetic fixtures use it and a
data migration cannot invent the labels it never had -- inventing them here is
exactly the failure the content gate exists to prevent. Legacy options therefore
parse with ``label = None``, which is an honest "no approved label exists", not
an empty string pretending to be one. Production content must use the governed
shape; that is enforced by the content package, and by
:func:`requires_governed_options` for any caller that needs to assert it.

The stored **response** contract is untouched: a response still stores the
stable machine value (`{"option": "CODE_A"}` / `{"options": [...]}`). Labels are
presentation and export-interpretation only, never the stored answer -- so
re-labelling an option later can never silently change what was answered.
"""

from __future__ import annotations

from dataclasses import dataclass

from .execution_constants import MAX_SELECT_OPTIONS

#: The exact key set a governed option object may carry. Closed, like every
#: other governed payload shape in this app: an unexpected key is a rejection,
#: not something to ignore, because a silently-dropped key is how an approved
#: attribute goes missing without anyone noticing.
_GOVERNED_OPTION_KEYS = frozenset({"value", "label"})

#: Bounded for the same reason the response side is: a label is regulated
#: content shown to a reviewer, not a free-form note.
MAX_OPTION_LABEL_CHARS = 200


class OptionConfigurationError(Exception):
    """A question's authored option list is structurally invalid.

    Raised at authoring time (`ChecklistQuestion.clean()`), never at answer
    time: a malformed vocabulary is a content defect, and every answer against
    it would otherwise fail with a message pointing at the answer instead.
    """

    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code


@dataclass(frozen=True, slots=True)
class QuestionOption:
    """One governed option. ``label`` is ``None`` only for legacy content."""

    value: str
    label: str | None

    @property
    def display_label(self) -> str:
        """What a UI should show.

        Falls back to the machine value **only** for legacy unlabelled content,
        where there is nothing else in existence to show. This is not a
        licence to ship production content without labels: 5A-DEC-002 requires
        the governed shape, and `requires_governed_options()` is what enforces
        it where that assertion belongs.
        """
        return self.label if self.label else self.value


def parse_options(validation_rule) -> tuple[QuestionOption, ...] | None:
    """Parse a question's authored option list.

    Returns ``None`` when the question declares no closed vocabulary at all --
    which is different from declaring an empty one, and is why the caller gets
    ``None`` rather than ``()``. Structural validation lives in
    :func:`validate_options`; this function is the reader and assumes it ran.

    **Authored order is preserved.** It is the approved display order, and
    sorting it here would silently reorder a reviewer's choices. (The separate
    rule that a *multi_select response* must be sorted ascending is about the
    stored answer, not the vocabulary, and is untouched.)
    """
    if not isinstance(validation_rule, dict):
        return None
    raw = validation_rule.get("options")
    if not isinstance(raw, list):
        return None

    parsed: list[QuestionOption] = []
    for entry in raw:
        if isinstance(entry, str):
            parsed.append(QuestionOption(value=entry, label=None))
        elif isinstance(entry, dict):
            value = entry.get("value")
            label = entry.get("label")
            parsed.append(
                QuestionOption(
                    value=value if isinstance(value, str) else "",
                    label=label if isinstance(label, str) and label else None,
                )
            )
        else:
            # Unparseable entry -- surfaced by validate_options(), not silently
            # dropped here, because dropping it would shrink the vocabulary.
            parsed.append(QuestionOption(value="", label=None))
    return tuple(parsed)


def option_values(validation_rule) -> set[str] | None:
    """The set of valid machine values, or ``None`` if no closed list exists.

    This is the answer-time authority and is deliberately label-blind: what a
    response is checked against is the stable value, never the wording.
    """
    parsed = parse_options(validation_rule)
    if parsed is None:
        return None
    return {option.value for option in parsed}


def labels_for(validation_rule, values) -> dict[str, str]:
    """Map selected machine values to their display labels.

    Values with no matching option map to themselves rather than disappearing:
    an answer recorded against a vocabulary that later changed must still be
    readable, and dropping it would make a regulated answer invisible.
    """
    parsed = parse_options(validation_rule) or ()
    by_value = {option.value: option.display_label for option in parsed}
    return {value: by_value.get(value, value) for value in values}


def validate_options(validation_rule) -> None:
    """Structural validation of an authored option list. Raises on any defect.

    Silent on a question that declares no options: not every select question is
    obliged to carry a closed vocabulary, and that decision is made elsewhere.
    """
    if not isinstance(validation_rule, dict):
        return
    raw = validation_rule.get("options")
    if raw is None:
        return
    if not isinstance(raw, list):
        raise OptionConfigurationError(
            "OPTIONS_NOT_A_LIST", "validation_rule['options'] must be a list."
        )
    if not raw:
        raise OptionConfigurationError(
            "OPTIONS_EMPTY",
            "validation_rule['options'] must not be an empty list; omit the key instead.",
        )
    if len(raw) > MAX_SELECT_OPTIONS:
        raise OptionConfigurationError(
            "OPTIONS_TOO_MANY",
            f"A question may declare at most {MAX_SELECT_OPTIONS} options.",
        )

    seen: set[str] = set()
    for entry in raw:
        if isinstance(entry, str):
            value, label = entry, None
        elif isinstance(entry, dict):
            unknown = set(entry) - _GOVERNED_OPTION_KEYS
            if unknown:
                raise OptionConfigurationError(
                    "OPTION_UNKNOWN_KEY",
                    f"Option carries unsupported keys: {sorted(unknown)}.",
                )
            value = entry.get("value")
            label = entry.get("label")
            if not isinstance(value, str) or not value.strip():
                raise OptionConfigurationError(
                    "OPTION_VALUE_EMPTY", "Each option requires a non-empty 'value'."
                )
            if not isinstance(label, str) or not label.strip():
                # 5A-DEC-002: the governed shape exists to carry a label. An
                # object option without one is a half-migrated option, which is
                # worse than the legacy form because it looks governed.
                raise OptionConfigurationError(
                    "OPTION_LABEL_EMPTY", "Each governed option requires a non-empty 'label'."
                )
            if len(label) > MAX_OPTION_LABEL_CHARS:
                raise OptionConfigurationError(
                    "OPTION_LABEL_TOO_LONG",
                    f"An option label may be at most {MAX_OPTION_LABEL_CHARS} characters.",
                )
        else:
            raise OptionConfigurationError(
                "OPTION_INVALID_SHAPE",
                "Each option must be a string (legacy) or a {'value','label'} object.",
            )

        if not isinstance(value, str) or not value.strip():
            raise OptionConfigurationError(
                "OPTION_VALUE_EMPTY", "Each option requires a non-empty 'value'."
            )
        if value in seen:
            # Duplicate values make a stored answer ambiguous about which option
            # was chosen, so this is refused rather than de-duplicated.
            raise OptionConfigurationError(
                "OPTION_VALUE_DUPLICATE", f"Duplicate option value: {value!r}."
            )
        seen.add(value)


def requires_governed_options(validation_rule) -> bool:
    """True when every declared option carries an explicit approved label.

    The assertion production content must satisfy under 5A-DEC-002. Kept as a
    query rather than folded into `validate_options()` so that pre-5A synthetic
    fixtures keep loading while production content can still be held to the
    governed shape.
    """
    parsed = parse_options(validation_rule)
    if not parsed:
        return False
    return all(option.label for option in parsed)
