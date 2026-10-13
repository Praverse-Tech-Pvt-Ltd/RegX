"""propose_iid_mappings: PROPOSED mappings only for exact matches to ACTIVE SPL
terms; everything else reported; idempotent; never approves anything.

Uses the 11 real IID rows in `fixtures/iid/iir_ocomm_sample.csv` and lines of
the saved SPL snapshots in `fixtures/spl/` (activated through the lifecycle).
"""

from __future__ import annotations

import datetime
import io
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from audit.models import AuditEvent
from fda_data import lifecycle
from fda_data.audit_events import FdaDataEvent
from fda_data.mapping_proposals import propose_iid_mappings
from fda_data.models import (
    ControlledRoute,
    DosageFormMapping,
    FDADataSourceRelease,
    MappingDecisionStatus,
    RouteMapping,
)
from fda_data.spl_terminology import load_snapshot

FIXTURES = Path(__file__).parent / "fixtures"
IID = (FIXTURES / "iid" / "iir_ocomm_sample.csv").read_bytes()
SPL_ROUTES = (FIXTURES / "spl" / "route_administration_sample.csv").read_bytes()
SPL_FORMS = (FIXTURES / "spl" / "dosage_forms_sample.csv").read_bytes()
#: The 11 fixture rows use 5 routes and 10 dosage forms. The route fixture
#: lists ORAL (and DENTAL etc.), so ORAL is the one exact route match. The
#: dosage-form snapshot is the fixture (which includes "AEROSOL, METERED") plus
#: two more real lines of the saved SPL CSV (OINTMENT line 90, TABLET line 135).
FORMS_SNAPSHOT = SPL_FORMS + b"OINTMENT,C42966\nTABLET,C42998\n"


def _iid_release(tmp_path):
    path = tmp_path / "IIR_OCOMM.csv"
    path.write_bytes(IID)
    call_command(
        "import_fda_release",
        str(path),
        dataset_type="fda_iid",
        source_reference="Test fixture: real FDA rows",
        stdout=io.StringIO(),
    )
    return FDADataSourceRelease.objects.get(dataset_type="fda_iid")


def _activate_spl(loader, approver):
    for list_name, raw in (("routes", SPL_ROUTES), ("dosage-forms", FORMS_SNAPSHOT)):
        release, _ = load_snapshot(
            list_name=list_name,
            raw=raw,
            filename=f"{list_name}.csv",
            page_date=datetime.date(2021, 10, 29),
            source_reference="test",
            actor=loader,
        )
        lifecycle.submit_for_review(release, loader)
        lifecycle.approve(release, approver)
        lifecycle.activate(release, approver)


@pytest.mark.django_db
class TestProposals:
    def test_exact_active_matches_are_proposed_and_the_rest_reported(
        self, tmp_path, user_a, vp_user
    ):
        release = _iid_release(tmp_path)
        _activate_spl(user_a, vp_user)
        reports = propose_iid_mappings(release)
        routes, forms = reports["route"], reports["dosage_form"]
        assert routes.distinct_values == 5 and forms.distinct_values == 10
        assert routes.proposed == [("ORAL", "C38288")]
        assert sorted(forms.proposed) == [
            ("AEROSOL, METERED", "C42960"),
            ("OINTMENT", "C42966"),
            ("TABLET", "C42998"),
        ]
        assert {raw for raw, _ in routes.not_exact} == {
            "ENDOTRACHEAL",
            "RESPIRATORY (INHALATION)",
            "TOPICAL",
            "TRANSDERMAL",
        }
        assert ("TABLET, FILM COATED", 2) in forms.not_exact
        mapping = RouteMapping.objects.get(source_raw_value="ORAL")
        assert mapping.status == MappingDecisionStatus.PROPOSED
        assert mapping.is_current is True
        assert mapping.controlled_route.code == "C38288"
        assert AuditEvent.objects.filter(event_type=FdaDataEvent.MAPPING_PROPOSED).count() == 4

    def test_never_creates_an_approved_mapping(self, tmp_path, user_a, vp_user):
        release = _iid_release(tmp_path)
        _activate_spl(user_a, vp_user)
        propose_iid_mappings(release)
        for model in (RouteMapping, DosageFormMapping):
            assert not model.objects.exclude(status=MappingDecisionStatus.PROPOSED).exists()
        # And nothing resolves: lookups use approved mappings only.
        assert not release.iid_records.exclude(route_normalized=None).exists()

    def test_running_twice_creates_nothing_new(self, tmp_path, user_a, vp_user):
        release = _iid_release(tmp_path)
        _activate_spl(user_a, vp_user)
        propose_iid_mappings(release)
        counts = (
            RouteMapping.objects.count(),
            DosageFormMapping.objects.count(),
            AuditEvent.objects.count(),
        )
        reports = propose_iid_mappings(release)
        assert reports["route"].proposed == []
        assert reports["route"].already_mapped == [("ORAL", "proposed")]
        assert (
            RouteMapping.objects.count(),
            DosageFormMapping.objects.count(),
            AuditEvent.objects.count(),
        ) == counts

    def test_draft_and_retired_terms_are_never_proposed(self, tmp_path, user_a):
        release = _iid_release(tmp_path)
        load_snapshot(  # loaded but never activated: stays draft
            list_name="routes",
            raw=SPL_ROUTES,
            filename="routes.csv",
            page_date=datetime.date(2021, 10, 29),
            source_reference="test",
            actor=user_a,
        )
        ControlledRoute.objects.create(
            code="C38304", canonical_label="TOPICAL", lifecycle="retired"
        )
        reports = propose_iid_mappings(release)
        assert reports["route"].proposed == []
        assert not RouteMapping.objects.exists()

    def test_case_and_spaces_are_ignored_but_nothing_else(self, tmp_path):
        release = _iid_release(tmp_path)
        ControlledRoute.objects.create(code="C38288", canonical_label=" oral ", lifecycle="active")
        ControlledRoute.objects.create(
            code="C00002", canonical_label="TOPICALS", lifecycle="active"
        )
        reports = propose_iid_mappings(release)
        assert reports["route"].proposed == [("ORAL", "C38288")]
        assert ("TOPICAL", 2) in reports["route"].not_exact

    def test_dry_run_writes_nothing(self, tmp_path, user_a, vp_user):
        release = _iid_release(tmp_path)
        _activate_spl(user_a, vp_user)
        reports = propose_iid_mappings(release, dry_run=True)
        assert reports["route"].proposed == [("ORAL", "C38288")]
        assert not RouteMapping.objects.exists() and not DosageFormMapping.objects.exists()


@pytest.mark.django_db
class TestCommand:
    def test_reports_counts_and_not_exact_values(self, tmp_path, user_a, vp_user):
        release = _iid_release(tmp_path)
        _activate_spl(user_a, vp_user)
        out = io.StringIO()
        call_command("propose_iid_mappings", release=str(release.public_id), stdout=out)
        text = out.getvalue()
        assert "route: 5 distinct values | proposed 1 | already mapped 0 | not exact 4" in text
        assert "NOT EXACT (no proposal): 'TOPICAL'" in text
        assert "Nothing was approved" in text

    def test_needs_an_active_release_or_an_explicit_one(self, tmp_path):
        _iid_release(tmp_path)  # registered, not active
        with pytest.raises(CommandError, match="No active IID release"):
            call_command("propose_iid_mappings", stdout=io.StringIO())
