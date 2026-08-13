"""`5A-DEC-005` -- explicit, structured, governed jurisdiction on ChecklistVersion.

Additive and non-destructive: one nullable-equivalent column with an empty-string
default. **Nothing is backfilled.** Every pre-5A version keeps `""`, meaning
*not stated*, because retro-labelling historical synthetic content `US_FDA`
would assert a regulatory approval basis that no one ever approved it under --
precisely the kind of invented regulatory meaning this milestone exists to
prevent. Existing rows remain fully usable; production content states its
jurisdiction explicitly through the governed content package.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('iig_checklist', '0003_alter_calculationoutcome_input_provenance_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='checklistversion',
            name='jurisdiction',
            field=models.CharField(blank=True, choices=[('US_FDA', 'United States FDA')], default='', max_length=20),
        ),
    ]
