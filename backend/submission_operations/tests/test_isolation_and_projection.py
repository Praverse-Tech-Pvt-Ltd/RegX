"""The two ways a cross-domain dashboard leaks: across tenants, and across
permissions.

Both are tested adversarially -- the fixtures build a world in which a leak
would be obvious and loud, then assert it does not happen. A test that only ever
sees an empty other-tenant proves nothing.

Synthetic codes throughout. No CTD, CEP, DMF or ANDA structure.
"""

import pytest

from submission_operations.attention import REASON_MODULE, AttentionReason
from submission_operations.projection import ALL_MODULES, visibility_for
from submission_operations.tests.conftest import (
    OPS_API,
    _client,
    _make_user,
    _membership_with_roles,
    add_blocker,
    attention_of,
    make_case,
    make_dossier,
    make_section,
    overview_of,
    reasons_of,
)


def _user_with_roles(tenant, roles, email):
    user = _make_user(email, "Scoped User")
    _membership_with_roles(tenant, user, roles)
    return user


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestTenantIsolation:
    @pytest.fixture
    def loud_tenant_b(self, tenant_b, admin_b):
        """Tenant B, full of work. If any of it reaches A, the numbers shout."""
        case = make_case(tenant_b, admin_b, title="B case")
        dossier = make_dossier(case, tenant_b, admin_b, title="B dossier")
        for i in range(12):
            section = make_section(dossier, tenant_b, admin_b, f"B{i}")
            add_blocker(section, tenant_b, admin_b)
        for i in range(5):
            make_case(tenant_b, admin_b, title=f"B extra {i}")
        return tenant_b

    def test_the_overview_counts_only_this_tenant(
        self, client_admin_a, tenant_a, admin_a, loud_tenant_b
    ):
        case = make_case(tenant_a, admin_a)
        dossier = make_dossier(case, tenant_a, admin_a)
        make_section(dossier, tenant_a, admin_a, "A")

        data = overview_of(client_admin_a)
        assert data["cases"]["open"] == 1, "tenant B has six more"
        assert data["dossiers"]["open"] == 1
        assert data["sections"]["required_total"] == 1, "tenant B has twelve more"
        assert data["blockers"]["open"] == 0, "every open blocker belongs to B"

    def test_the_attention_queue_holds_nothing_from_another_tenant(
        self, client_admin_a, tenant_a, admin_a, loud_tenant_b
    ):
        payload = attention_of(client_admin_a)
        a_case = make_case(tenant_a, admin_a)
        assert a_case is not None
        for row in payload["results"]:
            assert row["reason_code"] in AttentionReason.values
        # B's twelve blockers are the loudest possible signal.
        assert AttentionReason.OPEN_BLOCKER not in reasons_of(payload)

    def test_case_and_dossier_lists_are_scoped(
        self, client_admin_a, tenant_a, admin_a, loud_tenant_b
    ):
        case = make_case(tenant_a, admin_a, title="Only mine")
        make_dossier(case, tenant_a, admin_a, title="Only my dossier")

        cases = client_admin_a.get(f"{OPS_API}/cases/").data
        assert cases["count"] == 1
        assert cases["results"][0]["title"] == "Only mine"

        dossiers = client_admin_a.get(f"{OPS_API}/dossiers/").data
        assert dossiers["count"] == 1
        assert dossiers["results"][0]["title"] == "Only my dossier"

    def test_owner_workload_never_names_another_tenants_user(
        self, client_admin_a, tenant_a, admin_a, tenant_b, admin_b
    ):
        """User existence is itself disclosure. B's owner must not appear even
        as an anonymous row that reveals how many owners B has."""
        b_case = make_case(tenant_b, admin_b)
        b_dossier = make_dossier(b_case, tenant_b, admin_b)
        b_section = make_section(b_dossier, tenant_b, admin_b, "B1")
        from submission_dossiers import services as ds

        ds.update_section(section=b_section, tenant=tenant_b, actor=admin_b, owner=admin_b)

        rows = client_admin_a.get(f"{OPS_API}/owners/").data["results"]
        assert rows == []
        assert admin_b.email not in str(rows)

    def test_recent_activity_is_scoped(self, client_admin_a, tenant_a, admin_a, loud_tenant_b):
        make_case(tenant_a, admin_a, title="A only")
        rows = client_admin_a.get(f"{OPS_API}/recent-activity/").data["results"]
        assert rows, "tenant A did something"
        for row in rows:
            assert "B case" not in str(row)
            assert "B dossier" not in str(row)

    def test_a_tenant_b_admin_sees_only_b(self, client_admin_b, tenant_a, admin_a, loud_tenant_b):
        """The mirror. Isolation that only holds in one direction is a bug that
        happens to be pointing the other way."""
        make_case(tenant_a, admin_a)
        data = overview_of(client_admin_b)
        assert data["cases"]["open"] == 6
        assert data["blockers"]["open"] == 12


