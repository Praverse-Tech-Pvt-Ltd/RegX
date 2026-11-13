"""Merge tenant-scoped copies of the built-in system roles into the platform-wide ones.

A system role (`is_system=True`) must have no tenant: the five built-ins are
seeded once, platform-wide, by `authorization/seed.py`. Some databases hold
tenant-scoped rows with the same names and `is_system=True` (made by an ad-hoc
shell script on 2026-09-09; `PROJECT_OVERVIEW.md` §11 #25). They break any
lookup by name and could hand one tenant's role to another tenant's user.

`merge_tenant_scoped_system_roles` runs inside migration 0003 (with historical
models) before the constraint that forbids such rows. For each duplicate it:

1. finds the platform-wide role with the same name (`tenant IS NULL`, `is_system`);
2. moves every assignment (`MembershipRole`) to it, or drops the assignment when
   that membership already holds the platform role (nothing is lost);
3. deletes the duplicate's `RolePermission` rows, which are allowed only if the
   platform role already grants every one of those permissions;
4. deletes the duplicate.

It refuses, and changes nothing, when a duplicate has no platform-wide
counterpart or grants a permission the platform role does not: moving those
assignments would change what someone may do. On a database without
duplicates it does nothing.
"""


class RoleCleanupRefused(Exception):
    """A duplicate could not be merged safely. Nothing was changed."""


def merge_tenant_scoped_system_roles(
    role_model, membership_role_model, role_permission_model, log=print
):
    # Models are passed in so the migration can use its historical versions.
    Role, MembershipRole, RolePermission = (  # noqa: N806
        role_model,
        membership_role_model,
        role_permission_model,
    )
    duplicates = list(Role.objects.filter(is_system=True, tenant__isnull=False).order_by("id"))
    if not duplicates:
        log("authorization: no tenant-scoped system roles; nothing to merge.")
        return {"duplicates": 0, "moved": 0, "dropped_redundant": 0}

    # Check everything first, so a refusal leaves the database untouched.
    plan, problems = [], []
    for dup in duplicates:
        target = Role.objects.filter(name=dup.name, tenant__isnull=True, is_system=True).first()
        if target is None:
            problems.append(
                f"role id={dup.id} name={dup.name!r}: no platform-wide system role with that name"
            )
            continue
        dup_perms = set(
            RolePermission.objects.filter(role=dup).values_list("permission_id", flat=True)
        )
        target_perms = set(
            RolePermission.objects.filter(role=target).values_list("permission_id", flat=True)
        )
        extra = dup_perms - target_perms
        if extra:
            problems.append(
                f"role id={dup.id} name={dup.name!r}: grants {len(extra)} permission(s) the "
                f"platform role id={target.id} does not; moving its assignments would change access"
            )
            continue
        plan.append((dup, target))
    if problems:
        raise RoleCleanupRefused(
            "Refusing to merge tenant-scoped system roles; nothing was changed:\n  - "
            + "\n  - ".join(problems)
        )

    moved = dropped = 0
    for dup, target in plan:
        for assignment in MembershipRole.objects.filter(role=dup):
            if MembershipRole.objects.filter(
                membership_id=assignment.membership_id, role=target
            ).exists():
                assignment.delete()
                dropped += 1
            else:
                assignment.role = target
                assignment.save(update_fields=["role"])
                moved += 1
        RolePermission.objects.filter(role=dup).delete()
        assert not MembershipRole.objects.filter(role=dup).exists()
        log(
            f"authorization: merged role id={dup.id} {dup.name!r} into platform role id={target.id}"
        )
        dup.delete()
    log(
        f"authorization: {len(plan)} duplicate system role(s) removed; "
        f"{moved} assignment(s) moved, {dropped} redundant assignment(s) dropped."
    )
    return {"duplicates": len(plan), "moved": moved, "dropped_redundant": dropped}
