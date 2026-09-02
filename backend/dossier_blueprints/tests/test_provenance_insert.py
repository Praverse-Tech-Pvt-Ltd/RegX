"""False provenance cannot be written, by ORM or by raw SQL.

MAJOR finding from independent review of PR #38.

`0002` froze `BlueprintInstantiation` and `BlueprintSectionOrigin` against
UPDATE and DELETE, and did not validate INSERT. That combination is worse than
either gap alone: a caller could write a provenance row asserting a dossier came
from a blueprint version in another tenant, or from a version belonging to a
different blueprint, or carrying a fabricated version number -- and the `0002`
triggers would then freeze that false record permanently. Immutability applied
to an unvalidated write does not protect the truth; it preserves the lie.

Provenance is the only surviving statement of where a dossier came from. A
dossier is deliberately a snapshot that never reads back to its blueprint, so a
false row cannot be detected afterwards by comparing the two. It has to be
refused at the moment it is written.

Every case here is proven twice where both are reachable: through the ORM, and
through a raw cursor that never runs a line of Python.

Synthetic data only.
"""

import pytest
from django.db import InternalError, ProgrammingError, connection, transaction

from dossier_blueprints import services
from dossier_blueprints.models import (
    BlueprintInstantiation,
    BlueprintSectionOrigin,
    DossierBlueprintSection,
    DossierBlueprintVersion,
)
from dossier_blueprints.tests.conftest import make_section
from submission_dossiers.models import DossierSection

INSTANTIATION_TABLE = BlueprintInstantiation._meta.db_table
ORIGIN_TABLE = BlueprintSectionOrigin._meta.db_table
DB_ERRORS = (InternalError, ProgrammingError)


def _sql(statement, params=()):
    """One statement in its own savepoint, so a refusal stays local and the
    assertions afterwards can still read."""
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute(statement, params)


def _instantiate(version, tenant, actor, case, **kw):
    return services.instantiate_version(
        version=version,
        tenant=tenant,
        actor=actor,
        case_public_id=case.public_id,
        title=kw.pop("title", "Instantiated dossier"),
        **kw,
    )


@pytest.fixture
def other_tenant_setup(db, tenant_b, admin_b, case_b):
    """A complete, valid instantiation in tenant B.

    Gives every cross-tenant test a real row to point at, rather than a
    fabricated id that would be refused by the existence check instead of the
    tenant check -- which would make the tenant rule dead code hidden behind it.
    """
    from dossier_blueprints import services as svc

    blueprint = svc.create_blueprint(tenant=tenant_b, actor=admin_b, name="Outline B")
    version = svc.create_version(blueprint=blueprint, tenant=tenant_b, actor=admin_b)
    make_section(version, tenant_b, admin_b, "X")
    svc.activate_version(version=version, tenant=tenant_b, actor=admin_b)
    record = svc.instantiate_version(
        version=version,
        tenant=tenant_b,
        actor=admin_b,
        case_public_id=case_b.public_id,
        title="Tenant B dossier",
    )
    return {
        "tenant": tenant_b,
        "actor": admin_b,
        "blueprint": blueprint,
        "version": version,
        "instantiation": record,
        "dossier": record.dossier,
        "dossier_section": DossierSection.objects.filter(dossier=record.dossier).first(),
        "blueprint_section": version.sections.first(),
    }


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestInsertGuardWiring:
    def test_insert_triggers_are_installed(self):
        expected = {
            INSTANTIATION_TABLE: ("guard_insert_blueprint_instantiation", "INSERT"),
            ORIGIN_TABLE: ("guard_insert_blueprint_section_origin", "INSERT"),
        }
        with connection.cursor() as cur:
            for table, wanted in expected.items():
                cur.execute(
                    "SELECT trigger_name, event_manipulation FROM information_schema.triggers "
                    "WHERE event_object_table = %s",
                    [table],
                )
                rows = set(cur.fetchall())
                assert wanted in rows, f"{table}: missing {wanted}; has {sorted(rows)}"

    def test_insert_guard_functions_exist(self):
        with connection.cursor() as cur:
            for fn in (
                "dossier_blueprints_guard_instantiation_insert",
                "dossier_blueprints_guard_origin_insert",
            ):
                cur.execute("SELECT COUNT(*) FROM pg_proc WHERE proname = %s", [fn])
                assert cur.fetchone()[0] == 1, fn

    def test_the_update_and_delete_freeze_still_stands(self):
        """`0003` must not have replaced `0002`'s triggers -- both events on both
        tables have to remain covered."""
        with connection.cursor() as cur:
            for table in (INSTANTIATION_TABLE, ORIGIN_TABLE):
                cur.execute(
                    "SELECT event_manipulation FROM information_schema.triggers "
                    "WHERE event_object_table = %s",
                    [table],
                )
                events = {row[0] for row in cur.fetchall()}
                assert {"INSERT", "UPDATE", "DELETE"} <= events, f"{table}: {events}"


