"""Fixtures for upgrade tests.

Synthetic data only. Section codes are generic -- A, A.1, B -- and encode no
CTD, CEP, DMF or ANDA structure: none ships in this milestone and none is
implied by a test.

The core fixture is `upgraded_setup`: a dossier instantiated from blueprint v1,
with v2 published carrying a known set of differences. Almost every test needs
exactly that.
"""

import pytest
from rest_framework.test import APIClient

DOSSIER_API = "/api/regx/v1/submission-dossiers"
PLAN_API = "/api/regx/v1/dossier-upgrade-plans"


def _make_tenant(name, slug):
    from tenancy.models import Tenant

    return Tenant.objects.create(name=name, slug=slug)


def _make_user(email, full_name):
    from identity.models import User

    return User.objects.create_user(email=email, password="TestPass1234!", full_name=full_name)


def _membership_with_role(tenant, user, role_name):
    from authorization.models import MembershipRole, Role
    from tenancy.models import TenantMembership

    membership = TenantMembership.objects.create(tenant=tenant, user=user, is_active=True)
    role, _ = Role.objects.get_or_create(name=role_name, defaults={"description": role_name})
    MembershipRole.objects.create(membership=membership, role=role)
    return membership


def _client(user, tenant):
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_TENANT_SLUG=tenant.slug)
    return client


@pytest.fixture
def tenant_a(db):
    return _make_tenant("Upgrade Tenant A", "up-tenant-a")


@pytest.fixture
def tenant_b(db):
    return _make_tenant("Upgrade Tenant B", "up-tenant-b")


def _role_user(tenant, role, email, name):
    user = _make_user(email, name)
    _membership_with_role(tenant, user, role)
    return user


@pytest.fixture
def admin_a(db, tenant_a):
    from authorization.models import Role

    return _role_user(tenant_a, Role.BuiltIn.TENANT_ADMIN, "up-admin-a@example.test", "Admin A")


@pytest.fixture
def doer_a(db, tenant_a):
    from authorization.models import Role

    return _role_user(tenant_a, Role.BuiltIn.DOER, "up-doer-a@example.test", "Doer A")


@pytest.fixture
def reviewer_a(db, tenant_a):
    from authorization.models import Role

    return _role_user(tenant_a, Role.BuiltIn.REVIEWER, "up-reviewer-a@example.test", "Reviewer A")


@pytest.fixture
def vp_a(db, tenant_a):
    from authorization.models import Role

    return _role_user(tenant_a, Role.BuiltIn.VP, "up-vp-a@example.test", "VP A")


@pytest.fixture
def support_a(db, tenant_a):
    """Holds `dossier_upgrades.view` and no `submission_dossiers.manage_sections`,
    so it is the natural probe for the multi-gate apply rule."""
    from authorization.models import Role

    return _role_user(
        tenant_a, Role.BuiltIn.PLATFORM_SUPPORT, "up-support-a@example.test", "Support A"
    )


@pytest.fixture
def admin_b(db, tenant_b):
    from authorization.models import Role

    return _role_user(tenant_b, Role.BuiltIn.TENANT_ADMIN, "up-admin-b@example.test", "Admin B")


@pytest.fixture
def client_admin_a(admin_a, tenant_a):
    return _client(admin_a, tenant_a)


@pytest.fixture
def client_doer_a(doer_a, tenant_a):
    return _client(doer_a, tenant_a)


@pytest.fixture
def client_reviewer_a(reviewer_a, tenant_a):
    return _client(reviewer_a, tenant_a)


@pytest.fixture
def client_support_a(support_a, tenant_a):
    return _client(support_a, tenant_a)


@pytest.fixture
def client_admin_b(admin_b, tenant_b):
    return _client(admin_b, tenant_b)


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------
def make_case(tenant, actor, title="Synthetic case"):
    from regulatory_cases import services as case_services

    return case_services.create_case(
        tenant=tenant, actor=actor, title=title, description="Synthetic"
    )


def make_blueprint_section(version, tenant, actor, code, *, parent=None, **kw):
    from dossier_blueprints import services as bp

    return bp.create_section(
        version=version,
        tenant=tenant,
        actor=actor,
        parent=parent,
        section_code=code,
        title=kw.pop("title", f"Section {code}"),
        **kw,
    )


