"""Workflow API surface, tenant isolation and concurrency.

Tenant isolation failures here are release-blocking. Synthetic data only.
"""

import pytest

from workflows.models import WorkflowItem, WorkflowTransition

S = WorkflowItem.State


def _url(item, suffix=""):
    return f"/api/regx/v1/workflows/{item.public_id}/{suffix}"


@pytest.mark.django_db
class TestApiLifecycle:
    def test_create_list_retrieve(self, client_doer_a, tenant_a):
        created = client_doer_a.post(
            "/api/regx/v1/workflows/", {"title": "Synthetic API item"}, format="json"
        )
        assert created.status_code == 201
        public_id = created.data["public_id"]
        assert created.data["state"] == S.DRAFT

        listing = client_doer_a.get("/api/regx/v1/workflows/")
        assert listing.status_code == 200
        assert any(row["public_id"] == public_id for row in listing.data["results"])

        detail = client_doer_a.get(f"/api/regx/v1/workflows/{public_id}/")
        assert detail.status_code == 200
        assert detail.data["title"] == "Synthetic API item"

    def test_no_internal_pk_in_any_response(self, client_doer_a, item_a):
        """public_id only -- an integer PK must never appear."""
        detail = client_doer_a.get(_url(item_a))
        assert "id" not in detail.data
        assert "pk" not in detail.data
        for nested in ("created_by", "assigned_to"):
            if detail.data.get(nested):
                assert "id" not in detail.data[nested]
        assert str(item_a.public_id) == detail.data["public_id"]

    def test_full_lifecycle_through_api(self, client_doer_a, client_reviewer_a, item_a):
        assert client_doer_a.post(_url(item_a, "submit/"), {}, format="json").status_code == 200
        assert (
            client_reviewer_a.post(_url(item_a, "begin-review/"), {}, format="json").status_code
            == 200
        )
        approved = client_reviewer_a.post(_url(item_a, "approve/"), {}, format="json")
        assert approved.status_code == 200
        assert approved.data["state"] == S.APPROVED
        assert approved.data["is_terminal"] is True
        assert approved.data["available_actions"] == []

    def test_history_endpoint(self, client_doer_a, client_reviewer_a, item_a):
        client_doer_a.post(_url(item_a, "submit/"), {}, format="json")
        client_reviewer_a.post(_url(item_a, "begin-review/"), {}, format="json")
        history = client_doer_a.get(_url(item_a, "history/"))
        assert history.status_code == 200
        assert [(r["from_state"], r["to_state"]) for r in history.data] == [
            (S.DRAFT, S.SUBMITTED),
            (S.SUBMITTED, S.IN_REVIEW),
        ]
        assert "id" not in history.data[0]

    def test_history_has_no_write_methods(self, client_doer_a, item_a):
        for method in ("post", "put", "patch", "delete"):
            resp = getattr(client_doer_a, method)(_url(item_a, "history/"))
            assert resp.status_code == 405, f"{method} on history should not be allowed"

    def test_available_actions_reflect_permissions(self, client_doer_a, client_reviewer_a, item_a):
        """A doer sees submit/cancel on a draft; a reviewer does not see submit."""
        doer_view = client_doer_a.get(_url(item_a))
        assert set(doer_view.data["available_actions"]) == {"submit", "cancel"}

        reviewer_view = client_reviewer_a.get(_url(item_a))
        assert "submit" not in reviewer_view.data["available_actions"]


@pytest.mark.django_db
class TestStatePatchRejected:
    def test_patch_with_state_is_rejected(self, client_doer_a, item_a):
        resp = client_doer_a.patch(_url(item_a), {"state": "approved"}, format="json")
        assert resp.status_code == 400
        item_a.refresh_from_db()
        assert item_a.state == S.DRAFT

    def test_patch_with_state_alongside_valid_field_still_rejected(self, client_doer_a, item_a):
        resp = client_doer_a.patch(
            _url(item_a), {"title": "New", "state": "approved"}, format="json"
        )
        assert resp.status_code == 400
        item_a.refresh_from_db()
        assert item_a.state == S.DRAFT
        assert item_a.title != "New", "the whole request must be refused, not partly applied"

    def test_patch_editable_fields_works(self, client_doer_a, item_a):
        resp = client_doer_a.patch(_url(item_a), {"title": "Renamed"}, format="json")
        assert resp.status_code == 200
        assert resp.data["title"] == "Renamed"


@pytest.mark.django_db
class TestApiPermissions:
    def test_doer_cannot_approve(self, client_doer_a, client_reviewer_a, item_a):
        client_doer_a.post(_url(item_a, "submit/"), {}, format="json")
        client_reviewer_a.post(_url(item_a, "begin-review/"), {}, format="json")
        denied = client_doer_a.post(_url(item_a, "approve/"), {}, format="json")
        assert denied.status_code == 403
        item_a.refresh_from_db()
        assert item_a.state == S.IN_REVIEW

    def test_reject_without_reason_is_400(self, client_doer_a, client_reviewer_a, item_a):
        client_doer_a.post(_url(item_a, "submit/"), {}, format="json")
        client_reviewer_a.post(_url(item_a, "begin-review/"), {}, format="json")
        resp = client_reviewer_a.post(_url(item_a, "reject/"), {"reason": ""}, format="json")
        assert resp.status_code == 400
        item_a.refresh_from_db()
        assert item_a.state == S.IN_REVIEW

    def test_illegal_transition_is_409(self, client_reviewer_a, item_a):
        resp = client_reviewer_a.post(_url(item_a, "approve/"), {}, format="json")
        assert resp.status_code == 409
        assert resp.data["current_state"] == S.DRAFT

    def test_unauthenticated_denied(self, item_a):
        from rest_framework.test import APIClient

        anon = APIClient()
        assert anon.get("/api/regx/v1/workflows/").status_code in (401, 403)


