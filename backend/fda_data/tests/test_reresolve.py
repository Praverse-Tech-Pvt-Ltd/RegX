"""reresolve_terminology: fill empty route/dosage-form links from approved
mappings, only before review, never overwriting. Plus the submit-review guard.

Uses the 11 real IID rows in `fixtures/iid/iir_ocomm_sample.csv`. Six of them
have route ORAL; one (ACRYLATES COPOLYMER) is ORAL + TABLET.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from audit.models import AuditEvent
from fda_data import lifecycle
from fda_data.audit_events import FdaDataEvent
from fda_data.models import (
    ControlledDosageForm,
    ControlledRoute,
    DosageFormMapping,
    FDADataSourceRelease,
    FDAReleaseStatus,
    IIDCalculabilityStatus,
    IIDPrecedentRecord,
    RouteMapping,
)
from fda_data.reresolve import ReresolveRefused, count_unmapped, reresolve
from fda_data.tests._loader import loader_email

FIXTURES = Path(__file__).parent / "fixtures"
IID = (FIXTURES / "iid" / "iir_ocomm_sample.csv").read_bytes()
PRODUCTS = (FIXTURES / "orange_book" / "products_sample.txt").read_bytes()
URL = "/api/regx/v1/fda-data/releases/{}/submit-review/"


def _import(tmp_path, data=IID, name="IIR_OCOMM.csv", dataset_type="fda_iid"):
    path = tmp_path / name
    path.write_bytes(data)
    call_command(
        "import_fda_release",
        str(path),
        dataset_type=dataset_type,
        source_reference="Test fixture: real FDA rows",
        actor=loader_email(),
        stdout=io.StringIO(),
    )
    return FDADataSourceRelease.objects.latest("created_at")


def _approve(raw_route="ORAL", raw_form="TABLET"):
    route = ControlledRoute.objects.create(
        code="C38288", canonical_label="ORAL", lifecycle="active"
    )
    form = ControlledDosageForm.objects.create(
        code="C42998", canonical_label="TABLET", lifecycle="active"
    )
    RouteMapping.objects.create(
        source_dataset="fda_iid",
        source_raw_value=raw_route,
        controlled_route=route,
        status="approved",
    )
    DosageFormMapping.objects.create(
        source_dataset="fda_iid",
        source_raw_value=raw_form,
        controlled_dosage_form=form,
        status="approved",
    )
    return route, form


def _rec(name, route, form):
    return IIDPrecedentRecord.objects.get(
        ingredient_name_raw=name, route_raw=route, dosage_form_raw=form
    )


def _events(event_type):
    return AuditEvent.objects.filter(event_type=event_type).count()


@pytest.mark.django_db
class TestReresolve:
    def test_dry_run_reports_and_writes_nothing(self, tmp_path):
        release = _import(tmp_path)
        _approve()
        changes = reresolve(release, dry_run=True)
        assert sorted((c.field, c.raw_value) for c in changes) == [
            ("dosage_form", "TABLET"),
            *[("route", "ORAL")] * 6,
        ]
        assert not IIDPrecedentRecord.objects.exclude(route_normalized=None).exists()
        assert _events(FdaDataEvent.RECORD_TERMINOLOGY_RERESOLVED) == 0
        assert _events(FdaDataEvent.RELEASE_TERMINOLOGY_RERESOLVED) == 0

    def test_fills_empty_links_and_audits_each_record(self, tmp_path):
        release = _import(tmp_path)
        route, form = _approve()
        assert count_unmapped(release) == 11
        changes = reresolve(release)
        assert len(changes) == 7
        acrylates = _rec("ACRYLATES COPOLYMER", "ORAL", "TABLET")
        assert (acrylates.route_normalized, acrylates.dosage_form_normalized) == (route, form)
        # Daily-exposure-only row: now blocked one step later, on potency.
        assert acrylates.calculability_status == IIDCalculabilityStatus.POTENCY_MISSING
        assert IIDPrecedentRecord.objects.filter(route_normalized=route).count() == 6
        assert count_unmapped(release) == 10  # only ACRYLATES has both links
        assert _events(FdaDataEvent.RECORD_TERMINOLOGY_RERESOLVED) == 6
        assert _events(FdaDataEvent.RELEASE_TERMINOLOGY_RERESOLVED) == 1
        event = AuditEvent.objects.get(
            event_type=FdaDataEvent.RECORD_TERMINOLOGY_RERESOLVED,
            resource_id=str(acrylates.public_id),
        )
        assert {f["field"] for f in event.payload["filled"]} == {"route", "dosage_form"}
        assert all(f["old"] is None for f in event.payload["filled"])

    def test_running_twice_changes_nothing(self, tmp_path):
        release = _import(tmp_path)
        _approve()
        reresolve(release)
        before = list(IIDPrecedentRecord.objects.order_by("pk").values())
        events = AuditEvent.objects.count()
        assert reresolve(release) == []
        assert list(IIDPrecedentRecord.objects.order_by("pk").values()) == before
        assert AuditEvent.objects.count() == events

    def test_never_changes_or_clears_an_existing_link(self, tmp_path):
        release = _import(tmp_path)
        other = ControlledRoute.objects.create(
            code="C00001", canonical_label="OTHER", lifecycle="active"
        )
        acacia = _rec("ACACIA", "ORAL", "TABLET, FILM COATED")
        acacia.route_normalized = other
        acacia.save(update_fields=["route_normalized"])
        _approve()
        reresolve(release)
        acacia.refresh_from_db()
        assert acacia.route_normalized == other

    def test_only_approved_current_mappings_are_used(self, tmp_path):
        release = _import(tmp_path)
        topical = ControlledRoute.objects.create(
            code="C38304", canonical_label="TOPICAL", lifecycle="active"
        )
        RouteMapping.objects.create(
            source_dataset="fda_iid",
            source_raw_value="TOPICAL",
            controlled_route=topical,
            status="proposed",
        )
        RouteMapping.objects.create(
            source_dataset="fda_iid",
            source_raw_value="TOPICAL",
            controlled_route=topical,
            status="approved",
            is_current=False,
        )
        assert reresolve(release) == []

    @pytest.mark.parametrize("target", ["under_review", "active"])
    def test_refused_once_submitted(self, tmp_path, user_a, vp_user, target):
        release = _import(tmp_path)
        _approve()
        lifecycle.submit_for_review(release, user_a)
        if target == "active":
            lifecycle.approve(release, vp_user)
            lifecycle.activate(release, vp_user)
        with pytest.raises(ReresolveRefused, match="not been submitted for review"):
            reresolve(release)
        with pytest.raises(CommandError, match="not been submitted for review"):
            call_command("reresolve_terminology", str(release.public_id), stdout=io.StringIO())
        assert not IIDPrecedentRecord.objects.exclude(route_normalized=None).exists()

    def test_orange_book_is_not_wired_up_yet(self, tmp_path):
        release = _import(tmp_path, PRODUCTS, "products.txt", "orange_book_products")
        with pytest.raises(ReresolveRefused, match="not available for orange_book_products"):
            reresolve(release)

    def test_command_dry_run_then_apply(self, tmp_path):
        release = _import(tmp_path)
        _approve()
        out = io.StringIO()
        call_command("reresolve_terminology", str(release.public_id), dry_run=True, stdout=out)
        assert "would fill links             7" in out.getvalue()
        assert "nothing was written" in out.getvalue()
        assert not IIDPrecedentRecord.objects.exclude(route_normalized=None).exists()
        out = io.StringIO()
        call_command("reresolve_terminology", str(release.public_id), stdout=out)
        assert "filled links             7" in out.getvalue()
        assert "records missing a link after   10" in out.getvalue()


@pytest.mark.django_db
class TestSubmitReviewGuard:
    def test_unmapped_rows_block_submission_without_confirm(self, tmp_path, api_client_doer):
        release = _import(tmp_path)
        response = api_client_doer.post(URL.format(release.public_id), {}, format="json")
        assert response.status_code == 409
        assert response.data["error_code"] == "unmapped_rows"
        assert response.data["unmapped_count"] == 11
        release.refresh_from_db()
        assert release.status == FDAReleaseStatus.REGISTERED

    def test_confirm_flag_submits_with_a_warning_and_audits_the_count(
        self, tmp_path, api_client_doer
    ):
        release = _import(tmp_path)
        response = api_client_doer.post(
            URL.format(release.public_id), {"confirm_unmapped": True}, format="json"
        )
        assert response.status_code == 200
        assert response.data["status"] == FDAReleaseStatus.UNDER_REVIEW
        assert "11 unmapped" in response.data["warning"]
        event = AuditEvent.objects.get(
            event_type=FdaDataEvent.RELEASE_SUBMITTED_FOR_REVIEW, resource_id=str(release.public_id)
        )
        assert event.payload["unmapped_rows_confirmed"] == 11

    def test_fully_mapped_release_needs_no_confirm(self, tmp_path, api_client_doer):
        _approve()
        header, *rows = IID.split(b"\r\n")
        acrylates = next(r for r in rows if r.startswith(b"ACRYLATES COPOLYMER,ORAL,TABLET,"))
        release = _import(tmp_path, header + b"\r\n" + acrylates + b"\r\n", "one_row.csv")
        response = api_client_doer.post(URL.format(release.public_id), {}, format="json")
        assert response.status_code == 200
        assert "warning" not in response.data

    def test_orange_book_release_is_not_affected(self, tmp_path, api_client_doer):
        release = _import(tmp_path, PRODUCTS, "products.txt", "orange_book_products")
        response = api_client_doer.post(URL.format(release.public_id), {}, format="json")
        assert response.status_code == 200
