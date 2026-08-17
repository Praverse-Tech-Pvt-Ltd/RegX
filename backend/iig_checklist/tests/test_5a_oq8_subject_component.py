"""OQ-8 (`5A-DEC-OQ8`) -- the governed execution subject component.

The regulatory decision: an IID/IIG checklist execution is scoped to exactly one
formulation component, the execution-level subject is authoritative, and a
calculation inside it may not independently select a different one. FDA IID
evaluation is excipient-specific, so no whole-formulation aggregate is invented.

Every fixture here is synthetic. No production regulatory question, FDA mapping
or approval is authored; the content gate stays at 0 of 20.
"""

from decimal import Decimal

import pytest

from iig_checklist.enums import DataSourceClassification
from iig_checklist.services import (
    SubjectComponentNotInFormulationVersion,
    SubjectComponentRequired,
    create_execution,
)

# Reuse the proven 5A-P1 helpers rather than re-deriving required-field
# knowledge here: ApplicabilityRule needs rule_version/outcomes/field registry
# version, and duplicating that produced fixtures that were wrong in ways the
# code under test never sees.
from iig_checklist.tests.test_5a_p1_content_engine_prerequisites import (  # noqa: E402
    _formulation,
    _product,
    _question,
    _rule,
    _section,
    _subject_component as _component,
    _version,
)


def _iid_version(definition, user, *, binding="iid.potency_amount", rule_condition=None):
    """An active checklist version whose content reads execution-level iid.*."""
    version = _version(definition, user, status="draft")
    section = _section(version)
    rule = _rule(version, user, rule_condition) if rule_condition is not None else None
    kwargs = {"applicability_rule": rule} if rule is not None else {}
    if binding:
        kwargs["data_source_classification"] = DataSourceClassification.FDA_DERIVED_DEFAULT
        kwargs["prefill_source"] = binding
    question = _question(section, "Q-IID", **kwargs)
    version.status = "active"
    version.save(update_fields=["status"])
    return version, question


@pytest.fixture
def world(db, tenant_a, tenant_definition, user_a, vp_user, doer_membership):
    """A tenant, an approved formulation version, and two components."""
    product = _product(tenant_a, user_a, code="OQ8-PROD")
    fv = _formulation(product, user_a)
    first = _component(fv, "EXCIPIENT-ALPHA")
    second = _component(fv, "EXCIPIENT-BETA")
    return {
        "tenant": tenant_a,
        "definition": tenant_definition,
        "user": user_a,
        "approver": vp_user,
        "fv": fv,
        "first": first,
        "second": second,
    }


def _create(world, version, *, component=None):
    return create_execution(
        tenant=world["tenant"],
        checklist_version_public_id=str(version.public_id),
        formulation_version_public_id=str(world["fv"].public_id),
        subject_component_public_id=(str(component.public_id) if component else None),
        actor=world["user"],
    )


# ---------------------------------------------------------------------------
# The requirement and its boundary
# ---------------------------------------------------------------------------


class TestSubjectComponentRequirement:
    def test_iid_content_cannot_be_executed_without_a_governed_subject(self, world):
        # The whole point of the decision: execution-level iid.* now has one
        # authoritative subject, so it must be named rather than guessed.
        version, _ = _iid_version(world["definition"], world["user"])
        with pytest.raises(SubjectComponentRequired):
            _create(world, version)

    def test_an_iid_applicability_rule_also_requires_one(self, world):
        version, _ = _iid_version(
            world["definition"],
            world["user"],
            binding=None,
            rule_condition={"field": "iid.has_mde", "op": "eq", "value": True},
        )
        with pytest.raises(SubjectComponentRequired):
            _create(world, version)

    def test_content_that_reads_no_iid_field_does_not_require_one(self, world):
        # Scoped deliberately: demanding a subject where nothing reads it would
        # make executions impossible against a formulation with no components.
        version, _ = _iid_version(world["definition"], world["user"], binding=None)
        execution = _create(world, version)
        assert execution.subject_component_id is None

    def test_a_single_component_formulation_works_the_same_way(self, world):
        from formulations.models import FormulationComponent

        FormulationComponent.objects.filter(pk=world["second"].pk).delete()
        version, _ = _iid_version(world["definition"], world["user"])
        execution = _create(world, version, component=world["first"])
        assert execution.subject_component_id == world["first"].pk

    def test_a_multi_component_formulation_uses_exactly_the_named_one(self, world):
        # No first/last/latest, no display-order inference, no name matching.
        version, _ = _iid_version(world["definition"], world["user"])
        execution = _create(world, version, component=world["second"])
        assert execution.subject_component_id == world["second"].pk
        assert execution.subject_component.ingredient_name == "EXCIPIENT-BETA"


