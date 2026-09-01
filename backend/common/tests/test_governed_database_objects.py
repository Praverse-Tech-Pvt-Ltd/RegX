"""The governed database floor is installed, by name and by table.

WHY A CATALOGUE TEST EXISTS

Every module from Milestone 9 onward puts its last line of defence in
PostgreSQL rather than in Python, because `Model.save()` resolves through
`_base_manager` and a manager restriction cannot cover it. Those triggers are
created by migrations and are invisible afterwards: nothing in the ORM
references them, no import fails if one is missing, and no existing test
notices a trigger that was never installed on a *fresh* database.

The specific failure this catches: a later migration that alters or recreates a
governed table, dropping its triggers as a side effect, or a `DROP TRIGGER` in
a reverse operation that is never paired with a re-create. The suite would stay
green -- every behavioural test that exercises the trigger runs against a
database where some *earlier* migration installed it, and a trigger silently
lost at migration N+1 looks identical to one that was never needed.

WHAT THIS ASSERTS, AND WHAT IT DELIBERATELY DOES NOT

It asserts presence by name and attachment table. It does not assert behaviour
-- each module already owns tests that attempt the forbidden write and expect
the database to refuse it, and duplicating those here would be a worse copy of
a better test. This is the inventory; those are the proof.

The expected set below was not copied from a live database and then blessed.
Each entry traces to the migration that creates it, and the totals were
reconciled against the migration sources: 46 plpgsql functions and 57 triggers,
where 57 is the 49 `CREATE TRIGGER` statements in the migrations plus the
templated expansion of two statements over three link tables in each of
`regulatory_cases` and `submission_dossiers`.

**Absences are recorded too.** `iig_checklist` and `documents` have no
governed triggers at all. That is a real property of the platform, not an
oversight, and it is asserted here so that any doc claiming a database floor
for those modules disagrees with a test.
"""

import pytest
from django.db import connection

EXPECTED_TRIGGERS = {
    "audit_auditevent": (
        "no_delete_audit_event",
        "no_update_audit_event",
    ),
    "dossier_blueprints_blueprintinstantiation": (
        "freeze_blueprint_instantiation",
        "guard_insert_blueprint_instantiation",
    ),
    "dossier_blueprints_blueprintsectionorigin": (
        "freeze_blueprint_section_origin",
        "guard_insert_blueprint_section_origin",
    ),
    "dossier_blueprints_dossierblueprintsection": (
        "guard_insert_blueprint_section",
        "guard_update_blueprint_section",
        "no_delete_blueprint_section",
    ),
    "dossier_blueprints_dossierblueprintversion": (
        "guard_update_blueprint_version",
        "no_delete_blueprint_version",
    ),
    "dossier_upgrades_dossierupgradeapplication": (
        "freeze_upgrade_history",
        "guard_insert_upgrade_application",
        "guard_upgrade_application_chain",
    ),
    "dossier_upgrades_dossierupgradeplan": (
        "guard_update_upgrade_plan",
        "no_delete_upgrade_plan",
    ),
    "dossier_upgrades_dossierupgradeplanitem": (
        "guard_delete_upgrade_plan_item",
        "guard_update_upgrade_plan_item",
    ),
    "dossier_upgrades_upgradesectionorigin": ("freeze_upgrade_section_origin",),
    "external_integrations_connector": (
        "guard_insert_connector",
        "guard_update_connector",
    ),
    "external_integrations_connectorcredentialreference": ("guard_insert_credential_reference",),
    "external_integrations_connectorexecution": (
        "guard_insert_execution",
        "guard_update_execution",
        "no_delete_execution",
    ),
    "external_integrations_externalobjectlink": (
        "guard_insert_external_object_link",
        "guard_update_external_object_link",
        "no_delete_external_object_link",
    ),
    "regulatory_cases_regulatorycasechecklist": (
        "guard_update_case_checklist_link",
        "no_delete_case_checklist_link",
    ),
    "regulatory_cases_regulatorycasedocument": (
        "guard_update_case_document_link",
        "no_delete_case_document_link",
    ),
    "regulatory_cases_regulatorycaseworkflow": (
        "guard_update_case_workflow_link",
        "no_delete_case_workflow_link",
    ),
    "submission_dossiers_dossiersection": (
        "guard_insert_dossier_section",
        "guard_update_dossier_section",
        "no_delete_dossier_section",
    ),
    "submission_dossiers_dossiersectionblocker": (
        "guard_update_section_blocker",
        "no_delete_section_blocker",
    ),
    "submission_dossiers_dossiersectionchecklist": (
        "guard_update_section_checklist_link",
        "no_delete_section_checklist_link",
    ),
    "submission_dossiers_dossiersectiondocument": (
        "guard_update_section_document_link",
        "no_delete_section_document_link",
    ),
    "submission_dossiers_dossiersectionworkflow": (
        "guard_update_section_workflow_link",
        "no_delete_section_workflow_link",
    ),
    "submission_packages_submissionpackage": (
        "guard_insert_package",
        "guard_update_package",
        "no_delete_package",
    ),
    "submission_packages_submissionpackageentry": (
        "guard_delete_package_entry",
        "guard_insert_package_entry",
        "guard_update_package_entry",
    ),
    "submission_packages_submissionpackagesnapshot": (
        "freeze_package_snapshot",
        "guard_insert_package_snapshot",
    ),
    "workflows_workflowevidence": (
        "guard_update_workflow_evidence",
        "no_delete_workflow_evidence",
    ),
    "workflows_workflowtransition": (
        "no_delete_workflow_transition",
        "no_update_workflow_transition",
    ),
}

