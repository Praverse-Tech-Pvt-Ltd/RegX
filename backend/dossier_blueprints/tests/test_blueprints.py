"""Blueprint identity, versioning, structure and lifecycle.

Synthetic data only. Section codes are generic (A, A.1, B) and encode no
regulatory structure -- none ships in this milestone.
"""

import pytest

from dossier_blueprints import services
from dossier_blueprints.models import (
    MAX_BLUEPRINT_DEPTH,
    BlueprintVersionStatus,
    DossierBlueprint,
    DossierBlueprintSection,
    DossierBlueprintVersion,
)
from dossier_blueprints.tests.conftest import (
    BLUEPRINT_API,
    SECTION_API,
    VERSION_API,
    make_section,
)


def _reload(obj):
    obj.refresh_from_db()
    return obj


# ---------------------------------------------------------------------------
# Blueprint identity
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestBlueprint:
    def test_create(self, tenant_a, admin_a):
        blueprint = services.create_blueprint(
            tenant=tenant_a, actor=admin_a, name="  Padded name  "
        )
        assert blueprint.name == "Padded name"
        assert blueprint.tenant_id == tenant_a.pk
        assert blueprint.created_by_id == admin_a.pk
        assert not blueprint.is_archived

    def test_duplicate_active_name_refused(self, tenant_a, admin_a, blueprint_a):
        with pytest.raises(services.DuplicateValue):
            services.create_blueprint(tenant=tenant_a, actor=admin_a, name=blueprint_a.name)

    def test_archiving_frees_the_name(self, tenant_a, admin_a, blueprint_a):
        """A typo should not burn a name permanently -- the same reasoning as a
        retired section freeing its code."""
        services.archive_blueprint(blueprint=blueprint_a, tenant=tenant_a, actor=admin_a)
        reused = services.create_blueprint(tenant=tenant_a, actor=admin_a, name=blueprint_a.name)
        assert reused.pk != blueprint_a.pk

    def test_the_same_name_may_exist_in_another_tenant(self, tenant_b, admin_b, blueprint_a):
        other = services.create_blueprint(tenant=tenant_b, actor=admin_b, name=blueprint_a.name)
        assert other.tenant_id == tenant_b.pk

    def test_archived_blueprint_refuses_edits_and_versions(self, tenant_a, admin_a, blueprint_a):
        services.archive_blueprint(blueprint=blueprint_a, tenant=tenant_a, actor=admin_a)
        with pytest.raises(services.BlueprintLocked):
            services.update_blueprint(
                blueprint=blueprint_a, tenant=tenant_a, actor=admin_a, name="Renamed"
            )
        with pytest.raises(services.BlueprintLocked):
            services.create_version(blueprint=blueprint_a, tenant=tenant_a, actor=admin_a)

    def test_owner_must_be_a_member_of_this_tenant(self, client_admin_a, doer_b):
        r = client_admin_a.post(
            f"{BLUEPRINT_API}/",
            {"name": "With a foreign owner", "owner_public_id": str(doer_b.public_id)},
            format="json",
        )
        assert r.status_code == 400
        assert not DossierBlueprint.objects.filter(name="With a foreign owner").exists()

    def test_blueprint_cannot_be_deleted(self, blueprint_a):
        from dossier_blueprints.models import BlueprintMutationForbidden

        with pytest.raises(BlueprintMutationForbidden):
            blueprint_a.delete()
        assert DossierBlueprint.objects.filter(pk=blueprint_a.pk).exists()


