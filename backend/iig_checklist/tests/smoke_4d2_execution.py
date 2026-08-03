import json
import os
from decimal import Decimal

RUN_TAG = os.urandom(4).hex()

from django.contrib.auth import get_user_model
from django.test import Client

from authorization.models import MembershipRole, Role
from tenancy.models import Tenant, TenantMembership
from formulations.models import FormulationVersion, ProductDevelopmentRecord
from iig_checklist.models import (
    ChecklistDefinition,
    ChecklistExecution as CLE,
    ChecklistQuestion,
    ChecklistResponseHistory,
    ChecklistSection,
    ChecklistVersion,
)

User = get_user_model()
BASE = "/api/regx/v1"

tenant, _ = Tenant.objects.get_or_create(
    slug="docker-ci-4d2-v2", defaults={"name": "Docker CI 4D-2 v2"}
)


def make_actor(email, full_name, role_name):
    user, _ = User.objects.get_or_create(email=email, defaults={"full_name": full_name})
    membership, _ = TenantMembership.objects.get_or_create(tenant=tenant, user=user)
    role, _ = Role.objects.get_or_create(
        tenant=tenant, name=role_name, defaults={"is_system": True}
    )
    MembershipRole.objects.get_or_create(membership=membership, role=role)
    return user


def api_client(user):
    c = Client(SERVER_NAME="localhost")
    c.force_login(user)
    return c


doer = make_actor("ci-v2-doer@example.com", "CI Doer v2", "doer")
reviewer = make_actor("ci-v2-reviewer@example.com", "CI Reviewer v2", "reviewer")
vp = make_actor("ci-v2-vp@example.com", "CI VP v2", "vp")
doer_client = api_client(doer)
reviewer_client = api_client(reviewer)
vp_client = api_client(vp)
H = {"HTTP_X_TENANT_SLUG": tenant.slug, "content_type": "application/json"}

defn, _ = ChecklistDefinition.objects.get_or_create(
    code="CI-4D2-V2",
    tenant=tenant,
    defaults={
        "title": "CI 4D-2 v2 (synthetic)",
        "scope_type": "tenant",
        "created_by": doer,
    },
)
cv, _ = ChecklistVersion.objects.get_or_create(
    definition=defn, version_number=1, defaults={"status": "active", "created_by": doer}
)
section, _ = ChecklistSection.objects.get_or_create(
    checklist_version=cv,
    code="SEC-RC-1",
    defaults={"title": "RC Section", "display_order": 1, "criticality": "medium"},
)
ChecklistQuestion.objects.get_or_create(
    section=section,
    code="Q-RC-1",
    defaults={
        "question_text": "Reviewer conclusion?",
        "display_order": 1,
        "answer_type": "reviewer_conclusion",
        "data_source_classification": "reviewer_confirmed",
        "criticality": "high",
        "reviewer_confirmation_required": True,
    },
)
print("STEP 1 active checklist version + reviewer_conclusion question: OK")

product = ProductDevelopmentRecord.objects.create(
    tenant=tenant,
    product_code="CI-V2-PROD-" + RUN_TAG,
    proposed_product_name="CI v2 Product",
    active_ingredient="Synthetic v2 Ingredient",
    dosage_form="tablet",
    route="oral",
    created_by=doer,
)
fv = FormulationVersion(
    product=product,
    version_number=1,
    status="approved",
    total_dosage_unit_weight=Decimal("100"),
    total_dosage_unit_weight_unit="mg",
    created_by=doer,
)
fv.save()
print("STEP 2 approved formulation version: OK")

resp = doer_client.post(
    BASE + "/iig-checklists/executions/",
    data=json.dumps(
        {
            "checklist_version_public_id": str(cv.public_id),
            "formulation_version_public_id": str(fv.public_id),
        }
    ),
    **H,
)
assert resp.status_code == 201, "STEP 3 FAIL: %s %s" % (resp.status_code, resp.content)
ex = resp.json()
assert ex["status"] == "draft"
assert "id" not in ex and "pk" not in ex
epub = ex["public_id"]
print("STEP 3 execution created in draft (UUID-only): OK")

