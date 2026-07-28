"""Scope-aware managers for the IIG checklist definition-governance domain.

A `ChecklistDefinition` is either platform-master (tenant=NULL, visible
to every authenticated tenant member, editable only with a platform-level
grant) or tenant-scoped (visible/editable only within its own tenant).
"""

from django.db import models


class ChecklistDefinitionManager(models.Manager):
    def visible_to(self, tenant):
        """Platform-master rows plus this tenant's own rows -- never
        another tenant's rows."""
        return self.get_queryset().filter(
            models.Q(scope_type="platform_master") | models.Q(tenant=tenant)
        )


class RelatedChecklistScopeManager(models.Manager):
    """For models FK'd (directly or transitively) to ChecklistDefinition --
    filters by the same platform-master-or-own-tenant visibility rule."""

    definition_path = "checklist_version__definition"

    def visible_to(self, tenant):
        prefix = self.definition_path
        return self.get_queryset().filter(
            models.Q(**{f"{prefix}__scope_type": "platform_master"})
            | models.Q(**{f"{prefix}__tenant": tenant})
        )


class ChecklistVersionManager(RelatedChecklistScopeManager):
    definition_path = "definition"


class ChecklistSectionManager(RelatedChecklistScopeManager):
    definition_path = "checklist_version__definition"


class ChecklistQuestionManager(RelatedChecklistScopeManager):
    definition_path = "section__checklist_version__definition"