@pytest.mark.django_db
class TestBlueprintPermissions:
    def test_support_may_read_but_not_create(self, client_support_a):
        assert client_support_a.get(f"{BLUEPRINT_API}/").status_code == 200
        r = client_support_a.post(f"{BLUEPRINT_API}/", {"name": "Nope"}, format="json")
        assert r.status_code == 403

    def test_doer_may_author_but_not_activate(self, client_doer_a, populated_draft_a):
        r = client_doer_a.post(f"{VERSION_API}/{populated_draft_a.public_id}/activate/")
        assert r.status_code == 403
        assert _reload(populated_draft_a).status == BlueprintVersionStatus.DRAFT

    def test_reviewer_may_activate(self, client_reviewer_a, populated_draft_a):
        r = client_reviewer_a.post(f"{VERSION_API}/{populated_draft_a.public_id}/activate/")
        assert r.status_code == 200
        assert _reload(populated_draft_a).status == BlueprintVersionStatus.ACTIVE

    def test_reviewer_may_not_author_sections(self, client_reviewer_a, draft_a):
        r = client_reviewer_a.post(
            f"{VERSION_API}/{draft_a.public_id}/sections/",
            {"section_code": "A", "title": "A"},
            format="json",
        )
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestTenantIsolation:
    def test_blueprint_list_shows_only_this_tenant(self, client_doer_a, blueprint_a, blueprint_b):
        r = client_doer_a.get(f"{BLUEPRINT_API}/")
        ids = {row["public_id"] for row in r.data["results"]}
        assert str(blueprint_a.public_id) in ids
        assert str(blueprint_b.public_id) not in ids

    def test_cross_tenant_blueprint_is_404_not_403(self, client_doer_a, blueprint_b):
        """404, so the response cannot confirm the row exists."""
        assert client_doer_a.get(f"{BLUEPRINT_API}/{blueprint_b.public_id}/").status_code == 404

    def test_cross_tenant_version_is_404(self, client_doer_a, draft_b):
        assert client_doer_a.get(f"{VERSION_API}/{draft_b.public_id}/").status_code == 404

    def test_cross_tenant_section_is_404(self, client_admin_a, draft_b, tenant_b, admin_b):
        section = make_section(draft_b, tenant_b, admin_b, "A")
        r = client_admin_a.patch(
            f"{SECTION_API}/{section.public_id}/", {"title": "Hijacked"}, format="json"
        )
        assert r.status_code == 404
        assert _reload(section).title != "Hijacked"

    def test_cross_tenant_activation_refused(self, client_admin_a, draft_b, tenant_b, admin_b):
        make_section(draft_b, tenant_b, admin_b, "A")
        r = client_admin_a.post(f"{VERSION_API}/{draft_b.public_id}/activate/")
        assert r.status_code == 404
        assert _reload(draft_b).status == BlueprintVersionStatus.DRAFT

    def test_cross_tenant_clone_refused(self, tenant_a, admin_a, blueprint_a, draft_b):
        """A version from another tenant must not seed a local draft."""
        with pytest.raises(Exception) as exc:
            services.create_version(
                blueprint=blueprint_a, tenant=tenant_a, actor=admin_a, source_version=draft_b
            )
        assert exc.type in (
            DossierBlueprintVersion.DoesNotExist,
            services.InvalidTarget,
        )

    def test_service_level_tenant_gate_refuses_a_foreign_version(self, tenant_a, admin_a, draft_b):
        """Isolates `_assert_tenant` from the view's tenant filter.

        Most cross-tenant paths are stopped twice: the view looks rows up
        `filter(tenant=...)`, and the service re-asserts. Mutation-testing the
        service gate showed only one test noticing when it was removed -- the
        rest were passing on the view's filter alone. These call the service
        directly with a foreign object, so only the service gate can refuse.
        """
        for call in (
            lambda: services.retire_version(version=draft_b, tenant=tenant_a, actor=admin_a),
            lambda: services.activate_version(version=draft_b, tenant=tenant_a, actor=admin_a),
        ):
            with pytest.raises(DossierBlueprintVersion.DoesNotExist):
                call()
        assert _reload(draft_b).status == BlueprintVersionStatus.DRAFT

    def test_service_level_tenant_gate_refuses_a_foreign_blueprint(
        self, tenant_a, admin_a, blueprint_b
    ):
        with pytest.raises(DossierBlueprint.DoesNotExist):
            services.update_blueprint(
                blueprint=blueprint_b, tenant=tenant_a, actor=admin_a, name="Hijacked"
            )
        with pytest.raises(DossierBlueprint.DoesNotExist):
            services.archive_blueprint(blueprint=blueprint_b, tenant=tenant_a, actor=admin_a)
        with pytest.raises(DossierBlueprint.DoesNotExist):
            services.create_version(blueprint=blueprint_b, tenant=tenant_a, actor=admin_a)
        assert _reload(blueprint_b).name != "Hijacked"
        assert not _reload(blueprint_b).is_archived

    def test_service_level_tenant_gate_refuses_a_foreign_section(
        self, tenant_a, admin_a, draft_b, tenant_b, admin_b
    ):
        section = make_section(draft_b, tenant_b, admin_b, "A")
        for call in (
            lambda: services.update_section(
                section=section, tenant=tenant_a, actor=admin_a, title="Hijacked"
            ),
            lambda: services.retire_section(section=section, tenant=tenant_a, actor=admin_a),
            lambda: services.reorder_section(
                section=section, tenant=tenant_a, actor=admin_a, sequence=0
            ),
        ):
            with pytest.raises(DossierBlueprintSection.DoesNotExist):
                call()
        assert _reload(section).title != "Hijacked"
        assert not _reload(section).is_retired

    def test_clone_source_must_belong_to_the_same_blueprint(self, tenant_a, admin_a, draft_a):
        other = services.create_blueprint(tenant=tenant_a, actor=admin_a, name="Other outline")
        with pytest.raises(services.InvalidTarget):
            services.create_version(
                blueprint=other, tenant=tenant_a, actor=admin_a, source_version=draft_a
            )


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestVersions:
    def test_first_version_is_one(self, draft_a):
        assert draft_a.version_number == 1
        assert draft_a.status == BlueprintVersionStatus.DRAFT

    def test_next_version_increments(self, blueprint_a, tenant_a, admin_a, draft_a):
        second = services.create_version(blueprint=blueprint_a, tenant=tenant_a, actor=admin_a)
        assert second.version_number == 2

    def test_version_numbers_are_blueprint_local(self, tenant_a, admin_a, draft_a):
        other = services.create_blueprint(tenant=tenant_a, actor=admin_a, name="Second outline")
        first_of_other = services.create_version(blueprint=other, tenant=tenant_a, actor=admin_a)
        assert first_of_other.version_number == 1

    def test_clone_copies_structure_and_hierarchy(self, blueprint_a, tenant_a, admin_a, active_a):
        v2 = services.create_version(
            blueprint=blueprint_a, tenant=tenant_a, actor=admin_a, source_version=active_a
        )
        source = list(active_a.sections.order_by("section_code"))
        cloned = list(v2.sections.order_by("section_code"))
        assert [s.section_code for s in cloned] == [s.section_code for s in source]
        assert [s.required for s in cloned] == [s.required for s in source]
        assert v2.supersedes_id == active_a.pk

        # New rows, not shared ones.
        assert {s.pk for s in cloned}.isdisjoint({s.pk for s in source})

        # Parents remapped into the new version, never left pointing at the old.
        for s in cloned:
            if s.parent_id:
                assert s.parent.blueprint_version_id == v2.pk

    def test_clone_skips_retired_source_sections(
        self, blueprint_a, tenant_a, admin_a, populated_draft_a
    ):
        doomed = populated_draft_a.sections.get(section_code="A.2")
        services.retire_section(section=doomed, tenant=tenant_a, actor=admin_a)
        services.activate_version(version=populated_draft_a, tenant=tenant_a, actor=admin_a)

        v2 = services.create_version(
            blueprint=blueprint_a,
            tenant=tenant_a,
            actor=admin_a,
            source_version=populated_draft_a,
        )
        assert not v2.sections.filter(section_code="A.2").exists()

    def test_editing_an_active_version_is_refused(self, active_a, tenant_a, admin_a):
        """The whole point of versioning: corrections need a new version."""
        with pytest.raises(services.BlueprintLocked):
            make_section(active_a, tenant_a, admin_a, "C")

        existing = active_a.sections.first()
        with pytest.raises(services.BlueprintLocked):
            services.update_section(
                section=existing, tenant=tenant_a, actor=admin_a, title="Edited"
            )

    def test_retired_version_is_immutable(self, active_a, tenant_a, admin_a):
        services.retire_version(version=active_a, tenant=tenant_a, actor=admin_a)
        with pytest.raises(services.BlueprintLocked):
            make_section(active_a, tenant_a, admin_a, "C")
        with pytest.raises(services.BlueprintLocked):
            services.retire_version(version=active_a, tenant=tenant_a, actor=admin_a)

    def test_activating_v2_retires_v1_atomically(self, blueprint_a, tenant_a, admin_a, active_a):
        v2 = services.create_version(
            blueprint=blueprint_a, tenant=tenant_a, actor=admin_a, source_version=active_a
        )
        services.activate_version(version=v2, tenant=tenant_a, actor=admin_a)

        assert _reload(active_a).status == BlueprintVersionStatus.RETIRED
        assert _reload(v2).status == BlueprintVersionStatus.ACTIVE
        assert (
            DossierBlueprintVersion.objects.filter(
                blueprint=blueprint_a, status=BlueprintVersionStatus.ACTIVE
            ).count()
            == 1
        )

    def test_only_one_active_version_is_enforced_by_the_database(
        self, blueprint_a, tenant_a, admin_a, active_a
    ):
        """Defence in depth behind the service: the partial unique index makes a
        second ACTIVE row impossible even for a path that skips the service."""
        from django.db import IntegrityError, transaction
        from django.utils import timezone

        v2 = services.create_version(blueprint=blueprint_a, tenant=tenant_a, actor=admin_a)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                DossierBlueprintVersion.governed.filter(pk=v2.pk).update(
                    status=BlueprintVersionStatus.ACTIVE,
                    activated_at=timezone.now(),
                    activated_by=admin_a,
                )

    def test_activation_requires_at_least_one_section(self, draft_a, tenant_a, admin_a):
        with pytest.raises(services.NotActivatable):
            services.activate_version(version=draft_a, tenant=tenant_a, actor=admin_a)

    def test_activation_is_not_a_regulatory_claim(self, active_a):
        """Pins the vocabulary: there is no APPROVED state to reach.

        `templates_registry` has one, backed by a real approval trail tied to the
        regulatory content gate. Borrowing that word here would assert a decision
        nobody made, so the enum simply does not contain it.
        """
        assert set(BlueprintVersionStatus.values) == {"draft", "active", "retired"}
        assert "approved" not in BlueprintVersionStatus.values

    def test_version_cannot_be_deleted(self, draft_a):
        from dossier_blueprints.models import BlueprintMutationForbidden

        with pytest.raises(BlueprintMutationForbidden):
            draft_a.delete()
        with pytest.raises(BlueprintMutationForbidden):
            DossierBlueprintVersion.objects.filter(pk=draft_a.pk).delete()
        assert DossierBlueprintVersion.objects.filter(pk=draft_a.pk).exists()

    def test_a_draft_may_be_retired_without_activation(self, draft_a, tenant_a, admin_a):
        """Abandoning a draft is retirement, not deletion: its creation was
        audited and the row stays readable."""
        services.retire_version(version=draft_a, tenant=tenant_a, actor=admin_a)
        assert _reload(draft_a).status == BlueprintVersionStatus.RETIRED
        assert DossierBlueprintVersion.objects.filter(pk=draft_a.pk).exists()