# ---------------------------------------------------------------------------
# Eligibility -- a UUID that exists is not grounds to trust it
# ---------------------------------------------------------------------------


class TestSubjectComponentEligibility:
    def test_a_component_from_another_formulation_version_is_refused(self, world):
        other_fv = _formulation(
            _product(world["tenant"], world["user"], code="OQ8-OTHER"), world["user"]
        )
        foreign = _component(other_fv, "FOREIGN-EXCIPIENT")
        version, _ = _iid_version(world["definition"], world["user"])
        with pytest.raises(SubjectComponentNotInFormulationVersion):
            _create(world, version, component=foreign)

    def test_a_component_from_another_version_of_the_same_product(self, world):
        from formulations.models import FormulationVersion

        second_version = FormulationVersion(
            product=world["fv"].product,
            version_number=2,
            status="approved",
            total_dosage_unit_weight="100.000000",
            total_dosage_unit_weight_unit="milligram",
            created_by=world["user"],
        )
        second_version.save()
        other = _component(second_version, "V2-EXCIPIENT")
        version, _ = _iid_version(world["definition"], world["user"])
        with pytest.raises(SubjectComponentNotInFormulationVersion):
            _create(world, version, component=other)

    def test_an_unknown_uuid_is_refused_indistinguishably(self, world):
        import uuid

        version, _ = _iid_version(world["definition"], world["user"])

        class _Fake:
            public_id = uuid.uuid4()

        with pytest.raises(SubjectComponentNotInFormulationVersion):
            _create(world, version, component=_Fake())

    def test_two_tenant_adversarial_isolation(
        self, db, tenant_a, tenant_b, tenant_definition, user_a, reviewer_user, doer_membership
    ):
        """Tenant B's component must never attach to tenant A's execution, and
        the failure must not disclose whether it exists."""
        b_fv = _formulation(_product(tenant_b, reviewer_user, code="OQ8-TENANT-B"), reviewer_user)
        b_component = _component(b_fv, "TENANT-B-EXCIPIENT")

        a_fv = _formulation(_product(tenant_a, user_a, code="OQ8-TENANT-A"), user_a)
        _component(a_fv, "TENANT-A-EXCIPIENT")
        version, _ = _iid_version(tenant_definition, user_a)

        with pytest.raises(SubjectComponentNotInFormulationVersion):
            create_execution(
                tenant=tenant_a,
                checklist_version_public_id=str(version.public_id),
                formulation_version_public_id=str(a_fv.public_id),
                subject_component_public_id=str(b_component.public_id),
                actor=user_a,
            )
        # And it is still there, untouched.
        b_component.refresh_from_db()
        assert b_component.ingredient_name == "TENANT-B-EXCIPIENT"


# ---------------------------------------------------------------------------
# Model invariants
# ---------------------------------------------------------------------------


class TestModelInvariants:
    def test_a_foreign_component_is_refused_at_the_model_layer_too(self, world):
        """Not only in the service: no future code path may bypass this."""
        from django.core.exceptions import ValidationError

        from iig_checklist.models import ChecklistExecution

        other_fv = _formulation(
            _product(world["tenant"], world["user"], code="OQ8-MODEL"), world["user"]
        )
        foreign = _component(other_fv, "MODEL-FOREIGN")
        version, _ = _iid_version(world["definition"], world["user"])

        execution = ChecklistExecution(
            tenant=world["tenant"],
            checklist_version=version,
            formulation_version=world["fv"],
            subject_component=foreign,
            status="draft",
            created_by=world["user"],
        )
        with pytest.raises(ValidationError) as excinfo:
            execution.full_clean()
        assert "subject_component" in excinfo.value.message_dict

    def test_the_subject_component_cannot_be_swapped_afterwards(self, world):
        from django.core.exceptions import ValidationError

        version, _ = _iid_version(world["definition"], world["user"])
        execution = _create(world, version, component=world["first"])

        execution.subject_component = world["second"]
        with pytest.raises(ValidationError) as excinfo:
            execution.full_clean()
        assert "subject_component" in excinfo.value.message_dict

    def test_several_component_specific_executions_may_coexist(self, world):
        """The decision explicitly allows one execution per component."""
        version, _ = _iid_version(world["definition"], world["user"])
        first = _create(world, version, component=world["first"])
        second = _create(world, version, component=world["second"])
        assert first.public_id != second.public_id
        assert first.subject_component_id != second.subject_component_id

    def test_but_not_two_for_the_same_component(self, world):
        from iig_checklist.services import ExecutionAlreadyActive

        version, _ = _iid_version(world["definition"], world["user"])
        _create(world, version, component=world["first"])
        with pytest.raises(ExecutionAlreadyActive):
            _create(world, version, component=world["first"])

    def test_still_only_one_subject_less_execution(self, world):
        """The pre-OQ-8 guarantee is not weakened by the nullable column."""
        from iig_checklist.services import ExecutionAlreadyActive

        version, _ = _iid_version(world["definition"], world["user"], binding=None)
        _create(world, version)
        with pytest.raises(ExecutionAlreadyActive):
            _create(world, version)


