"""Milestone 5A-P1 -- the four production content-engine prerequisites.

5A discovery found that a regulatory authority would have been asked to approve
content against capabilities that did not exist: FDA-derived bindings that were
inert, applicability rules that were never evaluated, select options with no
labels, and no structured jurisdiction at all. These pin the closed behaviour.

Every fixture here is synthetic. No production regulatory question, option
label, jurisdiction claim or FDA mapping is authored -- the content gate remains
at 0 of 20, and these tests would be equally valid if it never moved.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError

from iig_checklist.enums import (
    AnswerType,
    ApplicabilityOutcome,
    ApplicabilityRuleStatus,
    DataSourceClassification,
    Jurisdiction,
)

#: Fixed so a checksum comparison isolates the field under test rather
#: than drifting with the clock.
_FIXED_TIME = datetime(2026, 8, 13, 12, 0, 0, tzinfo=UTC)

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _product(tenant, user, code="PROD-5AP1-01", route="oral", dosage_form="tablet"):
    from formulations.models import ProductDevelopmentRecord

    return ProductDevelopmentRecord.objects.create(
        tenant=tenant,
        product_code=code,
        proposed_product_name=f"Product {code}",
        active_ingredient="Synthetic 5A-P1 Ingredient",
        dosage_form=dosage_form,
        route=route,
        created_by=user,
    )


def _formulation(product, user):
    from formulations.models import FormulationVersion

    fv = FormulationVersion(
        product=product,
        version_number=1,
        status="approved",
        total_dosage_unit_weight="100.000000",
        total_dosage_unit_weight_unit="mg",
        created_by=user,
    )
    fv.save()
    return fv


def _version(definition, user, status="active", **kwargs):
    from iig_checklist.models import ChecklistVersion

    # version_number is popped rather than hard-coded so a caller can create
    # several versions of one definition; unique_version_number_per_definition
    # otherwise rejects the second.
    version_number = kwargs.pop("version_number", 1)
    return ChecklistVersion.objects.create(
        definition=definition,
        version_number=version_number,
        status=status,
        created_by=user,
        **kwargs,
    )


def _section(version, code="SEC-1"):
    from iig_checklist.models import ChecklistSection

    return ChecklistSection.objects.create(
        checklist_version=version, code=code, title="Section", display_order=1, criticality="low"
    )


def _rule(version, user, condition_json, *, code="RULE-5AP1", **kwargs):
    from iig_checklist.models import ApplicabilityRule

    defaults = {
        "outcome_if_true": kwargs.pop("t", ApplicabilityOutcome.NOT_APPLICABLE),
        "outcome_if_false": kwargs.pop("f", ApplicabilityOutcome.APPLICABLE),
        "reason_code": "NOT_APPLICABLE_BY_RULE",
    }
    defaults.update(kwargs)
    return ApplicabilityRule.objects.create(
        checklist_version=version,
        code=code,
        rule_version=1,
        condition_json=condition_json,
        explanation_template="Synthetic rule.",
        field_registry_version=1,
        status=ApplicabilityRuleStatus.APPROVED,
        created_by=user,
        **defaults,
    )


def _question(section, code, **kwargs):
    from iig_checklist.models import ChecklistQuestion

    defaults = {
        "question_text": f"Synthetic question {code}",
        "display_order": kwargs.pop("display_order", 1),
        "answer_type": AnswerType.SHORT_TEXT,
        "data_source_classification": DataSourceClassification.USER_REQUIRED,
        "criticality": "low",
    }
    defaults.update(kwargs)
    return ChecklistQuestion.objects.create(section=section, code=code, **defaults)


def _subject_component(formulation_version, name="SYNTHETIC-EXCIPIENT"):
    """One inactive component to act as the execution's governed OQ-8 subject."""
    from formulations.models import FormulationComponent

    component = FormulationComponent(
        formulation_version=formulation_version,
        component_type="inactive",
        ingredient_name=name,
        quantity_per_dosage_unit="10.000000",
        quantity_unit="milligram",
        display_order=1,
    )
    component.full_clean()
    component.save()
    return component


def _execute(tenant, version, user, *, with_subject_component=False):
    from iig_checklist.services import create_execution

    product = _product(tenant, user, code=f"PROD-{version.public_id.hex[:8]}")
    fv = _formulation(product, user)
    subject = _subject_component(fv) if with_subject_component else None
    return create_execution(
        tenant=tenant,
        checklist_version_public_id=str(version.public_id),
        formulation_version_public_id=str(fv.public_id),
        subject_component_public_id=(str(subject.public_id) if subject else None),
        actor=user,
    )


