"""Controlled units, increment 2: the reviewed unit list, unit-mapping proposals,
and re-resolve of the new potency_expression link.

Records come from `fixtures/iid/iir_ocomm_units_sample.csv`, copied byte-for-byte
from the FDA file (see test_quantity_expression.py): one real row per potency
unit string in the July 2026 IID (20 that state an exact meaning, plus `mg/mg`)
and one maximum-daily-exposure row. The unit list is the committed
`fda_data/reference/controlled_units_v1.json`.
"""

from __future__ import annotations

import csv
import io
import json
from decimal import Decimal
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from audit.models import AuditEvent
from fda_data import controlled_units as cu
from fda_data import lifecycle
from fda_data.models import (
    ControlledUnit,
    FDADataSourceRelease,
    FDAReleaseStatus,
    IIDCalculabilityStatus,
    IIDPrecedentRecord,
    MappingDecisionStatus,
    QuantityExpression,
    UnitMapping,
)
from fda_data.reresolve import ReresolveRefused, reresolve
from fda_data.serializers import TerminologyMappingSerializer
from fda_data.terminology import lookup_unit

HERE = Path(__file__).parent
FIXTURE = HERE / "fixtures" / "iid" / "iir_ocomm_units_sample.csv"
ROWS = list(csv.DictReader(io.StringIO(FIXTURE.read_bytes().decode("latin-1"), newline="")))
LIST_PATH = HERE.parent / "reference" / "controlled_units_v1.json"
LIST = LIST_PATH.read_bytes()
EXACT = sorted(
    r["POTENCY_UNIT"] for r in ROWS if r["POTENCY_UNIT"] and r["POTENCY_UNIT"] != "mg/mg"
)


@pytest.fixture
def doer(user_a, doer_membership):
    return user_a


@pytest.fixture
def vp(vp_user, vp_membership):
    return vp_user


def _load(actor, raw=LIST):
    return cu.load_snapshot(
        raw=raw, filename="controlled_units_v1.json", source_reference="test", actor=actor
    )


def _activate(release, vp):
    release = lifecycle.submit_for_review(release, vp)
    release = lifecycle.approve(release, vp)
    return lifecycle.activate(release, vp)


@pytest.fixture
def active_units(doer, vp):
    release, _ = _load(doer)
    return _activate(release, vp)


@pytest.fixture
def iid_release(db):
    """A not-yet-reviewed IID release holding the real fixture rows."""
    release = FDADataSourceRelease.objects.create(
        dataset_type="fda_iid",
        source_name="FDA IID",
        official_source_reference="iig_july_2026.zip (fixture rows)",
        source_checksum_sha256="a" * 64,
        status=FDAReleaseStatus.REGISTERED,
    )
    for n, row in enumerate(ROWS, start=1):
        IIDPrecedentRecord.objects.create(
            release=release,
            ingredient_name_raw=row["INGREDIENT_NAME"],
            route_raw=row["ROUTE"],
            dosage_form_raw=row["DOSAGE_FORM"],
            potency_amount=Decimal(row["POTENCY_AMOUNT"]) if row["POTENCY_AMOUNT"] else None,
            potency_amount_raw=row["POTENCY_AMOUNT"],
            potency_unit_raw=row["POTENCY_UNIT"],
            maximum_daily_exposure=Decimal(row["MAXIMUM_DAILY_EXPOSURE"])
            if row["MAXIMUM_DAILY_EXPOSURE"]
            else None,
            mde_amount_raw=row["MAXIMUM_DAILY_EXPOSURE"],
            mde_unit_raw=row["MAXIMUM_DAILY_EXPOSURE_UNIT"],
            raw_row_checksum=f"{n:064x}",
            calculability_status=IIDCalculabilityStatus.POTENCY_UNIT_MISSING,
        )
    return release


def _approve_all(statuses=(MappingDecisionStatus.PROPOSED,)):
    """Test approvals only (the API path is covered in TestReviewThroughTheApi)."""
    UnitMapping.objects.filter(status__in=statuses).update(status=MappingDecisionStatus.APPROVED)


# --- the reviewed list ----------------------------------------------------------


class TestReviewedList:
    def test_the_committed_list_covers_exactly_the_exact_iid_strings(self):
        snapshot = cu.parse_snapshot(LIST)
        assert [u["code"] for u in snapshot["units"]] == ["mg", "ml"]
        assert len(snapshot["meanings"]) == 20 == len(EXACT)

    @pytest.mark.parametrize(
        "mutate,message",
        [
            (lambda d: d.update(format="other"), "format"),
            (lambda d: d["meanings"].append(dict(d["meanings"][0])), "listed twice"),
            (
                lambda d: d["meanings"].append(
                    {"family": "mass", "basis": "per_dose_unit", "numerator": "g"}
                ),
                "not a listed unit",
            ),
            (lambda d: d["units"][0].update(factor_to_base="-1"), "positive"),
            (
                lambda d: d["units"].append(
                    {"code": "mg", "symbol": "x", "dimension": "mass", "factor_to_base": "1"}
                ),
                "unique",
            ),
            (lambda d: d["units"][0].update(dimension="percentage"), "mass or volume"),
        ],
    )
    def test_malformed_lists_are_refused(self, mutate, message):
        data = json.loads(LIST)
        mutate(data)
        with pytest.raises(cu.SnapshotError, match=message):
            cu.parse_snapshot(json.dumps(data).encode())


