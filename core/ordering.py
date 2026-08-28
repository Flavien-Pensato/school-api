"""Display order for school classes.

Class names are not sortable on their own: "Seconde" comes before "Première"
which comes before "Terminale", and the CAP variants only differ by their
speciality. The curriculum sequence therefore lives here, and every class gets
a ``position`` from it when it is created (see ``SchoolClass.save``).

Positions are plain integers on the row, so an admin can always override the
sequence for one school year without touching this file.
"""

import re
import unicodedata

#: The curriculum sequence, from the first class shown to the last. Each entry
#: lists every spelling of one level: the name DEFAULT_CLASS_NAMES creates
#: first, then the shorthands people type by hand. Matching ignores case,
#: accents and spacing, so only real wording differences need an alias.
CLASS_SEQUENCE = [
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

#: Gap between two consecutive levels, so a class can be slipped in between
#: without renumbering the whole year.
POSITION_STEP = 10


def sequence_key(name):
    """Collapse a class name to a spacing- and accent-insensitive key.

    "4 ème A", "4ème A" and "4EME  a" all collapse to "4emea", so the
    sequence above matches however the name was typed.
    """
    text = unicodedata.normalize('NFKD', '' if name is None else str(name))
    text = ''.join(char for char in text if not unicodedata.combining(char))
    return ''.join(re.split(r'[^a-z0-9]+', text.lower()))


_SEQUENCE_POSITIONS = {
    sequence_key(alias): (index + 1) * POSITION_STEP
    for index, aliases in enumerate(CLASS_SEQUENCE)
    for alias in aliases
}

#: Where a name absent from CLASS_SEQUENCE lands.
UNKNOWN_POSITION = (len(CLASS_SEQUENCE) + 1) * POSITION_STEP


def default_position(name):
    """Position for a class name, used when none was given explicitly.

    A name outside CLASS_SEQUENCE falls back to UNKNOWN_POSITION, which puts
    it after every known level; such classes are then ordered by name between
    themselves (see SchoolClass.Meta.ordering).
    """
    return _SEQUENCE_POSITIONS.get(sequence_key(name), UNKNOWN_POSITION)
