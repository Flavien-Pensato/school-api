"""Business logic spanning multiple models: student import, rotation."""

import csv
import io
from collections import Counter
from datetime import date

from django.db import transaction

from .models import Assignment, ClassPresence, Enrollment, Group, Student, Task

# Accepted column headers (case-insensitive), French and English.
# Adjust to match real school-software exports.
HEADER_ALIASES = {
    'first_name': {'first_name', 'prénom', 'prenom'},
    'last_name': {'last_name', 'nom'},
    'external_id': {'external_id', 'identifiant', 'id'},
}
REQUIRED_FIELDS = ('first_name', 'last_name')


class ImportError_(Exception):
    """Import failed; `errors` is a list of {"row": n, "errors": [...]}
    or {"errors": [...]} for file-level problems."""

    def __init__(self, errors):
        self.errors = errors
        super().__init__(str(errors))


def _map_headers(raw_headers):
    """Map file headers to model fields. Returns {field: column_index}."""
    mapping = {}
    for index, raw in enumerate(raw_headers):
        name = (raw or '').strip().lower()
        for field, aliases in HEADER_ALIASES.items():
            if name in aliases and field not in mapping:
                mapping[field] = index
    missing = [f for f in REQUIRED_FIELDS if f not in mapping]
    if missing:
        raise ImportError_([{
            'errors': [
                f'Missing required column(s): {", ".join(missing)}. '
                f'Accepted headers: '
                + '; '.join(
                    f'{field}: {sorted(aliases)}'
                    for field, aliases in HEADER_ALIASES.items()
                )
            ]
        }])
    return mapping


def _rows_from_csv(file):
    text = io.TextIOWrapper(file, encoding='utf-8-sig')
    sample = text.read(4096)
    text.seek(0)
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=';,\t')
    except csv.Error:
        dialect = csv.excel  # comma fallback
    return list(csv.reader(text, dialect))


def _rows_from_xlsx(file):
    from openpyxl import load_workbook

    workbook = load_workbook(file, read_only=True, data_only=True)
    sheet = workbook.worksheets[0]
    return [
        ['' if cell is None else str(cell) for cell in row]
        for row in sheet.iter_rows(values_only=True)
    ]


def parse_student_file(file, filename):
    """Returns list of {'first_name', 'last_name', 'external_id'} dicts.
    Raises ImportError_ with row-level errors — nothing is written."""
    lowered = filename.lower()
    if lowered.endswith('.csv'):
        rows = _rows_from_csv(file)
    elif lowered.endswith('.xlsx'):
        rows = _rows_from_xlsx(file)
    else:
        raise ImportError_([{'errors': ['Unsupported file type; use .csv or .xlsx.']}])

    rows = [row for row in rows if any((cell or '').strip() for cell in row)]
    if not rows:
        raise ImportError_([{'errors': ['File is empty.']}])

    mapping = _map_headers(rows[0])
    students, errors = [], []
    for line_number, row in enumerate(rows[1:], start=2):
        def cell(field):
            index = mapping.get(field)
            if index is None or index >= len(row):
                return ''
            return (row[index] or '').strip()

        record = {field: cell(field) for field in HEADER_ALIASES}
        row_errors = [
            f'{field} missing' for field in REQUIRED_FIELDS if not record[field]
        ]
        if row_errors:
            errors.append({'row': line_number, 'errors': row_errors})
        else:
            students.append(record)
    if errors:
        raise ImportError_(errors)
    return students


@transaction.atomic
def import_students(school_class, records):
    """Create/reuse students and enroll them in `school_class`.

    Matching rule: by external_id when present, else by case-insensitive
    (school, first_name, last_name). A student already enrolled in a
    DIFFERENT class this year is a row error — moving requires an explicit
    PATCH on the enrollment, never a silent reassign. All-or-nothing.
    """
    school = school_class.school_year.school
    year = school_class.school_year
    counts = {
        'created_students': 0,
        'reused_students': 0,
        'enrollments_created': 0,
        'already_enrolled': 0,
    }
    errors = []

    for line_number, record in enumerate(records, start=2):
        student = None
        if record['external_id']:
            student = Student.objects.filter(
                school=school, external_id=record['external_id']
            ).first()
        if student is None:
            student = Student.objects.filter(
                school=school,
                first_name__iexact=record['first_name'],
                last_name__iexact=record['last_name'],
            ).first()

        if student is None:
            student = Student.objects.create(
                school=school,
                first_name=record['first_name'],
                last_name=record['last_name'],
                external_id=record['external_id'],
            )
            counts['created_students'] += 1
        else:
            counts['reused_students'] += 1

        enrollment = student.enrollments.filter(school_year=year).first()
        if enrollment is None:
            Enrollment.objects.create(
                student=student, school_year=year, school_class=school_class
            )
            counts['enrollments_created'] += 1
        elif enrollment.school_class_id == school_class.pk:
            counts['already_enrolled'] += 1
        else:
            errors.append({
                'row': line_number,
                'errors': [
                    f'{student} already enrolled in '
                    f'{enrollment.school_class.name} this year; '
                    'move via the enrollments API.'
                ],
            })

    if errors:
        raise ImportError_(errors)  # rolls back the transaction
    return counts


