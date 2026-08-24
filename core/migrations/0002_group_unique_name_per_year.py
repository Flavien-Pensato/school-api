"""Group names become unique per school year, not per class.

Existing groups are renamed to the "<class> - <name>" scheme so the new
constraint holds without touching enrollments or assignments.
"""

import django.db.models.deletion
from django.db import migrations, models


def prefix_group_names_with_class(apps, schema_editor):
    Group = apps.get_model('core', 'Group')
    for group in Group.objects.select_related('school_class').iterator():
        class_name = group.school_class.name
        group.school_year_id = group.school_class.school_year_id
        if not group.name.startswith(f'{class_name} - '):
            group.name = f'{class_name} - {group.name}'[:150]
        group.save(update_fields=['name', 'school_year'])


def strip_class_prefix(apps, schema_editor):
    Group = apps.get_model('core', 'Group')
    for group in Group.objects.select_related('school_class').iterator():
        prefix = f'{group.school_class.name} - '
        if group.name.startswith(prefix):
            group.name = group.name[len(prefix):]
            group.save(update_fields=['name'])


class Migration(migrations.Migration):

    dependencies = [('core', '0001_initial')]

    operations = [
        migrations.RemoveConstraint(
            model_name='group', name='unique_group_per_class',
        ),
        migrations.AlterField(
            model_name='group',
            name='name',
            field=models.CharField(max_length=150),
        ),
        migrations.AddField(
            model_name='group',
            name='school_year',
            field=models.ForeignKey(
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='groups',
                to='core.schoolyear',
            ),
        ),
        migrations.RunPython(
            prefix_group_names_with_class, strip_class_prefix,
        ),
        migrations.AlterField(
            model_name='group',
            name='school_year',
            field=models.ForeignKey(
                editable=False,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='groups',
                to='core.schoolyear',
            ),
        ),
        migrations.AddConstraint(
            model_name='group',
            constraint=models.UniqueConstraint(
                fields=('school_year', 'name'), name='unique_group_per_year',
            ),
        ),
    ]
