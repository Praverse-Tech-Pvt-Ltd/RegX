"""Controlled export: the audit record is saved FIRST; the file goes out only after
(owner decision 2026-11-23, QA-09 follow-up).

The export event used to be written through `transaction.on_commit()`. Inside a caller's
transaction that meant `export_execution` handed the file back first and wrote the record
only at commit, where the write could fail: a file out with no record of who exported
it. Now the record is written and saved before anything is returned; if it cannot be
saved, the export is refused (503 `export_not_recorded` at the API) and no file is given.

No `django_capture_on_commit_callbacks` in this file.
"""

from __future__ import annotations

import pytest
from django.db import transaction

from audit.models import AuditEvent
from audit.testing import attempt, audit_writes_fail
from iig_checklist.controlled_export import export_execution

from .test_4d4_controlled_export import _url, world  # noqa: F401

EVENT = "iig_checklist.execution.exported"


def _events(world_):
    return AuditEvent.objects.filter(
        event_type=EVENT, resource_id=str(world_["execution"].public_id)
    )


@pytest.mark.django_db
def test_a_normal_export_writes_exactly_one_record(world, api_client_vp, vp_membership):  # noqa: F811
    resp = api_client_vp.get(_url(world["execution"]))
    assert resp.status_code == 200
    events = list(_events(world))
    assert len(events) == 1
    assert events[0].payload["checksum"] == resp["X-RegX-Export-Checksum"]


@pytest.mark.django_db(transaction=True)
class TestAnAuditFailureMeansNoFile:
    def test_the_api_refuses_the_export_and_returns_no_file(
        self,
        world,  # noqa: F811
        api_client_vp,
        vp_membership,
    ):
        with audit_writes_fail():
            resp = attempt(api_client_vp.get, _url(world["execution"]))
        assert resp is not None, "the export must be refused cleanly, not crash"
        assert resp.status_code == 503
        assert resp.data["error_code"] == "export_not_recorded"
        assert "X-RegX-Export-Checksum" not in resp
        assert not _events(world).exists()

    def test_inside_a_callers_transaction_no_file_is_handed_back(
        self,
        world,  # noqa: F811
        vp_user,
        vp_membership,
        tenant_a,
    ):
        """The case on_commit got wrong: the caller holds a transaction."""
        handed_back = {}

        def export_in_a_transaction():
            with transaction.atomic():
                handed_back["file"] = export_execution(
                    tenant=tenant_a,
                    execution_public_id=world["execution"].public_id,
                    actor=vp_user,
                )

        with audit_writes_fail():
            attempt(export_in_a_transaction)
        assert "file" not in handed_back
        assert not _events(world).exists()