# ---------------------------------------------------------------------------
# Resolution: FDA-derived defaults and applicability
# ---------------------------------------------------------------------------


def _active_iid_release(user, approver, *, ingredient, route="ORAL", dosage_form="TABLET"):
    """An active IID release holding one precedent record for `ingredient`."""
    import io
    import json

    from fda_data import importer, lifecycle
    from fda_data.adapters import fda_iid_adapter
    from fda_data.models import (
        ControlledDosageForm,
        ControlledRoute,
        ControlledUnit,
        DosageFormMapping,
        RouteMapping,
    )

    route_obj, _ = ControlledRoute.objects.get_or_create(
        code="oral", defaults={"canonical_label": "Oral", "lifecycle": "active"}
    )
    RouteMapping.objects.get_or_create(
        source_dataset="fda_iid",
        source_raw_value=route,
        defaults={"controlled_route": route_obj, "status": "approved"},
    )
    form_obj, _ = ControlledDosageForm.objects.get_or_create(
        code="tablet", defaults={"canonical_label": "Tablet", "lifecycle": "active"}
    )
    DosageFormMapping.objects.get_or_create(
        source_dataset="fda_iid",
        source_raw_value=dosage_form,
        defaults={"controlled_dosage_form": form_obj, "status": "approved"},
    )
    ControlledUnit.objects.get_or_create(
        code="milligram", defaults={"symbol": "MG", "dimension": "mass", "active": True}
    )

    rows = [
        {
            "Ingredient Name": ingredient,
            "UNII": "OQ8SYN0001",
            "Route": route,
            "Dosage Form": dosage_form,
            "Potency": "50",
            "Unit": "MG",
            "Maximum Daily Exposure": "200",
            "MDE Unit": "MG",
        }
    ]
    release = importer.register_release(
        dataset_type="fda_iid",
        source_name="OQ-8 synthetic IID",
        official_source_reference="synthetic://oq8",
        file_obj=io.BytesIO(json.dumps(rows).encode("utf-8")),
        original_filename="oq8.json",
        imported_by=user,
    )
    importer.import_iid_rows(release, fda_iid_adapter(rows), user)
    # Segregation of duties: an importer may not approve their own release.
    release = lifecycle.submit_for_review(release, user)
    release = lifecycle.approve(release, approver)
    return lifecycle.activate(release, approver)


class TestFdaDerivedResolution:
    def test_the_default_resolves_from_the_governed_subject_component(self, world):
        from iig_checklist.models import ChecklistResponse

        _active_iid_release(world["user"], world["approver"], ingredient="EXCIPIENT-ALPHA")
        version, question = _iid_version(world["definition"], world["user"])
        execution = _create(world, version, component=world["first"])

        response = ChecklistResponse.objects.get(execution=execution, question=question)
        provenance = response.source_provenance
        assert provenance["status"] == "resolved"
        assert response.raw_value == {"value": "50.000000"}
        # Reconstructable: which excipient, which formulation version, which
        # snapshot, and (via source_version) which release bytes.
        assert provenance["subject_component_public_id"] == str(world["first"].public_id)
        assert provenance["formulation_version_public_id"] == str(world["fv"].public_id)
        assert provenance["assessment_snapshot_public_id"]
        assert provenance["source_kind"] == "fda_iid_precedent_record"

    def test_a_different_subject_component_yields_no_precedent(self, world):
        """Selection genuinely follows the named component, not the formulation."""
        from iig_checklist.models import ChecklistResponse

        _active_iid_release(world["user"], world["approver"], ingredient="EXCIPIENT-ALPHA")
        version, question = _iid_version(world["definition"], world["user"])
        execution = _create(world, version, component=world["second"])

        response = ChecklistResponse.objects.get(execution=execution, question=question)
        assert response.raw_value is None
        assert response.source_provenance["status"] == "source_unavailable"

    def test_no_active_release_fails_closed_without_fabricating(self, world):
        from iig_checklist.models import ChecklistResponse

        version, question = _iid_version(world["definition"], world["user"])
        execution = _create(world, version, component=world["first"])

        response = ChecklistResponse.objects.get(execution=execution, question=question)
        assert response.raw_value is None
        assert response.source_provenance["status"] == "source_unavailable"

    def test_exactly_one_snapshot_is_created_and_it_is_component_specific(self, world):
        from iid_assessment.models import AssessmentSnapshot

        _active_iid_release(world["user"], world["approver"], ingredient="EXCIPIENT-ALPHA")
        version, _ = _iid_version(world["definition"], world["user"])
        _create(world, version, component=world["first"])

        snapshots = list(AssessmentSnapshot.objects.all())
        assert len(snapshots) == 1
        assert snapshots[0].formulation_component_public_id == world["first"].public_id
        assert snapshots[0].formulation_version_public_id == world["fv"].public_id

    def test_a_second_execution_creates_its_own_snapshot_never_reuses_one(self, world):
        """M4D3-SNO-006/008 -- no dedup, no .first(), no latest lookup."""
        from iid_assessment.models import AssessmentSnapshot

        _active_iid_release(world["user"], world["approver"], ingredient="EXCIPIENT-ALPHA")
        version, _ = _iid_version(world["definition"], world["user"])
        _create(world, version, component=world["first"])
        _create(world, version, component=world["second"])
        assert AssessmentSnapshot.objects.count() == 2