# ---------------------------------------------------------------------------
# Positive controls -- the guard must not have broken the real path
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestValidProvenanceStillInserts:
    def test_service_instantiation_still_succeeds_end_to_end(
        self, active_a, tenant_a, admin_a, case_a
    ):
        record = _instantiate(active_a, tenant_a, admin_a, case_a)
        assert record.section_count == 5
        assert BlueprintInstantiation.objects.filter(pk=record.pk).exists()
        assert BlueprintSectionOrigin.objects.filter(instantiation=record).count() == 5
        assert DossierSection.objects.filter(dossier=record.dossier).count() == 5

    def test_a_coherent_instantiation_row_inserts_directly(
        self, active_a, tenant_a, admin_a, case_a
    ):
        """The positive control for the guard itself: a row that satisfies every
        rule is accepted, so a failure elsewhere means the rule fired, not that
        the table became unwritable."""
        from submission_dossiers import services as dossier_services

        dossier = dossier_services.create_dossier(
            case=case_a, tenant=tenant_a, actor=admin_a, title="Hand-built"
        )
        record = BlueprintInstantiation.objects.create(
            tenant=tenant_a,
            dossier=dossier,
            blueprint=active_a.blueprint,
            blueprint_version=active_a,
            version_number=active_a.version_number,
            blueprint_name=active_a.blueprint.name,
            section_count=0,
            instantiated_by=admin_a,
        )
        assert BlueprintInstantiation.objects.filter(pk=record.pk).exists()

    def test_a_coherent_origin_row_inserts_directly(self, active_a, tenant_a, admin_a, case_a):
        record = _instantiate(active_a, tenant_a, admin_a, case_a)
        # Retire one origin's counterpart is impossible; instead build a second
        # dossier section in the same dossier and map it to a section of the
        # same version. Both coherence rules are satisfied.
        extra = DossierSection.objects.create(
            tenant=tenant_a,
            dossier=record.dossier,
            created_by=admin_a,
            section_code="EXTRA",
            title="Extra",
            sequence=900,
        )
        origin = BlueprintSectionOrigin.objects.create(
            tenant=tenant_a,
            instantiation=record,
            dossier_section=extra,
            blueprint_section=active_a.sections.first(),
        )
        assert BlueprintSectionOrigin.objects.filter(pk=origin.pk).exists()