@pytest.mark.django_db
class TestLoad:
    def test_load_registers_a_draft_release_with_the_loader_recorded(self, doer):
        release, summary = _load(doer)
        assert release.dataset_type == "regx_controlled_units"
        assert release.status == FDAReleaseStatus.REGISTERED
        assert release.imported_by == doer
        assert summary == {
            "already_loaded": False,
            "unit_new": 2,
            "unit_unchanged": 0,
            "meaning_new": 20,
            "meaning_unchanged": 0,
        }
        assert QuantityExpression.objects.count() == 20
        # Kept out of the legacy importer's unit lookup (see controlled_units module doc).
        assert set(ControlledUnit.objects.values_list("code", "active")) == {
            ("mg", False),
            ("ml", False),
        }
        assert lookup_unit("mg") is None and lookup_unit("ml") is None

    def test_loading_the_same_bytes_twice_changes_nothing(self, doer):
        first, _ = _load(doer)
        second, summary = _load(doer)
        assert first.pk == second.pk and summary["already_loaded"] is True
        assert QuantityExpression.objects.count() == 20 and ControlledUnit.objects.count() == 2

    def test_a_conflicting_existing_unit_refuses_the_load_and_writes_nothing(self, doer):
        ControlledUnit.objects.create(code="mg", symbol="MG", dimension="mass", active=True)
        with pytest.raises(cu.SnapshotError, match="never changed"):
            _load(doer)
        assert not FDADataSourceRelease.objects.filter(
            dataset_type="regx_controlled_units"
        ).exists()
        assert QuantityExpression.objects.count() == 0
        assert ControlledUnit.objects.get(code="mg").symbol == "MG"

    def test_a_meaning_the_model_cannot_state_refuses_the_load(self, doer):
        data = json.loads(LIST)
        data["meanings"].append(  # mg per mg: mass is not a basis
            {
                "family": "mass",
                "basis": "per_volume",
                "numerator": "mg",
                "denominator_amount": "1",
                "denominator_unit": "mg",
            }
        )
        with pytest.raises(cu.SnapshotError, match="not a volume"):
            _load(doer, json.dumps(data).encode())
        assert QuantityExpression.objects.count() == 0

    def test_the_command_needs_a_real_doer_as_actor(self, doer, vp):
        with pytest.raises(CommandError, match="does not hold"):
            call_command(
                "load_controlled_units",
                str(LIST_PATH),
                "--actor",
                vp.email,
                "--source-reference",
                "t",
            )
        out = io.StringIO()
        call_command(
            "load_controlled_units",
            str(LIST_PATH),
            "--actor",
            doer.email,
            "--source-reference",
            "t",
            stdout=out,
        )
        assert "registered" in out.getvalue() and "meaning_new        20" in out.getvalue()


@pytest.mark.django_db
class TestDraftUntilAVpApproves:
    def test_nothing_is_in_force_until_the_release_is_active(self, doer, vp):
        release, _ = _load(doer)
        assert cu.in_force_expressions() == set()
        release = lifecycle.submit_for_review(release, vp)
        release = lifecycle.approve(release, vp)
        assert cu.in_force_expressions() == set()
        lifecycle.activate(release, vp)
        assert len(cu.in_force_expressions()) == 20

    def test_the_loader_cannot_approve_or_activate(self, doer):
        release, _ = _load(doer)
        release = lifecycle.submit_for_review(release, doer)
        with pytest.raises(lifecycle.SeparationOfDutiesError):
            lifecycle.approve(release, doer)

    def test_a_superseded_list_is_no_longer_in_force(self, doer, vp, active_units):
        data = json.loads(LIST)
        data["meanings"] = data["meanings"][:5]  # v2 drops the per-volume meanings
        v2, _ = _load(doer, json.dumps(data).encode())
        _activate(v2, vp)
        active_units.refresh_from_db()
        assert active_units.status == FDAReleaseStatus.SUPERSEDED
        assert len(cu.in_force_expressions()) == 5


# --- proposals ------------------------------------------------------------------