# ---------------------------------------------------------------------------
# Permission projection: null is not zero
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestPermissionProjection:
    @pytest.fixture
    def populated(self, tenant_a, admin_a):
        """Real work in every dimension, so a wrongly-zeroed module is visible."""
        from documents.models import Document
        from submission_dossiers import services as ds

        case = make_case(tenant_a, admin_a)
        dossier = make_dossier(case, tenant_a, admin_a)
        sections = [make_section(dossier, tenant_a, admin_a, f"A{i}") for i in range(3)]
        for section in sections:
            document = Document.objects.create(
                tenant=tenant_a, title="Synthetic document", document_type="other"
            )
            ds.link_target(
                kind="document",
                section=section,
                target_public_id=document.public_id,
                actor=admin_a,
                tenant=tenant_a,
            )
        add_blocker(sections[0], tenant_a, admin_a)
        return dossier

    def test_an_admin_sees_every_module(self, client_admin_a, populated):
        data = overview_of(client_admin_a)
        assert data["restricted_modules"] == []
        assert data["documents"]["linked"] == 3

    def test_a_caller_without_document_permission_gets_null_not_zero(
        self, tenant_a, support_a, client_support_a, populated
    ):
        """THE test the brief names, end to end over HTTP.

        Three linked documents exist. The answer must be `null`: `0` would be a
        false statement, and a leak on the day it becomes `3`.

        PLATFORM_SUPPORT is used because it is the only built-in role that
        genuinely lacks `documents.view` -- DOER, REVIEWER, VP and TENANT_ADMIN
        all hold it. Stripping a permission from a role that has it would make
        this pass for the wrong reason.
        """
        vis = visibility_for(support_a, tenant_a)
        assert vis.documents is False, "precondition: this role lacks documents.view"

        data = overview_of(client_support_a)
        assert data["documents"] is None
        assert data["documents"] != {"linked": 0}
        assert "documents" in data["restricted_modules"]

    def test_a_caller_without_checklist_permission_gets_null_not_zero(
        self, tenant_a, support_a, client_support_a, populated
    ):
        vis = visibility_for(support_a, tenant_a)
        assert vis.checklists is False, "precondition: this role lacks view_execution"
        data = overview_of(client_support_a)
        assert data["checklists"] is None
        assert "checklists" in data["restricted_modules"]

    @pytest.mark.parametrize(
        "module", ["cases", "dossiers", "documents", "workflows", "checklists", "upgrades"]
    )
    def test_every_module_is_null_when_its_gate_is_closed(
        self, tenant_a, admin_a, populated, module
    ):
        """Each dimension, driven at the service layer with one gate closed.

        Not every module has a built-in role that lacks it -- no shipped role is
        missing `workflows.view`, for instance -- so the gate is closed
        explicitly here. That covers the rule for every module rather than only
        the two reachable through a role today, and the HTTP-level tests above
        prove the wiring behind it is real.
        """
        from dataclasses import replace

        from submission_operations import services

        full = visibility_for(admin_a, tenant_a)
        assert full.allows(module), "precondition: an admin can normally see it"
        closed = replace(full, **{module: False})

        data = services.overview(user=admin_a, tenant=tenant_a, visibility=closed)
        assert data[module] is None, f"{module} must be null when its gate is closed"
        assert module in data["restricted_modules"]
        # The same request with the gate open is a real object, so the null
        # above is the gate rather than an empty tenant.
        open_data = services.overview(user=admin_a, tenant=tenant_a, visibility=full)
        assert open_data[module] is not None

    def test_platform_support_can_open_the_door_and_see_nothing_behind_it(
        self, client_support_a, tenant_a, support_a, populated
    ):
        """The dashboard permission is a door, not a key.

        PLATFORM_SUPPORT holds `submission_operations.view`. Whatever it does
        not separately hold comes back null -- the page renders and discloses
        nothing.
        """
        vis = visibility_for(support_a, tenant_a)
        data = overview_of(client_support_a)

        for module in ALL_MODULES:
            block = data.get(module)
            if not vis.allows(module):
                assert block is None, f"{module} leaked to a caller without its permission"

    def test_a_restricted_module_contributes_no_attention_rows(self, tenant_a, admin_a):
        """Not a redacted row, and not a "3 hidden" note -- the count is the leak."""
        from workflows.models import WorkflowItem

        case = make_case(tenant_a, admin_a)
        dossier = make_dossier(case, tenant_a, admin_a)
        make_section(dossier, tenant_a, admin_a, "A")
        for i in range(3):
            WorkflowItem.objects.create(
                tenant=tenant_a,
                title=f"Rejected workflow {i}",
                state=WorkflowItem.State.REJECTED,
                created_by=admin_a,
            )

        from dataclasses import replace

        from submission_operations import services

        full = visibility_for(admin_a, tenant_a)
        # An admin, who may see them, does -- so the absence below is the gate
        # and not an empty fixture.
        allowed_codes = reasons_of(attention_of(_client(admin_a, tenant_a)))
        assert AttentionReason.WORKFLOW_REJECTED in allowed_codes

        closed = replace(full, workflows=False)
        rows, _ = services.attention_rows(tenant=tenant_a, visibility=closed)
        codes = [r["reason_code"] for r in rows]
        assert AttentionReason.WORKFLOW_REJECTED not in codes
        assert AttentionReason.WORKFLOW_WAITING_REVIEW not in codes
        assert "Rejected workflow" not in str(rows)
        # No count of what was withheld either: "3 hidden" is the disclosure.
        assert "hidden" not in str(rows).lower()
        assert "withheld" not in str(rows).lower()

    def test_case_and_dossier_panels_say_restricted_rather_than_empty(self, tenant_a):
        """ "No cases" and "you may not see cases" are different states, and a
        screen that renders them identically teaches users the wrong thing."""
        from authorization.models import Role

        user = _make_user("doorman@example.test", "Doorman")
        _membership_with_roles(tenant_a, user, [Role.BuiltIn.PLATFORM_SUPPORT])
        full = visibility_for(user, tenant_a)
        client = _client(user, tenant_a)

        body = client.get(f"{OPS_API}/cases/").data
        if full.cases:
            # Permitted and empty: an empty list and a zero count. This is a
            # different answer from the restricted branch, and the screen must
            # not render them the same way.
            assert body["results"] == []
            assert body["count"] == 0
            assert "restricted" not in body
        else:
            assert body["restricted"] is True
            assert body["results"] is None
            assert body["count"] is None

    def test_every_attention_reason_declares_the_module_that_gates_it(self):
        """A reason with no module mapping is a row nobody gated."""
        for reason in AttentionReason.values:
            assert REASON_MODULE[reason] in ALL_MODULES


