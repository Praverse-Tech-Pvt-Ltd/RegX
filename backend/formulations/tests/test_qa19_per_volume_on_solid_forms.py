# ruff: noqa: F811  (units_in_force is a pytest fixture imported by name)
"""QA-19 (QA_CODEX_REPORT.md): per-volume amounts were accepted for plain POWDER and GRANULE.

A per-volume meaning (mg/5mL, %w/v, %v/v) is refused on a solid product unless its
dosage form says it is made into a liquid before use ("FOR SOLUTION", "FOR
SUSPENSION", "FOR LIPOSOMAL SUSPENSION", ...). POWDER and GRANULE were missing
from the solid words, so a plain powder took "mg/5mL".

The rule reads the product's dosage form as text (the product stores free text,
not an SPL code), so it is tested against the whole public FDA SPL dosage-form
list (fixtures/spl_dosage_forms_2022-02-03.csv, 158 terms with NCI codes; FDA page
"content current as of" 2022-02-03; sha256 350450f5...). SOLID_NCI_CODES below
is the reviewed outcome for every SPL term: any change to the rule shows up
here code by code.
"""

from __future__ import annotations

import csv
import pathlib
from decimal import Decimal

import pytest

from formulations.dosage_forms import is_solid_dosage_form

from .test_input_validation_qa import (  # noqa: F401
    _add,
    _components_url,
    _err,
    _meaning,
    units_in_force,
)

SPL = pathlib.Path(__file__).parent / "fixtures" / "spl_dosage_forms_2022-02-03.csv"

#: The SPL terms on which a per-volume amount is refused (46 of 158).
SOLID_NCI_CODES = {
    "C124794", "C147579", "C25158", "C42893", "C42894", "C42895", "C42896", "C42897",
    "C42902", "C42903", "C42904", "C42905", "C42908", "C42909", "C42910", "C42916",
    "C42917", "C42918", "C42924", "C42927", "C42928", "C42930", "C42931", "C42936",
    "C42938", "C42942", "C42943", "C42954", "C42955", "C42961", "C42963", "C42964",
    "C42969", "C42971", "C42972", "C42985", "C42992", "C42993", "C42997", "C42998",
    "C42999", "C43001", "C43003", "C60985", "C60997", "C61006",
}  # fmt: skip

#: The SPL terms whose outcome QA-19 changes (accepted before, refused now).
NEWLY_REFUSED = {
    "C42971": "AEROSOL, POWDER",
    "C42938": "GRANULE",
    "C42903": "GRANULE, DELAYED RELEASE",
    "C42909": "GRANULE, EFFERVESCENT",
    "C42972": "POWDER",
    "C42908": "POWDER, DENTIFRICE",
    "C42961": "POWDER, METERED",
}


def _spl_terms():
    with SPL.open(encoding="utf-8", newline="") as fh:
        return [(row["nci_code"], row["spl_term"]) for row in csv.DictReader(fh)]


class TestEverySplDosageForm:
    def test_the_fixture_is_the_full_public_list(self):
        assert len(_spl_terms()) == 158

    def test_solid_outcome_for_every_spl_term(self):
        solid = {code for code, term in _spl_terms() if is_solid_dosage_form(term)}
        assert solid == SOLID_NCI_CODES, {
            "refused but not listed": sorted(solid - SOLID_NCI_CODES),
            "listed but not refused": sorted(SOLID_NCI_CODES - solid),
        }

    def test_every_reconstituted_powder_or_granule_stays_liquid(self):
        terms = dict(_spl_terms())
        for code, term in terms.items():
            if ("POWDER" in term or "GRANULE" in term) and "FOR " in term:
                assert not is_solid_dosage_form(term), (code, term)


def mg_per_5ml():
    return _meaning(
        family="mass",
        basis="per_volume",
        numerator_unit__code="mg",
        denominator_amount=Decimal("5"),
        denominator_unit__code="ml",
    )


@pytest.mark.django_db
class TestThroughTheComponentApi:
    @pytest.mark.parametrize("form", list(NEWLY_REFUSED.values()))
    def test_per_volume_is_refused_on_plain_powders_and_granules(
        self,
        api_client_a,
        units_in_force,
        form,
    ):
        url = _components_url(api_client_a, f"QA19-{form[:12]}", form)
        resp = _add(api_client_a, url, "40", "mg", mg_per_5ml())
        assert resp.status_code == 400, resp.json()
        assert "a solid" in _err(resp)["quantity_expression_public_id"][0]

    @pytest.mark.parametrize(
        "form",
        [
            "POWDER, FOR SOLUTION",
            "POWDER, FOR SUSPENSION",
            "GRANULE, FOR SUSPENSION",
            "INJECTION, POWDER, LYOPHILIZED, FOR LIPOSOMAL SUSPENSION",
            "SOLUTION",
        ],
    )
    def test_per_volume_is_accepted_when_made_into_a_liquid(
        self,
        api_client_a,
        units_in_force,
        form,
    ):
        url = _components_url(api_client_a, f"QA19-OK-{form[:10]}", form)
        resp = _add(api_client_a, url, "40", "mg", mg_per_5ml())
        assert resp.status_code == 201, resp.json()

    def test_a_capsule_is_still_refused(self, api_client_a, units_in_force):
        url = _components_url(api_client_a, "QA19-CAP", "CAPSULE")
        assert _add(api_client_a, url, "40", "mg", mg_per_5ml()).status_code == 400