# ---------------------------------------------------------------------------
# BlueprintInstantiation -- ORM
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestInstantiationInsertGuardViaOrm:
    def _valid_kwargs(self, active_a, tenant_a, admin_a, dossier):
        return {
            "tenant": tenant_a,
            "dossier": dossier,
            "blueprint": active_a.blueprint,
            "blueprint_version": active_a,
            "version_number": active_a.version_number,
            "blueprint_name": active_a.blueprint.name,
            "section_count": 0,
            "instantiated_by": admin_a,
        }

    @pytest.fixture
    def dossier_a_shell(self, tenant_a, admin_a, case_a):
        from submission_dossiers import services as dossier_services

        return dossier_services.create_dossier(
            case=case_a, tenant=tenant_a, actor=admin_a, title="Shell"
        )

    def test_cross_tenant_dossier_is_blocked(self, active_a, tenant_a, admin_a, other_tenant_setup):
        kwargs = self._valid_kwargs(active_a, tenant_a, admin_a, other_tenant_setup["dossier"])
        with pytest.raises(DB_ERRORS) as exc:
            with transaction.atomic():
                BlueprintInstantiation.objects.create(**kwargs)
        assert "tenant does not match" in str(exc.value).lower()
        assert BlueprintInstantiation.objects.filter(tenant=tenant_a).count() == 0

    def test_cross_tenant_blueprint_is_blocked(
        self, active_a, tenant_a, admin_a, dossier_a_shell, other_tenant_setup
    ):
        kwargs = self._valid_kwargs(active_a, tenant_a, admin_a, dossier_a_shell)
        kwargs["blueprint"] = other_tenant_setup["blueprint"]
        with pytest.raises(DB_ERRORS) as exc:
            with transaction.atomic():
                BlueprintInstantiation.objects.create(**kwargs)
        # Either the tenant rule or the ownership rule may fire first; both are
        # correct refusals, and the row must not exist either way.
        assert (
            "tenant does not match" in str(exc.value).lower()
            or "does not own" in str(exc.value).lower()
        )
        assert BlueprintInstantiation.objects.filter(tenant=tenant_a).count() == 0

    def test_cross_tenant_version_is_blocked(
        self, active_a, tenant_a, admin_a, dossier_a_shell, other_tenant_setup
    ):
        kwargs = self._valid_kwargs(active_a, tenant_a, admin_a, dossier_a_shell)
        kwargs["blueprint_version"] = other_tenant_setup["version"]
        kwargs["version_number"] = other_tenant_setup["version"].version_number
        with pytest.raises(DB_ERRORS):
            with transaction.atomic():
                BlueprintInstantiation.objects.create(**kwargs)
        assert BlueprintInstantiation.objects.filter(tenant=tenant_a).count() == 0

    def test_version_from_a_different_blueprint_is_blocked(
        self, active_a, tenant_a, admin_a, dossier_a_shell
    ):
        """Same tenant, both rows real -- and still incoherent. A record naming
        Blueprint A while pointing at a version of Blueprint B says something
        untrue that nothing downstream would notice."""
        other_blueprint = services.create_blueprint(
            tenant=tenant_a, actor=admin_a, name="A different outline"
        )
        other_version = services.create_version(
            blueprint=other_blueprint, tenant=tenant_a, actor=admin_a
        )

        kwargs = self._valid_kwargs(active_a, tenant_a, admin_a, dossier_a_shell)
        kwargs["blueprint_version"] = other_version
        kwargs["version_number"] = other_version.version_number

        with pytest.raises(DB_ERRORS) as exc:
            with transaction.atomic():
                BlueprintInstantiation.objects.create(**kwargs)
        assert "does not own" in str(exc.value).lower()
        assert BlueprintInstantiation.objects.filter(tenant=tenant_a).count() == 0

    def test_fabricated_version_number_is_blocked(
        self, active_a, tenant_a, admin_a, dossier_a_shell
    ):
        """A truthful FK beside a fabricated snapshot. Every reader that trusts
        the snapshot -- which is the point of having one -- would be misled."""
        kwargs = self._valid_kwargs(active_a, tenant_a, admin_a, dossier_a_shell)
        kwargs["version_number"] = 99

        with pytest.raises(DB_ERRORS) as exc:
            with transaction.atomic():
                BlueprintInstantiation.objects.create(**kwargs)
        assert "version_number snapshot does not match" in str(exc.value).lower()
        assert BlueprintInstantiation.objects.filter(tenant=tenant_a).count() == 0


