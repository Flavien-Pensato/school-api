"""Re-label every class task from the current prefix.

The label is cosmetic — it is what staff read on the planning and the PDF —
so it is allowed to change, and a class task is only renamed when its class
is saved. This lines up the rows already in the database.
"""

from django.db import migrations

CLEANING_TASK_PREFIX = 'Classe'


def resync_names(apps, schema_editor):
    Task = apps.get_model('core', 'Task')
    for task in Task.objects.filter(
        school_class__isnull=False
    ).select_related('school_class'):
        name = f'{CLEANING_TASK_PREFIX} {task.school_class.name}'
        if task.name != name:
            task.name = name
            task.save(update_fields=['name'])


class Migration(migrations.Migration):
    dependencies = [('core', '0008_alter_assignment_task')]

    operations = [
        migrations.RunPython(resync_names, migrations.RunPython.noop),
    ]