@pytest.mark.django_db
class TestTenantIsolation:
    """Release-blocking. Every one of these must hold."""

    def test_tenant_a_cannot_read_tenant_b_item(self, client_doer_a, item_b):
        resp = client_doer_a.get(_url(item_b))
        assert resp.status_code == 404, "cross-tenant read must 404, never 403"

    def test_tenant_a_cannot_mutate_tenant_b_item(self, client_doer_a, item_b):
        assert client_doer_a.patch(_url(item_b), {"title": "x"}, format="json").status_code == 404
        assert client_doer_a.post(_url(item_b, "submit/"), {}, format="json").status_code == 404
        item_b.refresh_from_db()
        assert item_b.state == S.DRAFT
        assert item_b.title == "Synthetic item B"

    def test_list_never_leaks_other_tenant(self, client_doer_a, item_a, item_b):
        listing = client_doer_a.get("/api/regx/v1/workflows/")
        ids = {row["public_id"] for row in listing.data["results"]}
        assert str(item_a.public_id) in ids
        assert str(item_b.public_id) not in ids

    def test_cannot_assign_other_tenant_user(self, client_reviewer_a, item_a, doer_b):
        resp = client_reviewer_a.post(
            _url(item_a, "assign/"), {"assigned_to": str(doer_b.public_id)}, format="json"
        )
        assert resp.status_code == 400
        item_a.refresh_from_db()
        assert item_a.assigned_to_id is None

    def test_nonexistent_and_cross_tenant_user_are_indistinguishable(
        self, client_reviewer_a, item_a, doer_b
    ):
        """Both must produce the same message, or the response leaks whether a
        user exists in another tenant."""
        import uuid

        cross = client_reviewer_a.post(
            _url(item_a, "assign/"), {"assigned_to": str(doer_b.public_id)}, format="json"
        )
        missing = client_reviewer_a.post(
            _url(item_a, "assign/"), {"assigned_to": str(uuid.uuid4())}, format="json"
        )
        assert cross.status_code == missing.status_code == 400
        # Errors come wrapped by common.exceptions.regx_exception_handler.
        cross_detail = cross.data["error"]["detail"]["assigned_to"]
        missing_detail = missing.data["error"]["detail"]["assigned_to"]
        assert str(cross_detail) == str(missing_detail), (
            "differing wording lets a caller distinguish a user in another "
            "tenant from a user that does not exist"
        )

    def test_history_cannot_leak_cross_tenant(self, client_doer_a, client_doer_b, item_b):
        client_doer_b.post(_url(item_b, "submit/"), {}, format="json")
        assert WorkflowTransition.objects.filter(workflow_item=item_b).count() == 1
        assert client_doer_a.get(_url(item_b, "history/")).status_code == 404

    def test_transition_public_id_not_usable_cross_tenant(
        self, client_doer_a, client_doer_b, item_b
    ):
        """A transition UUID from tenant B must not resolve anything for A."""
        client_doer_b.post(_url(item_b, "submit/"), {}, format="json")
        row = WorkflowTransition.objects.get(workflow_item=item_b)
        for path in (
            f"/api/regx/v1/workflows/{row.public_id}/",
            f"/api/regx/v1/workflows/{row.public_id}/history/",
        ):
            assert client_doer_a.get(path).status_code == 404


@pytest.mark.django_db(transaction=True)
class TestConcurrentTransitions:
    """Two actors, one IN_REVIEW item, conflicting decisions.

    Requires real transactions and row locks, so the class is marked
    transaction=True and runs against PostgreSQL. SQLite could not express
    this, which is one reason the project prohibits it.
    """

    def test_approve_and_reject_race_has_exactly_one_winner(
        self, tenant_a, doer_a, reviewer_a, second_reviewer_a
    ):
        import threading

        from django.db import connection

        from workflows import services
        from workflows.transitions import IllegalWorkflowTransition

        item = WorkflowItem.objects.create(tenant=tenant_a, created_by=doer_a, title="Race item")
        services.perform_transition(item=item, action="submit", actor=doer_a, tenant=tenant_a)
        services.perform_transition(
            item=item, action="begin_review", actor=reviewer_a, tenant=tenant_a
        )

        barrier = threading.Barrier(2, timeout=20)
        outcomes: dict[str, str] = {}

        def attempt(name, action, actor, reason):
            try:
                barrier.wait()
                services.perform_transition(
                    item=item, action=action, actor=actor, tenant=tenant_a, reason=reason
                )
                outcomes[name] = "ok"
            except IllegalWorkflowTransition:
                outcomes[name] = "conflict"
            except Exception as exc:  # surfaced rather than swallowed
                outcomes[name] = f"error:{type(exc).__name__}"
            finally:
                connection.close()

        threads = [
            threading.Thread(target=attempt, args=("approver", "approve", reviewer_a, "")),
            threading.Thread(
                target=attempt, args=("rejecter", "reject", second_reviewer_a, "No good")
            ),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert len(outcomes) == 2, f"both threads must report: {outcomes}"
        assert sorted(outcomes.values()) == ["conflict", "ok"], (
            f"exactly one transition may succeed; got {outcomes}"
        )

        item.refresh_from_db()
        assert item.state in (S.APPROVED, S.REJECTED)
        # One transition attempted, one recorded -- the loser wrote nothing.
        rows = WorkflowTransition.objects.filter(workflow_item=item, from_state=S.IN_REVIEW)
        assert rows.count() == 1, "the losing transition must not appear in history"
        assert rows.first().to_state == item.state