# ---------------------------------------------------------------------------
# BlueprintSectionOrigin -- ORM
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestSectionOriginInsertGuardViaOrm:
    def test_cross_tenant_instantiation_is_blocked(
        self, active_a, tenant_a, admin_a, case_a, other_tenant_setup
    ):
        record = _instantiate(active_a, tenant_a, admin_a, case_a)
        before = BlueprintSectionOrigin.objects.count()
        with pytest.raises(DB_ERRORS):
            with transaction.atomic():
                BlueprintSectionOrigin.objects.create(
                    tenant=tenant_a,
                    instantiation=other_tenant_setup["instantiation"],
                    dossier_section=DossierSection.objects.filter(dossier=record.dossier).first(),
                    blueprint_section=active_a.sections.first(),
                )
        assert BlueprintSectionOrigin.objects.count() == before

    def test_cross_tenant_dossier_section_is_blocked(
        self, active_a, tenant_a, admin_a, case_a, other_tenant_setup
    ):
        record = _instantiate(active_a, tenant_a, admin_a, case_a)
        before = BlueprintSectionOrigin.objects.count()
        with pytest.raises(DB_ERRORS):
            with transaction.atomic():
                BlueprintSectionOrigin.objects.create(
                    tenant=tenant_a,
                    instantiation=record,
                    dossier_section=other_tenant_setup["dossier_section"],
                    blueprint_section=active_a.sections.first(),
                )
        assert BlueprintSectionOrigin.objects.count() == before

    def test_cross_tenant_blueprint_section_is_blocked(
        self, active_a, tenant_a, admin_a, case_a, other_tenant_setup
    ):
        record = _instantiate(active_a, tenant_a, admin_a, case_a)
        before = BlueprintSectionOrigin.objects.count()
        with pytest.raises(DB_ERRORS):
            with transaction.atomic():
                BlueprintSectionOrigin.objects.create(
                    tenant=tenant_a,
                    instantiation=record,
                    dossier_section=DossierSection.objects.filter(dossier=record.dossier).first(),
                    blueprint_section=other_tenant_setup["blueprint_section"],
                )
        assert BlueprintSectionOrigin.objects.count() == before

    def test_the_tenant_rule_is_load_bearing_on_its_own(
        self, active_a, tenant_a, tenant_b, admin_a, case_a
    ):
        """Isolates the origin tenant check from the coherence checks beside it.

        Mutation-testing showed the cross-tenant cases above are *also* caught by
        the dossier and version coherence rules -- defence in depth, but it left
        the tenant rule barely tested on its own. Here every referenced row is a
        coherent tenant-A row, so both coherence rules pass, and only
        `NEW.tenant_id` is wrong. Nothing but the tenant rule can refuse it.
        """
        record = _instantiate(active_a, tenant_a, admin_a, case_a)
        before = BlueprintSectionOrigin.objects.count()

        extra = DossierSection.objects.create(
            tenant=tenant_a,
            dossier=record.dossier,
            created_by=admin_a,
            section_code="TENANT-PROBE",
            title="Probe",
            sequence=910,
        )
        with pytest.raises(DB_ERRORS) as exc:
            with transaction.atomic():
                BlueprintSectionOrigin.objects.create(
                    tenant=tenant_b,  # the only thing wrong
                    instantiation=record,
                    dossier_section=extra,
                    blueprint_section=active_a.sections.first(),
                )
        assert "tenant does not match" in str(exc.value).lower()
        assert BlueprintSectionOrigin.objects.count() == before

    def test_dossier_section_from_another_dossier_is_blocked(
        self, active_a, tenant_a, admin_a, case_a
    ):
        """Same tenant, both rows real. An origin row claims *this* dossier
        section came from *that* blueprint section; it is meaningless if the
        section is not in the instantiation's dossier."""
        first = _instantiate(active_a, tenant_a, admin_a, case_a, title="First")
        second = _instantiate(active_a, tenant_a, admin_a, case_a, title="Second")
        foreign_section = DossierSection.objects.filter(dossier=second.dossier).first()

        before = BlueprintSectionOrigin.objects.count()
        with pytest.raises(DB_ERRORS) as exc:
            with transaction.atomic():
                BlueprintSectionOrigin.objects.create(
                    tenant=tenant_a,
                    instantiation=first,
                    dossier_section=foreign_section,
                    blueprint_section=active_a.sections.first(),
                )
        assert "different dossier" in str(exc.value).lower()
        assert BlueprintSectionOrigin.objects.count() == before

    def test_blueprint_section_from_another_version_is_blocked(
        self, active_a, tenant_a, admin_a, case_a, blueprint_a
    ):
        record = _instantiate(active_a, tenant_a, admin_a, case_a)
        other_version = services.create_version(
            blueprint=blueprint_a, tenant=tenant_a, actor=admin_a
        )
        foreign_blueprint_section = make_section(other_version, tenant_a, admin_a, "OTHER")

        before = BlueprintSectionOrigin.objects.count()
        with pytest.raises(DB_ERRORS) as exc:
            with transaction.atomic():
                BlueprintSectionOrigin.objects.create(
                    tenant=tenant_a,
                    instantiation=record,
                    dossier_section=DossierSection.objects.filter(dossier=record.dossier).first(),
                    blueprint_section=foreign_blueprint_section,
                )
        assert "different version" in str(exc.value).lower()
        assert BlueprintSectionOrigin.objects.count() == before