resp2 = doer_client.post(
    BASE + "/iig-checklists/executions/",
    data=json.dumps(
        {
            "checklist_version_public_id": str(cv.public_id),
            "formulation_version_public_id": str(fv.public_id),
        }
    ),
    **H,
)
assert resp2.status_code == 409, "STEP 4 FAIL: %s" % resp2.status_code
print("STEP 4 duplicate active execution rejected with 409: OK")

resp = doer_client.post(
    BASE + "/iig-checklists/executions/%s/submit-review/" % epub, **H
)
assert resp.status_code == 200 and resp.json()["status"] == "submitted_for_review", (
    "STEP 5 FAIL: %s %s" % (resp.status_code, resp.content)
)
print("STEP 5 execution submitted for review: OK")

resp_list = reviewer_client.get(
    BASE + "/iig-checklists/executions/%s/responses/" % epub, **H
)
assert resp_list.status_code == 200, "STEP 5b FAIL status: %s" % resp_list.status_code
rl = resp_list.json()
assert "results" in rl and "count" in rl, (
    "STEP 5b FAIL: not paginated, keys=%s" % list(rl.keys())
)
print("STEP 5b response list paginated (count + results): OK")

from iig_checklist.models import ChecklistQuestion
rc_question = ChecklistQuestion.objects.get(section=section, answer_type="reviewer_conclusion")
rc_question_pub = str(rc_question.public_id)
rc_resp = next(
    r for r in rl["results"]
    if str(r.get("question_public_id")) == rc_question_pub
)
rc_pid = rc_resp["public_id"]
rc_ver = rc_resp["version"]

resp_rc = reviewer_client.post(
    BASE + "/iig-checklists/executions/%s/responses/%s/reviewer-conclusion/" % (epub, rc_pid),
    data=json.dumps(
        {"raw_value": {"value": "Initial CI conclusion."}, "expected_version": rc_ver}
    ),
    **H,
)
assert resp_rc.status_code == 200, "STEP 5c FAIL: %s %s" % (resp_rc.status_code, resp_rc.content)
rc_ver = resp_rc.json()["version"]
print("STEP 5c reviewer conclusion first entry: OK")

resp_rc2 = reviewer_client.post(
    BASE + "/iig-checklists/executions/%s/responses/%s/reviewer-conclusion/" % (epub, rc_pid),
    data=json.dumps(
        {
            "raw_value": {"value": "Amended."},
            "expected_version": rc_ver,
            "correction_reason": "Typo.",
        }
    ),
    **H,
)
assert resp_rc2.status_code == 200, "STEP 5d FAIL: %s %s" % (resp_rc2.status_code, resp_rc2.content)
actual_ex = CLE.objects.get(public_id=epub)
rc_response_obj = actual_ex.responses.get(public_id=rc_pid)
hist = ChecklistResponseHistory.objects.filter(response=rc_response_obj).count()
assert hist == 1, "STEP 5d FAIL: expected 1 history row, got %d" % hist
rc_ver = resp_rc2.json()["version"]
print("STEP 5d reviewer conclusion amendment + 1 history row: OK")

resp_stale = reviewer_client.post(
    BASE + "/iig-checklists/executions/%s/responses/%s/reviewer-conclusion/" % (epub, rc_pid),
    data=json.dumps(
        {"raw_value": {"value": "Stale."}, "expected_version": rc_ver + 99, "correction_reason": "x"}
    ),
    **H,
)
assert resp_stale.status_code in (400, 409, 422), (
    "STEP 5e FAIL: stale got %s" % resp_stale.status_code
)
hist_after = ChecklistResponseHistory.objects.filter(response=rc_response_obj).count()
assert hist_after == 1, "STEP 5e FAIL: stale created history, now %d" % hist_after
print("STEP 5e stale version no history created: OK")

resp = reviewer_client.post(
    BASE + "/iig-checklists/executions/%s/return/" % epub,
    data=json.dumps({"return_reason": "Review needed."}),
    **H,
)
assert resp.status_code == 200 and resp.json()["status"] == "returned", (
    "STEP 6 FAIL: %s %s" % (resp.status_code, resp.content)
)
print("STEP 6 execution returned with reason: OK")

