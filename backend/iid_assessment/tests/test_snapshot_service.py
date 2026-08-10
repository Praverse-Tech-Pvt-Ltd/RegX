"""Governed AssessmentSnapshot creation service -- PostgreSQL-backed.

Covers the service directly and through the API adapter it now backs: ownership,
exact release identity, always-new creation, immutability, audit, cross-tenant
isolation and release-drift reproducibility.

This module deliberately imports nothing from ``iig_checklist``. The
import-linter contract ``iig-checklist-content-is-not-imported-by-governed-domains``
covers the whole ``iid_assessment`` package including its tests, so the
execution-integration tests live in ``iig_checklist/tests`` instead.
"""

from __future__ import annotations

import dataclasses
from decimal import Decimal

import pytest

from iid_assessment.models import AssessmentSnapshot
from iid_assessment.services import (
    ActiveReleaseUnavailable,
    AssessmentSnapshotCreationResult,
    ComponentNotInFormulationVersion,
    FormulationVersionNotInTenant,
    ReleaseNotEligible,
    create_assessment_snapshot,
    resolve_active_iid_release,
)

pytestmark = pytest.mark.django_db

BASE = "/api/regx/v1"


def _create(world, **overrides):
    kwargs = {
        "tenant": world["tenant"],
        "formulation_version": world["formulation_version"],
        "formulation_component": world["component"],
        "actor": world["user"],
    }
    kwargs.update(overrides)
    return create_assessment_snapshot(**kwargs)


@pytest.fixture
def tenant_b(db):
    from tenancy.models import Tenant

    return Tenant.objects.create(name="Tenant Beta", slug="tenant-beta")


@pytest.fixture
def world(db, tenant_a, user_a, active_iid_setup, snapshot_formulation):
    return {
        "tenant": tenant_a,
        "user": user_a,
        "iid": active_iid_setup,
        "product": snapshot_formulation["product"],
        "formulation_version": snapshot_formulation["formulation_version"],
        "component": snapshot_formulation["component"],
    }


# ===========================================================================
# A. Successful creation
# ===========================================================================