# ---------------------------------------------------------------------------
# Raw SQL -- the path that never runs a line of Python
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestFalseProvenanceViaRawSql:
    INSTANTIATION_INSERT = (
        f"INSERT INTO {INSTANTIATION_TABLE} "
        f"(public_id, created_at, updated_at, tenant_id, dossier_id, blueprint_id, "
        f" blueprint_version_id, version_number, blueprint_name, section_count, "
        f" instantiated_by_id) "
        f"VALUES (gen_random_uuid(), NOW(), NOW(), %s, %s, %s, %s, %s, 'forged', 0, %s)"
    )
    ORIGIN_INSERT = (
        f"INSERT INTO {ORIGIN_TABLE} "
        f"(public_id, created_at, tenant_id, instantiation_id, dossier_section_id, "
        f" blueprint_section_id) "
        f"VALUES (gen_random_uuid(), NOW(), %s, %s, %s, %s)"
    )

    def test_instantiation_tenant_mismatch_is_rejected(
        self, active_a, tenant_a, admin_a, other_tenant_setup
    ):
        before = BlueprintInstantiation.objects.count()
        with pytest.raises(DB_ERRORS) as exc:
            _sql(
                self.INSTANTIATION_INSERT,
                [
                    tenant_a.pk,
                    other_tenant_setup["dossier"].pk,
                    active_a.blueprint_id,
                    active_a.pk,
                    active_a.version_number,
                    admin_a.pk,
                ],
            )
        assert "tenant does not match" in str(exc.value).lower()
        assert BlueprintInstantiation.objects.count() == before

    def test_instantiation_version_blueprint_mismatch_is_rejected(
        self, active_a, tenant_a, admin_a, case_a
    ):
        from submission_dossiers import services as dossier_services

        dossier = dossier_services.create_dossier(
            case=case_a, tenant=tenant_a, actor=admin_a, title="Shell"
        )
        other_blueprint = services.create_blueprint(
            tenant=tenant_a, actor=admin_a, name="Another outline"
        )
        other_version = services.create_version(
            blueprint=other_blueprint, tenant=tenant_a, actor=admin_a
        )

        before = BlueprintInstantiation.objects.count()
        with pytest.raises(DB_ERRORS) as exc:
            _sql(
                self.INSTANTIATION_INSERT,
                [
                    tenant_a.pk,
                    dossier.pk,
                    active_a.blueprint_id,
                    other_version.pk,
                    other_version.version_number,
                    admin_a.pk,
                ],
            )
        assert "does not own" in str(exc.value).lower()
        assert BlueprintInstantiation.objects.count() == before

    def test_instantiation_version_number_mismatch_is_rejected(
        self, active_a, tenant_a, admin_a, case_a
    ):
        from submission_dossiers import services as dossier_services

        dossier = dossier_services.create_dossier(
            case=case_a, tenant=tenant_a, actor=admin_a, title="Shell"
        )
        before = BlueprintInstantiation.objects.count()
        with pytest.raises(DB_ERRORS) as exc:
            _sql(
                self.INSTANTIATION_INSERT,
                [
                    tenant_a.pk,
                    dossier.pk,
                    active_a.blueprint_id,
                    active_a.pk,
                    99,
                    admin_a.pk,
                ],
            )
        assert "version_number snapshot does not match" in str(exc.value).lower()
        assert BlueprintInstantiation.objects.count() == before

    def test_instantiation_tenant_rule_is_load_bearing_on_its_own(
        self, active_a, tenant_a, tenant_b, admin_a, case_a
    ):
        """Every referenced row is a coherent tenant-A row and the ownership and
        snapshot rules both pass; only `NEW.tenant_id` is wrong."""
        from submission_dossiers import services as dossier_services

        dossier = dossier_services.create_dossier(
            case=case_a, tenant=tenant_a, actor=admin_a, title="Shell"
        )
        before = BlueprintInstantiation.objects.count()
        with pytest.raises(DB_ERRORS) as exc:
            _sql(
                self.INSTANTIATION_INSERT,
                [
                    tenant_b.pk,  # the only thing wrong
                    dossier.pk,
                    active_a.blueprint_id,
                    active_a.pk,
                    active_a.version_number,
                    admin_a.pk,
                ],
            )
        assert "tenant does not match" in str(exc.value).lower()
        assert BlueprintInstantiation.objects.count() == before

    def test_instantiation_referencing_a_missing_dossier_is_rejected(
        self, active_a, tenant_a, admin_a
    ):
        """Fails closed: a missing referenced row is refused, not skipped.

        The FK would also refuse this. The point is that the guard refuses it
        first and by name, so the guard is not silently relying on a constraint
        that a future schema change could relax.
        """
        before = BlueprintInstantiation.objects.count()
        with pytest.raises(DB_ERRORS):
            _sql(
                self.INSTANTIATION_INSERT,
                [
                    tenant_a.pk,
                    2_000_000_000,
                    active_a.blueprint_id,
                    active_a.pk,
                    active_a.version_number,
                    admin_a.pk,
                ],
            )
        assert BlueprintInstantiation.objects.count() == before

    def test_origin_tenant_mismatch_is_rejected(
        self, active_a, tenant_a, admin_a, case_a, other_tenant_setup
    ):
        record = _instantiate(active_a, tenant_a, admin_a, case_a)
        before = BlueprintSectionOrigin.objects.count()
        with pytest.raises(DB_ERRORS) as exc:
            _sql(
                self.ORIGIN_INSERT,
                [
                    tenant_a.pk,
                    record.pk,
                    other_tenant_setup["dossier_section"].pk,
                    active_a.sections.first().pk,
                ],
            )
        assert "tenant does not match" in str(exc.value).lower()
        assert BlueprintSectionOrigin.objects.count() == before

    def test_origin_wrong_dossier_is_rejected(self, active_a, tenant_a, admin_a, case_a):
        first = _instantiate(active_a, tenant_a, admin_a, case_a, title="First")
        second = _instantiate(active_a, tenant_a, admin_a, case_a, title="Second")
        foreign_section = DossierSection.objects.filter(dossier=second.dossier).first()

        before = BlueprintSectionOrigin.objects.count()
        with pytest.raises(DB_ERRORS) as exc:
            _sql(
                self.ORIGIN_INSERT,
                [tenant_a.pk, first.pk, foreign_section.pk, active_a.sections.first().pk],
            )
        assert "different dossier" in str(exc.value).lower()
        assert BlueprintSectionOrigin.objects.count() == before

    def test_origin_wrong_blueprint_version_is_rejected(
        self, active_a, tenant_a, admin_a, case_a, blueprint_a
    ):
        record = _instantiate(active_a, tenant_a, admin_a, case_a)
        other_version = services.create_version(
            blueprint=blueprint_a, tenant=tenant_a, actor=admin_a
        )
        foreign = make_section(other_version, tenant_a, admin_a, "OTHER")

        before = BlueprintSectionOrigin.objects.count()
        with pytest.raises(DB_ERRORS) as exc:
            _sql(
                self.ORIGIN_INSERT,
                [
                    tenant_a.pk,
                    record.pk,
                    DossierSection.objects.filter(dossier=record.dossier).first().pk,
                    foreign.pk,
                ],
            )
        assert "different version" in str(exc.value).lower()
        assert BlueprintSectionOrigin.objects.count() == before