# ---------------------------------------------------------------------------
# Recent activity payload discipline
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestRecentActivityDiscipline:
    def test_only_allow_listed_payload_keys_travel(self, client_admin_a, tenant_a, admin_a):
        """An allow-list, so a new event type from a later milestone appears
        here when somebody decides it is safe -- not automatically."""
        from submission_operations.services import ACTIVITY_PAYLOAD_KEYS

        case = make_case(tenant_a, admin_a, title="Very Secret Case Title")
        dossier = make_dossier(case, tenant_a, admin_a, title="Very Secret Dossier")
        make_section(dossier, tenant_a, admin_a, "A")

        rows = client_admin_a.get(f"{OPS_API}/recent-activity/").data["results"]
        assert rows
        for row in rows:
            assert set(row["detail"]) <= set(ACTIVITY_PAYLOAD_KEYS)  # keys, not modules
        assert "Very Secret Case Title" not in str(rows)
        assert "Very Secret Dossier" not in str(rows)

    def test_no_actor_identity_travels_with_an_activity_row(
        self, client_admin_a, tenant_a, admin_a
    ):
        """`Visibility` has no identity gate.

        It covers cases, dossiers, documents, workflows, checklists, blueprints
        and upgrades -- nothing about people. Emitting `actor_email` would turn
        permission to see an event's MODULE into permission to learn who
        performed it, which is a disclosure this projection never agreed to
        make. The operational question is what happened to which thing, and
        when.
        """
        make_case(tenant_a, admin_a, title="Something happened")

        rows = client_admin_a.get(f"{OPS_API}/recent-activity/").data["results"]
        assert rows, "precondition: the actor did something auditable"
        for row in rows:
            assert "actor_email" not in row
            assert "actor" not in row
        assert admin_a.email not in str(rows)
        assert "@" not in str(rows), "no address of any shape reaches the feed"

    def test_the_serialized_row_carries_exactly_the_intended_fields(
        self, client_admin_a, tenant_a, admin_a
    ):
        make_case(tenant_a, admin_a)
        row = client_admin_a.get(f"{OPS_API}/recent-activity/").data["results"][0]
        assert set(row) == {
            "event_type",
            "resource_type",
            "resource_public_id",
            "occurred_at",
            "detail",
        }

    def test_another_tenants_actor_never_appears(
        self, client_admin_a, tenant_a, admin_a, tenant_b, admin_b
    ):
        make_case(tenant_b, admin_b, title="B did something")
        make_case(tenant_a, admin_a, title="A did something")

        rows = client_admin_a.get(f"{OPS_API}/recent-activity/").data["results"]
        assert admin_b.email not in str(rows)
        assert "B did something" not in str(rows)

    def test_the_feed_still_works_without_actor_identity(self, client_admin_a, tenant_a, admin_a):
        """Removing the field must not empty the panel."""
        case = make_case(tenant_a, admin_a)
        dossier = make_dossier(case, tenant_a, admin_a)
        make_section(dossier, tenant_a, admin_a, "A")

        rows = client_admin_a.get(f"{OPS_API}/recent-activity/").data["results"]
        assert len(rows) >= 2
        for row in rows:
            assert row["event_type"]
            assert row["resource_public_id"]
            assert row["occurred_at"]

    def test_every_allow_listed_event_type_is_a_real_event(self):
        """An allow-list of names that match nothing does not fail loudly.

        The first version of this list was written from memory and named
        `dossier.created` where the enum says `submission_dossier.created`, so
        the feed silently carried case events and nothing else. This asserts
        every entry against the owning app's own enum, which is the only way a
        typo here becomes visible.
        """
        from dossier_blueprints.audit_events import BlueprintEvent
        from dossier_upgrades.audit_events import UpgradeEvent
        from regulatory_cases.audit_events import CaseEvent
        from submission_dossiers.audit_events import DossierEvent
        from submission_operations.services import ACTIVITY_EVENT_MODULES
        from workflows.audit_events import WorkflowEvent

        real = set()
        for enum in (CaseEvent, DossierEvent, WorkflowEvent, BlueprintEvent, UpgradeEvent):
            real |= {
                v for k, v in vars(enum).items() if not k.startswith("_") and isinstance(v, str)
            }

        unknown = set(ACTIVITY_EVENT_MODULES) - real
        assert unknown == set(), f"allow-listed events that no app emits: {unknown}"

    def test_the_feed_carries_dossier_and_section_events_not_only_cases(
        self, client_admin_a, tenant_a, admin_a
    ):
        """The regression the wrong names caused: a feed that looked alive
        because cases still appeared."""
        case = make_case(tenant_a, admin_a)
        dossier = make_dossier(case, tenant_a, admin_a)
        section = make_section(dossier, tenant_a, admin_a, "A")
        add_blocker(section, tenant_a, admin_a)

        types = {
            row["event_type"]
            for row in client_admin_a.get(f"{OPS_API}/recent-activity/").data["results"]
        }
        assert "regulatory_case.created" in types
        assert "submission_dossier.created" in types
        assert "dossier_section.created" in types
        assert "dossier_section.blocker_created" in types

    def test_an_event_type_outside_the_allow_list_never_appears(
        self, client_admin_a, tenant_a, admin_a
    ):
        from audit.models import AuditEvent

        AuditEvent.objects.create(
            tenant_id=tenant_a.pk,
            event_type="something.unreviewed",
            resource_type="mystery",
            resource_id="x",
            payload={"secret": "should never surface"},
        )
        rows = client_admin_a.get(f"{OPS_API}/recent-activity/").data["results"]
        assert all(r["event_type"] != "something.unreviewed" for r in rows)
        assert "should never surface" not in str(rows)