class TestSuccessfulCreation:
    def test_service_creates_one_snapshot_without_a_request(self, world):
        """The whole point: callable with no DRF request anywhere in sight."""
        assert AssessmentSnapshot.objects.count() == 0
        result = _create(world)
        assert AssessmentSnapshot.objects.count() == 1
        assert isinstance(result, AssessmentSnapshotCreationResult)
        assert result.snapshot_public_id == str(result.snapshot.public_id)

    def test_exact_formulation_and_component_linkage(self, world):
        result = _create(world)
        snapshot = AssessmentSnapshot.objects.get()
        assert snapshot.formulation_version_public_id == (world["formulation_version"].public_id)
        assert snapshot.formulation_component_public_id == world["component"].public_id
        assert result.formulation_version_public_id == str(world["formulation_version"].public_id)
        assert result.formulation_component_public_id == str(world["component"].public_id)

    def test_exact_release_identity_is_frozen(self, world):
        result = _create(world)
        snapshot = AssessmentSnapshot.objects.get()
        assert snapshot.iid_release_public_id == world["iid"]["release"].public_id
        assert result.iid_release_public_id == str(world["iid"]["release"].public_id)
        assert result.iid_release_status == "active"
        assert snapshot.iid_precedent_record_public_id == world["iid"]["record"].public_id

    def test_exact_potency_mde_and_units(self, world):
        """The frozen values come from the precedent record, not the caller."""
        result = _create(world)
        snapshot = AssessmentSnapshot.objects.get()
        assert snapshot.iid_potency_amount == Decimal("50")
        assert snapshot.iid_potency_unit == "milligram"
        assert snapshot.iid_mde == Decimal("200")
        assert snapshot.iid_mde_unit == "milligram"
        assert result.potency_amount == Decimal("50")
        assert result.mde == Decimal("200")

    def test_proposed_quantity_comes_from_the_component(self, world):
        """M4D3-SRC-004 -- the formulation is the governed source, not input."""
        result = _create(world)
        snapshot = AssessmentSnapshot.objects.get()
        assert snapshot.proposed_quantity_per_unit == (world["component"].quantity_per_dosage_unit)
        assert snapshot.proposed_quantity_unit == world["component"].quantity_unit
        assert result.match_status == "EXACT_MATCH"

    def test_result_is_immutable(self, world):
        result = _create(world)
        for field in dataclasses.fields(result):
            with pytest.raises(dataclasses.FrozenInstanceError):
                setattr(result, field.name, None)
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.injected = 1
        assert not hasattr(result, "__dict__")

    def test_result_carries_public_uuids_not_database_ids(self, world):
        result = _create(world)
        for field in dataclasses.fields(result):
            if field.name == "snapshot":
                continue  # M4D3-SNO-007 -- the exact in-memory object, by design
            value = getattr(result, field.name)
            assert not isinstance(value, int) or isinstance(value, bool), field.name

    def test_route_and_dosage_form_resolution_is_reported(self, world):
        result = _create(world)
        assert result.route_resolved is True
        assert result.dosage_form_resolved is True

    def test_blank_controlled_terms_are_missing_data_not_a_match(self, world):
        """M4D3-RTE-002/003 -- a blank route can never resolve."""
        world["product"].route = "   "
        world["product"].save(update_fields=["route", "updated_at"])
        result = _create(world)
        assert result.route_resolved is False
        assert result.match_status != "EXACT_MATCH"
        # The event is still recorded, with no precedent frozen.
        assert AssessmentSnapshot.objects.count() == 1
        assert result.iid_precedent_record_public_id is None

    def test_one_audit_event_after_commit(self, world, django_capture_on_commit_callbacks):
        from audit.models import AuditEvent

        with django_capture_on_commit_callbacks(execute=True):
            result = _create(world)
        events = list(AuditEvent.objects.filter(event_type="iid_assessment.snapshot.created"))
        assert len(events) == 1
        payload = events[0].payload
        assert events[0].resource_id == result.snapshot_public_id
        assert payload["formulation_version_public_id"] == (result.formulation_version_public_id)
        assert payload["formulation_component_public_id"] == (
            result.formulation_component_public_id
        )
        assert payload["iid_release_public_id"] == result.iid_release_public_id
        for value in payload.values():
            assert not isinstance(value, int)

    def test_no_audit_when_the_transaction_rolls_back(
        self, world, django_capture_on_commit_callbacks
    ):
        from django.db import transaction

        from audit.models import AuditEvent

        before = AuditEvent.objects.count()

        class Boom(RuntimeError):
            pass

        with pytest.raises(Boom), django_capture_on_commit_callbacks(execute=True):
            with transaction.atomic():
                _create(world)
                raise Boom()

        assert AssessmentSnapshot.objects.count() == 0
        assert AuditEvent.objects.count() == before


# ===========================================================================
# B. Always-new policy (M4D3-SNO-006/008)
# ===========================================================================


