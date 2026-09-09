"""
Seed demo data into a REGX tenant so the screens are not empty.

Uses each app's service layer where one exists (regulatory_cases) so governance
rules run and domain events fire, rather than writing rows behind the domain's
back. Idempotent: re-running adds nothing.

    docker compose exec -T backend python manage.py shell < seed_sample_data.py
"""

from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction

from identity.models import User
from tenancy.models import Tenant

TENANT_SLUG = "praverse"
ADMIN_EMAIL = "admin@praverse.local"

tenant = Tenant.objects.get(slug=TENANT_SLUG)
actor = User.objects.get(email=ADMIN_EMAIL)
created = {}


def note(kind, n=1):
    created[kind] = created.get(kind, 0) + n


# --------------------------------------------------------------------------
# Regulatory cases — via services.create_case so the case number is claimed
# under lock and a CaseEvent is emitted.
# --------------------------------------------------------------------------
from regulatory_cases import services as case_services
from regulatory_cases.models import RegulatoryCase

CASES = [
    dict(title="Metoprolol Succinate ER 50 mg - ANDA",
         product_name="Metoprolol Succinate ER", product_code="MET-ER-050",
         market="United States", authority="FDA", submission_type="ANDA",
         description="Extended-release tablet, 50 mg. Bioequivalence to the RLD."),
    dict(title="Budesonide Inhalation Suspension 0.5 mg/2 mL - ANDA",
         product_name="Budesonide Inhalation Suspension", product_code="BUD-INH-05",
         market="United States", authority="FDA", submission_type="ANDA",
         description="Nebuliser suspension. Q1/Q2 match to the reference product."),
    dict(title="Latanoprost Ophthalmic Solution 0.005% - ANDA",
         product_name="Latanoprost Ophthalmic Solution", product_code="LAT-OPH-005",
         market="United States", authority="FDA", submission_type="ANDA",
         description="Sterile multi-dose ophthalmic solution."),
    dict(title="Tacrolimus Ointment 0.1% - DMF Type II",
         product_name="Tacrolimus Ointment", product_code="TAC-OIN-01",
         market="United States", authority="FDA", submission_type="DMF",
         description="Drug master file covering the API supplier."),
    dict(title="Rivaroxaban Tablets 20 mg - EU Variation",
         product_name="Rivaroxaban Tablets", product_code="RIV-TAB-020",
         market="European Union", authority="EMA", submission_type="Variation",
         description="Type IB variation adding a manufacturing site."),
]

with transaction.atomic():
    for i, fields in enumerate(CASES):
        if RegulatoryCase.objects.filter(tenant=tenant, title=fields["title"]).exists():
            continue
        case_services.create_case(
            tenant=tenant, actor=actor,
            target_date=date.today() + timedelta(days=30 * (i + 2)),
            **fields,
        )
        note("regulatory cases")


# --------------------------------------------------------------------------
# Formulations — product records, versions, components, dosing regimens.
# --------------------------------------------------------------------------
from formulations.models import (
    ComponentType, DosingRegimen, FormulationComponent, FormulationStatus,
    FormulationVersion, ProductDevelopmentRecord, ProductRecordStatus, ReleaseType,
)

A, I = ComponentType.ACTIVE, ComponentType.INACTIVE

