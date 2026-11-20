# ruff: noqa: F811  (units_in_force is a pytest fixture imported by name)
"""QA-19 follow-up: per-volume amounts are refused on every clearly solid SPL dosage form.

QA-19 (#143) added POWDER and GRANULE. PILL, FILM, PATCH, INSERT, STRIP and the
other solid SPL forms still accepted mg/5mL, %w/v or %v/v. "Clearly solid" stays
narrow: a liquid on a carrier (CLOTH, SWAB, DRESSING), semi-solids (CREAM, GEL,
PASTE, POULTICE, ...) and non-forms (KIT, SYSTEM, NOT APPLICABLE, CELLULAR SHEET)
are not refused here; that is a reviewer decision.

The full SPL list outcome is pinned in test_qa19_per_volume_on_solid_forms.py.
"""

from __future__ import annotations

import pytest

from formulations.dosage_forms import is_solid_dosage_form

from .test_input_validation_qa import (  # noqa: F401
    _add,
    _components_url,
    _err,
    _meaning,
    units_in_force,
)
from .test_qa19_per_volume_on_solid_forms import _spl_terms, mg_per_5ml

#: Accepted before this change, refused now (26 SPL terms).
NEWLY_REFUSED = {
    "C42892": "BAR, CHEWABLE",
    "C42890": "BEAD",
    "C134876": "CHEWABLE GEL",
    "C42901": "CRYSTAL",
    "C43525": "DISC",
    "C185352": "DRUG-ELUTING CONTACT LENS",
    "C60926": "FIBER, EXTENDED RELEASE",
    "C42932": "FILM",
    "C42920": "FILM, EXTENDED RELEASE",
    "C42984": "FILM, SOLUBLE",
    "C42937": "GLOBULE",
    "C60933": "INSERT",
    "C42922": "INSERT, EXTENDED RELEASE",
    "C47915": "INTRAUTERINE DEVICE",
    "C42952": "LIPSTICK",
    "C42968": "PATCH",
    "C42923": "PATCH, EXTENDED RELEASE",
    "C42911": "PATCH, EXTENDED RELEASE, ELECTRICALLY CONTROLLED",
    "C25394": "PILL",
    "C42970": "PLASTER",
    "C60988": "RING",
    "C47912": "SPONGE",
    "C42991": "STICK",
    "C47914": "STRIP",
    "C47892": "TAMPON",
    "C47897": "TAPE",
}

#: Deliberately NOT refused (reviewer decision): liquid on a carrier, semi-solid, or not a form.
LEFT_FOR_REVIEW = [
    "CLOTH",
    "SWAB",
    "DRESSING",
    "POULTICE",
    "PASTE",
    "KIT",
    "SYSTEM",
    "CELLULAR SHEET",
]


def test_the_newly_refused_terms_are_spl_terms_with_these_codes():
    assert {c: t for c, t in _spl_terms() if c in NEWLY_REFUSED} == NEWLY_REFUSED


@pytest.mark.parametrize("term", list(NEWLY_REFUSED.values()))
def test_solid(term):
    assert is_solid_dosage_form(term)


@pytest.mark.parametrize("term", LEFT_FOR_REVIEW)
def test_not_refused_here(term):
    assert not is_solid_dosage_form(term)


@pytest.mark.django_db
class TestThroughTheComponentApi:
    @pytest.mark.parametrize(
        "form", ["PILL", "FILM", "PATCH", "INSERT", "STRIP", "RING", "LIPSTICK", "TAPE"]
    )
    def test_per_volume_is_refused(self, api_client_a, units_in_force, form):
        url = _components_url(api_client_a, f"SOLID-{form[:10]}", form)
        resp = _add(api_client_a, url, "40", "mg", mg_per_5ml())
        assert resp.status_code == 400, resp.json()
        assert "a solid" in _err(resp)["quantity_expression_public_id"][0]

    @pytest.mark.parametrize("form", ["FILM", "PATCH"])
    def test_per_dose_unit_is_still_accepted(self, api_client_a, units_in_force, form):
        url = _components_url(api_client_a, f"SOLID-OK-{form}", form)
        resp = _add(api_client_a, url, "40", "mg")
        assert resp.status_code == 201, resp.json()

    @pytest.mark.parametrize("form", ["CLOTH", "SWAB", "SOLUTION"])
    def test_carriers_and_liquids_still_accept_per_volume(self, api_client_a, units_in_force, form):
        url = _components_url(api_client_a, f"LIQ-{form}", form)
        assert _add(api_client_a, url, "40", "mg", mg_per_5ml()).status_code == 201