class TestAlwaysNew:
    def test_two_identical_calls_create_two_distinct_snapshots(self, world):
        first = _create(world)
        second = _create(world)
        assert AssessmentSnapshot.objects.count() == 2
        assert first.snapshot_public_id != second.snapshot_public_id
        # Same governed inputs, so the frozen content agrees -- but the rows
        # are distinct records of two distinct events.
        assert first.iid_release_public_id == second.iid_release_public_id
        assert first.potency_amount == second.potency_amount

    def test_an_existing_matching_snapshot_is_never_reused(self, world):
        existing = _create(world).snapshot
        result = _create(world)
        assert result.snapshot.pk != existing.pk
        existing.refresh_from_db()
        # The first row is untouched: no update, no delete-and-recreate.
        assert AssessmentSnapshot.objects.filter(pk=existing.pk).exists()

    def test_creation_issues_no_snapshot_select(self, world):
        """No lookup at all -- nothing to reuse, dedupe or order by."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as ctx:
            _create(world)
        selects = [
            q["sql"]
            for q in ctx.captured_queries
            if "iid_assessment_assessmentsnapshot" in q["sql"].lower()
            and q["sql"].lstrip().upper().startswith("SELECT")
        ]
        # full_clean() probes public_id uniqueness; that is Django validating the
        # row it is about to write, not a search for one to reuse. Nothing may
        # query by the fields a reuse or dedupe lookup would use.
        for sql in selects:
            lowered = sql.lower()
            assert "public_id" in lowered, sql
            for reuse_key in (
                "tenant_id",
                "formulation_component_public_id",
                "formulation_version_public_id",
                "iid_release_public_id",
                "order by",
            ):
                assert reuse_key not in lowered, (reuse_key, sql)

    def test_the_service_exposes_no_update_path(self):
        import inspect

        from iid_assessment import services

        source = inspect.getsource(services)
        assert ".update(" not in source
        assert "update_assessment_snapshot" not in source
        assert "\n    snapshot.save()" in source  # create only


# ===========================================================================
# C. Ownership and isolation (M4D3-SNO-010, M4D3-SRC-007)
# ===========================================================================


class TestOwnershipAndIsolation:
    def test_formulation_version_from_another_tenant_is_rejected(self, world, tenant_b):
        world["product"].tenant = tenant_b
        world["product"].save(update_fields=["tenant", "updated_at"])
        world["formulation_version"].refresh_from_db()
        with pytest.raises(FormulationVersionNotInTenant):
            _create(world)
        assert AssessmentSnapshot.objects.count() == 0

    def test_component_from_another_formulation_is_rejected(self, world, user_a):
        from formulations.models import (
            FormulationComponent,
            FormulationVersion,
            ProductDevelopmentRecord,
        )

        other_product = ProductDevelopmentRecord.objects.create(
            tenant=world["tenant"],
            product_code="OTHER-01",
            proposed_product_name="Other",
            active_ingredient="Other",
            dosage_form="tablet",
            route="oral",
            created_by=user_a,
        )
        other_version = FormulationVersion.objects.create(
            product=other_product,
            version_number=1,
            status="approved",
            total_dosage_unit_weight=Decimal("500.000000"),
            total_dosage_unit_weight_unit="milligram",
            created_by=user_a,
        )
        foreign_component = FormulationComponent.objects.create(
            formulation_version=other_version,
            component_type="inactive",
            ingredient_name="Other Excipient",
            quantity_per_dosage_unit=Decimal("10.000000"),
            quantity_unit="milligram",
            display_order=1,
        )
        with pytest.raises(ComponentNotInFormulationVersion):
            _create(world, formulation_component=foreign_component)
        assert AssessmentSnapshot.objects.count() == 0

    def test_rejections_leak_no_identifiers(self, world, tenant_b):
        world["product"].tenant = tenant_b
        world["product"].save(update_fields=["tenant", "updated_at"])
        with pytest.raises(FormulationVersionNotInTenant) as raised:
            _create(world)
        text = f"{raised.value!r} {raised.value.args!r} {raised.value!s}"
        for secret in (
            str(world["formulation_version"].public_id),
            str(world["component"].public_id),
            str(tenant_b.id),
        ):
            assert secret not in text
        assert raised.value.args == ()


# ===========================================================================
# D. Release policy (M4D3-SRC-001/003, M4D3-SNO-011)
# ===========================================================================


class TestReleasePolicy:
    def test_active_release_is_resolved_server_side(self, world):
        assert resolve_active_iid_release().pk == world["iid"]["release"].pk

    def test_no_active_release_fails_closed(self, world):
        from fda_data.models import FDAReleaseStatus

        world["iid"]["release"].status = FDAReleaseStatus.REGISTERED
        world["iid"]["release"].save(update_fields=["status"])
        with pytest.raises(ActiveReleaseUnavailable):
            resolve_active_iid_release()
        with pytest.raises(ActiveReleaseUnavailable):
            _create(world)
        assert AssessmentSnapshot.objects.count() == 0

    def test_a_non_iid_release_is_rejected(self, world, user_a):
        from fda_data.models import FDADataSourceRelease, FDAReleaseStatus

        orange_book = FDADataSourceRelease.objects.create(
            dataset_type="fda_orange_book",
            source_name="OB",
            official_source_reference="ref",
            source_checksum_sha256="c" * 64,
            status=FDAReleaseStatus.ACTIVE,
        )
        with pytest.raises(ReleaseNotEligible):
            _create(world, selected_release=orange_book)
        assert AssessmentSnapshot.objects.count() == 0

    def test_a_release_that_was_never_approved_is_rejected(self, world):
        from fda_data.models import FDADataSourceRelease, FDAReleaseStatus

        staged = FDADataSourceRelease.objects.create(
            dataset_type="fda_iid",
            source_name="FDA IID staged",
            official_source_reference="ref",
            source_checksum_sha256="d" * 64,
            status=FDAReleaseStatus.STAGED,
        )
        with pytest.raises(ReleaseNotEligible):
            _create(world, selected_release=staged)
        assert AssessmentSnapshot.objects.count() == 0

    def test_a_superseded_release_is_rejected(self, world):
        """A superseded release can never freeze a precedent, so it is refused.

        ``find_iid_candidates()`` matches only APPROVED or ACTIVE releases, so
        allowing a superseded one would create an empty regulated record that
        looks like an assessment. Reproducibility comes from the snapshot that
        was already frozen, not from re-deriving against an old release.
        """
        from fda_data.models import FDAReleaseStatus

        release = world["iid"]["release"]
        release.status = FDAReleaseStatus.SUPERSEDED
        release.save(update_fields=["status"])
        with pytest.raises(ReleaseNotEligible):
            _create(world, selected_release=release)
        assert AssessmentSnapshot.objects.count() == 0

    def test_eligibility_matches_the_governed_matcher(self):
        """The service's status set is the matcher's, not a second rule."""
        from iid_assessment.services import ELIGIBLE_RELEASE_STATUSES

        assert ELIGIBLE_RELEASE_STATUSES == {"active", "approved"}

    def test_an_approved_release_can_be_pinned(self, world):
        """APPROVED matches, so an explicitly pinned approved release works."""
        from fda_data.models import FDAReleaseStatus

        release = world["iid"]["release"]
        release.status = FDAReleaseStatus.APPROVED
        release.save(update_fields=["status"])
        result = _create(world, selected_release=release)
        assert result.iid_release_status == "approved"
        assert result.potency_amount == Decimal("50")


# ===========================================================================
# E. Release drift -- the reproducibility proof (§17)
# ===========================================================================


class TestReleaseDrift:
    def _publish_newer_release(self, world, *, potency="75", mde="300"):
        """Supersede A and activate B carrying different values."""
        from fda_data.models import (
            FDADataSourceRelease,
            FDAReleaseStatus,
            IIDCalculabilityStatus,
            IIDPrecedentRecord,
        )

        old = world["iid"]["release"]
        old.status = FDAReleaseStatus.SUPERSEDED
        old.save(update_fields=["status"])
        new = FDADataSourceRelease.objects.create(
            dataset_type="fda_iid",
            source_name="FDA IID 2",
            official_source_reference="ref2",
            source_checksum_sha256="9" * 64,
            status=FDAReleaseStatus.ACTIVE,
        )
        IIDPrecedentRecord.objects.create(
            release=new,
            ingredient=world["iid"]["ingredient"],
            ingredient_name_raw="Synthetic Starch",
            route_raw="ORAL",
            route_normalized=world["iid"]["route"],
            dosage_form_raw="TABLET",
            dosage_form_normalized=world["iid"]["dosage_form"],
            potency_amount=Decimal(potency),
            potency_unit_raw="MG",
            potency_unit_normalized=world["iid"]["unit"],
            maximum_daily_exposure=Decimal(mde),
            mde_unit_raw="MG",
            mde_unit_normalized=world["iid"]["unit"],
            raw_row_checksum="8" * 64,
            calculability_status=IIDCalculabilityStatus.CALCULABLE,
        )
        return old, new

    def test_an_earlier_snapshot_stays_tied_to_its_own_release(self, world):
        first = _create(world)
        assert first.potency_amount == Decimal("50")

        old, new = self._publish_newer_release(world)

        # The already-frozen snapshot is untouched by the refresh.
        first.snapshot.refresh_from_db()
        assert first.snapshot.iid_release_public_id == old.public_id
        assert first.snapshot.iid_potency_amount == Decimal("50")

    def test_a_later_event_uses_the_new_active_release(self, world):
        first = _create(world)
        old, new = self._publish_newer_release(world)

        second = _create(world)
        assert second.iid_release_public_id == str(new.public_id)
        assert second.potency_amount == Decimal("75")
        assert second.snapshot_public_id != first.snapshot_public_id
        assert AssessmentSnapshot.objects.count() == 2

    def test_the_superseded_release_can_no_longer_be_assessed_against(self, world):
        """Where reproducibility actually comes from.

        Once A is superseded it cannot be re-derived against -- the governed
        matcher excludes it, so the service refuses it rather than freezing an
        empty record. The already-frozen snapshot is what preserves A's values,
        and it still does.
        """
        first = _create(world)
        old, _new = self._publish_newer_release(world)

        with pytest.raises(ReleaseNotEligible):
            _create(world, selected_release=old)

        first.snapshot.refresh_from_db()
        assert first.snapshot.iid_potency_amount == Decimal("50")
        assert first.snapshot.iid_release_public_id == old.public_id
        assert AssessmentSnapshot.objects.count() == 1

    def test_no_automatic_substitution_of_the_newer_release(self, world):
        """The first snapshot is never rewritten to point at B."""
        first = _create(world)
        _old, new = self._publish_newer_release(world)
        first.snapshot.refresh_from_db()
        assert first.snapshot.iid_release_public_id != new.public_id
        assert first.snapshot.iid_potency_amount == Decimal("50")


# ===========================================================================
# F. The API adapter (§10, §18)
# ===========================================================================


def _post(client, world, **overrides):
    payload = {
        "ingredient_public_id": str(world["iid"]["ingredient"].public_id),
        "route_code": "oral",
        "dosage_form_code": "tablet",
        "active_release_public_id": str(world["iid"]["release"].public_id),
        "proposed_quantity_per_unit": "30",
        "proposed_quantity_unit": "milligram",
        "total_dosage_unit_weight": "500",
        "total_dosage_unit_weight_unit": "milligram",
        # maximum_dosage_units_per_day is deliberately absent: M4D3-MDU-006
        # prohibits a client dosing value on the persisted endpoint, and the
        # server derives it from the formulation instead.
        "formulation_component_public_id": str(world["component"].public_id),
        "formulation_version_public_id": str(world["formulation_version"].public_id),
    }
    payload.update(overrides)
    return client.post(f"{BASE}/iid-assessments/snapshot/", data=payload, format="json")


class TestSnapshotApi:
    def test_creation_still_returns_201_and_the_same_body(self, api_client_doer, world):
        resp = _post(api_client_doer, world)
        assert resp.status_code == 201, resp.content
        body = resp.json()
        assert body["public_id"] == str(AssessmentSnapshot.objects.get().public_id)
        assert body["iid_potency_amount"] == "50.000000"
        assert "id" not in body

    def test_the_view_creates_through_the_service_only(self, api_client_doer, world):
        resp = _post(api_client_doer, world)
        assert resp.status_code == 201
        snapshot = AssessmentSnapshot.objects.get()
        # Values the service derived from the formulation, not from the body.
        assert snapshot.formulation_component_public_id == world["component"].public_id
        assert snapshot.proposed_quantity_per_unit == (world["component"].quantity_per_dosage_unit)

    def test_unknown_formulation_version_is_404(self, api_client_doer, world):
        resp = _post(
            api_client_doer,
            world,
            formulation_version_public_id="11111111-1111-1111-1111-111111111111",
        )
        assert resp.status_code == 404
        assert AssessmentSnapshot.objects.count() == 0

    def test_another_tenants_formulation_version_is_404(self, api_client_doer, world, tenant_b):
        world["product"].tenant = tenant_b
        world["product"].save(update_fields=["tenant", "updated_at"])
        resp = _post(api_client_doer, world)
        assert resp.status_code == 404
        # Indistinguishable from "does not exist" -- nothing to probe with.
        assert str(world["formulation_version"].public_id) not in resp.content.decode()
        assert AssessmentSnapshot.objects.count() == 0

    def test_a_component_from_another_formulation_is_404(self, api_client_doer, world, user_a):
        from formulations.models import (
            FormulationComponent,
            FormulationVersion,
            ProductDevelopmentRecord,
        )

        other_product = ProductDevelopmentRecord.objects.create(
            tenant=world["tenant"],
            product_code="OTHER-API",
            proposed_product_name="Other",
            active_ingredient="Other",
            dosage_form="tablet",
            route="oral",
            created_by=user_a,
        )
        other_version = FormulationVersion.objects.create(
            product=other_product,
            version_number=1,
            status="approved",
            total_dosage_unit_weight=Decimal("500.000000"),
            total_dosage_unit_weight_unit="milligram",
            created_by=user_a,
        )
        foreign = FormulationComponent.objects.create(
            formulation_version=other_version,
            component_type="inactive",
            ingredient_name="Other",
            quantity_per_dosage_unit=Decimal("10.000000"),
            quantity_unit="milligram",
            display_order=1,
        )
        resp = _post(
            api_client_doer,
            world,
            formulation_component_public_id=str(foreign.public_id),
        )
        assert resp.status_code == 404
        assert AssessmentSnapshot.objects.count() == 0

    def test_unknown_release_is_404(self, api_client_doer, world):
        resp = _post(
            api_client_doer,
            world,
            active_release_public_id="22222222-2222-2222-2222-222222222222",
        )
        assert resp.status_code == 404
        assert AssessmentSnapshot.objects.count() == 0

    def test_an_ineligible_release_is_a_structured_400(self, api_client_doer, world):
        from fda_data.models import FDADataSourceRelease, FDAReleaseStatus

        staged = FDADataSourceRelease.objects.create(
            dataset_type="fda_iid",
            source_name="staged",
            official_source_reference="ref",
            source_checksum_sha256="7" * 64,
            status=FDAReleaseStatus.STAGED,
        )
        resp = _post(
            api_client_doer,
            world,
            active_release_public_id=str(staged.public_id),
        )
        assert resp.status_code == 400
        assert "release_not_eligible" in resp.content.decode()
        assert AssessmentSnapshot.objects.count() == 0

    def test_an_unauthenticated_caller_cannot_create(self, world):
        from rest_framework.test import APIClient

        resp = _post(APIClient(), world)
        assert resp.status_code in (401, 403)
        assert AssessmentSnapshot.objects.count() == 0

    def test_a_failed_request_writes_no_audit(self, api_client_doer, world):
        from audit.models import AuditEvent

        before = AuditEvent.objects.count()
        _post(
            api_client_doer,
            world,
            formulation_version_public_id="11111111-1111-1111-1111-111111111111",
        )
        assert AuditEvent.objects.count() == before


# ===========================================================================
# G. M4D3-MDU-006 -- no client dosing value on the persisted endpoint
# ===========================================================================


def _regimen(formulation_version, units):
    from formulations.models import DosingRegimen

    return DosingRegimen.objects.create(
        formulation_version=formulation_version,
        units_per_administration=Decimal("1.0000"),
        administrations_per_day=Decimal(units),
        maximum_units_per_day=Decimal(units),
    )


class TestClientDosingValueProhibited:
    """M4D3-MDU-006 -- "no dosing value shall ever be accepted from a client
    request payload", enforced at the request serializer as the acceptance
    matrix specifies.

    The reviewed defect: a client could post ``maximum_dosage_units_per_day: 1``
    against a formulation carrying a governed ``DosingRegimen`` of 10, and the
    endpoint froze ``PASS_WITH_IID_PRECEDENT`` where the governed Part 14.1 worst
    case gives ``EXCEEDS_IID_PRECEDENT``.
    """

    def _worst_case_fixture(self, world):
        fv = world["formulation_version"]
        fv.maximum_dosage_units_per_day = Decimal("1.0000")
        fv.save(update_fields=["maximum_dosage_units_per_day", "updated_at"])
        _regimen(fv, "10")
        return fv

    # -- A. the field is refused, not ignored ---------------------------------

    def test_supplying_the_field_is_a_structured_400(self, api_client_doer, world):
        from audit.models import AuditEvent

        self._worst_case_fixture(world)
        before = AuditEvent.objects.count()

        resp = _post(api_client_doer, world, maximum_dosage_units_per_day="1")

        assert resp.status_code == 400, resp.content
        body = resp.content.decode()
        assert "prohibited_request_field" in body
        assert "maximum_dosage_units_per_day" in body
        # Refused, never silently dropped, and nothing was written.
        assert AssessmentSnapshot.objects.count() == 0
        assert AuditEvent.objects.count() == before

    @pytest.mark.parametrize(
        "supplied",
        ["0", "1", "999", None, "-5", "not-a-number", 7, 7.5],
        ids=["zero", "one", "large", "null", "negative", "string", "int", "float"],
    )
    def test_no_client_value_of_any_shape_is_accepted(self, api_client_doer, world, supplied):
        self._worst_case_fixture(world)
        resp = _post(api_client_doer, world, maximum_dosage_units_per_day=supplied)
        assert resp.status_code == 400, (supplied, resp.content)
        assert AssessmentSnapshot.objects.count() == 0

    @pytest.mark.parametrize(
        "field",
        [
            "maximumDosageUnitsPerDay",
            "max_daily_units",
            "maximum_units_per_day",
        ],
    )
    def test_an_alternate_spelling_cannot_reintroduce_it(self, api_client_doer, world, field):
        """An unknown field is inert: nothing reads it, so nothing changes."""
        self._worst_case_fixture(world)
        resp = _post(api_client_doer, world, **{field: "1"})
        assert resp.status_code == 201, resp.content
        snapshot = AssessmentSnapshot.objects.get()
        # The governed worst case still applied.
        assert snapshot.decision_status == "EXCEEDS_IID_PRECEDENT"

    def test_a_nested_attempt_cannot_reintroduce_it(self, api_client_doer, world):
        self._worst_case_fixture(world)
        resp = _post(
            api_client_doer,
            world,
            dosing={"maximum_dosage_units_per_day": "1"},
        )
        assert resp.status_code == 201, resp.content
        assert AssessmentSnapshot.objects.get().decision_status == ("EXCEEDS_IID_PRECEDENT")

    def test_the_field_is_not_advertised_on_the_persisted_endpoint(self):
        from iid_assessment.serializers import (
            MatchPreviewRequestSerializer,
            SnapshotRequestSerializer,
        )

        assert "maximum_dosage_units_per_day" not in SnapshotRequestSerializer().fields
        # The non-persisting preview keeps its own contract untouched.
        assert "maximum_dosage_units_per_day" in MatchPreviewRequestSerializer().fields

    # -- B. the governed value is derived server-side -------------------------

    def test_the_reviewed_scenario_now_freezes_the_worst_case(
        self, api_client_doer, world, django_capture_on_commit_callbacks
    ):
        from audit.models import AuditEvent

        self._worst_case_fixture(world)

        with django_capture_on_commit_callbacks(execute=True):
            resp = _post(api_client_doer, world)
        assert resp.status_code == 201, resp.content

        snapshot = AssessmentSnapshot.objects.get()
        daily = snapshot.calculation_results["daily_exposure"]
        assert daily["status"] == "OK"
        # 30 mg per unit x 10 units/day, not x 1.
        assert daily["value"] == "300.0000000000"
        assert snapshot.decision_status == "EXCEEDS_IID_PRECEDENT"
        assert snapshot.decision_status != "PASS_WITH_IID_PRECEDENT"
        note = snapshot.decision_note.lower()
        assert "exceeds the selected iid mde precedent" in note
        assert "percentage_of_iid_mde" in snapshot.calculation_results
        assert "difference_from_iid_mde" in snapshot.calculation_results

        assert AuditEvent.objects.filter(event_type="iid_assessment.snapshot.created").count() == 1

    def test_null_version_scalar_uses_the_regimen(self, api_client_doer, world):
        fv = world["formulation_version"]
        fv.maximum_dosage_units_per_day = None
        fv.save(update_fields=["maximum_dosage_units_per_day", "updated_at"])
        _regimen(fv, "8")

        resp = _post(api_client_doer, world)
        assert resp.status_code == 201, resp.content
        snapshot = AssessmentSnapshot.objects.get()
        daily = snapshot.calculation_results["daily_exposure"]
        assert daily["status"] == "OK"
        assert daily["value"] == "240.0000000000"
        assert "percentage_of_iid_mde" in snapshot.calculation_results

    def test_version_scalar_higher_than_every_regimen_wins(self, api_client_doer, world):
        fv = world["formulation_version"]
        fv.maximum_dosage_units_per_day = Decimal("12.0000")
        fv.save(update_fields=["maximum_dosage_units_per_day", "updated_at"])
        _regimen(fv, "3")
        _regimen(fv, "5")

        resp = _post(api_client_doer, world)
        assert resp.status_code == 201, resp.content
        daily = AssessmentSnapshot.objects.get().calculation_results["daily_exposure"]
        assert daily["value"] == "360.0000000000"

    def test_no_regimen_uses_the_version_scalar(self, api_client_doer, world):
        fv = world["formulation_version"]
        fv.maximum_dosage_units_per_day = Decimal("4.0000")
        fv.save(update_fields=["maximum_dosage_units_per_day", "updated_at"])
        assert not fv.dosing_regimens.exists()

        resp = _post(api_client_doer, world)
        assert resp.status_code == 201, resp.content
        daily = AssessmentSnapshot.objects.get().calculation_results["daily_exposure"]
        assert daily["value"] == "120.0000000000"

    def test_no_source_at_all_fails_closed(self, api_client_doer, world):
        fv = world["formulation_version"]
        fv.maximum_dosage_units_per_day = None
        fv.save(update_fields=["maximum_dosage_units_per_day", "updated_at"])

        resp = _post(api_client_doer, world)
        assert resp.status_code == 201, resp.content
        snapshot = AssessmentSnapshot.objects.get()
        daily = snapshot.calculation_results["daily_exposure"]
        assert daily["status"] == "DATA_REQUIRED"
        assert daily["value"] is None
        # No invented default and no favourable MDE conclusion.
        assert "percentage_of_iid_mde" not in snapshot.calculation_results
        assert snapshot.decision_status != "PASS_WITH_IID_PRECEDENT"

    @pytest.mark.parametrize("scalar", ["0.0000", "-3.0000"])
    def test_non_positive_scalar_alone_fails_closed(self, api_client_doer, world, scalar):
        fv = world["formulation_version"]
        fv.maximum_dosage_units_per_day = Decimal(scalar)
        fv.save(update_fields=["maximum_dosage_units_per_day", "updated_at"])

        resp = _post(api_client_doer, world)
        assert resp.status_code == 201, resp.content
        daily = AssessmentSnapshot.objects.get().calculation_results["daily_exposure"]
        assert daily["status"] == "DATA_REQUIRED"
        assert daily["value"] is None

    def test_zero_scalar_with_a_valid_regimen_uses_the_regimen(self, api_client_doer, world):
        fv = world["formulation_version"]
        fv.maximum_dosage_units_per_day = Decimal("0.0000")
        fv.save(update_fields=["maximum_dosage_units_per_day", "updated_at"])
        _regimen(fv, "6")

        resp = _post(api_client_doer, world)
        assert resp.status_code == 201, resp.content
        daily = AssessmentSnapshot.objects.get().calculation_results["daily_exposure"]
        assert daily["value"] == "180.0000000000"

    def test_the_view_uses_the_shared_governed_helper(self):
        """One helper, both snapshot callers -- no second selection rule."""
        import inspect

        from formulations import dosing
        from iid_assessment import views

        assert "governed_maximum_daily_units_value" in inspect.getsource(views)
        assert 'data.get("maximum_dosage_units_per_day")' not in inspect.getsource(views)
        # The helper delegates; it implements no comparison of its own.
        helper_source = inspect.getsource(dosing)
        assert "select_maximum_daily_units" in helper_source
        assert "max(" not in helper_source

    def test_the_view_binds_the_shared_helper_itself(self):
        """The checklist side of this pairing is asserted in iig_checklist's
        own suite: this package may not import ``iig_checklist`` at all
        (contract ``iig-checklist-content-is-not-imported-by-governed-domains``),
        and that applies to its tests too."""
        from formulations.dosing import governed_maximum_daily_units_value
        from iid_assessment import views

        assert views.governed_maximum_daily_units_value is governed_maximum_daily_units_value
