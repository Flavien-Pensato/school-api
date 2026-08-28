"""Groups hang off the school year instead of a class.

`school_year` was already carried (and backfilled) by 0002, so nothing needs
moving forward — the class FK is simply dropped. Going back is lossy: a group
now mixes classes, so the reverse pass rebuilds `school_class` from the group's
first enrollment, falling back to the year's first class for empty groups.
"""

import django.db.models.deletion
from django.db import migrations, models


def restore_school_class(apps, schema_editor):
    Group = apps.get_model('core', 'Group')
    SchoolClass = apps.get_model('core', 'SchoolClass')
    for group in Group.objects.iterator():
        enrollment = group.enrollments.first()
        if enrollment is not None:
            group.school_class_id = enrollment.school_class_id
        else:
            fallback = SchoolClass.objects.filter(
                school_year_id=group.school_year_id
            ).first()
            if fallback is None:
                raise RuntimeError(
                    f'No class in {group.school_year_id} to re-attach '
                    f'group {group.pk} to.'
                )
            group.school_class_id = fallback.pk
        group.save(update_fields=['school_class'])


class Migration(migrations.Migration):

    dependencies = [('core', '0003_group_numeric_names')]

    operations = [
        migrations.AlterField(
            model_name='group',
            name='school_year',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='groups',
                to='core.schoolyear',
            ),
        ),
        # Nullable first so the reverse pass has somewhere to write before the
        # column goes back to NOT NULL.
        migrations.AlterField(
            model_name='group',
            name='school_class',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='groups',
                to='core.schoolclass',
            ),
        ),
        migrations.RunPython(
            migrations.RunPython.noop, restore_school_class,
        ),
        migrations.RemoveField(model_name='group', name='school_class'),
    ]
