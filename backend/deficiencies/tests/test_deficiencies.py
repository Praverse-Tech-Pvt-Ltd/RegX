"""Deficiency corpus API tests.

Covers the three things a port most easily gets wrong: access control that only
appears to work, filters that silently ignore their argument, and facets that
return every row instead of the distinct values.
"""

import pytest
from rest_framework.test import APIClient

from deficiencies.models import DeficiencyCorpus, DeficiencyRecord
from deficiencies.permissions import PERM_IMPORT, PERM_VIEW, ROLE_PERMISSIONS

from .conftest import _client

LIST = "/api/regx/v1/deficiencies/"
FACETS = "/api/regx/v1/deficiencies/facets/"


# --------------------------------------------------------------------------
# Access control
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_anonymous_is_refused(corpus):
    assert APIClient().get(LIST).status_code in (401, 403)


@pytest.mark.django_db
def test_authenticated_user_without_membership_is_refused(corpus, outsider, tenant):
    """Authentication is not authorisation: a real user with no membership in
    this tenant sees nothing."""
    client = _client(outsider, tenant)
    assert client.get(LIST).status_code == 403


@pytest.mark.django_db
def test_missing_tenant_header_is_refused(corpus, doer):
    """Without X-Tenant-Slug there is no tenant scope, so the check fails closed."""
    client = APIClient()
    client.force_authenticate(user=doer)
    assert client.get(LIST).status_code == 403


@pytest.mark.django_db
def test_member_can_read(corpus, client):
    assert client.get(LIST).status_code == 200


@pytest.mark.django_db
def test_the_corpus_is_read_only_over_http(corpus, client):
    """It is published reference data, loaded by the import command. No role has
    a write path, so POST must not be routed at all."""
    assert client.post(LIST, {}, format="json").status_code in (403, 405)


def test_only_platform_support_may_import():
    """A tenant cannot edit FDA reference material, however senior."""
    for perms in ROLE_PERMISSIONS.values():
        assert PERM_VIEW in perms
    assert PERM_IMPORT in ROLE_PERMISSIONS["platform_support"]
    for role in ("doer", "reviewer", "vp", "tenant_admin"):
        assert PERM_IMPORT not in ROLE_PERMISSIONS[role]


# --------------------------------------------------------------------------
# Filtering
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_lists_the_whole_corpus_by_default(corpus, client):
    assert client.get(LIST).json()["count"] == 4


@pytest.mark.django_db
@pytest.mark.parametrize(
    "query,expected",
    [
        ("?corpus=anda", 3),
        ("?corpus=major_cr", 1),
        ("?main_category=Solid Oral-Deficiency", 2),
        ("?dosage_form=Cream", 1),
        ("?cmc_section=Drug Product", 2),
        ("?deficiency_type=Sterility", 1),
    ],
)
def test_each_filter_narrows_the_result(corpus, client, query, expected):
    assert client.get(LIST + query).json()["count"] == expected


@pytest.mark.django_db
def test_filters_combine(corpus, client):
    r = client.get(LIST + "?corpus=anda&cmc_section=Drug Product")
    assert r.json()["count"] == 1


@pytest.mark.django_db
def test_search_matches_the_deficiency_body(corpus, client):
    r = client.get(LIST + "?search=sterility")
    assert r.json()["count"] == 1
    assert "Sterility assurance" in r.json()["results"][0]["deficiency"]


@pytest.mark.django_db
def test_search_matching_nothing_returns_empty_not_everything(corpus, client):
    """A failed search must not silently degrade to an unfiltered list."""
    assert client.get(LIST + "?search=zzzznotpresent").json()["count"] == 0


# --------------------------------------------------------------------------
# Facets
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_facets_are_distinct_values_not_rows(corpus, client):
    """Regression: Meta.ordering leaks into SELECT DISTINCT, so an unguarded
    .distinct() returns one entry per row rather than per value."""
    data = client.get(FACETS).json()
    assert data["corpora"] == ["anda", "major_cr"]
    assert data["cmc_sections"] == ["Drug Product", "Drug Substance", "Microbiology"]
    assert len(data["main_categories"]) == 3
    assert len(data["dosage_forms"]) == 4


@pytest.mark.django_db
def test_facets_are_derived_from_the_data(client, db):
    """No hardcoded category list: an empty corpus yields empty facets."""
    data = client.get(FACETS).json()
    assert data["corpora"] == []
    assert data["main_categories"] == []


# --------------------------------------------------------------------------
# Serialisation
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_response_exposes_public_id_and_never_the_pk(corpus, client):
    record = client.get(LIST).json()["results"][0]
    assert "public_id" not in record
    assert record["id"] != 1
    stored = DeficiencyRecord.objects.get(public_id=record["id"])
    assert str(stored.public_id) == record["id"]


@pytest.mark.django_db
def test_detail_by_public_id(corpus, client):
    listed = client.get(LIST).json()["results"][0]
    detail = client.get(f"/api/regx/v1/deficiencies/{listed['id']}/")
    assert detail.status_code == 200
    assert detail.json()["id"] == listed["id"]


@pytest.mark.django_db
def test_unknown_public_id_is_404(client, db):
    r = client.get("/api/regx/v1/deficiencies/00000000-0000-0000-0000-000000000000/")
    assert r.status_code == 404


@pytest.mark.django_db
def test_corpus_display_is_human_readable(corpus, client):
    r = client.get(LIST + "?corpus=major_cr").json()["results"][0]
    assert r["corpus"] == "major_cr"
    assert r["corpus_display"] == DeficiencyCorpus.MAJOR_CR.label
