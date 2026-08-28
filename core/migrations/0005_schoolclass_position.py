"""School classes are ordered by curriculum level instead of by name.

Alphabetical order put "BTS 1" before "Seconde" and split the CAP levels
apart. Classes now carry a ``position``, filled from the curriculum sequence
in ``core.ordering`` when the class is created.

The sequence is frozen below rather than imported: editing
``core.ordering.CLASS_SEQUENCE`` later must not silently change what this
backfill produced on databases that already ran it.
"""

import re
import unicodedata

from django.db import migrations, models

FROZEN_SEQUENCE = [
    ['4ème A'],
    ['4ème B'],
    ['3ème A'],
    ['3ème B'],
    ['Seconde', '2nde'],
    ['Première', '1ère'],
    ['Terminale', 'Term'],
    ['BTS 1'],
    ['BTS 2'],
    ['CAP 1 MACON + IMTB', 'CAP 1 maç + IMTB'],
    ['CAP 1 CHARP BOIS + IS', 'CAP 1 MIS + Charp'],
    ['CAP 2 MACON + IMTB', 'CAP 2 maç + IMTB'],
    ['CAP 2 CHARP BOIS + IS', 'CAP 2 MIS + Charp'],
]
POSITION_STEP = 10
UNKNOWN_POSITION = (len(FROZEN_SEQUENCE) + 1) * POSITION_STEP


def _key(name):
    text = unicodedata.normalize('NFKD', '' if name is None else str(name))
    text = ''.join(char for char in text if not unicodedata.combining(char))
    return ''.join(re.split(r'[^a-z0-9]+', text.lower()))


_POSITIONS = {
    _key(alias): (index + 1) * POSITION_STEP
    for index, aliases in enumerate(FROZEN_SEQUENCE)
    for alias in aliases
}


def fill_positions(apps, schema_editor):
    SchoolClass = apps.get_model('core', 'SchoolClass')
    for school_class in SchoolClass.objects.filter(position=None).iterator():
        school_class.position = _POSITIONS.get(
            _key(school_class.name), UNKNOWN_POSITION
        )
        school_class.save(update_fields=['position'])


def clear_positions(apps, schema_editor):
    SchoolClass = apps.get_model('core', 'SchoolClass')
    SchoolClass.objects.update(position=None)


class Migration(migrations.Migration):

    dependencies = [('core', '0004_group_belongs_to_year')]

    operations = [
        migrations.AlterModelOptions(
            name='schoolclass',
            options={
                'ordering': ['position', 'name'],
                'verbose_name_plural': 'school classes',
            },
        ),
        migrations.AddField(
            model_name='schoolclass',
            name='position',
            field=models.PositiveIntegerField(
                blank=True,
                null=True,
                help_text=(
                    "Ordre d'affichage. Laisser vide pour le déduire du nom "
                    'de la classe (voir core/ordering.py).'
                ),
            ),
        ),
        migrations.RunPython(fill_positions, clear_positions),
    ]
