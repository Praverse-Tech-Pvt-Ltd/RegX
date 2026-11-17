"""GET /fda-data/controlled-units/meanings/ (controlled units, increment 4):
the meanings a formulation may state -- in force, never per day."""

from __future__ import annotations

import pathlib

import pytest

from fda_data import controlled_units as cu
from fda_data import lifecycle

URL = "/api/regx/v1/fda-data/controlled-units/meanings/"
FDA = pathlib.Path(__file__).resolve().parents[1]


@pytest.mark.django_db
class TestMeaningsEndpoint:
    def test_empty_without_an_active_unit_list(self, api_client_doer):
        resp = api_client_doer.get(URL)
        assert resp.status_code == 200
        assert resp.json() == {"unit_list_release_public_id": None, "meanings": []}

    def test_lists_the_in_force_meanings_except_per_day(self, api_client_doer, vp_user):
        release, _ = cu.load_snapshot(
            raw=(FDA / "reference" / "controlled_units_v1.json").read_bytes(),
            filename="controlled_units_v1.json",
            source_reference="test",
            actor=None,
        )
        release = lifecycle.activate(
            lifecycle.approve(lifecycle.submit_for_review(release, vp_user), vp_user), vp_user
        )
        body = api_client_doer.get(URL).json()
        assert body["unit_list_release_public_id"] == str(release.public_id)
        labels = {m["label"] for m in body["meanings"]}
        assert {"mg per dose unit", "mg/5mL", "%w/w", "%w/v", "%v/v", "mL/5mL"} <= labels
        assert all(m["basis"] != "per_day" for m in body["meanings"])
        assert len(body["meanings"]) == 20  # the 20 meanings of controlled_units_v1
        assert all("id" not in m for m in body["meanings"])

    def test_requires_authentication(self, db):
        from rest_framework.test import APIClient

        assert APIClient().get(URL).status_code in (401, 403)