# ---------------------------------------------------------------------------
# Sections and hierarchy
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestSectionHierarchy:
    def test_root_and_child(self, draft_a, tenant_a, admin_a):
        root = make_section(draft_a, tenant_a, admin_a, "A")
        child = make_section(draft_a, tenant_a, admin_a, "A.1", parent=root)
        assert child.parent_id == root.pk

    def test_hierarchy_is_not_derived_from_the_code(self, draft_a, tenant_a, admin_a):
        """ "A.1" is a label, not a parent reference. Creating it without a parent
        must leave it a root -- no string parsing anywhere."""
        make_section(draft_a, tenant_a, admin_a, "A")
        loose = make_section(draft_a, tenant_a, admin_a, "A.1")
        assert loose.parent_id is None

    def test_arbitrary_codes_are_accepted(self, draft_a, tenant_a, admin_a):
        for code in ("1", "1.1", "A", "Response-01", "zz_9"):
            section = make_section(draft_a, tenant_a, admin_a, code)
            assert section.section_code == code

    def test_self_parent_refused(self, draft_a, tenant_a, admin_a):
        section = make_section(draft_a, tenant_a, admin_a, "A")
        with pytest.raises(services.InvalidHierarchy):
            services.update_section(section=section, tenant=tenant_a, actor=admin_a, parent=section)

    def test_cycle_refused(self, draft_a, tenant_a, admin_a):
        a = make_section(draft_a, tenant_a, admin_a, "A")
        b = make_section(draft_a, tenant_a, admin_a, "A.1", parent=a)
        c = make_section(draft_a, tenant_a, admin_a, "A.1.1", parent=b)
        with pytest.raises(services.InvalidHierarchy):
            services.update_section(section=a, tenant=tenant_a, actor=admin_a, parent=c)

    def test_cross_version_parent_refused(self, blueprint_a, draft_a, tenant_a, admin_a):
        other_version = services.create_version(
            blueprint=blueprint_a, tenant=tenant_a, actor=admin_a
        )
        foreign_parent = make_section(other_version, tenant_a, admin_a, "X")
        with pytest.raises(services.InvalidHierarchy):
            make_section(draft_a, tenant_a, admin_a, "A", parent=foreign_parent)

    def test_cross_tenant_parent_refused(
        self, draft_a, tenant_a, admin_a, draft_b, tenant_b, admin_b
    ):
        foreign = make_section(draft_b, tenant_b, admin_b, "X")
        with pytest.raises(services.InvalidHierarchy):
            make_section(draft_a, tenant_a, admin_a, "A", parent=foreign)

    def test_retired_parent_refused(self, draft_a, tenant_a, admin_a):
        parent = make_section(draft_a, tenant_a, admin_a, "A")
        services.retire_section(section=parent, tenant=tenant_a, actor=admin_a)
        with pytest.raises(services.InvalidHierarchy):
            make_section(draft_a, tenant_a, admin_a, "B", parent=parent)

    def test_depth_ceiling(self, draft_a, tenant_a, admin_a):
        parent = None
        for level in range(MAX_BLUEPRINT_DEPTH):
            parent = make_section(draft_a, tenant_a, admin_a, f"L{level}", parent=parent)
        with pytest.raises(services.InvalidHierarchy):
            make_section(draft_a, tenant_a, admin_a, "TooDeep", parent=parent)

    def test_depth_ceiling_matches_the_dossier_ceiling(self):
        """A blueprint deeper than a dossier may hold would be unusable."""
        from submission_dossiers.models import MAX_SECTION_DEPTH

        assert MAX_BLUEPRINT_DEPTH == MAX_SECTION_DEPTH

    def test_duplicate_active_code_refused(self, draft_a, tenant_a, admin_a):
        make_section(draft_a, tenant_a, admin_a, "A")
        with pytest.raises(services.DuplicateValue):
            make_section(draft_a, tenant_a, admin_a, "A")

    def test_retiring_frees_the_code(self, draft_a, tenant_a, admin_a):
        first = make_section(draft_a, tenant_a, admin_a, "A")
        services.retire_section(section=first, tenant=tenant_a, actor=admin_a)
        again = make_section(draft_a, tenant_a, admin_a, "A")
        assert again.pk != first.pk

    def test_retire_refused_while_children_are_active(self, draft_a, tenant_a, admin_a):
        parent = make_section(draft_a, tenant_a, admin_a, "A")
        make_section(draft_a, tenant_a, admin_a, "A.1", parent=parent)
        with pytest.raises(services.InvalidHierarchy):
            services.retire_section(section=parent, tenant=tenant_a, actor=admin_a)

    def test_section_cannot_be_deleted(self, draft_a, tenant_a, admin_a):
        from dossier_blueprints.models import BlueprintMutationForbidden

        section = make_section(draft_a, tenant_a, admin_a, "A")
        with pytest.raises(BlueprintMutationForbidden):
            section.delete()
        with pytest.raises(BlueprintMutationForbidden):
            DossierBlueprintSection.objects.filter(pk=section.pk).delete()
        assert DossierBlueprintSection.objects.filter(pk=section.pk).exists()

    def test_reorder(self, draft_a, tenant_a, admin_a):
        make_section(draft_a, tenant_a, admin_a, "A")
        make_section(draft_a, tenant_a, admin_a, "B")
        third = make_section(draft_a, tenant_a, admin_a, "C")
        services.reorder_section(section=third, tenant=tenant_a, actor=admin_a, sequence=0)

        order = list(
            DossierBlueprintSection.objects.filter(
                blueprint_version=draft_a, retired_at__isnull=True
            )
            .order_by("sequence", "id")
            .values_list("section_code", flat=True)
        )
        assert order == ["C", "A", "B"]

    def test_reorder_refused_on_an_active_version(self, active_a, tenant_a, admin_a):
        section = active_a.sections.first()
        with pytest.raises(services.BlueprintLocked):
            services.reorder_section(section=section, tenant=tenant_a, actor=admin_a, sequence=0)