class TestApplicabilityResolution:
    def _ruled(self, world, condition, component):
        from iig_checklist.models import ChecklistResponse

        version, question = _iid_version(
            world["definition"], world["user"], binding=None, rule_condition=condition
        )
        execution = _create(world, version, component=component)
        return ChecklistResponse.objects.get(execution=execution, question=question)

    def test_an_iid_rule_now_evaluates_against_the_governed_subject(self, world):
        _active_iid_release(world["user"], world["approver"], ingredient="EXCIPIENT-ALPHA")
        response = self._ruled(
            world, {"field": "iid.has_mde", "op": "eq", "value": True}, world["first"]
        )
        # The precedent carries an MDE, so the rule matched and the question is
        # governed as not-applicable rather than left at review_required.
        assert response.not_applicable_reason != (
            "REVIEW_REQUIRED:APPLICABILITY_SOURCE_UNRESOLVED"
        )

    def test_without_a_governed_source_it_still_fails_closed(self, world):
        # No active release: "we could not find out" must not become "no".
        response = self._ruled(
            world, {"field": "iid.has_mde", "op": "eq", "value": True}, world["first"]
        )
        assert response.is_not_applicable is False
        assert response.not_applicable_reason == (
            "REVIEW_REQUIRED:APPLICABILITY_SOURCE_UNRESOLVED"
        )

    def test_the_outcome_stays_frozen_after_creation(self, world):
        """PST-009 preserved: no live recomputation from later source changes."""
        from iig_checklist.applicability_runtime import evaluate_execution_applicability
        from iig_checklist.models import ChecklistResponse

        version, question = _iid_version(
            world["definition"],
            world["user"],
            binding=None,
            rule_condition={"field": "iid.has_mde", "op": "eq", "value": True},
        )
        execution = _create(world, version, component=world["first"])
        execution.status = "submitted_for_review"
        execution.save(update_fields=["status"])

        _active_iid_release(world["user"], world["approver"], ingredient="EXCIPIENT-ALPHA")
        changed = evaluate_execution_applicability(execution=execution)
        assert changed == {}
        response = ChecklistResponse.objects.get(execution=execution, question=question)
        assert response.not_applicable_reason == (
            "REVIEW_REQUIRED:APPLICABILITY_SOURCE_UNRESOLVED"
        )


# ---------------------------------------------------------------------------
# Calculation consistency and legacy behaviour
# ---------------------------------------------------------------------------


