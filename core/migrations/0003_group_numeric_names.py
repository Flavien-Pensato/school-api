"""Groups are numbered across the school year instead of per class.

"4ème A - Groupe 1" becomes "1", the next class's groups continue at 11, and
so on. Renaming happens in two passes (temporary names first) so the
unique-per-year constraint holds even when a digit name is already taken.
"""

from django.db import migrations
from django.db.models.functions import Length


def _in_generation_order(Group):
    return Group.objects.select_related('school_class').order_by(
        'school_class__school_year_id', 'school_class_id', 'pk'
    )


def _stage_temporary_names(Group):
    for group in _in_generation_order(Group).iterator():
        group.name = f'tmp-{group.pk}'
        group.save(update_fields=['name'])


def number_groups_across_year(apps, schema_editor):
    Group = apps.get_model('core', 'Group')
    ordered = list(_in_generation_order(Group))
    _stage_temporary_names(Group)

    next_number = {}
    for group in ordered:
        year_id = group.school_class.school_year_id
        number = next_number.get(year_id, 1)
        next_number[year_id] = number + 1
        group.name = str(number)
        group.save(update_fields=['name'])


def name_groups_per_class(apps, schema_editor):
    Group = apps.get_model('core', 'Group')
    ordered = list(_in_generation_order(Group))
    _stage_temporary_names(Group)

    next_number = {}
    for group in ordered:
        class_id = group.school_class_id
        number = next_number.get(class_id, 1)
        next_number[class_id] = number + 1
        group.name = f'{group.school_class.name} - Groupe {number}'[:150]
        group.save(update_fields=['name'])


class Migration(migrations.Migration):

    dependencies = [('core', '0002_group_unique_name_per_year')]

    operations = [
        migrations.AlterModelOptions(
            name='group',
            options={'ordering': [Length('name'), 'name']},
        ),
        migrations.RunPython(
            number_groups_across_year, name_groups_per_class,
        ),
    ]