class TestStrictGrammar:
    @pytest.mark.parametrize("raw", EXACT)
    def test_every_exact_iid_string_states_a_meaning(self, raw):
        assert cu.parse_unit_string(raw) is not None

    @pytest.mark.parametrize(
        "raw",
        [
            "mg/mg",
            "NA",
            "ADJ PH",
            "",
            "mg/0ml",
            "mg / 5ml",
            "mg/5 ml",
            "mcg",
            "g/5ml",
            "%",
            "%w",
            "5ml",
        ],
    )
    def test_anything_else_states_nothing(self, raw):
        assert cu.parse_unit_string(raw) is None

    def test_meanings(self):
        assert cu.parse_unit_string("mg/2.5ml") == cu.StatedMeaning(
            "mass", "per_volume", "mg", Decimal("2.5"), "ml"
        )
        assert cu.parse_unit_string("%w/v") == cu.StatedMeaning(
            "percentage", "w_v", None, None, None
        )
        assert cu.parse_unit_string(" ML ") == cu.StatedMeaning(
            "volume", "per_dose_unit", "ml", None, None
        )


@pytest.mark.django_db
class TestProposals:
    def test_refused_without_an_active_unit_list(self, doer, iid_release):
        _load(doer)  # draft only
        with pytest.raises(cu.ProposalRefused, match="No active controlled-units release"):
            cu.propose_unit_mappings(iid_release, actor=doer)
        assert not UnitMapping.objects.exists()

    def test_exact_strings_are_proposed_and_mg_per_mg_is_reported(
        self, doer, active_units, iid_release
    ):
        report = cu.propose_unit_mappings(iid_release, actor=doer)
        assert report.distinct_strings == 21
        assert sorted(raw for raw, _, _ in report.proposed) == EXACT
        assert report.unclear == [("mg/mg", cu.NO_STATED_MEANING, 1)]
        assert UnitMapping.objects.count() == 20
        assert set(UnitMapping.objects.values_list("status", flat=True)) == {"proposed"}
        m = UnitMapping.objects.get(source_raw_value="mg/5ml")
        assert m.controlled_unit is None and str(m.quantity_expression) == "mg/5mL"
        event = AuditEvent.objects.filter(event_type="fda_data.mapping.proposed").first()
        assert event.actor_id == doer.pk and event.payload["rule"] == "exact_unit_string_grammar"

    def test_idempotent(self, doer, active_units, iid_release):
        cu.propose_unit_mappings(iid_release, actor=doer)
        again = cu.propose_unit_mappings(iid_release, actor=doer)
        assert again.proposed == [] and len(again.already_mapped) == 20
        assert UnitMapping.objects.count() == 20

    def test_dry_run_writes_nothing(self, doer, active_units, iid_release):
        report = cu.propose_unit_mappings(iid_release, actor=doer, dry_run=True)
        assert len(report.proposed) == 20 and not UnitMapping.objects.exists()

    def test_a_meaning_not_in_the_active_list_is_reported_not_guessed(self, doer, vp, iid_release):
        data = json.loads(LIST)
        data["meanings"] = [m for m in data["meanings"] if m.get("denominator_amount") != "5"]
        release, _ = _load(doer, json.dumps(data).encode())
        _activate(release, vp)
        report = cu.propose_unit_mappings(iid_release, actor=doer)
        unclear = {raw: why for raw, why, _ in report.unclear}
        assert unclear == {
            "mg/5ml": cu.NOT_IN_FORCE,
            "ml/5ml": cu.NOT_IN_FORCE,
            "mg/mg": cu.NO_STATED_MEANING,
        }

    def test_the_command(self, doer, active_units, iid_release):
        out = io.StringIO()
        call_command(
            "propose_unit_mappings",
            "--actor",
            doer.email,
            "--release",
            str(iid_release.public_id),
            stdout=out,
        )
        text = out.getvalue()
        assert "proposed 20" in text and "UNCLEAR (no proposal): 'mg/mg'" in text
        assert "Nothing was approved" in text

    def test_the_review_list_shows_the_meaning(self, doer, active_units, iid_release):
        cu.propose_unit_mappings(iid_release, actor=doer)
        m = UnitMapping.objects.get(source_raw_value="%w/v")
        assert (
            TerminologyMappingSerializer.from_instance("unit", m, 1)["proposed_controlled_value"]
            == "%w/v"
        )


# --- re-resolve -----------------------------------------------------------------


