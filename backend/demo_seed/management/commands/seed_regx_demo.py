"""Seed a demonstrable REGX environment.

The IIG checklist engine is the most heavily tested part of this codebase and
it cannot be exercised from a fresh install, because `create_execution` has two
hard gates (see `iig_checklist/services.py`):

* the checklist version must be ``active`` -- a freshly created one is ``draft``
* the formulation version must be ``approved``

Neither state can be reached by clicking around a new environment, so a clean
setup shows an IIG UI that is navigable and unusable. This command closes that
gap with clearly labelled demo content.

WHAT THIS DOES NOT DO
---------------------
It does not touch the six platform checklist definitions that ship with the
database. Those are regulatory content; activating them here would silently
promote unreviewed material into an executable state. This command creates its
own definition, prefixed `DEMO-`, and activates only that.

It does not fabricate FDA or IIG source data. The demo formulation is obviously
synthetic and is labelled as such.

HOW THE CHECKLIST VERSION IS ACTIVATED
--------------------------------------
Through the real lifecycle, not by writing `status`. `draft -> under_review ->
approved -> active` is enforced by `validate_version_transition`, and the
transitions live in the API views rather than in a service function, so this
command drives those views in-process with `APIRequestFactory`. That keeps
every governance rule in play: permission classes, the effective-date
requirement, calculation-binding validation, and the audit events each
transition emits.

Two of those rules shape the seed and are worth knowing before editing it:

* `ChecklistVersionApproveView.self_approval_forbidden` is True, so the user
  who submits cannot be the user who approves. The Doer submits; the VP
  approves.
* `PERM_APPROVE` and `PERM_ACTIVATE` are held by the VP role only -- not by
  Tenant Admin, which holds view permissions alone.

Formulations are different. That app has no transition service, no approval
endpoint, and `FormulationVersionSerializer` sets `read_only_fields = fields`,
so there is no sanctioned path to move a formulation version to `approved`.
Creating it in that state directly is what the app's own tests do. This is
recorded as a known asymmetry rather than worked around.

USAGE
-----
    python manage.py seed_regx_demo
    python manage.py seed_regx_demo --password-env DEMO_PASSWORD
    python manage.py seed_regx_demo --tenant-slug demo --dry-run

Idempotent: run it as often as you like. Every object is looked up before it is
created, and a second run reports zeros.

WHY THIS LIVES IN `iig_checklist`
---------------------------------
It seeds tenants and accounts too, so `common` looked like the natural home.
It is not: the `common-has-no-domain-imports` import-linter contract forbids
`common` from importing any domain app, and this command needs iig_checklist,
formulations, tenancy, identity and authorization. `iig_checklist` already
depends on all of those, and nothing may import it back, so it is the correct
layer for a command that composes them.
"""

from __future__ import annotations

import os
import secrets
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

#: Everything this command creates carries one of these markers, so seeded
#: content can be told apart from real content at a glance and in a query.
DEMO_PREFIX = "DEMO-"
DEMO_EMAIL_DOMAIN = "demo.regx.invalid"

#: No default password is shipped. When none is supplied the command mints a
#: random one and prints it, so the repository never carries a credential and
#: a demo environment never comes up with a guessable one. Pass --password or
#: --password-env when a stable password across runs is wanted.
_GENERATED_PASSWORD_BYTES = 12

ROLES = ("doer", "reviewer", "vp", "tenant_admin")


def _build_minimal_pdf(text: str) -> bytes:
    """A one-page PDF that a strict reader accepts: every object, a
    cross-reference table with exact byte offsets, a trailer and `startxref`.

    The previous 193-byte placeholder had no cross-reference table, so pypdf
    refused it ("startxref not found") and the demo document always showed
    processing "failed". Built here rather than committed as a binary fixture,
    so the repository carries no opaque file and it is obvious what the demo
    document contains: one line of text saying it is synthetic. `text` must be
    plain ASCII with no parentheses or backslashes (PDF string syntax).
    """
    content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]"
        b" /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref_at = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref_at,
    )
    return bytes(out)


#: The demo document: a valid one-page PDF whose only content says it is
#: synthetic (see `_build_minimal_pdf`).
DEMO_PDF_TEXT = "DEMO - synthetic document for the REGX demo tenant. No real content."
_MINIMAL_PDF = _build_minimal_pdf(DEMO_PDF_TEXT)