# ---------------------------------------------------------------------------
# Cross-module identifiers
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCrossModuleIdentifiers:
    """A field is gated on the module that OWNS it, not the one that surfaced it.

    Found by adversarial review: an upgrade attention row carried the dossier's
    title and `public_id` gated only on `dossier_upgrades.view`, and the activity
    feed did the same in its detail payload. An upgrade permission is not a
    dossier permission, and "which module emitted this row" is the wrong question
    to ask when deciding what may travel with it.

    No shipped role holds upgrades without dossiers, so this is defence in depth
    -- but a projection that is correct only because of a role coincidence is not
    a projection, and the roles are in-code and editable.
    """

    def _plan_setup(self, tenant, actor):
        from dossier_blueprints import services as bp
        from dossier_upgrades import services as up

        blueprint = bp.create_blueprint(tenant=tenant, actor=actor, name="Outline")
        v1 = bp.create_version(blueprint=blueprint, tenant=tenant, actor=actor)
        bp.create_section(
            version=v1, tenant=tenant, actor=actor, section_code="A", title="Section A"
        )
        v1 = bp.activate_version(version=v1, tenant=tenant, actor=actor)
        case = make_case(tenant, actor, title="Upgrade case")
        instantiation = bp.instantiate_version(
            version=v1,
            tenant=tenant,
            actor=actor,
            case_public_id=case.public_id,
            title="Confidential dossier name",
        )
        v2 = bp.create_version(blueprint=blueprint, tenant=tenant, actor=actor, source_version=v1)
        bp.create_section(
            version=v2, tenant=tenant, actor=actor, section_code="B", title="Section B"
        )
        v2 = bp.activate_version(version=v2, tenant=tenant, actor=actor)
        plan = up.generate_plan(
            dossier=instantiation.dossier,
            tenant=tenant,
            actor=actor,
            target_version_public_id=v2.public_id,
        )
        # Make the plan stale so it reaches the attention queue.
        from submission_dossiers import services as ds

        ds.create_section(
            dossier=instantiation.dossier,
            tenant=tenant,
            actor=actor,
            section_code="MANUAL",
            title="Manual",
        )
        return instantiation.dossier, plan

    def test_an_upgrade_row_hides_the_dossier_from_a_caller_without_dossier_view(
        self, tenant_a, admin_a
    ):
        from dataclasses import replace

        from submission_operations import services

        dossier, _plan = self._plan_setup(tenant_a, admin_a)
        full = visibility_for(admin_a, tenant_a)

        # With dossier permission, the row names the dossier.
        rows, _ = services.attention_rows(tenant=tenant_a, visibility=full)
        upgrade_rows = [r for r in rows if r["resource_type"] == "dossier_upgrade_plan"]
        assert upgrade_rows, "precondition: an upgrade row is in the queue"
        assert upgrade_rows[0]["resource_label"] == "Confidential dossier name"
        assert upgrade_rows[0]["dossier_public_id"] == dossier.public_id

        # Without it, the row is still there -- it is about the plan -- but it
        # says nothing about the dossier.
        closed = replace(full, dossiers=False)
        rows, _ = services.attention_rows(tenant=tenant_a, visibility=closed)
        upgrade_rows = [r for r in rows if r["resource_type"] == "dossier_upgrade_plan"]
        assert upgrade_rows, "the upgrade row itself is still permitted"
        assert upgrade_rows[0]["resource_label"] == "Upgrade plan"
        assert upgrade_rows[0]["dossier_public_id"] is None
        assert "Confidential dossier name" not in str(rows)
        assert str(dossier.public_id) not in str(rows)

    def test_activity_detail_gates_each_identifier_on_its_own_module(self, tenant_a, admin_a):
        from dataclasses import replace

        from submission_operations import services

        dossier, _plan = self._plan_setup(tenant_a, admin_a)
        full = visibility_for(admin_a, tenant_a)

        rows = services.recent_activity(tenant=tenant_a, visibility=full)
        assert any("dossier_public_id" in r["detail"] for r in rows), (
            "precondition: some event carries a dossier identifier"
        )

        closed = replace(full, dossiers=False)
        rows = services.recent_activity(tenant=tenant_a, visibility=closed)
        for row in rows:
            assert "dossier_public_id" not in row["detail"]
        assert str(dossier.public_id) not in str([r["detail"] for r in rows])

    def test_case_identifiers_are_gated_on_case_permission(self, tenant_a, admin_a):
        from dataclasses import replace

        from submission_operations import services

        case = make_case(tenant_a, admin_a)
        dossier = make_dossier(case, tenant_a, admin_a)
        make_section(dossier, tenant_a, admin_a, "A")

        full = visibility_for(admin_a, tenant_a)
        rows, _ = services.attention_rows(tenant=tenant_a, visibility=full)
        assert any(r["case_public_id"] == case.public_id for r in rows)

        closed = replace(full, cases=False)
        rows, _ = services.attention_rows(tenant=tenant_a, visibility=closed)
        assert all(r["case_public_id"] is None for r in rows)
        assert str(case.public_id) not in str([r["case_public_id"] for r in rows])