# ---------------------------------------------------------------------------
# The existing freeze must not have regressed
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestExistingImmutabilityUnchanged:
    def test_instantiation_update_still_blocked(self, active_a, tenant_a, admin_a, case_a):
        record = _instantiate(active_a, tenant_a, admin_a, case_a)
        with pytest.raises(DB_ERRORS) as exc:
            _sql(
                f"UPDATE {INSTANTIATION_TABLE} SET version_number = 99 WHERE id = %s",
                [record.pk],
            )
        assert "permanent record" in str(exc.value).lower()
        record.refresh_from_db()
        assert record.version_number == 1

    def test_instantiation_delete_still_blocked(self, active_a, tenant_a, admin_a, case_a):
        record = _instantiate(active_a, tenant_a, admin_a, case_a)
        with pytest.raises(DB_ERRORS):
            _sql(f"DELETE FROM {INSTANTIATION_TABLE} WHERE id = %s", [record.pk])
        assert BlueprintInstantiation.objects.filter(pk=record.pk).exists()

    def test_origin_update_and_delete_still_blocked(self, active_a, tenant_a, admin_a, case_a):
        _instantiate(active_a, tenant_a, admin_a, case_a)
        origin = BlueprintSectionOrigin.objects.first()
        with pytest.raises(DB_ERRORS):
            _sql(f"UPDATE {ORIGIN_TABLE} SET tenant_id = tenant_id WHERE id = %s", [origin.pk])
        with pytest.raises(DB_ERRORS):
            _sql(f"DELETE FROM {ORIGIN_TABLE} WHERE id = %s", [origin.pk])
        assert BlueprintSectionOrigin.objects.filter(pk=origin.pk).exists()