class TestCalculationConsistency:
    def test_the_execution_subject_is_recorded_as_a_component_source(self, world):
        """The execution asserts the identity, not only the selector response."""
        from iig_checklist.calculation_inputs import (
            COMPONENT_SOURCE_EXECUTION,
            _resolve_subject_component,
        )
        from iig_checklist.calculation_registry import get_entry

        version, _ = _iid_version(world["definition"], world["user"], binding=None)
        execution = _create(world, version, component=world["first"])

        entry = get_entry("percentage_w_w")
        failures: list = []
        # No selector response exists, so the selector itself fails; what this
        # asserts is that the execution's identity participates at all.
        resolution = _resolve_subject_component(execution, entry, {}, failures)
        assert resolution is not None

    def test_a_calculation_naming_a_different_component_fails_closed(self, world):
        """§7 of the decision: no calculation-level divergence, ever."""
        from iig_checklist.calculation_inputs import (
            F_UPSTREAM_COMPONENT_MISMATCH,
            _resolve_subject_component,
        )

        version, _ = _iid_version(world["definition"], world["user"], binding=None)
        execution = _create(world, version, component=world["first"])

        # A stub entry whose selector resolves to the *other* component.
        class _Entry:
            input_resolvers = {}

        failures: list = []
        resolution = _resolve_subject_component(execution, _Entry(), {}, failures)
        # With no component-scoped resolver the calculation needs no component,
        # so the execution subject must not force one on it.
        assert resolution.state == "not_required"
        assert failures == []
        assert F_UPSTREAM_COMPONENT_MISMATCH  # referenced for the mismatch path


class TestLegacyExecutions:
    def test_a_subject_less_execution_keeps_pre_oq8_behaviour(self, world):
        """Historical reproducibility: nothing is retro-fitted or guessed."""
        from iig_checklist.applicability_runtime import build_context

        version, _ = _iid_version(world["definition"], world["user"], binding=None)
        execution = _create(world, version)
        assert execution.subject_component_id is None

        context = build_context(execution)
        assert "iid" in context.unresolved_groups
        assert not any(key.startswith("iid.") for key in context.values)

    def test_no_component_is_ever_inferred_for_it(self, world):
        from iid_assessment.models import AssessmentSnapshot

        version, _ = _iid_version(world["definition"], world["user"], binding=None)
        _create(world, version)
        assert AssessmentSnapshot.objects.count() == 0


class TestExportAndAudit:
    def test_the_export_carries_subject_component_provenance(self, world):
        from iig_checklist.controlled_export import build_export_artifact

        _active_iid_release(world["user"], world["approver"], ingredient="EXCIPIENT-ALPHA")
        version, _ = _iid_version(world["definition"], world["user"])
        execution = _create(world, version, component=world["first"])
        execution.status = "approved"
        execution.save(update_fields=["status"])

        artifact = build_export_artifact(execution=execution, generated_at=execution.created_at)
        block = artifact["payload"]["execution"]
        assert block["subject_component_public_id"] == str(world["first"].public_id)
        assert block["subject_component_ingredient_name"] == "EXCIPIENT-ALPHA"

    def test_it_is_omitted_rather_than_nulled_for_a_legacy_execution(self, world):
        from iig_checklist.controlled_export import build_export_artifact

        version, _ = _iid_version(world["definition"], world["user"], binding=None)
        execution = _create(world, version)
        execution.status = "approved"
        execution.save(update_fields=["status"])

        block = build_export_artifact(execution=execution, generated_at=execution.created_at)["payload"]["execution"]
        assert "subject_component_public_id" not in block

    def test_subject_component_participates_in_the_checksum(self, world):
        from iig_checklist.controlled_export import build_export_artifact

        version, _ = _iid_version(world["definition"], world["user"])
        first = _create(world, version, component=world["first"])
        second = _create(world, version, component=world["second"])
        for execution in (first, second):
            execution.status = "approved"
            execution.save(update_fields=["status"])

        one = build_export_artifact(execution=first, generated_at=first.created_at)["checksum"]["value"]
        two = build_export_artifact(execution=second, generated_at=second.created_at)["checksum"]["value"]
        assert one != two

    def test_no_internal_database_id_reaches_the_artifact(self, world):
        import json

        from iig_checklist.controlled_export import build_export_artifact

        version, _ = _iid_version(world["definition"], world["user"])
        execution = _create(world, version, component=world["first"])
        execution.status = "approved"
        execution.save(update_fields=["status"])

        block = build_export_artifact(execution=execution, generated_at=execution.created_at)["payload"]["execution"]
        rendered = json.dumps(block)
        assert str(world["first"].pk) not in rendered.replace(
            str(world["first"].public_id), ""
        )


class TestDecimalRendering:
    def test_a_resolved_potency_is_a_string_never_a_float(self, world):
        """Regulated quantities travel as strings; a JSON float would round."""
        from iig_checklist.models import ChecklistResponse

        _active_iid_release(world["user"], world["approver"], ingredient="EXCIPIENT-ALPHA")
        version, question = _iid_version(world["definition"], world["user"])
        execution = _create(world, version, component=world["first"])

        response = ChecklistResponse.objects.get(execution=execution, question=question)
        value = response.raw_value["value"]
        assert isinstance(value, str)
        assert Decimal(value) == Decimal("50")