# ---------------------------------------------------------------------------
# Activation validation
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestActivationValidation:
    def test_valid_structure_activates(self, populated_draft_a, tenant_a, admin_a):
        activated = services.activate_version(
            version=populated_draft_a, tenant=tenant_a, actor=admin_a
        )
        assert activated.status == BlueprintVersionStatus.ACTIVE
        assert activated.activated_by_id == admin_a.pk
        assert activated.activated_at is not None

    def test_a_version_whose_only_sections_are_retired_cannot_activate(
        self, draft_a, tenant_a, admin_a
    ):
        only = make_section(draft_a, tenant_a, admin_a, "A")
        services.retire_section(section=only, tenant=tenant_a, actor=admin_a)
        with pytest.raises(services.NotActivatable):
            services.activate_version(version=draft_a, tenant=tenant_a, actor=admin_a)

    def test_activation_does_not_claim_regulatory_completeness(
        self, populated_draft_a, tenant_a, admin_a
    ):
        """`validate_structure` is a coherence check. RegX has no idea what a
        given submission requires, and nothing here should read as saying so."""
        import inspect

        source = inspect.getdoc(services.validate_structure) or ""
        assert "structural" in source.lower()
        services.activate_version(version=populated_draft_a, tenant=tenant_a, actor=admin_a)

    def test_second_activation_refused(self, active_a, tenant_a, admin_a):
        with pytest.raises(services.BlueprintLocked):
            services.activate_version(version=active_a, tenant=tenant_a, actor=admin_a)


