"""Backfill the per-class cleaning task for classes that already exist.

Every class gets one "Classe <classe>" task from now on (SchoolClass.save),
but classes created before that need one too -- the rotation looks the task
up by class and would silently skip any class without one.
"""

from django.db import migrations

CLEANING_TASK_PREFIX = 'Classe'


def create_cleaning_tasks(apps, schema_editor):
    SchoolClass = apps.get_model('core', 'SchoolClass')
    Task = apps.get_model('core', 'Task')
    for school_class in SchoolClass.objects.select_related(
        'school_year'
    ).iterator():
        Task.objects.update_or_create(
            school_class=school_class,
            defaults={
                'school_id': school_class.school_year.school_id,
                'name': f'{CLEANING_TASK_PREFIX} {school_class.name}',
            },
        )


def drop_cleaning_tasks(apps, schema_editor):
    Task = apps.get_model('core', 'Task')
    Task.objects.filter(school_class__isnull=False).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0006_remove_task_unique_task_per_school_task_school_class_and_more'),
    ]

    operations = [
        migrations.RunPython(create_cleaning_tasks, drop_cleaning_tasks),
    ]