@pytest.mark.django_db
class TestReresolve:
    def test_proposed_mappings_fill_nothing(self, doer, active_units, iid_release):
        cu.propose_unit_mappings(iid_release, actor=doer)
        assert [c for c in reresolve(iid_release) if c.field == "potency_expression"] == []

    def test_approved_mappings_fill_empty_links_only(self, doer, active_units, iid_release):
        cu.propose_unit_mappings(iid_release, actor=doer)
        _approve_all()
        changes = [c for c in reresolve(iid_release, actor=doer) if c.field == "potency_expression"]
        assert len(changes) == 20
        record = IIDPrecedentRecord.objects.get(release=iid_release, potency_unit_raw="mg/5ml")
        assert str(record.potency_expression) == "mg/5mL" and record.potency_amount == Decimal("45")
        # The legacy unit link stays empty, so the record never becomes "calculable"
        # for the old matching path through this link.
        assert record.potency_unit_normalized is None
        assert record.calculability_status != IIDCalculabilityStatus.CALCULABLE
        # mg/mg and the daily-exposure row stay empty.
        assert (
            IIDPrecedentRecord.objects.filter(
                release=iid_release, potency_expression__isnull=True
            ).count()
            == 2
        )
        # Running again changes nothing; an existing link is never overwritten.
        assert [c for c in reresolve(iid_release) if c.field == "potency_expression"] == []

    def test_an_existing_link_is_never_overwritten(self, doer, active_units, iid_release):
        cu.propose_unit_mappings(iid_release, actor=doer)
        _approve_all()
        record = IIDPrecedentRecord.objects.get(release=iid_release, potency_unit_raw="mg/5ml")
        other = QuantityExpression.objects.get(family="percentage", basis="w_w")
        record.potency_expression = other
        record.save()
        reresolve(iid_release)
        record.refresh_from_db()
        assert record.potency_expression == other

    def test_only_meanings_in_force(self, doer, vp, active_units, iid_release):
        cu.propose_unit_mappings(iid_release, actor=doer)
        _approve_all()
        data = json.loads(LIST)
        data["meanings"] = data["meanings"][:5]
        v2, _ = _load(doer, json.dumps(data).encode())
        _activate(v2, vp)  # per-volume meanings are no longer in force
        filled = {c.raw_value for c in reresolve(iid_release) if c.field == "potency_expression"}
        assert filled == {"mg", "ml", "%w/w", "%w/v", "%v/v"}

    def test_only_before_review(self, doer, vp, active_units, iid_release):
        cu.propose_unit_mappings(iid_release, actor=doer)
        _approve_all()
        lifecycle.submit_for_review(iid_release, vp)
        with pytest.raises(ReresolveRefused):
            reresolve(iid_release)
        assert not IIDPrecedentRecord.objects.filter(potency_expression__isnull=False).exists()

    def test_dry_run_and_audit(self, doer, active_units, iid_release):
        cu.propose_unit_mappings(iid_release, actor=doer)
        _approve_all()
        assert (
            len(
                [c for c in reresolve(iid_release, dry_run=True) if c.field == "potency_expression"]
            )
            == 20
        )
        assert not IIDPrecedentRecord.objects.filter(potency_expression__isnull=False).exists()
        reresolve(iid_release, actor=doer)
        events = AuditEvent.objects.filter(event_type="fda_data.record.terminology_reresolved")
        assert events.count() == 20
        assert any(f["field"] == "potency_expression" for e in events for f in e.payload["filled"])


# --- review through the real API (VP approves; reviewer != approver) -------------


@pytest.mark.django_db
class TestReviewThroughTheApi:
    def test_vp_activates_the_list_and_approves_a_unit_mapping(
        self, doer, api_client_doer, api_client_vp, api_client_reviewer, iid_release
    ):
        release, _ = _load(doer)
        base = f"/api/regx/v1/fda-data/releases/{release.public_id}"
        assert api_client_doer.post(f"{base}/submit-review/", {}, format="json").status_code == 200
        refused = api_client_doer.post(f"{base}/approve/", {}, format="json")
        assert refused.status_code == 403
        assert api_client_vp.post(f"{base}/approve/", {}, format="json").status_code == 200
        assert api_client_vp.post(f"{base}/activate/", {}, format="json").status_code == 200
        assert len(cu.in_force_expressions()) == 20

        cu.propose_unit_mappings(iid_release, actor=doer)
        mapping = UnitMapping.objects.get(source_raw_value="mg")
        mbase = f"/api/regx/v1/fda-data/mappings/{mapping.public_id}"
        assert (
            api_client_reviewer.post(
                f"{mbase}/submit-review/", {"reason": "checked"}, format="json"
            ).status_code
            == 200
        )
        assert (
            api_client_reviewer.post(
                f"{mbase}/approve/", {"reason": "x"}, format="json"
            ).status_code
            == 403
        )
        resp = api_client_vp.post(
            f"{mbase}/approve/", {"reason": "mg per dose unit"}, format="json"
        )
        assert resp.status_code == 200, resp.content
        mapping.refresh_from_db()
        assert mapping.status == MappingDecisionStatus.APPROVED
        changes = [c for c in reresolve(iid_release) if c.field == "potency_expression"]
        assert [(c.raw_value, c.new_code) for c in changes] == [("mg", "mg per dose unit")]
