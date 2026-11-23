"""Investigation (owner, 2026-11-20): QA-08, QA-18 and QA-09 (components) from docs/qa/QA_CODEX_REPORT.md.

Real PostgreSQL, no mocks. Each test asserts the CORRECT behaviour; a test marked
xfail(strict=True) is one whose issue reproduces today (it will start failing as an
XPASS when the issue is fixed, which is the signal to remove the marker).

QA-08: two versions of one product approved in overlapping transactions.
QA-18: the version trigger leaves the review stamps changeable while under review.
"""

from __future__ import annotations

import threading

import pytest
from django.db import IntegrityError, InternalError, ProgrammingError, connection, transaction

from formulations.models import FormulationStatus, FormulationVersion

from .test_version_approval import _draft, _post, people  # noqa: F401

DB_REFUSED = (ProgrammingError, InternalError, IntegrityError)
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


@pytest.mark.xfail(
    strict=True, reason="QA-08 reproduces: overlapping approvals leave two approved versions"
)
@pytest.mark.django_db(transaction=True)
def test_qa08_overlapping_approvals_leave_one_approved_version(people, tenant_a):  # noqa: F811
    from formulations.approval import approve

    doer = people["doer"][1]
    product, v1 = _draft(doer, code="INV-QA08")
    v2 = _second_version(doer, product)
    assert _post(doer, v1, "submit-review").status_code == 200
    assert _post(doer, v2, "submit-review").status_code == 200
    vp, vp2 = people["vp"][0], people["vp2"][0]

    a_done, b_done, errors = threading.Event(), threading.Event(), []

    def first():
        # Approves v1 and holds its transaction open until the second approval ran.
        try:
            with transaction.atomic():
                approve(FormulationVersion.objects.get(public_id=v1), vp, tenant_a, "A")
                a_done.set()
                b_done.wait(20)
        except Exception as exc:
            errors.append(("first", repr(exc)))
            a_done.set()
        finally:
            connection.close()

    def second():
        try:
            a_done.wait(20)
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
    approved = FormulationVersion.objects.filter(
        product__public_id=product["public_id"], status=FormulationStatus.APPROVED
    ).count()
    assert approved == 1, f"{approved} approved versions of one product"


def _under_review_by(people, code):  # noqa: F811
    """Created by the Doer, submitted by another user (Doer+VP), so creator != submitter."""
    creator, submitter_client = people["doer"][1], people["doer_vp"][1]
    _, vid = _draft(creator, code=code)
    assert _post(submitter_client, vid, "submit-review").status_code == 200
    v = FormulationVersion.objects.get(public_id=vid)
    assert v.submitted_by_id == people["doer_vp"][0].id
    return v


def _sql(statement, params):
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute(statement, params)


@pytest.mark.xfail(
    strict=True, reason="QA-18 reproduces: submitted_by can be changed while under review"
)
@pytest.mark.django_db
def test_qa18_submitter_stamp_is_frozen_under_review(people):  # noqa: F811
    v = _under_review_by(people, "INV-QA18A")
    with pytest.raises(DB_REFUSED):
        _sql(
            "UPDATE formulations_formulationversion SET submitted_by_id = %s WHERE id = %s",
            [people["reviewer"][0].id, v.id],
        )


@pytest.mark.xfail(
    strict=True,
    reason="QA-18 reproduces: the submitter can approve in one statement that rewrites the stamp",
)
@pytest.mark.django_db
def test_qa18_submitter_cannot_self_approve_by_rewriting_the_stamp(people):  # noqa: F811
    v = _under_review_by(people, "INV-QA18B")
    submitter = people["doer_vp"][0]
    with pytest.raises(DB_REFUSED):
        _sql(
            "UPDATE formulations_formulationversion SET submitted_by_id = %s, status = 'approved', "
            "approved_by_id = %s, approved_at = now(), approval_note = 'maintenance' WHERE id = %s",
            [people["reviewer"][0].id, submitter.id, v.id],
        )


FAIL_AUDIT = """
CREATE OR REPLACE FUNCTION qa09_fail_audit() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'QA-09 injected audit failure'; END $$;
CREATE TRIGGER qa09_fail_audit BEFORE INSERT ON audit_auditevent
FOR EACH ROW EXECUTE FUNCTION qa09_fail_audit();
"""
UNDO = "DROP TRIGGER IF EXISTS qa09_fail_audit ON audit_auditevent; DROP FUNCTION IF EXISTS qa09_fail_audit();"


@pytest.mark.xfail(
    strict=True, reason="QA-09 reproduces: a component is saved without its audit event"
)
@pytest.mark.django_db(transaction=True)
def test_qa09_component_and_its_audit_commit_together(people):  # noqa: F811
    from formulations.models import FormulationComponent

    doer = people["doer"][1]
    _, vid = _draft(doer, code="INV-QA09", components=0)
    with connection.cursor() as cur:
        cur.execute(FAIL_AUDIT)
    try:
        try:
            doer.post(
                f"{F}/versions/{vid}/components/",
                {
                    "component_type": "inactive",
                    "ingredient_name": "QA09",
                    "quantity_per_dosage_unit": "1",
                    "quantity_unit": "mg",
                },
                format="json",
            )
        except Exception:
            pass
    finally:
        with connection.cursor() as cur:
            cur.execute(UNDO)
    # Correct: no audit event, so no component either.
    assert not FormulationComponent.objects.filter(formulation_version__public_id=vid).exists()