doer_client.post(BASE + "/iig-checklists/executions/%s/submit-review/" % epub, **H)
resp = vp_client.post(
    BASE + "/iig-checklists/executions/%s/approve/" % epub,
    data=json.dumps({"reviewer_conclusion_note": "CI v2 approved."}),
    **H,
)
assert resp.status_code == 200 and resp.json()["status"] == "approved", (
    "STEP 7 FAIL: %s %s" % (resp.status_code, resp.content)
)
print("STEP 7 execution approved by VP: OK")

resp_imm = reviewer_client.post(
    BASE + "/iig-checklists/executions/%s/responses/%s/reviewer-conclusion/" % (epub, rc_pid),
    data=json.dumps(
        {"raw_value": {"value": "Post-approval."}, "expected_version": rc_ver, "correction_reason": "x"}
    ),
    **H,
)
assert resp_imm.status_code in (400, 409, 422), (
    "STEP 7b FAIL: approved state not immutable, got %s %s" % (resp_imm.status_code, resp_imm.content)
)
print("STEP 7b terminal (approved) reviewer_conclusion immutable: OK")

resp_patch = reviewer_client.patch(
    BASE + "/iig-checklists/executions/%s/responses/%s/" % (epub, rc_pid),
    data=json.dumps({"raw_value": {"value": "Patch attempt."}}),
    **H,
)
assert resp_patch.status_code in (400, 403), (
    "STEP 7c FAIL: generic PATCH got %s" % resp_patch.status_code
)
print("STEP 7c generic PATCH cannot edit reviewer_conclusion: OK")

other_tenant, _ = Tenant.objects.get_or_create(
    slug="docker-ci-4d2-other", defaults={"name": "Docker CI 4D-2 Other"}
)
# other_user is a member of other_tenant only; cannot see executions from tenant.
other_user, _ = User.objects.get_or_create(
    email="ci-v2-other@example.com", defaults={"full_name": "CI Other v2"}
)
other_membership, _ = TenantMembership.objects.get_or_create(tenant=other_tenant, user=other_user)
other_role, _ = Role.objects.get_or_create(
    tenant=other_tenant, name="doer", defaults={"is_system": True}
)
MembershipRole.objects.get_or_create(membership=other_membership, role=other_role)
other_client = Client(SERVER_NAME="localhost")
other_client.force_login(other_user)
resp_cross = other_client.get(
    BASE + "/iig-checklists/executions/%s/" % epub,
    HTTP_X_TENANT_SLUG="docker-ci-4d2-other",
)
assert resp_cross.status_code == 404, (
    "STEP 8 FAIL: cross-tenant got %s (expected 404)" % resp_cross.status_code
)
print("STEP 8 cross-tenant execution detail returns 404: OK")

product2 = ProductDevelopmentRecord.objects.create(
    tenant=tenant,
    product_code="CI-V2-PROD2-" + RUN_TAG,
    proposed_product_name="CI v2 Product 2",
    active_ingredient="Synthetic v2 Ingredient 2",
    dosage_form="tablet",
    route="oral",
    created_by=doer,
)
fv2 = FormulationVersion(
    product=product2,
    version_number=1,
    status="approved",
    total_dosage_unit_weight=Decimal("100"),
    total_dosage_unit_weight_unit="mg",
    created_by=doer,
)
fv2.save()
resp_new = doer_client.post(
    BASE + "/iig-checklists/executions/",
    data=json.dumps(
        {
            "checklist_version_public_id": str(cv.public_id),
            "formulation_version_public_id": str(fv2.public_id),
        }
    ),
    **H,
)
assert resp_new.status_code == 201
epub2 = resp_new.json()["public_id"]
doer_client.post(BASE + "/iig-checklists/executions/%s/submit-review/" % epub2, **H)

resp_403 = reviewer_client.post(
    BASE + "/iig-checklists/executions/%s/approve/" % epub2,
    data=json.dumps({"reviewer_conclusion_note": "x"}),
    **H,
)
assert resp_403.status_code == 403, (
    "STEP 8b FAIL: reviewer got %s (expected 403)" % resp_403.status_code
)
print("STEP 8b in-tenant reviewer (no approve perm) gets 403: OK")

print("IIG CHECKLIST EXECUTION 4D-2 SMOKE FLOW v2: ALL STEPS PASS")