# ---------------------------------------------------------------------------
# Rollback: a refused provenance insert leaves nothing behind
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestFailedProvenanceRollsBackEverything:
    def test_a_refused_provenance_insert_leaves_no_dossier_and_no_audit(
        self, active_a, tenant_a, admin_a, case_a, monkeypatch
    ):
        """The dossier and its sections are created before provenance is
        written, so a refusal there is the dangerous case: without one
        transaction it would leave a dossier that looks complete and has no
        record of where it came from.
        """
        from audit.models import AuditEvent
        from submission_dossiers.models import SubmissionDossier

        real_create = BlueprintInstantiation.objects.create

        def forging_create(*args, **kwargs):
            # Corrupt exactly the snapshot the new guard checks, so the refusal
            # comes from the database rather than from Python.
            kwargs["version_number"] = 99
            return real_create(*args, **kwargs)

        monkeypatch.setattr(BlueprintInstantiation.objects, "create", forging_create)

        audits_before = AuditEvent.objects.count()
        with pytest.raises(DB_ERRORS):
            _instantiate(active_a, tenant_a, admin_a, case_a)

        monkeypatch.setattr(BlueprintInstantiation.objects, "create", real_create)

        assert SubmissionDossier.objects.filter(tenant=tenant_a).count() == 0
        assert DossierSection.objects.filter(tenant=tenant_a).count() == 0
        assert BlueprintInstantiation.objects.count() == 0
        assert BlueprintSectionOrigin.objects.count() == 0
        assert AuditEvent.objects.count() == audits_before


# ---------------------------------------------------------------------------
# Migration symmetry and counts
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestMigrationSymmetry:
    """Docstring counts drift silently; SQL does not. Asserting the numbers
    against the generated SQL is what turns a documentation error into a build
    failure -- the `0002` docstring said "five functions and eight triggers"
    when the SQL had seven of each, and nothing caught it.
    """

    def _module(self, name):
        import importlib

        return importlib.import_module(f"dossier_blueprints.migrations.{name}")

    @pytest.mark.parametrize(
        "name,functions,triggers",
        [
            ("0002_blueprint_db_governance", 7, 7),
            ("0003_provenance_insert_governance", 2, 2),
        ],
    )
    def test_create_and_drop_are_symmetric(self, name, functions, triggers):
        m = self._module(name)
        assert m.CREATE_SQL.count("CREATE OR REPLACE FUNCTION") == functions
        assert m.CREATE_SQL.count("CREATE TRIGGER") == triggers
        assert m.DROP_SQL.count("DROP FUNCTION") == functions
        assert m.DROP_SQL.count("DROP TRIGGER") == triggers

    @pytest.mark.parametrize(
        "name,functions,triggers",
        [
            ("0002_blueprint_db_governance", 7, 7),
            ("0003_provenance_insert_governance", 2, 2),
        ],
    )
    def test_the_docstring_states_the_real_counts(self, name, functions, triggers):
        m = self._module(name)
        doc = m.__doc__ or ""
        assert f"{functions} plpgsql functions" in doc, doc[:400]
        assert f"{triggers}\n              triggers" in doc or f"{triggers} triggers" in doc

    def test_every_created_trigger_is_dropped_by_name(self):
        for name in ("0002_blueprint_db_governance", "0003_provenance_insert_governance"):
            m = self._module(name)
            created = {
                line.split()[2]
                for line in m.CREATE_SQL.splitlines()
                if line.startswith("CREATE TRIGGER")
            }
            dropped = {
                line.split()[4]
                for line in m.DROP_SQL.splitlines()
                if line.startswith("DROP TRIGGER")
            }
            assert created == dropped, f"{name}: {created ^ dropped}"

    def test_0003_expected_trigger_names(self):
        m = self._module("0003_provenance_insert_governance")
        created = {
            line.split()[2]
            for line in m.CREATE_SQL.splitlines()
            if line.startswith("CREATE TRIGGER")
        }
        assert created == {
            "guard_insert_blueprint_instantiation",
            "guard_insert_blueprint_section_origin",
        }

    def test_0003_forward_sql_is_create_only(self):
        """Class A means additive. Strip the plpgsql bodies first, or the
        SELECTs inside the guards read as data access at the top level."""
        import re

        m = self._module("0003_provenance_insert_governance")
        body_stripped = re.sub(r"\$fn\$.*?\$fn\$", " <body> ", m.CREATE_SQL, flags=re.S)
        statements = [s.strip().split("\n")[0] for s in body_stripped.split(";") if s.strip()]
        verbs = {s.split()[0].upper() for s in statements}
        assert verbs == {"CREATE"}, statements
        assert not any(s.upper().startswith(("ALTER TABLE", "DROP TABLE")) for s in statements)

    def test_0003_does_not_touch_the_0002_functions(self):
        """`0002`'s behaviour must be unchanged: `0003` may not redefine one of
        its functions under the same name."""
        older = self._module("0002_blueprint_db_governance")
        newer = self._module("0003_provenance_insert_governance")

        def created_functions(sql):
            return {
                line.split("FUNCTION ")[1].split("(")[0]
                for line in sql.splitlines()
                if line.startswith("CREATE OR REPLACE FUNCTION")
            }

        assert created_functions(older.CREATE_SQL).isdisjoint(created_functions(newer.CREATE_SQL))


