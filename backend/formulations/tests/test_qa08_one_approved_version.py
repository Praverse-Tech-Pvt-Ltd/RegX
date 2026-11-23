"""QA-08 (docs/qa/QA_CODEX_REPORT.md; reproduced in #154): overlapping approvals left two approved versions.

approve() locked the target version and the currently approved siblings, not the product, and
nothing in the database allowed at most one approved version per product. Two transactions
approving different versions of one product both saw "none approved" and both approved.

Fix: approve() locks the product row first, so approvals of one product run one at a time; and
a partial unique constraint (one `approved` version per product) is the database backstop.

The two-connection test is #154's reproduction with its xfail removed. With the fix the second
approval waits for the first, so the first no longer waits for the second to finish: it holds
its transaction open for at most 5 seconds, which is long enough for the second to start.
"""

from __future__ import annotations

import threading

import pytest
from django.db import IntegrityError, connection, transaction

from formulations.models import FormulationStatus, FormulationVersion

from .test_version_approval import _draft, _post, people  # noqa: F401

F = "/api/regx/v1/formulations"


def _second_version(client, product):
    vid = client.post(
        f"{F}/products/{product['public_id']}/versions/",
        {
            "total_dosage_unit_weight": "250",
            "total_dosage_unit_weight_unit": "mg",
            "maximum_dosage_units_per_day": "4",
        },
        format="json",
    ).json()["public_id"]
    resp = client.post(
        f"{F}/versions/{vid}/components/",
        {
            "component_type": "inactive",
            "ingredient_name": "EXCIPIENT B",
            "quantity_per_dosage_unit": "10",
            "quantity_unit": "mg",
        },
        format="json",
    )
    assert resp.status_code == 201, resp.json()
    return vid


def _two_under_review(people, code):  # noqa: F811
    doer = people["doer"][1]
    product, v1 = _draft(doer, code=code)
    v2 = _second_version(doer, product)
    assert _post(doer, v1, "submit-review").status_code == 200
    assert _post(doer, v2, "submit-review").status_code == 200
    return product, v1, v2


@pytest.mark.django_db(transaction=True)
def test_qa08_overlapping_approvals_leave_one_approved_version(people, tenant_a):  # noqa: F811
    from formulations.approval import approve

    product, v1, v2 = _two_under_review(people, "INV-QA08")
    vp, vp2 = people["vp"][0], people["vp2"][0]
    a_done, b_started, b_done, errors = threading.Event(), threading.Event(), threading.Event(), []

    def first():
        # Approves v1 and holds its transaction open while the second approval starts.
        try:
            with transaction.atomic():
                approve(FormulationVersion.objects.get(public_id=v1), vp, tenant_a, "A")
                a_done.set()
                b_started.wait(20)
                b_done.wait(5)
        except Exception as exc:
            errors.append(("first", repr(exc)))
            a_done.set()
        finally:
            connection.close()

    def second():
        try:
            a_done.wait(20)
            b_started.set()
            approve(FormulationVersion.objects.get(public_id=v2), vp2, tenant_a, "B")
        except Exception as exc:
            errors.append(("second", repr(exc)))
        finally:
            b_done.set()
            connection.close()

    t1, t2 = threading.Thread(target=first), threading.Thread(target=second)
    t1.start()
    t2.start()
    t1.join(60)
    t2.join(60)
    assert not errors, errors
    versions = dict(
        FormulationVersion.objects.filter(product__public_id=product["public_id"]).values_list(
            "public_id", "status"
        )
    )
    approved = [k for k, s in versions.items() if s == FormulationStatus.APPROVED]
    assert len(approved) == 1, f"{len(approved)} approved versions of one product"
    # The later approval wins and supersedes the earlier one, as in the sequential flow.
    assert str(approved[0]) == str(v2)
    assert (
        versions[FormulationVersion.objects.get(public_id=v1).public_id]
        == FormulationStatus.SUPERSEDED
    )


@pytest.mark.django_db
def test_the_database_refuses_a_second_approved_version(people):  # noqa: F811
    """Backstop: even a write that bypasses approve() cannot leave two approved versions."""
    from formulations.approval import approve

    product, v1, v2 = _two_under_review(people, "QA08-DB")
    tenant = FormulationVersion.objects.get(public_id=v1).product.tenant
    approve(FormulationVersion.objects.get(public_id=v1), people["vp"][0], tenant, "first")
    with pytest.raises(IntegrityError), transaction.atomic(), connection.cursor() as cur:
        cur.execute(
            "UPDATE formulations_formulationversion SET status = 'approved', approved_by_id = %s, "
            "approved_at = now(), approval_note = 'bypass' WHERE public_id = %s",
            [people["vp2"][0].id, str(v2)],
        )