class Command(BaseCommand):
    help = "Seed a clearly-labelled demo tenant, roles, checklist and formulation."

    def add_arguments(self, parser):
        parser.add_argument(
            "--tenant-slug",
            default="demo",
            help="Slug of the demo tenant to create or reuse (default: demo).",
        )
        parser.add_argument(
            "--password",
            default=None,
            help="Password for the demo accounts. Prefer --password-env.",
        )
        parser.add_argument(
            "--password-env",
            default=None,
            help="Name of an environment variable holding the demo password.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be created, then roll back.",
        )

    # -- helpers ---------------------------------------------------------

    def _resolve_password(self, options) -> str:
        if options["password"] and options["password_env"]:
            raise CommandError("Use --password or --password-env, not both.")
        if options["password_env"]:
            value = os.environ.get(options["password_env"])
            if not value:
                raise CommandError(
                    f"Environment variable {options['password_env']} is unset or empty."
                )
            return value
        if options["password"]:
            return options["password"]
        self.generated_password = secrets.token_urlsafe(_GENERATED_PASSWORD_BYTES)
        return self.generated_password

    def _note(self, created: bool, label: str) -> None:
        if created:
            self.created[label] = self.created.get(label, 0) + 1
            self.stdout.write(f"  created  {label}")
        else:
            self.stdout.write(f"  reused   {label}")

    # -- main ------------------------------------------------------------

    def handle(self, *args, **options):
        self.created: dict[str, int] = {}
        password = self._resolve_password(options)
        slug = options["tenant_slug"]
        dry_run = options["dry_run"]

        try:
            with transaction.atomic():
                summary = self._seed(slug, password)
                if dry_run:
                    self.stdout.write(self.style.WARNING("\n--dry-run: rolling back."))
                    raise _Rollback()
        except _Rollback:
            self.stdout.write(self.style.WARNING("Nothing was written."))
            return

        self.stdout.write("")
        if self.created:
            for label, count in sorted(self.created.items()):
                self.stdout.write(self.style.SUCCESS(f"  + {label} ({count})"))
        else:
            self.stdout.write(self.style.SUCCESS("  Already seeded; nothing to create."))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Demo environment ready."))
        self.stdout.write(f"  tenant slug        {slug}")
        self.stdout.write(f"  sign in as         doer@{DEMO_EMAIL_DOMAIN}")
        self.stdout.write(f"  other accounts     reviewer / vp / tenant_admin @{DEMO_EMAIL_DOMAIN}")
        if getattr(self, "generated_password", None):
            self.stdout.write(self.style.WARNING(f"  generated password {self.generated_password}"))
            self.stdout.write("  (random per run; pass --password or --password-env to pin it)")
        self.stdout.write(f"  checklist version  {summary['version_status']}")
        self.stdout.write(f"  formulation        {summary['formulation_status']}")
        if summary["execution_public_id"]:
            self.stdout.write(f"  sample execution   {summary['execution_public_id']}")
        self.stdout.write(f"  regulatory case    {summary['case_number']}")
        self.stdout.write(f"  workflow           {summary['workflow_state']}")
        self.stdout.write(f"  blueprint version  {summary['blueprint_version_status']}")
        self.stdout.write(f"  dossier            {summary['dossier_public_id'] or 'not created'}")
        self.stdout.write(
            f"  package            {summary['package_status'] or 'not created'} (internal)"
        )
        self.stdout.write(f"  connector          {summary['connector_status'] or 'not created'}")

        scan = summary["document_scan_status"]
        self.stdout.write(f"  document scan      {scan or 'not created'}")
        if scan == "clean":
            # Said out loud because CLEAN from the stub looks identical to
            # CLEAN from a real scanner, and this is demo data.
            self.stdout.write(
                self.style.WARNING(
                    "  NOTE: a CLEAN result under StubScanner means nothing was "
                    "inspected. See docs/MALWARE_SCANNING.md."
                )
            )

    def _seed(self, slug: str, password: str) -> dict:
        from authorization.models import MembershipRole, Role
        from identity.models import User
        from tenancy.context import set_current_tenant
        from tenancy.models import Tenant, TenantMembership

        self.stdout.write(self.style.MIGRATE_HEADING("Tenant and accounts"))
        tenant, made = Tenant.objects.get_or_create(
            slug=slug, defaults={"name": f"{DEMO_PREFIX}Tenant ({slug})"}
        )
        self._note(made, f"tenant {slug}")
        set_current_tenant(tenant)

        users: dict[str, object] = {}
        for role_name in ROLES:
            email = f"{role_name}@{DEMO_EMAIL_DOMAIN}"
            user, made = User.objects.get_or_create(
                email=email,
                defaults={"full_name": f"{DEMO_PREFIX}{role_name.replace('_', ' ').title()}"},
            )
            # Reset every run so a forgotten demo password is recoverable by
            # re-running the command rather than by editing the database.
            user.set_password(password)
            user.is_active = True
            user.save()
            self._note(made, f"user {email}")

            membership, made = TenantMembership.objects.get_or_create(
                user=user, tenant=tenant, defaults={"is_active": True}
            )
            if not membership.is_active:
                membership.is_active = True
                membership.save(update_fields=["is_active"])
            self._note(made, f"membership {role_name}")

            try:
                # Platform-wide built-in only (authorization/seed.py); never a
                # tenant's own role that happens to share the name.
                role = Role.objects.get(name=role_name, tenant__isnull=True, is_system=True)
            except Role.DoesNotExist as exc:
                raise CommandError(
                    f"Built-in role {role_name!r} is missing. Run migrations first."
                ) from exc
            _, made = MembershipRole.objects.get_or_create(membership=membership, role=role)
            self._note(made, f"role binding {role_name}")
            users[role_name] = user

        checklist = self._seed_checklist(tenant, users)
        formulation = self._seed_formulation(tenant, users["doer"])
        execution_public_id = self._seed_execution(
            tenant, users["doer"], checklist["version"], formulation["version"]
        )

        # The governed chain. The order is a real dependency chain, not a
        # preference: a dossier needs an ACTIVE blueprint version and a case,
        # and a package entry needs a document version that already exists.
        case = self._seed_case(tenant, users["doer"])
        workflow_state = self._seed_workflow(tenant, users)
        document = self._seed_document(tenant, users["doer"])
        blueprint = self._seed_blueprint(tenant, users)
        dossier = self._seed_dossier(tenant, users["doer"], blueprint["version"], case)
        package = self._seed_package(tenant, users["doer"], case, document)
        connector = self._seed_connector(tenant, users["doer"])

        return {
            "version_status": checklist["version"].status,
            "formulation_status": formulation["version"].status,
            "execution_public_id": execution_public_id,
            "case_number": case.case_number,
            "workflow_state": workflow_state,
            "document_scan_status": document["scan_status"] if document else None,
            "blueprint_version_status": blueprint["version"].status,
            "dossier_public_id": str(dossier.public_id) if dossier else None,
            "package_status": package.status if package else None,
            "connector_status": connector.status if connector else None,
        }

    # -- regulatory case -------------------------------------------------

    def _seed_case(self, tenant, actor):
        from regulatory_cases.models import RegulatoryCase
        from regulatory_cases.services import create_case

        self.stdout.write(self.style.MIGRATE_HEADING("Regulatory case"))
        title = f"{DEMO_PREFIX}Demonstration Tablet 100 mg (synthetic)"
        existing = RegulatoryCase.objects.filter(tenant=tenant, title=title).first()
        if existing is not None:
            self._note(False, f"regulatory case {existing.case_number}")
            return existing

        # create_case claims the next tenant-local case number under lock and
        # emits regulatory_case.created. Creating the row directly would skip
        # both.
        case = create_case(
            tenant=tenant,
            actor=actor,
            title=title,
            product_name=f"{DEMO_PREFIX}Demonstration Tablet",
            product_code=f"{DEMO_PREFIX}TAB-100",
            market="DEMO market -- not a real jurisdiction",
            submission_type="DEMO submission type",
            description=(
                "Synthetic case created by seed_regx_demo. Not a real "
                "submission and not derived from any regulatory source."
            ),
        )
        self._note(True, f"regulatory case {case.case_number}")
        return case

    # -- workflow --------------------------------------------------------

    def _seed_workflow(self, tenant, users) -> str:
        """One workflow item, moved once through a real transition.

        Submitted rather than left in DRAFT so the handoff demo has something
        a Reviewer can act on, and so the seed exercises the transition path
        rather than only the create path.
        """
        from workflows.models import WorkflowItem
        from workflows.services import create_item, perform_transition

        self.stdout.write(self.style.MIGRATE_HEADING("Workflow"))
        title = f"{DEMO_PREFIX}Review excipient rationale"
        item = WorkflowItem.objects.filter(tenant=tenant, title=title).first()
        if item is not None:
            self._note(False, f"workflow item ({item.state})")
            return item.state

        item = create_item(
            tenant=tenant,
            actor=users["doer"],
            title=title,
            description="Synthetic workflow item created by seed_regx_demo.",
        )
        self._note(True, "workflow item")

        # Through the sanctioned transition service: it validates the move,
        # writes WorkflowTransition history and emits workflow.submitted.
        perform_transition(item=item, action="submit", actor=users["doer"], tenant=tenant)
        item.refresh_from_db()
        self._note(True, f"workflow submit -> {item.state}")
        return item.state

    # -- document --------------------------------------------------------

    def _seed_document(self, tenant, actor):
        """One governed document through the real ingest path.

        `scan_status` is never written here. `ingest_new_document` validates
        the bytes, stores them, versions them and queues the real scan task,
        so the resulting status is whatever the configured scanner returns.

        THAT MATTERS FOR THE DEMO: the local compose stack runs StubScanner
        (DOCUMENT_SCANNER_ALLOW_STUB=true), which reports CLEAN without
        inspecting anything. A CLEAN result here is not evidence of malware
        inspection, which is why this document is labelled synthetic and why
        the package below is deliberately left in DRAFT rather than frozen on
        the strength of it.
        """
        import io as _io

        from documents.ingest import ingest_new_document
        from documents.models import Document, DocumentType

        self.stdout.write(self.style.MIGRATE_HEADING("Governed document"))
        title = f"{DEMO_PREFIX}Synthetic excipient rationale (demo only)"
        existing = Document.objects.filter(tenant=tenant, title=title).first()
        if existing is not None:
            version = existing.versions.order_by("version_number").last()
            self._note(False, f"document ({version.scan_status})")
            return {
                "document": existing,
                "version": version,
                "scan_status": version.scan_status,
            }

        try:
            document, version = ingest_new_document(
                tenant=tenant,
                actor=actor,
                file_obj=_io.BytesIO(_MINIMAL_PDF),
                filename="demo-excipient-rationale.pdf",
                declared_mime="application/pdf",
                title=title,
                document_type=DocumentType.PDF,
            )
        except Exception as exc:  # validation, storage or scanner wiring
            self.stdout.write(
                self.style.WARNING(f"  skipped  document ({type(exc).__name__}: {exc})")
            )
            return None

        version.refresh_from_db()
        self._note(True, f"document + version 1 (scan: {version.scan_status})")
        return {
            "document": document,
            "version": version,
            "scan_status": version.scan_status,
        }

    # -- dossier blueprint -----------------------------------------------

    def _seed_blueprint(self, tenant, users) -> dict:
        from dossier_blueprints.models import DossierBlueprint
        from dossier_blueprints.services import (
            activate_version,
            create_blueprint,
            create_section,
            create_version,
        )

        self.stdout.write(self.style.MIGRATE_HEADING("Dossier blueprint"))
        name = f"{DEMO_PREFIX}Generic submission outline"
        blueprint = DossierBlueprint.objects.filter(tenant=tenant, name=name).first()
        if blueprint is None:
            blueprint = create_blueprint(
                tenant=tenant,
                actor=users["doer"],
                name=name,
                description=(
                    "Synthetic blueprint created by seed_regx_demo. Not a CTD "
                    "outline and not derived from any regulatory source."
                ),
            )
            self._note(True, "blueprint")
        else:
            self._note(False, "blueprint")

        version = blueprint.versions.order_by("version_number").last()
        if version is None:
            version = create_version(
                blueprint=blueprint,
                tenant=tenant,
                actor=users["doer"],
                notes="Demo v1",
            )
            for sequence, (code, section_title) in enumerate(
                [
                    ("S1", "Product overview"),
                    ("S2", "Formulation and composition"),
                    ("S3", "Supporting evidence"),
                ],
                start=1,
            ):
                create_section(
                    version=version,
                    tenant=tenant,
                    actor=users["doer"],
                    section_code=code,
                    title=section_title,
                    sequence=sequence,
                )
            self._note(True, "blueprint version 1 + 3 sections")
        else:
            self._note(False, f"blueprint version {version.version_number}")

        version.refresh_from_db()
        if version.status != "active":
            # Through the sanctioned service: it enforces the draft->active
            # gate and emits dossier_blueprint.version_activated.
            activate_version(version=version, tenant=tenant, actor=users["vp"])
            version.refresh_from_db()
            self._note(True, f"blueprint version activate -> {version.status}")
        else:
            self._note(False, "blueprint version already active")

        return {"blueprint": blueprint, "version": version}

    # -- dossier ---------------------------------------------------------

    def _seed_dossier(self, tenant, actor, blueprint_version, case):
        """Instantiated from the ACTIVE blueprint version, keeping provenance.

        Readiness is derived by the dossier domain from its sections; nothing
        here sets or forces it.
        """
        from dossier_blueprints.services import instantiate_version
        from submission_dossiers.models import SubmissionDossier

        self.stdout.write(self.style.MIGRATE_HEADING("Dossier"))
        title = f"{DEMO_PREFIX}Demonstration dossier"
        existing = SubmissionDossier.objects.filter(regulatory_case=case, title=title).first()
        if existing is not None:
            self._note(False, "dossier")
            return existing

        try:
            dossier = instantiate_version(
                version=blueprint_version,
                tenant=tenant,
                actor=actor,
                case_public_id=str(case.public_id),
                title=title,
            )
        except Exception as exc:
            self.stdout.write(
                self.style.WARNING(f"  skipped  dossier ({type(exc).__name__}: {exc})")
            )
            return None

        self._note(True, "dossier instantiated from blueprint version")
        return dossier

    # -- submission package ----------------------------------------------

    def _seed_package(self, tenant, actor, case, document):
        """An INTERNAL package, left in DRAFT on purpose.

        Internal means internal: a ZIP of exact document versions for transfer
        between systems. It is not an eCTD sequence, an agency filing or a
        gateway submission, and nothing in this seed makes it one.

        Left DRAFT rather than frozen because its only evidence is the
        synthetic document above, which on a local stack was "scanned" by
        StubScanner. Freezing would present an inspected, immutable artifact
        built on a scan that never happened.
        """
        from submission_packages.models import SubmissionPackage
        from submission_packages.services import add_entry, create_package

        self.stdout.write(self.style.MIGRATE_HEADING("Submission package (internal)"))
        name = f"{DEMO_PREFIX}Internal transfer package"
        existing = SubmissionPackage.objects.filter(regulatory_case=case, name=name).first()
        if existing is not None:
            self._note(False, f"package ({existing.status})")
            return existing

        try:
            package = create_package(
                case_public_id=str(case.public_id),
                tenant=tenant,
                actor=actor,
                name=name,
                description=(
                    "Synthetic INTERNAL package created by seed_regx_demo. Not "
                    "an eCTD sequence, an agency filing or a gateway submission."
                ),
            )
        except Exception as exc:
            self.stdout.write(
                self.style.WARNING(f"  skipped  package ({type(exc).__name__}: {exc})")
            )
            return None

        self._note(True, f"package ({package.status})")

        if document is not None:
            try:
                add_entry(
                    package=package,
                    tenant=tenant,
                    actor=actor,
                    document_version_public_id=str(document["version"].public_id),
                    display_name="Synthetic excipient rationale",
                )
                self._note(True, "package entry (1 document version)")
            except Exception as exc:
                self.stdout.write(
                    self.style.WARNING(f"  skipped  package entry ({type(exc).__name__}: {exc})")
                )
        return package

    # -- external connector ----------------------------------------------

    def _seed_connector(self, tenant, actor):
        """One DISABLED connector, so the integrations screen is not empty.

        No credential reference, no secret, no execution, and a documentation
        host rather than anything private or routable inside this network.
        """
        from external_integrations.models import Connector
        from external_integrations.services import create_connector

        self.stdout.write(self.style.MIGRATE_HEADING("External connector"))
        name = f"{DEMO_PREFIX}Example inbound connector (disabled)"
        existing = Connector.objects.filter(tenant=tenant, name=name).first()
        if existing is not None:
            self._note(False, f"connector ({existing.status})")
            return existing

        try:
            connector = create_connector(
                tenant=tenant,
                actor=actor,
                name=name,
                connector_type="generic_https",
                configuration={
                    # example.invalid is reserved by RFC 2606 and never
                    # resolves, so this cannot reach anything -- and it is
                    # public, so it trips none of the SSRF/private-IP guards
                    # by being a loopback or RFC 1918 address.
                    "base_url": "https://example.invalid/",
                    "allowed_path_prefix": "/regx/",
                    "health_path": "health",
                    "connect_timeout_seconds": 5,
                    "read_timeout_seconds": 30,
                    "verify_tls": True,
                },
                description=(
                    "Synthetic connector created by seed_regx_demo. It stays "
                    "DRAFT, holds no credential reference and performs no I/O."
                ),
            )
        except Exception as exc:
            self.stdout.write(
                self.style.WARNING(f"  skipped  connector ({type(exc).__name__}: {exc})")
            )
            return None

        self._note(True, f"connector ({connector.status})")
        return connector

    # -- checklist -------------------------------------------------------

    def _seed_checklist(self, tenant, users) -> dict:
        from iig_checklist.enums import (
            AnswerType,
            ChecklistExecutionScope,
            ChecklistScopeType,
            Criticality,
            DataSourceClassification,
        )
        from iig_checklist.models import (
            ChecklistDefinition,
            ChecklistQuestion,
            ChecklistSection,
            ChecklistVersion,
        )

        self.stdout.write(self.style.MIGRATE_HEADING("Checklist definition"))
        definition, made = ChecklistDefinition.objects.get_or_create(
            tenant=tenant,
            code=f"{DEMO_PREFIX}EXCIPIENT-REVIEW",
            defaults={
                "title": f"{DEMO_PREFIX}Excipient review (demo content)",
                "description": (
                    "Demonstration checklist created by seed_regx_demo. Not "
                    "regulatory content and not derived from any FDA source."
                ),
                "scope_type": ChecklistScopeType.TENANT,
                # FORMULATION_VERSION rather than FORMULATION_COMPONENT: the
                # component scope requires a governed subject component on every
                # execution, which is more setup than a demo needs.
                "execution_scope": ChecklistExecutionScope.FORMULATION_VERSION,
                "created_by": users["doer"],
            },
        )
        self._note(made, "checklist definition")

        version, made = ChecklistVersion.objects.get_or_create(
            definition=definition,
            version_number=1,
            defaults={
                "status": "draft",
                # Activation refuses a version without one.
                "effective_date": date.today(),
                "created_by": users["doer"],
            },
        )
        self._note(made, "checklist version 1")

        if made:
            section = ChecklistSection.objects.create(
                checklist_version=version,
                code="S1",
                title="Excipient suitability",
                description="Demo section.",
                display_order=1,
                criticality=Criticality.MEDIUM,
            )
            questions = [
                (
                    "Q1",
                    "Is each inactive ingredient present in the proposed formulation?",
                    AnswerType.YES_NO,
                    Criticality.HIGH,
                ),
                (
                    "Q2",
                    "Has the quantity per dosage unit been recorded for every excipient?",
                    AnswerType.YES_NO,
                    Criticality.MEDIUM,
                ),
                (
                    "Q3",
                    "Summarise the basis for excipient selection.",
                    AnswerType.LONG_NARRATIVE,
                    Criticality.LOW,
                ),
            ]
            for order, (code, text, answer_type, criticality) in enumerate(questions, start=1):
                ChecklistQuestion.objects.create(
                    section=section,
                    code=code,
                    question_text=text,
                    display_order=order,
                    answer_type=answer_type,
                    data_source_classification=DataSourceClassification.USER_REQUIRED,
                    required=True,
                    criticality=criticality,
                )
            self._note(True, f"section + {len(questions)} questions")

        self._activate_version(version, users)
        return {"definition": definition, "version": version}

    def _activate_version(self, version, users) -> None:
        """Walk draft -> under_review -> approved -> active through the views.

        Deliberately not `version.status = "active"; version.save()`. The
        lifecycle carries permission checks, an effective-date requirement,
        calculation-binding validation and one audit event per transition.
        Writing the column directly would skip all four and leave a version
        that looks active but was never reviewed.
        """
        from rest_framework.test import APIRequestFactory, force_authenticate

        from iig_checklist import views as iig_views

        version.refresh_from_db()
        if version.status == "active":
            self.stdout.write("  reused   checklist version already active")
            return

        factory = APIRequestFactory()
        steps = (
            ("submit for review", iig_views.ChecklistVersionSubmitReviewView, "doer"),
            ("approve", iig_views.ChecklistVersionApproveView, "vp"),
            ("activate", iig_views.ChecklistVersionActivateView, "vp"),
        )
        for label, view_cls, role_name in steps:
            version.refresh_from_db()
            if version.status == "active":
                break
            request = factory.post(f"/seed/{version.public_id}/", {}, format="json")
            force_authenticate(request, user=users[role_name])
            response = view_cls.as_view()(request, public_id=str(version.public_id))
            if response.status_code >= 400:
                raise CommandError(
                    f"Checklist version {label} failed with HTTP "
                    f"{response.status_code}: {getattr(response, 'data', None)}"
                )
            version.refresh_from_db()
            self._note(True, f"version {label} -> {version.status}")

    # -- formulation -----------------------------------------------------

    def _seed_formulation(self, tenant, actor) -> dict:
        from formulations.models import (
            FormulationComponent,
            FormulationStatus,
            FormulationVersion,
            ProductDevelopmentRecord,
            ProductRecordStatus,
        )

        self.stdout.write(self.style.MIGRATE_HEADING("Formulation"))
        product, made = ProductDevelopmentRecord.objects.get_or_create(
            tenant=tenant,
            product_code=f"{DEMO_PREFIX}TAB-100",
            defaults={
                "proposed_product_name": f"{DEMO_PREFIX}Demonstration Tablet 100 mg",
                "active_ingredient": "Demonstration API (not a real substance)",
                "release_type": "immediate",
                "route": "oral",
                "dosage_form": "tablet",
                "proposed_strength_amount": Decimal("100.000000"),
                "proposed_strength_unit": "mg",
                "regulatory_market_context": "DEMO -- not a real submission",
                "status": ProductRecordStatus.APPROVED,
                "created_by": actor,
            },
        )
        self._note(made, "product development record")

        version = product.formulation_versions.filter(version_number=1).first()
        if version is None:
            # No transition service and no writable status field exists for
            # formulation versions, so `approved` is set at creation. This is
            # what the formulations and IIG test suites do; see the module
            # docstring for why it is not treated as a governance bypass.
            version = FormulationVersion.objects.create(
                product=product,
                version_number=1,
                status=FormulationStatus.APPROVED,
                total_dosage_unit_weight=Decimal("500.000000"),
                total_dosage_unit_weight_unit="milligram",
                maximum_dosage_units_per_day=Decimal("2.0000"),
                created_by=actor,
            )
            self._note(True, "formulation version 1 (approved)")

            for order, (name, qty, function) in enumerate(
                [
                    ("Microcrystalline cellulose", "250.000000", "Diluent"),
                    ("Croscarmellose sodium", "25.000000", "Disintegrant"),
                    ("Magnesium stearate", "5.000000", "Lubricant"),
                ],
                start=1,
            ):
                FormulationComponent.objects.create(
                    formulation_version=version,
                    component_type="inactive",
                    ingredient_name=name,
                    function=function,
                    quantity_per_dosage_unit=Decimal(qty),
                    quantity_unit="milligram",
                    display_order=order,
                )
            self._note(True, "3 excipient components")
        else:
            self._note(False, "formulation version 1")

        return {"product": product, "version": version}

    # -- execution -------------------------------------------------------

    def _seed_execution(self, tenant, actor, checklist_version, formulation_version):
        """Create one execution through the real service, as the Doer.

        This is the assertion the whole command exists for: if
        `create_execution` succeeds, both gates are genuinely open.
        """
        from iig_checklist.models import ChecklistExecution
        from iig_checklist.services import create_execution

        self.stdout.write(self.style.MIGRATE_HEADING("Sample execution"))
        existing = ChecklistExecution.objects.filter(
            checklist_version=checklist_version,
            formulation_version=formulation_version,
        ).first()
        if existing is not None:
            self._note(False, "sample execution")
            return str(existing.public_id)

        execution = create_execution(
            tenant=tenant,
            checklist_version_public_id=str(checklist_version.public_id),
            formulation_version_public_id=str(formulation_version.public_id),
            actor=actor,
        )
        self._note(True, "sample execution")
        return str(execution.public_id)


class _Rollback(Exception):
    """Raised to unwind the seeding transaction under --dry-run."""
