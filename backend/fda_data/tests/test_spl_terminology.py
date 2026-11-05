"""load_spl_terminology: FDA SPL routes and dosage forms as controlled vocabulary.

Fixtures in `fixtures/spl/` are lines copied from the CSV snapshots of FDA's
SPL pages saved on 2026-10-13 (route list: first 5 terms plus ORAL; dosage
forms: first 3 terms, two of them quoted because they contain a comma).
"""

from __future__ import annotations

import datetime
import io
from pathlib import Path

import pytest
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.core.management.base import CommandError

from fda_data import lifecycle
from fda_data.dispatch import UNSUPPORTED_REASONS
from fda_data.models import (
    ControlledDosageForm,
    ControlledRoute,
    FDADataSourceRelease,
    FdaImportRowResult,
    FDAReleaseStatus,
)
from fda_data.spl_terminology import SnapshotError, load_snapshot, parse_snapshot
from fda_data.tests._loader import loader_email

FIXTURES = Path(__file__).parent / "fixtures" / "spl"
ROUTES = (FIXTURES / "route_administration_sample.csv").read_bytes()
FORMS = (FIXTURES / "dosage_forms_sample.csv").read_bytes()
ROUTE_PAGE_DATE = datetime.date(2021, 10, 29)


def _load(raw=ROUTES, list_name="routes", page_date=ROUTE_PAGE_DATE, actor=None):
    return load_snapshot(
        list_name=list_name,
        raw=raw,
        filename=f"{list_name}.csv",
        page_date=page_date,
        source_reference="Test fixture: lines from the FDA SPL page saved 2026-10-13",
        actor=actor,
    )


def _activate(release, loader, approver):
    lifecycle.submit_for_review(release, loader)
    lifecycle.approve(release, approver)
    return lifecycle.activate(release, approver)


def _snapshot(*rows: tuple[str, str]) -> bytes:
    lines = ["spl_term,nci_code", *(f'"{t}",{c}' if "," in t else f"{t},{c}" for t, c in rows)]
    return ("\n".join(lines) + "\n").encode()


class TestParseSnapshot:
    def test_real_lines_parse_with_quoted_commas(self):
        assert parse_snapshot(FORMS) == [
            ("AEROSOL", "C42887"),
            ("AEROSOL, FOAM", "C42888"),
            ("AEROSOL, METERED", "C42960"),
        ]

    @pytest.mark.parametrize(
        "raw,match",
        [
            (b"term,code\nORAL,C38288\n", "header"),
            (b"spl_term,nci_code\n", "no terms"),
            (b"spl_term,nci_code\nORAL,38288\n", "not an NCI Thesaurus code"),
            (b"spl_term,nci_code\n,C38288\n", "empty SPL term"),
            (b"spl_term,nci_code\nORAL,C38288,extra\n", "expected 2 fields"),
            (b"spl_term,nci_code\nORAL,C38288\nORAL2,C38288\n", "Duplicate code"),
            (b"spl_term,nci_code\nORAL,C38288\noral,C99999\n", "Duplicate term"),
            (b"spl_term,nci_code\nOR\xff,C38288\n", "not UTF-8"),
        ],
    )
    def test_malformed_snapshots_are_refused(self, raw, match):
        with pytest.raises(SnapshotError, match=match):
            parse_snapshot(raw)


@pytest.mark.django_db
class TestLoad:
    def test_load_creates_draft_terms_coded_by_nci(self):
        release, summary = _load()
        assert summary["new_term"] == 6 and summary["already_loaded"] is False
        oral = ControlledRoute.objects.get(code="C38288")
        assert oral.canonical_label == "ORAL"
        assert oral.lifecycle == "draft"
        assert "NCI Thesaurus" in oral.fda_source and "2021-10-29" in oral.fda_source
        assert release.dataset_type == "fda_route_terminology"
        assert release.status == FDAReleaseStatus.REGISTERED
        assert release.publication_date == ROUTE_PAGE_DATE
        assert release.record_count_imported == 6
        assert FdaImportRowResult.objects.filter(release=release).count() == 6

    def test_loading_twice_changes_nothing(self):
        first, _ = _load()
        before = list(ControlledRoute.objects.order_by("code").values())
        second, summary = _load()
        assert second.pk == first.pk
        assert summary["already_loaded"] is True
        assert FDADataSourceRelease.objects.count() == 1
        assert FdaImportRowResult.objects.count() == 6
        assert list(ControlledRoute.objects.order_by("code").values()) == before

    def test_dosage_forms_load_into_their_own_vocabulary(self):
        release, _ = _load(raw=FORMS, list_name="dosage-forms", page_date=datetime.date(2022, 2, 3))
        assert release.dataset_type == "fda_dosage_form_terminology"
        assert ControlledDosageForm.objects.get(code="C42888").canonical_label == "AEROSOL, FOAM"
        assert ControlledRoute.objects.count() == 0

    def test_vocabulary_is_platform_level(self):
        for model in (ControlledRoute, ControlledDosageForm):
            assert "tenant" not in {f.name for f in model._meta.get_fields()}

    def test_the_generic_release_api_still_refuses_terminology(self):
        assert "load_spl_terminology" in UNSUPPORTED_REASONS["fda_route_terminology"]