EXPECTED_FUNCTIONS = (
    "audit_prevent_update_delete",
    "dossier_blueprints_check_section_parent",
    "dossier_blueprints_guard_instantiation_insert",
    "dossier_blueprints_guard_origin_insert",
    "dossier_blueprints_guard_section_insert",
    "dossier_blueprints_guard_section_update",
    "dossier_blueprints_guard_version_update",
    "dossier_blueprints_prevent_provenance_change",
    "dossier_blueprints_prevent_section_delete",
    "dossier_blueprints_prevent_version_delete",
    "dossier_upgrades_guard_application_chain",
    "dossier_upgrades_guard_application_insert",
    "dossier_upgrades_guard_item_delete",
    "dossier_upgrades_guard_item_update",
    "dossier_upgrades_guard_plan_update",
    "dossier_upgrades_prevent_history_change",
    "dossier_upgrades_prevent_plan_delete",
    "external_integrations_guard_connector_insert",
    "external_integrations_guard_connector_update",
    "external_integrations_guard_credential_insert",
    "external_integrations_guard_execution_insert",
    "external_integrations_guard_execution_update",
    "external_integrations_guard_link_insert",
    "external_integrations_guard_link_update",
    "external_integrations_prevent_delete",
    "regulatory_cases_guard_link_update",
    "regulatory_cases_prevent_link_delete",
    "submission_dossiers_check_section_parent",
    "submission_dossiers_guard_blocker_update",
    "submission_dossiers_guard_link_update",
    "submission_dossiers_guard_section_insert",
    "submission_dossiers_guard_section_update",
    "submission_dossiers_prevent_blocker_delete",
    "submission_dossiers_prevent_link_delete",
    "submission_dossiers_prevent_section_delete",
    "submission_packages_freeze_snapshot",
    "submission_packages_guard_entry_insert",
    "submission_packages_guard_entry_update",
    "submission_packages_guard_package_insert",
    "submission_packages_guard_package_update",
    "submission_packages_guard_snapshot_insert",
    "submission_packages_prevent_entry_delete",
    "submission_packages_prevent_package_delete",
    "workflows_guard_evidence_update",
    "workflows_prevent_evidence_delete",
    "workflows_prevent_transition_update_delete",
)

#: Modules whose governance is service-layer and model-layer only. Asserted so
#: that adding a trigger here forces a deliberate update to this list and to
#: whatever documentation describes the floor.
TABLES_WITH_NO_GOVERNED_TRIGGERS = (
    "documents_document",
    "documents_documentversion",
    "iig_checklist_checklistexecution",
    "iig_checklist_checklistresponse",
)


def _installed_triggers():
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT c.relname, t.tgname
              FROM pg_trigger t
              JOIN pg_class c ON c.oid = t.tgrelid
              JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE NOT t.tgisinternal AND n.nspname = 'public'
            """
        )
        found = {}
        for table, name in cursor.fetchall():
            found.setdefault(table, set()).add(name)
    return found


def _installed_functions():
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT p.proname
              FROM pg_proc p
              JOIN pg_namespace n ON n.oid = p.pronamespace
              JOIN pg_language l ON l.oid = p.prolang
             WHERE n.nspname = 'public' AND l.lanname = 'plpgsql'
            """
        )
        return {row[0] for row in cursor.fetchall()}


@pytest.mark.django_db
class TestGovernedTriggersAreInstalled:
    def test_every_expected_trigger_exists_on_its_own_table(self):
        """THE regression test.

        Checked per table rather than by total count, because a count passes
        while a trigger sits on the wrong relation -- which is exactly what a
        copy-pasted migration produces.
        """
        installed = _installed_triggers()
        missing = []
        for table, names in EXPECTED_TRIGGERS.items():
            present = installed.get(table, set())
            for name in names:
                if name not in present:
                    missing.append(f"{table}.{name}")

        assert missing == [], (
            f"{len(missing)} governed trigger(s) are not installed: "
            + ", ".join(missing)
            + ". A governed table without its trigger accepts writes the "
            "service layer refuses."
        )

    def test_every_expected_function_exists(self):
        installed = _installed_functions()
        missing = sorted(set(EXPECTED_FUNCTIONS) - installed)
        assert missing == [], f"missing governed function(s): {', '.join(missing)}"

    def test_no_governed_trigger_appeared_without_being_recorded(self):
        """The other direction.

        A trigger nobody wrote down is as much a problem as one that went
        missing: it means the floor moved and the inventory, the migration
        register and the release runbook no longer describe the system.
        """
        installed = _installed_triggers()
        expected_pairs = {
            (table, name) for table, names in EXPECTED_TRIGGERS.items() for name in names
        }
        found_pairs = {(table, name) for table, names in installed.items() for name in names}
        unrecorded = sorted(found_pairs - expected_pairs)
        assert unrecorded == [], (
            "governed trigger(s) exist that this inventory does not record: "
            + ", ".join(f"{t}.{n}" for t, n in unrecorded)
        )

    def test_the_totals_match_the_migration_sources(self):
        """A blunt cross-check on the two numbers the migration register cites."""
        installed = _installed_triggers()
        total = sum(len(names) for names in installed.values())
        assert total == 57, f"expected 57 governed triggers, found {total}"
        assert len(_installed_functions()) == 46


@pytest.mark.django_db
class TestModulesWithoutADatabaseFloor:
    """Recorded absence, so documentation cannot quietly overstate the floor."""

    def test_documents_and_checklists_have_no_governed_triggers(self):
        installed = _installed_triggers()
        unexpected = {
            table: sorted(installed[table])
            for table in TABLES_WITH_NO_GOVERNED_TRIGGERS
            if installed.get(table)
        }
        assert unexpected == {}, (
            "a governed trigger now exists on a table documented as having no "
            f"database floor: {unexpected}. Update the inventory and the docs "
            "that describe which modules are protected at the database."
        )
