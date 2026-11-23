"""Investigation (owner, 2026-11-20): QA-09 (mappings) and QA-10 from docs/qa/QA_CODEX_REPORT.md.

Real PostgreSQL, no mocks. Each test asserts the CORRECT behaviour; xfail(strict=True)
marks an issue that reproduces today.

QA-09: a mapping transition commits even when its audit event cannot be written.
       Fault injection is a real database trigger that makes audit inserts fail.
QA-10: two ordinary imports of the same content (different line endings) in
       overlapping transactions both register.
"""

from __future__ import annotations

import pathlib
import threading

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, transaction

from fda_data.models import FDADataSourceRelease, MappingDecisionStatus

from .test_mapping_lifecycle_transitions import route_mapping_proposed  # noqa: F401

BASE = "/api/regx/v1"
SAMPLE = pathlib.Path(__file__).parent / "fixtures" / "iid" / "iir_ocomm_sample.csv"

FAIL_AUDIT = """
CREATE OR REPLACE FUNCTION qa09_fail_audit() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'QA-09 injected audit failure'; END $$;
CREATE TRIGGER qa09_fail_audit BEFORE INSERT ON audit_auditevent
FOR EACH ROW EXECUTE FUNCTION qa09_fail_audit();
"""
UNDO = "DROP TRIGGER IF EXISTS qa09_fail_audit ON audit_auditevent; DROP FUNCTION IF EXISTS qa09_fail_audit();"


@pytest.mark.xfail(
    strict=True, reason="QA-09 reproduces: the mapping change commits without its audit event"
)
@pytest.mark.django_db(transaction=True)
def test_qa09_mapping_change_and_audit_commit_together(api_client_reviewer, route_mapping_proposed):  # noqa: F811
    with connection.cursor() as cur:
        cur.execute(FAIL_AUDIT)
    try:
        try:
            api_client_reviewer.post(
                f"{BASE}/fda-data/mappings/{route_mapping_proposed.public_id}/submit-review/",
                data={},
                format="json",
            )
        except Exception:
            pass
    finally:
        with connection.cursor() as cur:
            cur.execute(UNDO)
    route_mapping_proposed.refresh_from_db()
    # Correct: no audit event, so no state change either.
    assert route_mapping_proposed.status == MappingDecisionStatus.PROPOSED, (
        route_mapping_proposed.status
    )


@pytest.mark.xfail(
    strict=True,
    reason="QA-10 reproduces: two overlapping ordinary imports of the same content both register",
)
@pytest.mark.django_db(transaction=True)
def test_qa10_overlapping_imports_of_the_same_content_register_once(
    tmp_path, user_a, doer_membership
):
    lf = tmp_path / "IIR_LF.csv"
    crlf = tmp_path / "IIR_CRLF.csv"
    text = SAMPLE.read_bytes().decode("latin-1").replace("\r\n", "\n")
    lf.write_bytes(text.encode("latin-1"))
    crlf.write_bytes(text.replace("\n", "\r\n").encode("latin-1"))

    def run(path):
        call_command(
            "import_fda_release",
            str(path),
            "--dataset-type",
            "fda_iid",
            "--actor",
            user_a.email,
            "--source-reference",
            f"QA-10 investigation ({path.name})",
        )

    a_done, b_done, outcome = threading.Event(), threading.Event(), {}

    def first():
        try:
            with transaction.atomic():
                run(lf)
                a_done.set()
                b_done.wait(30)
            outcome["first"] = "registered"
        except Exception as exc:
            outcome["first"] = repr(exc)[:200]
            a_done.set()
        finally:
            connection.close()

    def second():
        try:
            a_done.wait(30)
            run(crlf)
            outcome["second"] = "registered"
        except CommandError as exc:
            outcome["second"] = f"refused: {str(exc)[:120]}"
        except Exception as exc:
            outcome["second"] = repr(exc)[:200]
        finally:
            b_done.set()
            connection.close()

    t1, t2 = threading.Thread(target=first), threading.Thread(target=second)
    t1.start()
    t2.start()
    t1.join(90)
    t2.join(90)
    ordinary = FDADataSourceRelease.objects.filter(dataset_type="fda_iid", reimport_of__isnull=True)
    prints = list(ordinary.values_list("content_fingerprint_sha256", flat=True))
    # Correct: at most one ordinary release carries this content.
    assert len(prints) == 1, (outcome, len(prints), len(set(prints)))