@pytest.mark.django_db
class TestActivation:
    def test_terms_become_active_only_when_the_release_is_activated(self, user_a, vp_user):
        release, _ = _load(actor=user_a)
        lifecycle.submit_for_review(release, user_a)
        assert set(ControlledRoute.objects.values_list("lifecycle", flat=True)) == {"draft"}
        with pytest.raises(PermissionDenied):
            lifecycle.approve(release, user_a)  # the loader cannot approve
        lifecycle.approve(release, vp_user)
        assert set(ControlledRoute.objects.values_list("lifecycle", flat=True)) == {"draft"}
        lifecycle.activate(release, vp_user)
        assert set(ControlledRoute.objects.values_list("lifecycle", flat=True)) == {"active"}
        assert ControlledRoute.objects.filter(active_release=release).count() == 6

    def test_a_new_version_changes_nothing_until_it_is_activated(self, user_a, vp_user):
        v1, _ = _load(actor=user_a)
        _activate(v1, user_a, vp_user)
        # v2: ORAL relabelled, DENTAL dropped, NASAL added; the rest unchanged.
        v2_raw = _snapshot(
            ("AURICULAR (OTIC)", "C38192"),
            ("BUCCAL", "C38193"),
            ("CONJUNCTIVAL", "C38194"),
            ("CUTANEOUS", "C38675"),
            ("ORAL (BY MOUTH)", "C38288"),
            ("NASAL", "C38284"),
        )
        v2, summary = _load(raw=v2_raw, page_date=datetime.date(2026, 1, 1), actor=user_a)
        assert summary == {
            "already_loaded": False,
            "terms": 6,
            "new_term": 1,
            "unchanged": 4,
            "label_changed": 1,
            "not_in_snapshot": 1,
        }
        oral = ControlledRoute.objects.get(code="C38288")
        assert (oral.canonical_label, oral.lifecycle) == ("ORAL", "active")
        assert ControlledRoute.objects.get(code="C38197").lifecycle == "active"  # DENTAL
        assert ControlledRoute.objects.get(code="C38284").lifecycle == "draft"  # NASAL

        _activate(v2, user_a, vp_user)
        oral.refresh_from_db()
        assert oral.canonical_label == "ORAL (BY MOUTH)"
        assert oral.aliases == ["ORAL"]
        assert oral.active_release_id == v2.pk
        assert ControlledRoute.objects.get(code="C38197").lifecycle == "retired"
        assert ControlledRoute.objects.get(code="C38284").lifecycle == "active"
        v1.refresh_from_db()
        assert v1.status == FDAReleaseStatus.SUPERSEDED

    def test_activating_a_route_release_leaves_dosage_forms_alone(self, user_a, vp_user):
        forms, _ = _load(raw=FORMS, list_name="dosage-forms", page_date=datetime.date(2022, 2, 3))
        routes, _ = _load(actor=user_a)
        _activate(routes, user_a, vp_user)
        assert set(ControlledDosageForm.objects.values_list("lifecycle", flat=True)) == {"draft"}


@pytest.mark.django_db
class TestCommand:
    def _run(self, tmp_path, raw=ROUTES, **extra):
        path = tmp_path / "route-administration.csv"
        path.write_bytes(raw)
        out = io.StringIO()
        call_command(
            "load_spl_terminology",
            str(path),
            list="routes",
            page_date=extra.pop("page_date", "2021-10-29"),
            source_reference="FDA SPL route page, saved 2026-10-13",
            actor=loader_email(),
            stdout=out,
            **extra,
        )
        return out.getvalue()

    def test_loads_and_reports_counts(self, tmp_path):
        out = self._run(tmp_path)
        assert "new terms (draft)  6" in out
        assert ControlledRoute.objects.count() == 6

    def test_second_run_reports_nothing_changed(self, tmp_path):
        self._run(tmp_path)
        out = self._run(tmp_path)
        assert "already loaded" in out
        assert FDADataSourceRelease.objects.count() == 1

    def test_dry_run_writes_nothing(self, tmp_path):
        out = self._run(tmp_path, dry_run=True)
        assert "terms in snapshot  6" in out
        assert ControlledRoute.objects.count() == 0
        assert FDADataSourceRelease.objects.count() == 0

    def test_bad_page_date_is_refused(self, tmp_path):
        with pytest.raises(CommandError, match="YYYY-MM-DD"):
            self._run(tmp_path, page_date="29/10/2021")

    def test_malformed_snapshot_leaves_nothing_behind(self, tmp_path):
        with pytest.raises(CommandError, match="NCI Thesaurus code"):
            self._run(tmp_path, raw=b"spl_term,nci_code\nORAL,38288\n")
        assert FDADataSourceRelease.objects.count() == 0
