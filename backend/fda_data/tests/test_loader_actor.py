"""`--actor` on the loader commands, and loader != approver / activator.

Before: `import_fda_release` and `load_spl_terminology` recorded no user, so the
release's `imported_by` was empty and "the approver is not the loader" held by
procedure only. Now both commands require `--actor` (an existing, active user
holding fda_data.import), record it on the release and its audit events, and
`lifecycle.approve` / `lifecycle.activate` refuse that same user.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from audit.models import AuditEvent
from fda_data import lifecycle
from fda_data.audit_events import FdaDataEvent
from fda_data.models import ControlledRoute, FDADataSourceRelease, FDAReleaseStatus

from .conftest import _membership_with_role

FIXTURES = Path(__file__).parent / "fixtures"
IID = (FIXTURES / "iid" / "iir_ocomm_sample.csv").read_bytes()
ROUTES = (FIXTURES / "spl" / "route_administration_sample.csv").read_bytes()
RELEASES = "/api/regx/v1/fda-data/releases/"


def _import_iid(tmp_path, actor: str | None):
    path = tmp_path / "IIR_OCOMM.csv"
    path.write_bytes(IID)
    kwargs = {"dataset_type": "fda_iid", "source_reference": "Test fixture: real FDA rows"}
    if actor is not None:
        kwargs["actor"] = actor
    call_command("import_fda_release", str(path), stdout=io.StringIO(), **kwargs)
    return FDADataSourceRelease.objects.get()


def _load_routes(tmp_path, actor: str | None):
    path = tmp_path / "route-administration.csv"
    path.write_bytes(ROUTES)
    kwargs = {
        "list": "routes",
        "page_date": "2021-10-29",
        "source_reference": "FDA SPL route page, saved 2026-10-13",
    }
    if actor is not None:
        kwargs["actor"] = actor
    call_command("load_spl_terminology", str(path), stdout=io.StringIO(), **kwargs)
    return FDADataSourceRelease.objects.get()


LOADERS = [_import_iid, _load_routes]


@pytest.fixture
def doer(user_a, doer_membership):
    return user_a


@pytest.fixture
def doer_and_vp(db, tenant_a):
    """One person holding both roles: allowed to load AND to approve/activate,
    which is exactly the case separation of duties must catch."""
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.create_user(
        email="both@example.com", password="TestPass1234!", full_name="Both"
    )
    _membership_with_role(tenant_a, user, "doer")
    _membership_with_role(tenant_a, user, "vp")
    return user


def _client(user, tenant):
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_TENANT_SLUG=tenant.slug)
    return client


@pytest.mark.django_db
class TestActorIsRequiredAndChecked:
    @pytest.mark.parametrize("load", LOADERS)
    def test_missing_actor_is_refused(self, tmp_path, load):
        with pytest.raises(CommandError, match="--actor"):
            load(tmp_path, None)
        assert FDADataSourceRelease.objects.count() == 0

    @pytest.mark.parametrize("load", LOADERS)
    def test_unknown_actor_is_refused(self, tmp_path, load):
        with pytest.raises(CommandError, match="no user with this email"):
            load(tmp_path, "nobody@example.com")
        assert FDADataSourceRelease.objects.count() == 0

    @pytest.mark.parametrize("load", LOADERS)
    def test_inactive_actor_is_refused(self, tmp_path, load, doer):
        doer.is_active = False
        doer.save(update_fields=["is_active"])
        with pytest.raises(CommandError, match="not active"):
            load(tmp_path, doer.email)
        assert FDADataSourceRelease.objects.count() == 0

    @pytest.mark.parametrize("load", LOADERS)
    def test_actor_without_import_permission_is_refused(
        self, tmp_path, load, vp_user, vp_membership, reviewer_user, reviewer_membership, user_b
    ):
        # VP and Reviewer hold no fda_data.import; user_b has no membership at all.
        for user in (vp_user, reviewer_user, user_b):
            with pytest.raises(CommandError, match="does not hold 'fda_data.import'"):
                load(tmp_path, user.email)
        assert FDADataSourceRelease.objects.count() == 0

    @pytest.mark.parametrize("load", LOADERS)
    def test_membership_of_a_suspended_tenant_does_not_count(self, tmp_path, load, doer, tenant_a):
        tenant_a.status = "suspended"
        tenant_a.save(update_fields=["status"])
        with pytest.raises(CommandError, match="does not hold"):
            load(tmp_path, doer.email)

    @pytest.mark.parametrize("load", LOADERS)
    def test_actor_is_recorded_on_release_and_audit(self, tmp_path, load, doer):
        release = load(tmp_path, doer.email.upper())  # email match is case-insensitive
        assert release.imported_by == doer
        registered = AuditEvent.objects.get(
            event_type=FdaDataEvent.RELEASE_REGISTERED, resource_id=str(release.public_id)
        )
        assert (registered.actor_id, registered.actor_email) == (doer.id, doer.email)

    def test_import_started_event_carries_the_actor(self, tmp_path, doer):
        release = _import_iid(tmp_path, doer.email)
        started = AuditEvent.objects.get(
            event_type=FdaDataEvent.IMPORT_STARTED, resource_id=str(release.public_id)
        )
        assert (started.actor_id, started.actor_email) == (doer.id, doer.email)

    def test_command_output_names_the_loader(self, tmp_path, doer):
        path = tmp_path / "IIR_OCOMM.csv"
        path.write_bytes(IID)
        out = io.StringIO()
        call_command(
            "import_fda_release",
            str(path),
            dataset_type="fda_iid",
            source_reference="Test fixture",
            actor=doer.email,
            stdout=out,
        )
        assert f"loaded by          {doer.email}" in out.getvalue()


@pytest.mark.django_db
class TestLoaderCannotApproveOrActivate:
    @pytest.mark.parametrize("load", LOADERS)
    def test_approver_equal_to_loader_is_refused(self, tmp_path, load, doer_and_vp):
        release = load(tmp_path, doer_and_vp.email)
        lifecycle.submit_for_review(release, doer_and_vp)
        with pytest.raises(lifecycle.SeparationOfDutiesError) as exc:
            lifecycle.approve(release, doer_and_vp)
        assert exc.value.error_code == "loader_cannot_approve"
        release.refresh_from_db()
        assert release.status == FDAReleaseStatus.UNDER_REVIEW
        assert release.approved_by is None

    @pytest.mark.parametrize("load", LOADERS)
    def test_activator_equal_to_loader_is_refused(self, tmp_path, load, doer_and_vp, vp_user):
        release = load(tmp_path, doer_and_vp.email)
        lifecycle.submit_for_review(release, doer_and_vp)
        lifecycle.approve(release, vp_user)
        with pytest.raises(lifecycle.SeparationOfDutiesError) as exc:
            lifecycle.activate(release, doer_and_vp)
        assert exc.value.error_code == "loader_cannot_activate"
        release.refresh_from_db()
        assert release.status == FDAReleaseStatus.APPROVED
        assert release.activated_by is None

    @pytest.mark.parametrize("load", LOADERS)
    def test_approver_and_activator_other_than_loader_are_accepted(
        self, tmp_path, load, doer, vp_user
    ):
        release = load(tmp_path, doer.email)
        lifecycle.submit_for_review(release, doer)
        lifecycle.approve(release, vp_user)
        release = lifecycle.activate(release, vp_user)
        assert release.status == FDAReleaseStatus.ACTIVE
        assert (release.imported_by, release.approved_by, release.activated_by) == (
            doer,
            vp_user,
            vp_user,
        )

    def test_spl_terms_go_active_only_through_a_different_user(self, tmp_path, doer, vp_user):
        release = _load_routes(tmp_path, doer.email)
        lifecycle.submit_for_review(release, doer)
        lifecycle.approve(release, vp_user)
        lifecycle.activate(release, vp_user)
        assert ControlledRoute.objects.filter(lifecycle="active").exists()

    def test_api_returns_a_clear_403_for_the_loader(self, tmp_path, doer_and_vp, vp_user, tenant_a):
        _membership_with_role(tenant_a, vp_user, "vp")
        release = _import_iid(tmp_path, doer_and_vp.email)
        both = _client(doer_and_vp, tenant_a)
        url = f"{RELEASES}{release.public_id}/"
        # The fixture IID rows are unmapped; the #93 guard needs explicit confirmation.
        assert both.post(url + "submit-review/", {"confirm_unmapped": True}).status_code == 200

        resp = both.post(url + "approve/", {})
        assert resp.status_code == 403
        assert resp.data["error_code"] == "loader_cannot_approve"
        assert "loaded" in resp.data["detail"] or "imported" in resp.data["detail"]

        assert _client(vp_user, tenant_a).post(url + "approve/", {}).status_code == 200
        resp = both.post(url + "activate/", {})
        assert resp.status_code == 403
        assert resp.data["error_code"] == "loader_cannot_activate"
        assert _client(vp_user, tenant_a).post(url + "activate/", {}).status_code == 200

    def test_release_with_no_recorded_loader_is_not_blocked(self, tmp_path, doer, vp_user):
        """Releases loaded before --actor existed have no loader; nothing to compare."""
        release = _import_iid(tmp_path, doer.email)
        FDADataSourceRelease.objects.filter(pk=release.pk).update(imported_by=None)
        release.refresh_from_db()
        lifecycle.submit_for_review(release, vp_user)
        lifecycle.approve(release, vp_user)
        assert lifecycle.activate(release, vp_user).status == FDAReleaseStatus.ACTIVE
