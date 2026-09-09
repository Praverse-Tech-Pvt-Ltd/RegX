"""FDA inspection corpus API tests.

Weighted towards the failure shapes a port produces: access control that only
appears to work, filters that ignore their argument, facets that return rows
instead of values, and the observation-count annotation double-counting across a
join.
"""

import pytest
from rest_framework.test import APIClient

from inspections.models import Form483Inspection, Form483Observation, Form483System
from inspections.permissions import PERM_IMPORT, PERM_VIEW, ROLE_PERMISSIONS

from .conftest import _client

F483 = "/api/regx/v1/inspections/form483/"
FACETS = "/api/regx/v1/inspections/form483/facets/"
OBS = "/api/regx/v1/inspections/observations/"
LETTERS = "/api/regx/v1/inspections/warning-letters/"


# --------------------------------------------------------------------------
# Access control
# --------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("url", [F483, FACETS, OBS, LETTERS])
def test_anonymous_is_refused(corpus, url):
    assert APIClient().get(url).status_code in (401, 403)


@pytest.mark.django_db
def test_authenticated_user_without_membership_is_refused(corpus, outsider, tenant):
    assert _client(outsider, tenant).get(F483).status_code == 403


@pytest.mark.django_db
def test_missing_tenant_header_is_refused(corpus, doer):
    client = APIClient()
    client.force_authenticate(user=doer)
    assert client.get(F483).status_code == 403


@pytest.mark.django_db
def test_member_can_read(corpus, client):
    assert client.get(F483).status_code == 200


@pytest.mark.django_db
def test_the_corpus_is_read_only_over_http(corpus, client):
    assert client.post(F483, {}, format="json").status_code in (403, 405)


def test_only_platform_support_may_import():
    for perms in ROLE_PERMISSIONS.values():
        assert PERM_VIEW in perms
    assert PERM_IMPORT in ROLE_PERMISSIONS["platform_support"]
    for role in ("doer", "reviewer", "vp", "tenant_admin"):
        assert PERM_IMPORT not in ROLE_PERMISSIONS[role]


# --------------------------------------------------------------------------
# Form 483 list, filters, counts
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_lists_every_inspection(corpus, client):
    assert client.get(F483).json()["count"] == 2


@pytest.mark.django_db
@pytest.mark.parametrize(
    "query,expected",
    [
        ("?company_name=Acme", 1),
        ("?company_name=acme", 1),  # case-insensitive
        ("?investigator_name=Inspector", 1),
        ("?type_of_establishment=API Manufacturer", 1),
        ("?system=Quality System", 1),
        ("?year=2023", 1),
        ("?year=2024", 1),
        ("?date_from=2024-01-01", 1),
        ("?date_to=2023-12-31", 1),
    ],
)
def test_each_filter_narrows_the_result(corpus, client, query, expected):
    assert client.get(F483 + query).json()["count"] == expected


@pytest.mark.django_db
def test_observation_count_is_not_inflated_by_the_join(corpus, client):
    """Acme has 3 observations across 2 systems. Counting over a multi-valued
    join without distinct=True returns the cartesian product instead."""
    rows = {r["company_name"]: r for r in client.get(F483).json()["results"]}
    assert rows["Acme Pharma Ltd"]["observation_count"] == 3
    assert rows["Beta Labs Inc"]["observation_count"] == 1


@pytest.mark.django_db
def test_system_filter_does_not_duplicate_inspections(corpus, client):
    """Filtering across a to-many join can return one row per match."""
    body = client.get(F483 + "?system=Quality System").json()
    assert body["count"] == 1
    assert len(body["results"]) == 1


@pytest.mark.django_db
def test_year_is_derived_from_the_date(corpus, client):
    """The legacy schema stored year as a separate CharField that could disagree
    with the date. It is computed here."""
    row = client.get(F483 + "?company_name=Beta").json()["results"][0]
    assert row["year_of_inspection"] == 2024