def _min_cost_matching(groups, tasks, pair):
    """Assign each task to a distinct group minimizing the total of
    pair[(group.pk, task.pk)] — i.e. as few repeated (group, task) pairs
    as possible. Exact DP over a bitmask of groups; sizes are small because
    the working pool is already trimmed to len(tasks).

    Deterministic: cost ties are broken by task order (pk) then lowest
    group pk. If there are fewer groups than tasks, the leftover tasks stay
    unassigned. Returns [(group, task)].
    """
    skips_allowed = max(0, len(tasks) - len(groups))
    memo = {}

    def solve(task_index, used_mask, skips):
        if task_index == len(tasks):
            return (0, (), ())
        key = (task_index, used_mask, skips)
        if key in memo:
            return memo[key]
        task = tasks[task_index]
        best = None
        for bit, group in enumerate(groups):
            if used_mask & (1 << bit):
                continue
            cost, pks, picks = solve(task_index + 1, used_mask | (1 << bit), skips)
            candidate = (
                cost + pair[(group.pk, task.pk)],
                (group.pk,) + pks,
                ((group, task),) + picks,
            )
            if best is None or candidate[:2] < best[:2]:
                best = candidate
        if skips < skips_allowed:
            cost, pks, picks = solve(task_index + 1, used_mask, skips + 1)
            candidate = (cost, (float('inf'),) + pks, picks)
            if best is None or candidate[:2] < best[:2]:
                best = candidate
        memo[key] = best
        return best

    return list(solve(0, 0, 0)[2])


@transaction.atomic
def generate_week_assignments(week):
    """Auto-assign each active task to one eligible group for `week`.

    Eligible groups: groups whose class has a ClassPresence for this week.
    Manual assignments (is_manual=True) are preserved; their task and group
    are removed from the pools. Previous auto assignments for this week are
    replaced — re-running is idempotent.

    Fairness, over prior weeks of the same school year:
    - Phase 1 (rest fairness): if more groups than tasks, the groups with
      the fewest total assignments work first (tie: rested longest, then pk).
    - Phase 2 (pair fairness): greedy min-cost matching on how often each
      (group, task) pair already happened (tie: task pk, then group pk).

    Returns {"assignments": [Assignment], "explanation": [str]}.
    """
    school = week.school_year.school

    manual = list(
        week.assignments.filter(is_manual=True).select_related('task', 'group')
    )
    manual_task_ids = {a.task_id for a in manual}
    manual_group_ids = {a.group_id for a in manual}

    tasks = [
        t for t in Task.objects.filter(school=school, is_active=True)
        .order_by('pk')
        if t.pk not in manual_task_ids
    ]
    present_class_ids = ClassPresence.objects.filter(week=week).values_list(
        'school_class_id', flat=True
    )
    groups = [
        g for g in Group.objects.filter(school_class_id__in=present_class_ids)
        .order_by('pk')
        if g.pk not in manual_group_ids
    ]

    # History: prior weeks of the same school year (manual rows count too —
    # a group that worked, worked).
    history = Assignment.objects.filter(
        week__school_year=week.school_year,
        week__start_date__lt=week.start_date,
    ).values_list('group_id', 'task_id', 'week__start_date')
    total = Counter()
    pair = Counter()
    last_assigned = {}
    for group_id, task_id, week_start in history:
        total[group_id] += 1
        pair[(group_id, task_id)] += 1
        if group_id not in last_assigned or week_start > last_assigned[group_id]:
            last_assigned[group_id] = week_start

    explanation = [
        f'{a.group.name} → {a.task.name}: manual assignment (kept)'
        for a in manual
    ]

    # Phase 1 — who works this week (rest fairness).
    working = sorted(
        groups,
        key=lambda g: (total[g.pk], last_assigned.get(g.pk, date.min), g.pk),
    )[: len(tasks)]
    for group in groups:
        if group not in working:
            explanation.append(
                f'{group.name} rests this week '
                f'({total[group.pk]} assignments so far — highest)'
            )

    # Phase 2 — who does what (pair fairness): exact min-cost matching.
    # Greedy is not enough — the last free slot can force a repeated pair
    # while a different arrangement avoids all repeats.
    picks = _min_cost_matching(working, tasks, pair)
    assigned_task_ids = set()
    for group, task in picks:
        assigned_task_ids.add(task.pk)
        explanation.append(
            f'{group.name} → {task.name}: done {pair[(group.pk, task.pk)]}× '
            'before (minimizes repeats this week)'
        )
    for task in tasks:
        if task.pk not in assigned_task_ids:
            explanation.append(f'{task.name}: unassigned (no group available)')

    week.assignments.filter(is_manual=False).delete()
    created = Assignment.objects.bulk_create(
        Assignment(week=week, task=task, group=group, is_manual=False)
        for group, task in picks
    )
    return {'assignments': manual + created, 'explanation': explanation}


