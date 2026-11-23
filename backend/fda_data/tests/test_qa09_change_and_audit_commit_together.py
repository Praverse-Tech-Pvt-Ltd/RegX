"""QA-09 (fda_data): a governed change and its audit record commit together or not at all.

Fault injection: `audit.testing.audit_writes_fail()` makes every audit INSERT fail in
PostgreSQL. Each test asserts the change did NOT persist. On the old code each change
committed before (or without) its audit write, so these tests failed.

Covered here:
- the mapping transitions (submit / approve / reject / return share one view base,
  `_MappingActionViewBase`; one test drives submit-review: #154's test, xfail removed);
- the substance mapping proposal;
- the JSON release import (release registration and row import, one transaction).
"""

from __future__ import annotations

import pytest

from audit.testing import attempt, audit_writes_fail
from fda_data.models import (
    FDADataSourceRelease,
    MappingDecisionStatus,
    SubstanceSynonymMapping,
)

from .test_mapping_lifecycle_transitions import route_mapping_proposed  # noqa: F401
from .test_substance_mapping_proposal import _payload, active_release  # noqa: F401

BASE = "/api/regx/v1"
pytestmark = pytest.mark.django_db(transaction=True)


def test_qa09_mapping_change_and_audit_commit_together(
    api_client_reviewer,
    route_mapping_proposed,  # noqa: F811
):
    with audit_writes_fail():
        attempt(
            api_client_reviewer.post,
            f"{BASE}/fda-data/mappings/{route_mapping_proposed.public_id}/submit-review/",
            data={},
            format="json",
        )
    route_mapping_proposed.refresh_from_db()
    # No audit event, so no state change either.
    assert route_mapping_proposed.status == MappingDecisionStatus.PROPOSED


def test_substance_mapping_proposal_rolls_back_without_its_audit(
    api_client_reviewer,
    active_release,  # noqa: F811
):
    with audit_writes_fail():
        attempt(
            api_client_reviewer.post,
            f"{BASE}/fda-data/mappings/substances/proposals/",
            data=_payload(release_public_id=str(active_release.public_id)),
            format="json",
        )
    assert not SubstanceSynonymMapping.objects.exists()


def test_json_release_import_rolls_back_without_its_audit(api_client_doer):
    payload = {
        "dataset_type": "fda_iid",
        "source_name": "iid",
        "official_source_reference": "QA-09",
        "rows": [
            {
                "INGREDIENT_NAME": "ACACIA",
                "ROUTE": "ORAL",
                "DOSAGE_FORM": "TABLET, FILM COATED",
                "UNII": "5C5403N26O",
                "POTENCY_AMOUNT": "0.14",
                "POTENCY_UNIT": "mg",
            }
        ],
    }
    with audit_writes_fail():
        attempt(api_client_doer.post, f"{BASE}/fda-data/releases/", payload, format="json")
    assert not FDADataSourceRelease.objects.exists()