@pytest.mark.django_db
def test_undated_inspection_reports_no_year_rather_than_failing(client, db):
    Form483Inspection.objects.create(company_name="Undated Co", date_of_inspection=None)
    row = client.get(F483 + "?company_name=Undated").json()["results"][0]
    assert row["year_of_inspection"] is None


# --------------------------------------------------------------------------
# Detail
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_detail_nests_systems_and_observations(corpus, client):
    listed = client.get(F483 + "?company_name=Acme").json()["results"][0]
    body = client.get(f"{F483}{listed['id']}/").json()
    systems = {s["system"]: s for s in body["systems"]}
    assert set(systems) == {"Quality System", "Production System"}
    assert len(systems["Quality System"]["observations"]) == 2


@pytest.mark.django_db
def test_unknown_public_id_is_404(client, db):
    assert client.get(f"{F483}00000000-0000-0000-0000-000000000000/").status_code == 404


@pytest.mark.django_db
def test_list_is_ordered_so_pagination_is_stable(corpus, client):
    """annotate() clears Meta.ordering. An unordered queryset paginates
    inconsistently, which only shows up once there is more than one page."""
    rows = client.get(F483).json()["results"]
    dates = [r["date_of_inspection"] for r in rows]
    assert dates == sorted(dates, reverse=True)


@pytest.mark.django_db
def test_response_exposes_public_id_and_never_the_pk(corpus, client):
    row = client.get(F483).json()["results"][0]
    assert "public_id" not in row
    assert Form483Inspection.objects.filter(public_id=row["id"]).exists()


# --------------------------------------------------------------------------
# Observation search
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_search_matches_observation_text(corpus, client):
    body = client.get(OBS + "?search=sterility").json()
    assert body["count"] == 1
    assert "Sterility test failures" in body["results"][0]["content"]


@pytest.mark.django_db
def test_search_matching_nothing_returns_empty_not_everything(corpus, client):
    assert client.get(OBS + "?search=zzzznotpresent").json()["count"] == 0


@pytest.mark.django_db
def test_observations_carry_their_parent_context(corpus, client):
    row = client.get(OBS + "?search=sterility").json()["results"][0]
    assert row["system"] == "Quality System"
    assert row["company_name"] == "Acme Pharma Ltd"


@pytest.mark.django_db
def test_observation_filters_combine(corpus, client):
    assert client.get(OBS + "?company_name=Acme&system=Production System").json()["count"] == 1


# --------------------------------------------------------------------------
# Warning letters
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_warning_letters_list_and_filter(corpus, client):
    assert client.get(LETTERS).json()["count"] == 1
    assert client.get(LETTERS + "?country=India").json()["count"] == 1
    assert client.get(LETTERS + "?country=Ireland").json()["count"] == 0
    assert client.get(LETTERS + "?search=written procedures").json()["count"] == 1


# --------------------------------------------------------------------------
# Facets
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_facets_are_distinct_values_not_rows(corpus, client):
    """Regression: Meta.ordering leaks into SELECT DISTINCT, so an unguarded
    .distinct() returns one entry per row rather than per value."""
    data = client.get(FACETS).json()
    assert data["companies"] == ["Acme Pharma Ltd", "Beta Labs Inc"]
    assert data["systems"] == [
        "Laboratory Control System",
        "Production System",
        "Quality System",
    ]
    assert data["years"] == [2024, 2023]  # newest first


@pytest.mark.django_db
def test_facets_are_derived_from_the_data(client, db):
    data = client.get(FACETS).json()
    assert data["companies"] == []
    assert data["years"] == []


# --------------------------------------------------------------------------
# Model constraint
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_observation_number_is_unique_per_system(corpus):
    """The legacy schema allowed duplicates; the importer reports and skips them."""
    from django.db import IntegrityError

    system = Form483System.objects.filter(system="Quality System").first()
    with pytest.raises(IntegrityError):
        Form483Observation.objects.create(system=system, observation_number=1)