def _assert_no_dynamic_dispatch(module) -> None:
    """No `eval`/`exec`/dynamic import, and no `getattr` on a computed name.

    Structural, via the AST, because the distinction that matters is not
    whether the characters "getattr(" appear but whether the attribute being
    read is a literal the author wrote or a value that arrived from data.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(module))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        assert name not in {"eval", "exec", "compile", "__import__"}, (
            f"{module.__name__} calls {name}()"
        )
        if name == "getattr":
            assert node.args and isinstance(node.args[1], ast.Constant), (
                f"{module.__name__} calls getattr() with a computed attribute name"
            )
        if name == "import_module":
            raise AssertionError(f"{module.__name__} imports dynamically")


# ===========================================================================
# A. Jurisdiction -- 5A-DEC-005
# ===========================================================================


class TestJurisdiction:
    def test_vocabulary_is_exactly_us_fda(self):
        # 5A-DEC-005 authorises one jurisdiction. A member added without a
        # governed decision is exactly what this refuses to let pass silently.
        assert [choice[0] for choice in Jurisdiction.choices] == ["US_FDA"]

    def test_a_version_may_declare_the_governed_jurisdiction(self, db, tenant_definition, user_a):
        version = _version(tenant_definition, user_a, status="draft")
        version.jurisdiction = Jurisdiction.US_FDA
        version.full_clean()
        version.save()
        version.refresh_from_db()
        assert version.jurisdiction == "US_FDA"

    def test_free_text_is_refused(self, db, tenant_definition, user_a):
        version = _version(tenant_definition, user_a, status="draft")
        version.jurisdiction = "EU EMA, probably"
        with pytest.raises(DjangoValidationError):
            version.full_clean()

    def test_blank_means_not_stated_and_is_permitted(self, db, tenant_definition, user_a):
        # Pre-5A content has no jurisdiction and must stay usable; "not stated"
        # is a fact, not an error, and must never be read as US_FDA.
        version = _version(tenant_definition, user_a, status="draft")
        version.full_clean()
        assert version.jurisdiction == ""

    def test_it_is_frozen_once_the_version_leaves_draft(self, db, tenant_definition, user_a):
        version = _version(tenant_definition, user_a, status="draft")
        version.jurisdiction = Jurisdiction.US_FDA
        version.full_clean()
        version.save()
        version.status = "approved"
        version.save(update_fields=["status"])

        version.jurisdiction = ""
        with pytest.raises(DjangoValidationError) as exc:
            version.full_clean()
        assert "jurisdiction" in str(exc.value)

    def test_historical_rows_are_not_backfilled(self, db, tenant_definition, user_a):
        # The migration adds a column and nothing else. A version created
        # without a jurisdiction keeps "" rather than acquiring a regulator.
        version = _version(tenant_definition, user_a)
        version.refresh_from_db()
        assert version.jurisdiction == ""


class TestJurisdictionReachesTheExport:
    def _approved_execution(self, tenant, definition, user, jurisdiction):
        version = _version(definition, user, status="draft", jurisdiction=jurisdiction)
        section = _section(version)
        _question(section, "Q-1")
        version.status = "active"
        version.save(update_fields=["status"])
        execution = _execute(tenant, version, user)
        execution.status = "approved"
        execution.save(update_fields=["status"])
        return execution

    def test_jurisdiction_is_in_the_hashed_payload(
        self, db, tenant_a, tenant_definition, user_a, doer_membership
    ):
        from iig_checklist.controlled_export import build_export_artifact

        execution = self._approved_execution(
            tenant_a, tenant_definition, user_a, Jurisdiction.US_FDA
        )
        artifact = build_export_artifact(execution=execution, generated_at=_FIXED_TIME)
        assert artifact["payload"]["checklist_definition"]["jurisdiction"] == "US_FDA"

    def test_dropping_jurisdiction_changes_the_checksum(
        self, db, tenant_a, tenant_definition, user_a, doer_membership
    ):
        # Mutation proof E in executable form: provenance that does not move the
        # checksum is provenance an artifact does not actually protect.
        from iig_checklist.controlled_export import build_export_artifact, checksum_for

        execution = self._approved_execution(
            tenant_a, tenant_definition, user_a, Jurisdiction.US_FDA
        )
        artifact = build_export_artifact(execution=execution, generated_at=_FIXED_TIME)
        with_jurisdiction = artifact["checksum"]["value"]

        stripped = artifact["payload"]
        del stripped["checklist_definition"]["jurisdiction"]
        assert checksum_for(stripped) != with_jurisdiction

    def test_not_stated_is_emitted_rather_than_omitted(
        self, db, tenant_a, tenant_definition, user_a, doer_membership
    ):
        from iig_checklist.controlled_export import build_export_artifact

        execution = self._approved_execution(tenant_a, tenant_definition, user_a, "")
        artifact = build_export_artifact(execution=execution, generated_at=_FIXED_TIME)
        block = artifact["payload"]["checklist_definition"]
        # Present and empty, never missing: an auditor must be able to tell
        # "no jurisdiction was stated" from "this export predates the field".
        assert "jurisdiction" in block
        assert block["jurisdiction"] == ""


# ===========================================================================
# B. Select option labels -- 5A-DEC-002
# ===========================================================================


class TestOptionParsing:
    def test_governed_shape_parses_value_and_label(self):
        from iig_checklist.question_options import parse_options

        parsed = parse_options(
            {"options": [{"value": "A", "label": "Alpha"}, {"value": "B", "label": "Beta"}]}
        )
        assert [(o.value, o.label) for o in parsed] == [("A", "Alpha"), ("B", "Beta")]

    def test_legacy_shape_parses_with_no_label(self):
        from iig_checklist.question_options import parse_options

        parsed = parse_options({"options": ["A", "B"]})
        assert [(o.value, o.label) for o in parsed] == [("A", None), ("B", None)]
        # An honest absence, not an empty string pretending to be a label.
        assert parsed[0].display_label == "A"

    def test_authored_order_is_preserved(self):
        from iig_checklist.question_options import parse_options

        parsed = parse_options(
            {"options": [{"value": "Z", "label": "Zed"}, {"value": "A", "label": "Ay"}]}
        )
        # Not sorted: authored order is the approved display order, and
        # reordering it would silently rearrange a reviewer's choices.
        assert [o.value for o in parsed] == ["Z", "A"]

    def test_no_options_declared_is_distinct_from_an_empty_list(self):
        from iig_checklist.question_options import parse_options

        assert parse_options({}) is None
        assert parse_options({"options": []}) == ()

    def test_requires_governed_options_distinguishes_the_two_shapes(self):
        from iig_checklist.question_options import requires_governed_options

        assert requires_governed_options({"options": [{"value": "A", "label": "Alpha"}]}) is True
        assert requires_governed_options({"options": ["A"]}) is False


class TestOptionValidation:
    @pytest.mark.parametrize(
        ("options", "code"),
        [
            ([{"value": "", "label": "Alpha"}], "OPTION_VALUE_EMPTY"),
            ([{"value": "   ", "label": "Alpha"}], "OPTION_VALUE_EMPTY"),
            ([{"value": "A", "label": ""}], "OPTION_LABEL_EMPTY"),
            ([{"value": "A", "label": "   "}], "OPTION_LABEL_EMPTY"),
            (
                [{"value": "A", "label": "Alpha"}, {"value": "A", "label": "Again"}],
                "OPTION_VALUE_DUPLICATE",
            ),
            ([{"value": "A", "label": "Alpha", "colour": "red"}], "OPTION_UNKNOWN_KEY"),
            ([123], "OPTION_INVALID_SHAPE"),
            ([], "OPTIONS_EMPTY"),
            ("not-a-list", "OPTIONS_NOT_A_LIST"),
        ],
    )
    def test_defects_are_refused_with_a_governed_code(self, options, code):
        from iig_checklist.question_options import OptionConfigurationError, validate_options

        with pytest.raises(OptionConfigurationError) as exc:
            validate_options({"options": options})
        assert exc.value.error_code == code

    def test_over_long_label_is_refused(self):
        from iig_checklist.question_options import (
            MAX_OPTION_LABEL_CHARS,
            OptionConfigurationError,
            validate_options,
        )

        too_long = "x" * (MAX_OPTION_LABEL_CHARS + 1)
        with pytest.raises(OptionConfigurationError) as exc:
            validate_options({"options": [{"value": "A", "label": too_long}]})
        assert exc.value.error_code == "OPTION_LABEL_TOO_LONG"
        # The boundary itself is valid.
        validate_options({"options": [{"value": "A", "label": "x" * MAX_OPTION_LABEL_CHARS}]})

    def test_a_question_with_a_defective_vocabulary_cannot_be_authored(
        self, db, tenant_definition, user_a
    ):
        # Refused at authoring time -- a content defect must not be reported
        # later as though the reviewer's answer were the problem.
        version = _version(tenant_definition, user_a, status="draft")
        section = _section(version)
        from iig_checklist.models import ChecklistQuestion

        question = ChecklistQuestion(
            section=section,
            code="Q-BAD-OPTS",
            question_text="Synthetic",
            display_order=1,
            answer_type=AnswerType.SINGLE_SELECT,
            data_source_classification=DataSourceClassification.USER_REQUIRED,
            criticality="low",
            validation_rule={"options": [{"value": "A", "label": ""}]},
        )
        with pytest.raises(DjangoValidationError) as exc:
            question.full_clean()
        assert "OPTION_LABEL_EMPTY" in str(exc.value)


class TestOptionsAtAnswerTime:
    def test_answer_validation_is_label_blind(self):
        # A response is checked against the stable value. Re-labelling an option
        # must never invalidate an answer already recorded against it.
        from iig_checklist.response_validation import validate_raw_value_shape

        class _Q:
            answer_type = AnswerType.SINGLE_SELECT
            validation_rule = {"options": [{"value": "A", "label": "Alpha"}]}

        validate_raw_value_shape(AnswerType.SINGLE_SELECT, {"option": "A"}, question=_Q())

    def test_a_value_outside_the_vocabulary_is_still_refused(self):
        from iig_checklist.response_validation import (
            InvalidRawValueShape,
            validate_raw_value_shape,
        )

        class _Q:
            answer_type = AnswerType.SINGLE_SELECT
            validation_rule = {"options": [{"value": "A", "label": "Alpha"}]}

        with pytest.raises(InvalidRawValueShape):
            validate_raw_value_shape(AnswerType.SINGLE_SELECT, {"option": "B"}, question=_Q())

    def test_a_label_is_not_an_acceptable_answer(self):
        # Injection-adjacent: submitting the human label instead of the machine
        # value must fail, or the stored answer would stop being stable.
        from iig_checklist.response_validation import (
            InvalidRawValueShape,
            validate_raw_value_shape,
        )

        class _Q:
            answer_type = AnswerType.SINGLE_SELECT
            validation_rule = {"options": [{"value": "A", "label": "Alpha"}]}

        with pytest.raises(InvalidRawValueShape):
            validate_raw_value_shape(AnswerType.SINGLE_SELECT, {"option": "Alpha"}, question=_Q())

    def test_legacy_vocabulary_still_validates_answers(self):
        from iig_checklist.response_validation import validate_raw_value_shape

        class _Q:
            answer_type = AnswerType.SINGLE_SELECT
            validation_rule = {"options": ["A", "B"]}

        validate_raw_value_shape(AnswerType.SINGLE_SELECT, {"option": "A"}, question=_Q())


class TestOptionsOnTheApi:
    def test_resolved_options_are_exposed_and_read_only(self, db, tenant_definition, user_a):
        from iig_checklist.serializers import ChecklistQuestionSerializer

        version = _version(tenant_definition, user_a, status="draft")
        section = _section(version)
        question = _question(
            section,
            "Q-OPTS",
            answer_type=AnswerType.SINGLE_SELECT,
            validation_rule={"options": [{"value": "A", "label": "Alpha"}]},
        )
        data = ChecklistQuestionSerializer(question).data
        assert data["options"] == [{"value": "A", "label": "Alpha"}]
        assert "options" in ChecklistQuestionSerializer.Meta.read_only_fields

    def test_legacy_options_fall_back_to_the_value(self, db, tenant_definition, user_a):
        from iig_checklist.serializers import ChecklistQuestionSerializer

        version = _version(tenant_definition, user_a, status="draft")
        section = _section(version)
        question = _question(
            section,
            "Q-LEGACY",
            answer_type=AnswerType.SINGLE_SELECT,
            validation_rule={"options": ["A"]},
        )
        assert ChecklistQuestionSerializer(question).data["options"] == [
            {"value": "A", "label": "A"}
        ]

    def test_a_question_with_no_vocabulary_reports_none(self, db, tenant_definition, user_a):
        from iig_checklist.serializers import ChecklistQuestionSerializer

        version = _version(tenant_definition, user_a, status="draft")
        section = _section(version)
        question = _question(section, "Q-NONE")
        assert ChecklistQuestionSerializer(question).data["options"] is None


# ===========================================================================
# C. Applicability runtime -- 5A-DEC-004
# ===========================================================================


class TestEvaluatorSemantics:
    """M4D3-APP-002/004/005 -- the approved grammar, and nothing beyond it."""

    def _rule(self, condition, **kwargs):
        class _R:
            condition_json = condition
            outcome_if_true = kwargs.get("t", ApplicabilityOutcome.NOT_APPLICABLE)
            outcome_if_false = kwargs.get("f", ApplicabilityOutcome.APPLICABLE)

        return _R()

    @pytest.mark.parametrize(
        ("condition", "context", "expected"),
        [
            (
                {"field": "product.route", "op": "eq", "value": "oral"},
                {"product.route": "oral"},
                True,
            ),
            (
                {"field": "product.route", "op": "eq", "value": "oral"},
                {"product.route": "iv"},
                False,
            ),
            (
                {"field": "product.route", "op": "neq", "value": "oral"},
                {"product.route": "iv"},
                True,
            ),
            (
                {"field": "product.route", "op": "in", "value": ["oral", "iv"]},
                {"product.route": "iv"},
                True,
            ),
            (
                {"field": "product.route", "op": "not_in", "value": ["oral"]},
                {"product.route": "iv"},
                True,
            ),
            ({"field": "product.route", "op": "exists"}, {"product.route": "oral"}, True),
            ({"field": "product.route", "op": "exists"}, {}, False),
            ({"field": "product.route", "op": "not_exists"}, {}, True),
        ],
    )
    def test_leaf_operators(self, condition, context, expected):
        from iig_checklist.applicability import evaluate_condition

        assert evaluate_condition(condition, context) is expected

    def test_missing_field_is_false_for_comparisons(self):
        # M4D3-APP-005 -- absent is absent, not an error and not a match.
        from iig_checklist.applicability import evaluate_condition

        assert (
            evaluate_condition({"field": "product.route", "op": "eq", "value": "oral"}, {}) is False
        )

    def test_explicit_null_is_treated_as_absent(self):
        from iig_checklist.applicability import evaluate_condition

        assert (
            evaluate_condition({"field": "product.route", "op": "exists"}, {"product.route": None})
            is False
        )

    def test_booleans_and_integers_never_compare_equal(self):
        # Python says True == 1. Regulated branching must not turn on that.
        from iig_checklist.applicability import evaluate_condition

        assert (
            evaluate_condition(
                {"field": "iid.has_mde", "op": "eq", "value": 1}, {"iid.has_mde": True}
            )
            is False
        )
        assert (
            evaluate_condition(
                {"field": "iid.has_mde", "op": "eq", "value": True}, {"iid.has_mde": True}
            )
            is True
        )

    def test_composites(self):
        from iig_checklist.applicability import evaluate_condition

        tree = {
            "operator": "all",
            "conditions": [
                {"field": "product.route", "op": "eq", "value": "oral"},
                {"field": "product.dosage_form", "op": "eq", "value": "tablet"},
            ],
        }
        assert evaluate_condition(tree, {"product.route": "oral", "product.dosage_form": "tablet"})
        assert not evaluate_condition(tree, {"product.route": "oral"})
        any_tree = {"operator": "any", "conditions": tree["conditions"]}
        assert evaluate_condition(any_tree, {"product.route": "oral"})

    def test_outcome_comes_from_the_rule_not_the_evaluator(self):
        from iig_checklist.applicability import evaluate_applicability

        rule = self._rule(
            {"field": "product.route", "op": "eq", "value": "oral"},
            t=ApplicabilityOutcome.REVIEW_REQUIRED,
            f=ApplicabilityOutcome.NOT_APPLICABLE,
        )
        assert (
            evaluate_applicability(rule, {"product.route": "oral"})
            == ApplicabilityOutcome.REVIEW_REQUIRED
        )
        assert (
            evaluate_applicability(rule, {"product.route": "iv"})
            == ApplicabilityOutcome.NOT_APPLICABLE
        )

    @pytest.mark.parametrize(
        "node",
        [
            {"op": "always_true"},
            {"field": "product.route"},
            {"operator": "all"},
            {"operator": "all", "conditions": []},
            {"operator": "sometimes", "conditions": [{"field": "x", "op": "exists"}]},
            "not-a-node",
        ],
    )
    def test_malformed_nodes_raise_rather_than_defaulting(self, node):
        # M4D3-APP-003. Fail closed: a node the validator should have refused
        # must never quietly evaluate to True or False.
        from iig_checklist.applicability import (
            ApplicabilityEvaluationError,
            evaluate_condition,
        )

        with pytest.raises(ApplicabilityEvaluationError):
            evaluate_condition(node, {})

    def test_the_evaluator_executes_nothing(self):
        # No dynamic execution anywhere in the module that decides regulated
        # branching. Checked structurally rather than by substring: `getattr`
        # with a *literal* attribute name is ordinary attribute access, while
        # `getattr` with a variable is dispatch on data -- only the second is a
        # security concern, and a substring scan cannot tell them apart.
        from iig_checklist import applicability

        _assert_no_dynamic_dispatch(applicability)


class TestContextAssembly:
    def test_product_fields_come_from_the_execution(
        self, db, tenant_a, tenant_definition, user_a, doer_membership
    ):
        from iig_checklist.applicability_runtime import build_context

        version = _version(tenant_definition, user_a)
        _question(_section(version), "Q-1")
        execution = _execute(tenant_a, version, user_a)
        context = build_context(execution)
        assert context.values["product.route"] == "oral"
        assert context.values["product.dosage_form"] == "tablet"
        assert context.values["product.release_type"]

    def test_only_the_six_registry_fields_are_ever_assembled(
        self, db, tenant_a, tenant_definition, user_a, doer_membership
    ):
        from iig_checklist.applicability_runtime import build_context
        from iig_checklist.field_registry import allowed_fields_for_version

        version = _version(tenant_definition, user_a)
        _question(_section(version), "Q-1")
        execution = _execute(tenant_a, version, user_a)
        assert set(build_context(execution).values) <= allowed_fields_for_version(1)

    def test_iid_is_reported_unresolved_rather_than_guessed(
        self, db, tenant_a, tenant_definition, user_a, doer_membership
    ):
        # The snapshot-selection rule is a registered governance question
        # (5A-P1 OQ-8). Until it is answered the group is unresolved, which is
        # what makes the fail-closed path below correct rather than arbitrary.
        from iig_checklist.applicability_runtime import build_context

        version = _version(tenant_definition, user_a)
        _question(_section(version), "Q-1")
        execution = _execute(tenant_a, version, user_a)
        assert "iid" in build_context(execution).unresolved_groups

    def test_blank_product_values_are_absent_not_empty_string(
        self, db, tenant_a, tenant_definition, user_a, doer_membership
    ):
        from iig_checklist.applicability_runtime import build_context

        version = _version(tenant_definition, user_a)
        _question(_section(version), "Q-1")
        product = _product(tenant_a, user_a, code="PROD-BLANK", route="", dosage_form="")
        fv = _formulation(product, user_a)
        from iig_checklist.services import create_execution

        execution = create_execution(
            tenant=tenant_a,
            checklist_version_public_id=str(version.public_id),
            formulation_version_public_id=str(fv.public_id),
            actor=user_a,
        )
        values = build_context(execution).values
        assert "product.route" not in values
        assert "product.dosage_form" not in values


class TestApplicabilityIsActuallyEvaluated:
    def _world(self, tenant, definition, user, condition, **rule_kwargs):
        version = _version(definition, user, status="draft")
        section = _section(version)
        rule = _rule(version, user, condition, **rule_kwargs)
        question = _question(section, "Q-RULED", applicability_rule=rule)
        version.status = "active"
        version.save(update_fields=["status"])
        # A rule reading `iid.*` needs a governed subject component to be
        # executable at all now (OQ-8); supplying one for every case keeps the
        # helper uniform. No active FDA IID release exists in these tests, so an
        # `iid.*` rule still has no governed source and still fails closed --
        # which is exactly what the unresolved-source case asserts.
        needs_subject = "iid." in json.dumps(condition)
        execution = _execute(tenant, version, user, with_subject_component=needs_subject)
        from iig_checklist.models import ChecklistResponse

        return execution, ChecklistResponse.objects.get(execution=execution, question=question)

    def test_a_matching_rule_marks_the_response_not_applicable(
        self, db, tenant_a, tenant_definition, user_a, doer_membership
    ):
        # The whole point of 5A-DEC-004: before this, the rule was stored and
        # ignored, and the question was presented as applicable regardless.
        _, response = self._world(
            tenant_a,
            tenant_definition,
            user_a,
            {"field": "product.route", "op": "eq", "value": "oral"},
        )
        assert response.is_not_applicable is True
        assert response.not_applicable_reason == "NOT_APPLICABLE_BY_RULE"

    def test_a_non_matching_rule_leaves_the_response_applicable(
        self, db, tenant_a, tenant_definition, user_a, doer_membership
    ):
        _, response = self._world(
            tenant_a,
            tenant_definition,
            user_a,
            {"field": "product.route", "op": "eq", "value": "intravenous"},
        )
        assert response.is_not_applicable is False
        assert (response.not_applicable_reason or "") == ""

    def test_a_review_required_outcome_uses_the_reserved_marker(
        self, db, tenant_a, tenant_definition, user_a, doer_membership
    ):
        # M4D3-PST-002: is_not_applicable stays false and raw_value is untouched;
        # the question still needs answering, a human just decides whether it
        # applies first.
        _, response = self._world(
            tenant_a,
            tenant_definition,
            user_a,
            {"field": "product.route", "op": "eq", "value": "oral"},
            t=ApplicabilityOutcome.REVIEW_REQUIRED,
            reason_code="MANUAL_REVIEW_NEEDED",
        )
        assert response.is_not_applicable is False
        assert response.not_applicable_reason == "REVIEW_REQUIRED:MANUAL_REVIEW_NEEDED"
        assert response.raw_value is None

    def test_an_unresolvable_source_fails_closed_to_review(
        self, db, tenant_a, component_scoped_definition, user_a, doer_membership
    ):
        # "We could not find out" must not become "no". The rule's own false
        # branch would have said applicable; the unresolved source forces review.
        _, response = self._world(
            tenant_a,
            component_scoped_definition,
            user_a,
            {"field": "iid.has_mde", "op": "eq", "value": True},
        )
        assert response.is_not_applicable is False
        assert response.not_applicable_reason == "REVIEW_REQUIRED:APPLICABILITY_SOURCE_UNRESOLVED"

    def test_a_malformed_stored_rule_fails_closed_without_breaking_the_execution(
        self, db, tenant_a, tenant_definition, user_a, doer_membership
    ):
        # Reachable only if validation was bypassed -- but reachable. One bad
        # rule must not make the whole execution uncreatable, and must not be
        # silently treated as applicable either.
        _, response = self._world(tenant_a, tenant_definition, user_a, {"op": "always_true"})
        assert response.is_not_applicable is False
        assert response.not_applicable_reason == "REVIEW_REQUIRED:APPLICABILITY_RULE_MALFORMED"

    def test_an_ungoverned_question_is_untouched(
        self, db, tenant_a, tenant_definition, user_a, doer_membership
    ):
        # M4D3-APP-012 -- the pass only ever writes rule-governed responses.
        version = _version(tenant_definition, user_a, status="draft")
        section = _section(version)
        _question(section, "Q-FREE")
        version.status = "active"
        version.save(update_fields=["status"])
        execution = _execute(tenant_a, version, user_a)
        from iig_checklist.models import ChecklistResponse

        response = ChecklistResponse.objects.get(execution=execution)
        assert response.is_not_applicable is False
        assert response.not_applicable_reason is None

    def test_no_recomputation_once_the_execution_leaves_draft(
        self, db, tenant_a, tenant_definition, user_a, doer_membership
    ):
        # M4D3-PST-007/008 -- a submitted execution keeps the applicability it
        # was assessed under even if the product changes underneath it.
        from iig_checklist.applicability_runtime import evaluate_execution_applicability

        execution, response = self._world(
            tenant_a,
            tenant_definition,
            user_a,
            {"field": "product.route", "op": "eq", "value": "intravenous"},
        )
        execution.status = "submitted_for_review"
        execution.save(update_fields=["status"])
        product = execution.formulation_version.product
        product.route = "intravenous"
        product.save(update_fields=["route"])

        assert evaluate_execution_applicability(execution=execution) == {}
        response.refresh_from_db()
        assert response.is_not_applicable is False


class TestDerivedApplicabilityOutcome:
    """M4D3-PST-009 -- derived from persisted state, never recomputed."""

    def _response(self, flag, reason, has_rule=True):
        class _Q:
            applicability_rule_id = 1 if has_rule else None

        class _R:
            is_not_applicable = flag
            not_applicable_reason = reason
            question = _Q()

        return _R()

    @pytest.mark.parametrize(
        ("flag", "reason", "has_rule", "expected"),
        [
            (True, "NOT_APPLICABLE_BY_RULE", True, "not_applicable"),
            (False, "REVIEW_REQUIRED:X", True, "review_required"),
            (False, None, True, "applicable"),
            (False, None, False, "no_rule"),
        ],
    )
    def test_derivation(self, flag, reason, has_rule, expected):
        from iig_checklist.applicability_runtime import derive_applicability_outcome

        assert derive_applicability_outcome(self._response(flag, reason, has_rule)) == expected

    def test_never_reports_not_applicable_while_the_flag_is_false(self):
        # M4D3-PST-010 -- the combination must be unreachable by construction.
        from iig_checklist.applicability_runtime import derive_applicability_outcome

        for reason in (None, "", "REVIEW_REQUIRED:X", "anything"):
            assert derive_applicability_outcome(self._response(False, reason)) != "not_applicable"


# ===========================================================================
# D. FDA-derived resolvers -- 5A-DEC-001
# ===========================================================================


class TestResolverAllowList:
    def test_only_registered_identifiers_are_known(self):
        from iig_checklist.answer_sources import is_known_resolver

        assert is_known_resolver("iid.potency_amount") is True
        assert is_known_resolver("iid.definitely_not_real") is False

    @pytest.mark.parametrize(
        "hostile",
        [
            "os.system",
            "__import__",
            "builtins.eval",
            "iig_checklist.models.ChecklistResponse.objects.all",
            "../../etc/passwd",
            "",
        ],
    )
    def test_a_hostile_identifier_is_refused_not_dispatched(self, hostile):
        # The allow-list is the whole defence: an identifier is a key, never a
        # path to import or an attribute to look up.
        from iig_checklist.answer_sources import STATUS_UNKNOWN_RESOLVER, resolve

        outcome, version = resolve(hostile, None)
        assert outcome.status == STATUS_UNKNOWN_RESOLVER
        assert outcome.value is None
        assert version == ""

    def test_the_module_dispatches_nothing_dynamically(self):
        # The allow-list is only a defence if the identifier is a dictionary
        # key and never a name that gets imported or looked up.
        from iig_checklist import answer_sources

        _assert_no_dynamic_dispatch(answer_sources)

    def test_registry_is_immutable(self):
        from iig_checklist.answer_sources import ANSWER_SOURCE_REGISTRY

        with pytest.raises(TypeError):
            ANSWER_SOURCE_REGISTRY["injected"] = object()


class TestResolverBehaviour:
    class _Release:
        public_id = "11111111-1111-1111-1111-111111111111"
        source_checksum_sha256 = "abc123"

    class _Precedent:
        public_id = "22222222-2222-2222-2222-222222222222"
        potency_amount = Decimal("12.5000000000")
        maximum_daily_exposure = None
        route_raw = "ORAL"

        def __init__(self, release):
            self.release = release

    def _precedent(self):
        return self._Precedent(self._Release())

    def test_a_resolved_value_carries_full_source_provenance(self):
        from iig_checklist.answer_sources import STATUS_RESOLVED, resolve

        outcome, version = resolve("iid.potency_amount", self._precedent())
        assert outcome.status == STATUS_RESOLVED
        assert outcome.value == {"value": "12.5000000000"}
        assert outcome.source_field == "potency_amount"
        provenance = outcome.provenance("iid.potency_amount", version)
        # Release UUID *and* source checksum: the UUID says which release, the
        # checksum says which exact bytes of it. Either alone is insufficient
        # to reproduce an approved execution.
        assert self._Release.public_id in provenance["source_version"]
        assert self._Release.source_checksum_sha256 in provenance["source_version"]

    def test_decimals_never_become_floats(self):
        from iig_checklist.answer_sources import resolve

        outcome, _ = resolve("iid.potency_amount", self._precedent())
        assert isinstance(outcome.value["value"], str)
        assert "e" not in outcome.value["value"].lower()

    def test_a_missing_value_is_explicit_and_never_fabricated(self):
        from iig_checklist.answer_sources import STATUS_VALUE_UNAVAILABLE, resolve

        outcome, _ = resolve("iid.maximum_daily_exposure", self._precedent())
        assert outcome.status == STATUS_VALUE_UNAVAILABLE
        # Not 0, not "", not None-pretending-to-be-an-answer.
        assert outcome.value is None
        assert outcome.failure_detail

    def test_a_missing_source_is_explicit(self):
        from iig_checklist.answer_sources import STATUS_SOURCE_UNAVAILABLE, resolve

        outcome, _ = resolve("iid.potency_amount", None)
        assert outcome.status == STATUS_SOURCE_UNAVAILABLE
        assert outcome.value is None

    def test_resolution_is_deterministic(self):
        from iig_checklist.answer_sources import resolve

        first, _ = resolve("iid.potency_amount", self._precedent())
        second, _ = resolve("iid.potency_amount", self._precedent())
        assert first == second

    def test_provenance_carries_no_database_ids(self):
        from iig_checklist.answer_sources import resolve

        outcome, version = resolve("iid.potency_amount", self._precedent())
        provenance = outcome.provenance("iid.potency_amount", version)
        assert "id" not in provenance
        assert "pk" not in provenance


class TestBindingAuthoringValidation:
    def test_an_unknown_binding_cannot_be_authored(self, db, tenant_definition, user_a):
        from iig_checklist.models import ChecklistQuestion

        version = _version(tenant_definition, user_a, status="draft")
        section = _section(version)
        question = ChecklistQuestion(
            section=section,
            code="Q-BADBIND",
            question_text="Synthetic",
            display_order=1,
            answer_type=AnswerType.SHORT_TEXT,
            data_source_classification=DataSourceClassification.FDA_DERIVED_DEFAULT,
            criticality="low",
            prefill_source="iid.not_a_real_resolver",
        )
        with pytest.raises(DjangoValidationError) as exc:
            question.full_clean()
        assert "approved answer-source resolver" in str(exc.value)

    def test_a_binding_on_a_non_fda_question_is_refused(self, db, tenant_definition, user_a):
        # Nothing would ever read it, so it could only mislead a content reviewer.
        from iig_checklist.models import ChecklistQuestion

        version = _version(tenant_definition, user_a, status="draft")
        section = _section(version)
        question = ChecklistQuestion(
            section=section,
            code="Q-WRONGCLASS",
            question_text="Synthetic",
            display_order=1,
            answer_type=AnswerType.SHORT_TEXT,
            data_source_classification=DataSourceClassification.USER_REQUIRED,
            criticality="low",
            prefill_source="iid.potency_amount",
        )
        with pytest.raises(DjangoValidationError) as exc:
            question.full_clean()
        assert "FDA_DERIVED_DEFAULT" in str(exc.value)

    def test_an_approved_binding_is_accepted(self, db, tenant_definition, user_a):
        version = _version(tenant_definition, user_a, status="draft")
        section = _section(version)
        question = _question(
            section,
            "Q-GOODBIND",
            data_source_classification=DataSourceClassification.FDA_DERIVED_DEFAULT,
            prefill_source="iid.potency_amount",
        )
        question.full_clean()


class TestPopulationAtExecutionCreation:
    def _bound_execution(self, tenant, definition, user):
        # definition here must be component-scoped: iid.* content is only
        # executable under an IID/IIG classification (OQ-8).
        version = _version(definition, user, status="draft")
        section = _section(version)
        question = _question(
            section,
            "Q-FDA",
            data_source_classification=DataSourceClassification.FDA_DERIVED_DEFAULT,
            prefill_source="iid.potency_amount",
        )
        version.status = "active"
        version.save(update_fields=["status"])
        execution = _execute(tenant, version, user, with_subject_component=True)
        from iig_checklist.models import ChecklistResponse

        return ChecklistResponse.objects.get(execution=execution, question=question)

    def test_an_unresolvable_binding_records_why_and_fabricates_nothing(
        self, db, tenant_a, component_scoped_definition, user_a, doer_membership
    ):
        # The governed source-selection rule is OQ-8 and unanswered, so the
        # honest outcome is a recorded failure -- never an invented default.
        response = self._bound_execution(tenant_a, component_scoped_definition, user_a)
        assert response.raw_value is None
        assert response.source_provenance["status"] == "source_unavailable"
        assert response.source_provenance["resolver_identifier"] == "iid.potency_amount"
        assert response.source_provenance["resolver_version"] == "1.0.0"

    def test_an_unbound_question_records_no_provenance(
        self, db, tenant_a, tenant_definition, user_a, doer_membership
    ):
        version = _version(tenant_definition, user_a)
        question = _question(_section(version), "Q-PLAIN")
        execution = _execute(tenant_a, version, user_a)
        from iig_checklist.models import ChecklistResponse

        response = ChecklistResponse.objects.get(execution=execution, question=question)
        assert response.source_provenance is None

    def test_provenance_reaches_the_controlled_export(
        self, db, tenant_a, component_scoped_definition, user_a, doer_membership
    ):
        from iig_checklist.controlled_export import build_export_artifact

        response = self._bound_execution(tenant_a, component_scoped_definition, user_a)
        execution = response.execution
        execution.status = "approved"
        execution.save(update_fields=["status"])
        artifact = build_export_artifact(execution=execution, generated_at=_FIXED_TIME)
        projected = artifact["payload"]["responses"][0]
        assert projected["source_provenance"]["status"] == "source_unavailable"

    def test_a_client_cannot_write_provenance(
        self, db, tenant_a, tenant_definition, user_a, doer_membership
    ):
        from iig_checklist.serializers import ChecklistResponseSerializer

        # Read-only on the serializer the client sees: provenance is evidence
        # the server produced, not something a caller may assert.
        assert "source_provenance" in ChecklistResponseSerializer.Meta.read_only_fields