# ---------------------------------------------------------------------------
# API surface
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestApi:
    def test_list_returns_current_version_and_usage(self, client_doer_a, active_a, blueprint_a):
        r = client_doer_a.get(f"{BLUEPRINT_API}/")
        row = next(x for x in r.data["results"] if x["public_id"] == str(blueprint_a.public_id))
        assert row["current_version_number"] == 1
        assert row["current_version_status"] == "active"
        assert row["version_count"] == 1
        assert row["instantiation_count"] == 0

    def test_list_hides_archived_by_default(self, client_admin_a, blueprint_a, tenant_a, admin_a):
        services.archive_blueprint(blueprint=blueprint_a, tenant=tenant_a, actor=admin_a)
        default = client_admin_a.get(f"{BLUEPRINT_API}/")
        assert str(blueprint_a.public_id) not in {x["public_id"] for x in default.data["results"]}
        included = client_admin_a.get(f"{BLUEPRINT_API}/?include_archived=true")
        assert str(blueprint_a.public_id) in {x["public_id"] for x in included.data["results"]}

    def test_search_filters_by_name(self, client_admin_a, tenant_a, admin_a, blueprint_a):
        services.create_blueprint(tenant=tenant_a, actor=admin_a, name="Totally different")
        r = client_admin_a.get(f"{BLUEPRINT_API}/?search=Synthetic")
        names = {x["name"] for x in r.data["results"]}
        assert blueprint_a.name in names
        assert "Totally different" not in names

    def test_version_detail_returns_a_flat_section_list(self, client_doer_a, active_a):
        r = client_doer_a.get(f"{VERSION_API}/{active_a.public_id}/")
        assert r.status_code == 200
        assert r.data["section_count"] == 5
        assert r.data["is_editable"] is False
        codes = {s["section_code"] for s in r.data["sections"]}
        assert codes == {"A", "A.1", "A.2", "B", "B.1"}
        # Flat, with parent by public id -- the client assembles the tree.
        child = next(s for s in r.data["sections"] if s["section_code"] == "A.1")
        parent = next(s for s in r.data["sections"] if s["section_code"] == "A")
        assert child["parent_public_id"] == parent["public_id"]

    def test_draft_detail_is_editable(self, client_doer_a, populated_draft_a):
        r = client_doer_a.get(f"{VERSION_API}/{populated_draft_a.public_id}/")
        assert r.data["is_editable"] is True

    def test_no_internal_pks_are_exposed(self, client_doer_a, active_a):
        body = str(client_doer_a.get(f"{VERSION_API}/{active_a.public_id}/").data)
        assert "'id':" not in body
        assert "blueprint_version_id" not in body

    def test_section_create_via_api(self, client_doer_a, draft_a):
        r = client_doer_a.post(
            f"{VERSION_API}/{draft_a.public_id}/sections/",
            {"section_code": "A", "title": "Section A", "required": True},
            format="json",
        )
        assert r.status_code == 201
        assert r.data["section_code"] == "A"

    def test_section_create_on_active_version_is_409(self, client_admin_a, active_a):
        r = client_admin_a.post(
            f"{VERSION_API}/{active_a.public_id}/sections/",
            {"section_code": "C", "title": "Section C"},
            format="json",
        )
        assert r.status_code == 409

    def test_blank_code_refused(self, client_doer_a, draft_a):
        r = client_doer_a.post(
            f"{VERSION_API}/{draft_a.public_id}/sections/",
            {"section_code": "   ", "title": "Blank"},
            format="json",
        )
        assert r.status_code == 400

    def test_create_version_from_source_via_api(self, client_admin_a, blueprint_a, active_a):
        r = client_admin_a.post(
            f"{BLUEPRINT_API}/{blueprint_a.public_id}/versions/",
            {"source_version_public_id": str(active_a.public_id)},
            format="json",
        )
        assert r.status_code == 201
        assert r.data["version_number"] == 2
        assert r.data["status"] == "draft"