def build_week_dashboard(week):
    """Nested view of a week: present classes → groups → students + task.
    Shared by the JSON dashboard endpoint and the printable PDF."""
    assignments = {
        a.group_id: a
        for a in week.assignments.select_related('task')
    }
    present_classes = [
        p.school_class
        for p in week.presences.select_related('school_class')
        .order_by('school_class__name')
    ]
    classes = []
    for school_class in present_classes:
        groups = []
        for group in school_class.groups.prefetch_related(
            'enrollments__student'
        ).order_by('name'):
            assignment = assignments.get(group.pk)
            groups.append({
                'id': group.pk,
                'name': group.name,
                'students': [
                    {
                        'id': e.student.pk,
                        'first_name': e.student.first_name,
                        'last_name': e.student.last_name,
                    }
                    for e in sorted(
                        group.enrollments.all(),
                        key=lambda e: (e.student.last_name, e.student.first_name),
                    )
                ],
                'task': (
                    {'id': assignment.task.pk, 'name': assignment.task.name}
                    if assignment else None
                ),
            })
        classes.append({
            'id': school_class.pk,
            'name': school_class.name,
            'groups': groups,
        })
    return {
        'week': {
            'id': week.pk,
            'start_date': week.start_date.isoformat(),
            'label': week.label,
        },
        'school': {'id': week.school.pk, 'name': week.school.name},
        'classes': classes,
    }


def build_year_stats(school_year):
    """Per-group fairness matrix for a school year: how often each group
    did each task, plus totals and rest counts."""
    task_names = dict(
        Task.objects.filter(school=school_year.school).values_list('pk', 'name')
    )
    presence_weeks = Counter()  # group_id -> weeks its class was present
    group_rows = {}
    groups = (
        Group.objects.filter(school_class__school_year=school_year)
        .select_related('school_class')
        .order_by('school_class__name', 'name')
    )
    for group in groups:
        group_rows[group.pk] = {
            'group': {'id': group.pk, 'name': group.name},
            'school_class': group.school_class.name,
            'totals': {},
            'total': 0,
            'weeks_present': 0,
            'weeks_rested': 0,
        }
    class_presences = Counter(
        ClassPresence.objects.filter(
            week__school_year=school_year
        ).values_list('school_class_id', flat=True)
    )
    for group in groups:
        group_rows[group.pk]['weeks_present'] = class_presences[
            group.school_class_id
        ]
    for group_id, task_id in Assignment.objects.filter(
        week__school_year=school_year
    ).values_list('group_id', 'task_id'):
        row = group_rows.get(group_id)
        if row is None:
            continue
        name = task_names.get(task_id, str(task_id))
        row['totals'][name] = row['totals'].get(name, 0) + 1
        row['total'] += 1
    for row in group_rows.values():
        row['weeks_rested'] = row['weeks_present'] - row['total']
    return {
        'school_year': {'id': school_year.pk, 'name': school_year.name},
        'groups': list(group_rows.values()),
    }