# ---------------------------------------------------------------------------
# Coverage: every column the guards compare still exists
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestGuardColumnCoverage:
    def test_provenance_columns_are_accounted_for(self):
        """The guards name columns. If one is renamed the guard would silently
        stop comparing it, so the enumeration is asserted here."""
        instantiation = {
            "id",
            "public_id",
            "created_at",
            "updated_at",
            "tenant_id",
            "dossier_id",
            "blueprint_id",
            "blueprint_version_id",
            "version_number",
            "blueprint_name",
            "section_count",
            "instantiated_by_id",
        }
        origin = {
            "id",
            "public_id",
            "created_at",
            "tenant_id",
            "instantiation_id",
            "dossier_section_id",
            "blueprint_section_id",
        }
        with connection.cursor() as cur:
            for table, expected in (
                (INSTANTIATION_TABLE, instantiation),
                (ORIGIN_TABLE, origin),
            ):
                cur.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
                    [table],
                )
                actual = {row[0] for row in cur.fetchall()}
                assert actual == expected, (
                    f"{table}: dossier_blueprints/0003 names columns explicitly -- update the "
                    f"guard and this test together. Unaccounted: {actual - expected}; "
                    f"stale: {expected - actual}"
                )

    def test_the_guards_reference_only_real_tables(self):
        m = __import__(
            "dossier_blueprints.migrations.0003_provenance_insert_governance",
            fromlist=["x"],
        )
        tables = {
            m.INSTANTIATION_TABLE,
            m.ORIGIN_TABLE,
            m.BLUEPRINT_TABLE,
            m.VERSION_TABLE,
            m.BLUEPRINT_SECTION_TABLE,
            m.DOSSIER_TABLE,
            m.DOSSIER_SECTION_TABLE,
        }
        with connection.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
            )
            existing = {row[0] for row in cur.fetchall()}
        assert tables <= existing, f"missing: {tables - existing}"

    def test_model_table_names_match_the_migration_constants(self):
        m = __import__(
            "dossier_blueprints.migrations.0003_provenance_insert_governance",
            fromlist=["x"],
        )
        assert m.INSTANTIATION_TABLE == BlueprintInstantiation._meta.db_table
        assert m.ORIGIN_TABLE == BlueprintSectionOrigin._meta.db_table
        assert m.VERSION_TABLE == DossierBlueprintVersion._meta.db_table
        assert m.BLUEPRINT_SECTION_TABLE == DossierBlueprintSection._meta.db_table
        assert m.DOSSIER_SECTION_TABLE == DossierSection._meta.db_table