FORMULATIONS = [
    dict(code="MET-ER-050", name="Metoprolol Succinate ER Tablets 50 mg",
         active="Metoprolol succinate", release=ReleaseType.EXTENDED,
         route="Oral", form="Tablet, extended release",
         strength=Decimal("50.000000"), unit="mg", weight=Decimal("380.000000"),
         components=[
             ("Metoprolol succinate", A, Decimal("47.500000"), "Active"),
             ("Microcrystalline cellulose", I, Decimal("180.000000"), "Diluent"),
             ("Ethylcellulose", I, Decimal("95.000000"), "Release modifier"),
             ("Hypromellose", I, Decimal("53.700000"), "Binder"),
             ("Magnesium stearate", I, Decimal("3.800000"), "Lubricant"),
         ]),
    dict(code="LAT-OPH-005", name="Latanoprost Ophthalmic Solution 0.005%",
         active="Latanoprost", release=ReleaseType.IMMEDIATE,
         route="Ophthalmic", form="Solution/drops",
         strength=Decimal("0.005000"), unit="%", weight=Decimal("1000.000000"),
         components=[
             ("Latanoprost", A, Decimal("0.050000"), "Active"),
             ("Benzalkonium chloride", I, Decimal("0.200000"), "Preservative"),
             ("Sodium chloride", I, Decimal("4.100000"), "Tonicity agent"),
             ("Sodium dihydrogen phosphate monohydrate", I, Decimal("4.600000"), "Buffer"),
         ]),
    dict(code="TAC-OIN-01", name="Tacrolimus Ointment 0.1%",
         active="Tacrolimus", release=ReleaseType.IMMEDIATE,
         route="Topical", form="Ointment",
         strength=Decimal("0.100000"), unit="%", weight=Decimal("1000.000000"),
         components=[
             ("Tacrolimus monohydrate", A, Decimal("1.020000"), "Active"),
             ("White petrolatum", I, Decimal("880.000000"), "Ointment base"),
             ("Mineral oil", I, Decimal("60.000000"), "Emollient"),
             ("Propylene carbonate", I, Decimal("58.980000"), "Solvent"),
         ]),
    dict(code="BUD-INH-05", name="Budesonide Inhalation Suspension 0.5 mg/2 mL",
         active="Budesonide", release=ReleaseType.IMMEDIATE,
         route="Respiratory (inhalation)", form="Suspension for nebulisation",
         strength=Decimal("0.500000"), unit="mg", weight=Decimal("2000.000000"),
         components=[
             ("Budesonide", A, Decimal("0.500000"), "Active"),
             ("Disodium edetate", I, Decimal("0.200000"), "Chelating agent"),
             ("Sodium chloride", I, Decimal("17.000000"), "Tonicity agent"),
             ("Polysorbate 80", I, Decimal("0.400000"), "Surfactant"),
             ("Purified water", I, Decimal("1981.900000"), "Vehicle"),
         ]),
]

with transaction.atomic():
    for f in FORMULATIONS:
        product, made = ProductDevelopmentRecord.objects.get_or_create(
            tenant=tenant, product_code=f["code"],
            defaults=dict(
                proposed_product_name=f["name"],
                active_ingredient=f["active"],
                release_type=f["release"],
                route=f["route"],
                dosage_form=f["form"],
                proposed_strength_amount=f["strength"],
                proposed_strength_unit=f["unit"],
                regulatory_market_context="US ANDA",
                status=ProductRecordStatus.DRAFT,
                created_by=actor,
            ),
        )
        if made:
            note("formulation products")
        if product.formulation_versions.exists():
            continue
        version = FormulationVersion.objects.create(
            product=product,
            version_number=1,
            status=FormulationStatus.DRAFT,
            total_dosage_unit_weight=f["weight"],
            total_dosage_unit_weight_unit="mg",
            maximum_dosage_units_per_day=Decimal("2.0000"),
            dosing_basis="Per proposed label, adult dosing",
            rationale="Seeded demonstration formulation.",
            created_by=actor,
        )
        note("formulation versions")
        for order, (cname, ctype, qty, fn) in enumerate(f["components"], start=1):
            FormulationComponent.objects.create(
                formulation_version=version,
                component_type=ctype,
                ingredient_name=cname,
                function=fn,
                quantity_per_dosage_unit=qty,
                quantity_unit="mg",
                display_order=order,
            )
            note("formulation components")
        DosingRegimen.objects.create(
            formulation_version=version,
            units_per_administration=Decimal("1.0000"),
            administrations_per_day=Decimal("1.0000"),
            maximum_units_per_day=Decimal("2.0000"),
            patient_population="Adults",
            basis="Proposed label",
        )
        note("dosing regimens")


print("")
print("Seeded:")
for k in sorted(created):
    print("  %-26s %s" % (k, created[k]))
if not created:
    print("  nothing new - data already present")
