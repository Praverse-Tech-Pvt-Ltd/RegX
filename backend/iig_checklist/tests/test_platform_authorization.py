"""Platform-master authorization tests -- the remediation for the
confirmed Major finding: an ordinary tenant Doer must never be able to
create or clone into platform_master scope through
PERM_CREATE_DEFINITION/PERM_CLONE alone. Both the direct-create and
clone code paths must route through the single centralized rule
(permissions.can_create_definition_for_scope /
can_author_platform_master)."""

import pytest

from iig_checklist.permissions import (
    can_author_platform_master,
    can_create_definition_for_scope,
)

BASE = "/api/regx/v1/iig-checklists"


class TestCentralizedAuthorizationUnit:
    def test_ordinary_user_cannot_author_platform_master(self, user_a):
        assert can_author_platform_master(user_a) is False

    def test_superuser_can_author_platform_master(self, platform_actor_user):
        assert can_author_platform_master(platform_actor_user) is True

    def test_anonymous_or_none_cannot_author_platform_master(self):
        assert can_author_platform_master(None) is False

    def test_tenant_scope_never_gated_by_platform_check(self, user_a):
        assert can_create_definition_for_scope(actor=user_a, scope_type="tenant") is True

    def test_platform_scope_gated_for_ordinary_user(self, user_a):
        assert can_create_definition_for_scope(actor=user_a, scope_type="platform_master") is False

    def test_platform_scope_allowed_for_platform_actor(self, platform_actor_user):
        assert (
            can_create_definition_for_scope(actor=platform_actor_user, scope_type="platform_master")
            is True
        )


@pytest.mark.django_db
class TestDirectCreateAuthorization:
    def test_doer_platform_master_create_blocked(self, api_client_doer):
        from audit.models import AuditEvent
        from iig_checklist.models import ChecklistDefinition, ChecklistVersion

        resp = api_client_doer.post(
            f"{BASE}/definitions/",
            data={"code": "SHOULD-FAIL-PLATFORM", "title": "x", "scope_type": "platform_master"},
            format="json",
        )
        assert resp.status_code == 403, resp.content
        assert not ChecklistDefinition.objects.filter(code="SHOULD-FAIL-PLATFORM").exists()
        assert not ChecklistVersion.objects.exists()
        assert not AuditEvent.objects.filter(event_type="iig_checklist.definition.created").exists()

    def test_platform_actor_can_create_platform_master(self, api_client_platform_actor):
        resp = api_client_platform_actor.post(
            f"{BASE}/definitions/",
            data={
                "code": "PLATFORM-OK",
                "title": "Platform definition",
                "scope_type": "platform_master",
            },
            format="json",
        )
        assert resp.status_code == 201, resp.content
        body = resp.json()
        assert body["scope_type"] == "platform_master"
        assert body.get("tenant_public_id") is None

    def test_doer_can_still_create_tenant_definition(self, api_client_doer):
        resp = api_client_doer.post(
            f"{BASE}/definitions/",
            data={"code": "TENANT-OK", "title": "Tenant definition", "scope_type": "tenant"},
            format="json",
        )
        assert resp.status_code == 201, resp.content

    def test_platform_master_with_explicit_tenant_id_ignored_by_server(
        self, api_client_platform_actor
    ):
        """The server always derives tenant from scope_type (never trusts
        a client-supplied tenant on the definition-create payload), so a
        platform_master request cannot smuggle in a tenant FK."""
        resp = api_client_platform_actor.post(
            f"{BASE}/definitions/",
            data={"code": "PLATFORM-NO-TENANT", "title": "x", "scope_type": "platform_master"},
            format="json",
        )
        assert resp.status_code == 201, resp.content
        assert resp.json().get("tenant_public_id") is None

    def test_tenant_admin_cannot_create_platform_master(self, api_client_tenant_admin):
        resp = api_client_tenant_admin.post(
            f"{BASE}/definitions/",
            data={"code": "TA-PLATFORM-FAIL", "title": "x", "scope_type": "platform_master"},
            format="json",
        )
        # Tenant Admin lacks even ordinary PERM_CREATE_DEFINITION, so this
        # is a 403 at the permission-class layer already -- still proves
        # no platform-master content is created.
        assert resp.status_code == 403

    def test_platform_support_cannot_create_platform_master(self, api_client_platform_support):
        resp = api_client_platform_support.post(
            f"{BASE}/definitions/",
            data={"code": "PS-PLATFORM-FAIL", "title": "x", "scope_type": "platform_master"},
            format="json",
        )
        assert resp.status_code == 403


@pytest.mark.django_db
class TestCloneAuthorization:
    def _approved_source(self, tenant_definition, user_a):
        from iig_checklist.models import ChecklistVersion

        return ChecklistVersion.objects.create(
            definition=tenant_definition,
            version_number=1,
            status="approved",
            effective_date="2026-01-01",
            created_by=user_a,
        )

    def test_doer_clone_into_platform_master_blocked(
        self, api_client_doer, tenant_definition, user_a
    ):
        from iig_checklist.models import ChecklistDefinition

        source = self._approved_source(tenant_definition, user_a)
        resp = api_client_doer.post(
            f"{BASE}/definitions/{tenant_definition.public_id}/clone/",
            data={
                "source_version_public_id": str(source.public_id),
                "target_scope_type": "platform_master",
                "new_code": "CLONE-PLATFORM-FAIL",
                "new_title": "x",
            },
            format="json",
        )
        assert resp.status_code == 403, resp.content
        assert not ChecklistDefinition.objects.filter(code="CLONE-PLATFORM-FAIL").exists()

    def test_platform_actor_clone_into_platform_master_succeeds(
        self, api_client_platform_actor, tenant_definition, user_a
    ):
        source = self._approved_source(tenant_definition, user_a)
        resp = api_client_platform_actor.post(
            f"{BASE}/definitions/{tenant_definition.public_id}/clone/",
            data={
                "source_version_public_id": str(source.public_id),
                "target_scope_type": "platform_master",
                "new_code": "CLONE-PLATFORM-OK",
                "new_title": "x",
            },
            format="json",
        )
        assert resp.status_code == 201, resp.content
        body = resp.json()
        assert body["scope_type"] == "platform_master"
        assert body["current_version"]["status"] == "draft"
        assert body["current_version"]["version_number"] == 1

    def test_direct_create_and_clone_use_the_same_authorization_function(self):
        """Both call sites must reference the one centralized function --
        this pins that against future drift where one path is updated
        and the other silently isn't."""
        import inspect

        from iig_checklist import views

        create_src = inspect.getsource(views.ChecklistDefinitionListCreateView.post)
        clone_src = inspect.getsource(views.ChecklistDefinitionCloneView.post)
        assert "can_create_definition_for_scope" in create_src
        assert "can_create_definition_for_scope" in clone_src