def publish(blueprint, tenant, actor, sections, *, source=None):
    """Create a version, populate it, and activate it.

    `sections` is a list of `(code, parent_code, kwargs)`; the parent is looked
    up among sections created earlier in the same call, so a caller writes the
    outline in reading order.
    """
    from dossier_blueprints import services as bp

    version = bp.create_version(
        blueprint=blueprint, tenant=tenant, actor=actor, source_version=source
    )
    if source is None:
        created = {}
        for code, parent_code, kwargs in sections:
            created[code] = make_blueprint_section(
                version, tenant, actor, code, parent=created.get(parent_code), **kwargs
            )
    return bp.activate_version(version=version, tenant=tenant, actor=actor)


@pytest.fixture
def blueprint_a(db, tenant_a, admin_a):
    from dossier_blueprints import services as bp

    return bp.create_blueprint(tenant=tenant_a, actor=admin_a, name="Synthetic outline A")


#: v1: A, A.1, A.2, B.  Deliberately meaningless codes.
V1_SHAPE = [
    ("A", None, {}),
    ("A.1", "A", {}),
    ("A.2", "A", {"required": False}),
    ("B", None, {}),
]


@pytest.fixture
def v1(db, blueprint_a, tenant_a, admin_a):
    return publish(blueprint_a, tenant_a, admin_a, V1_SHAPE)


@pytest.fixture
def case_a(db, tenant_a, admin_a):
    return make_case(tenant_a, admin_a)


@pytest.fixture
def dossier_a(db, v1, tenant_a, admin_a, case_a):
    """A dossier instantiated from v1. Four sections, all at M9 defaults."""
    from dossier_blueprints import services as bp

    record = bp.instantiate_version(
        version=v1,
        tenant=tenant_a,
        actor=admin_a,
        case_public_id=case_a.public_id,
        title="Dossier from v1",
    )
    return record.dossier


def draft_from(version, tenant, actor):
    """A DRAFT clone of `version`, ready to be edited then activated."""
    from dossier_blueprints import services as bp

    return bp.create_version(
        blueprint=version.blueprint, tenant=tenant, actor=actor, source_version=version
    )


def activate(version, tenant, actor):
    from dossier_blueprints import services as bp

    return bp.activate_version(version=version, tenant=tenant, actor=actor)


@pytest.fixture
def v2(db, v1, tenant_a, admin_a):
    """v2, differing from v1 in one of each interesting way:

    * ``A``    title changed
    * ``A.2``  becomes required
    * ``B``    retired  -> proposes a dossier retirement
    * ``C``    new root -> proposes an addition
    * ``C.1``  new child of the new root
    """
    from dossier_blueprints import services as bp

    draft = draft_from(v1, tenant_a, admin_a)
    by_code = {s.section_code: s for s in draft.sections.all()}

    bp.update_section(
        section=by_code["A"], tenant=tenant_a, actor=admin_a, title="Section A, revised"
    )
    bp.update_section(section=by_code["A.2"], tenant=tenant_a, actor=admin_a, required=True)
    bp.retire_section(section=by_code["B"], tenant=tenant_a, actor=admin_a)
    c = make_blueprint_section(draft, tenant_a, admin_a, "C")
    make_blueprint_section(draft, tenant_a, admin_a, "C.1", parent=c)

    return activate(draft, tenant_a, admin_a)


def dossier_sections(dossier):
    from submission_dossiers.models import DossierSection

    return {
        s.section_code: s
        for s in DossierSection.objects.filter(dossier=dossier, retired_at__isnull=True)
    }


def generate(dossier, tenant, actor, target, notes=""):
    from dossier_upgrades import services

    return services.generate_plan(
        dossier=dossier,
        tenant=tenant,
        actor=actor,
        target_version_public_id=target.public_id,
        notes=notes,
    )


def accept_all(plan, tenant, actor):
    """Accept every actionable, unblocked item and mark the plan ready."""
    from dossier_upgrades import services
    from dossier_upgrades.models import ACTIONABLE_CHANGE_TYPES, ItemStatus

    for item in plan.items.all():
        if item.change_type in ACTIONABLE_CHANGE_TYPES and item.status == ItemStatus.PROPOSED:
            services.set_item_status(item=item, tenant=tenant, actor=actor, accept=True)
    return services.mark_ready(plan=plan, tenant=tenant, actor=actor)
