from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models.deletion import ProtectedError
from django.db import models, transaction
from django.db.models.functions import Length

from .ordering import default_position

# Back-office defaults: how many groups a school year is split into, and
# the class list MFR Chatte runs each year. Both are only starting points — the admin
# "générer" actions let a superuser edit them before creating anything.
DEFAULT_GROUP_COUNT = 10
DEFAULT_CLASS_NAMES = [
    'Seconde',
    'Première',
    'Terminale',
    '4ème A',
    '4ème B',
    '3ème A',
    '3ème B',
    'CAP 1 CHARP BOIS + IS',
    'CAP 2 CHARP BOIS + IS',
    'CAP 1 MACON + IMTB',
    'CAP 2 MACON + IMTB',
    'BTS 1',
    'BTS 2',
]
# Label of the per-class chore created automatically with every class:
# "Classe 4ème A". Not part of DEFAULT_TASK_NAMES -- it is never entered by
# hand and never rotates through the school-wide pool.
CLEANING_TASK_PREFIX = 'Classe'
DEFAULT_TASK_NAMES = [
    'Vaisselle matin/soir',
    'Exterieur',
    'Salle B / Salle verte',
    'Foyer',
    'Ancien dortoir',
    'Salle Jobin',
    'Vaisselle midi',
    'Nouveau dortoir',
    'Refectoir midi',
    'Machine à boisson',
    'Véhicules',
    'Refectoir matin/soir',
]


class SchoolScopedQuerySet(models.QuerySet):
    """QuerySet filterable to the schools a user belongs to.

    `school_lookup` is the ORM path from the model to its School ('' when
    the model IS School); subclasses are generated per model via
    `school_scoped_manager`.
    """

    school_lookup = 'school'

    def for_user(self, user):
        if user.is_superuser:
            return self
        prefix = f'{self.school_lookup}__' if self.school_lookup else ''
        return self.filter(**{f'{prefix}memberships__user': user})


def school_scoped_manager(lookup):
    qs_class = type(
        'ScopedQuerySet', (SchoolScopedQuerySet,), {'school_lookup': lookup}
    )
    return qs_class.as_manager()


class School(models.Model):
    name = models.CharField(max_length=255, unique=True)

    objects = school_scoped_manager('')

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def school(self):
        # Uniform access to the owning school across all scoped models.
        return self

    def generate_tasks(self, names):
        """Create one Task per name for this school. Idempotent — an existing
        task keeps its assignments and its is_active flag. Creation order sets
        the rotation order (Task.Meta.ordering = ['id']).
        Returns (tasks, created)."""
        tasks, created = [], 0
        for name in names:
            task, was_created = Task.objects.get_or_create(
                school=self, name=name
            )
            tasks.append(task)
            created += was_created
        return tasks, created


class SchoolMembership(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='school_memberships',
    )
    school = models.ForeignKey(
        School, on_delete=models.CASCADE, related_name='memberships'
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'school'], name='unique_user_school'
            )
        ]

    def __str__(self):
        return f'{self.user} @ {self.school}'


class SchoolYear(models.Model):
    """A French school year (année scolaire), e.g. "2026-2027".

    Runs roughly September → June/July and spans two calendar years;
    start/end dates are free — never assume calendar-year alignment.
    """

    school = models.ForeignKey(
        School, on_delete=models.CASCADE, related_name='years'
    )
    name = models.CharField(max_length=50)
    start_date = models.DateField()
    end_date = models.DateField()

    objects = school_scoped_manager('school')

    class Meta:
        ordering = ['-start_date']
        constraints = [
            models.UniqueConstraint(
                fields=['school', 'name'], name='unique_year_per_school'
            )
        ]

    def __str__(self):
        return f'{self.school} {self.name}'

    def clean(self):
        if self.start_date and self.end_date and self.start_date >= self.end_date:
            raise ValidationError('start_date must be before end_date.')

    def generate_classes(self, names):
        """Create one SchoolClass per name for this year. Idempotent —
        an existing class keeps its enrollments. Returns (classes, created)."""
        classes, created = [], 0
        for name in names:
            school_class, was_created = SchoolClass.objects.get_or_create(
                school_year=self, name=name
            )
            classes.append(school_class)
            created += was_created
        return classes, created

    def generate_weeks(self):
        """Create one Week per ISO week (anchored on Monday) covering the
        year's date range. Idempotent."""
        monday = self.start_date - timedelta(days=self.start_date.weekday())
        weeks = []
        while monday <= self.end_date:
            week, _ = Week.objects.get_or_create(
                school_year=self, start_date=monday
            )
            weeks.append(week)
            monday += timedelta(days=7)
        return weeks

    def generate_groups(self, count=DEFAULT_GROUP_COUNT):
        """Create the groups numbered 1…count for this year. Idempotent —
        an existing group keeps its enrollments. Returns (groups, created)."""
        groups, created = [], 0
        for number in range(1, count + 1):
            group, was_created = Group.objects.get_or_create(
                school_year=self, name=str(number)
            )
            groups.append(group)
            created += was_created
        return groups, created

    def reset_groups(self, count=DEFAULT_GROUP_COUNT):
        """Drop every group of this year and recreate 1…count.

        For a year still carrying the per-class blocks groups had before they
        moved to the year (1…10 for the first class, 11…20 for the next):
        those numbers no longer mean anything, and re-running generate_groups
        would only add to them. Destructive and irreversible — deleting a
        group cascades to its assignments and clears `Enrollment.group`, so
        every student has to be put back in a group afterwards.

        Returns (groups, deleted).
        """
        with transaction.atomic():
            deleted = self.groups.count()
            self.groups.all().delete()
            groups, _ = self.generate_groups(count)
        return groups, deleted


class Week(models.Model):
    school_year = models.ForeignKey(
        SchoolYear, on_delete=models.CASCADE, related_name='weeks'
    )
    start_date = models.DateField()  # always a Monday

    objects = school_scoped_manager('school_year__school')

    class Meta:
        ordering = ['start_date']
        constraints = [
            models.UniqueConstraint(
                fields=['school_year', 'start_date'],
                name='unique_week_per_year',
            )
        ]

    def __str__(self):
        return self.label

    @property
    def label(self):
        cal = self.start_date.isocalendar()
        return f'{cal.year}-W{cal.week:02d}'

    @property
    def school(self):
        return self.school_year.school


class Student(models.Model):
    school = models.ForeignKey(
        School, on_delete=models.CASCADE, related_name='students'
    )
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    external_id = models.CharField(max_length=100, blank=True, default='')

    objects = school_scoped_manager('school')

    class Meta:
        ordering = ['last_name', 'first_name']
        constraints = [
            models.UniqueConstraint(
                fields=['school', 'external_id'],
                name='unique_external_id_per_school',
                condition=~models.Q(external_id=''),
            )
        ]

    def __str__(self):
        return f'{self.first_name} {self.last_name}'


class SchoolClass(models.Model):
    """A class for one school year: "4A" of 2026-2027 is a distinct row
    from "4A" of 2027-2028."""

    school_year = models.ForeignKey(
        SchoolYear, on_delete=models.CASCADE, related_name='classes'
    )
    name = models.CharField(max_length=100)
    position = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text=(
            "Ordre d'affichage. Laisser vide pour le déduire du nom "
            'de la classe (voir core/ordering.py).'
        ),
    )

    objects = school_scoped_manager('school_year__school')

    class Meta:
        ordering = ['position', 'name']
        verbose_name_plural = 'school classes'
        constraints = [
            models.UniqueConstraint(
                fields=['school_year', 'name'], name='unique_class_per_year'
            )
        ]

    def save(self, *args, **kwargs):
        if self.position is None:
            self.position = default_position(self.name)
        with transaction.atomic():
            super().save(*args, **kwargs)
            self.sync_cleaning_task()

    def sync_cleaning_task(self):
        """Create -- or rename, after the class is renamed -- the task for
        cleaning this class's own room. Idempotent."""
        task, _ = Task.objects.update_or_create(
            school_class=self,
            defaults={'school': self.school, 'name': self.cleaning_task_name},
        )
        return task

    @property
    def cleaning_task_name(self):
        return f'{CLEANING_TASK_PREFIX} {self.name}'

    def __str__(self):
        return f'{self.name} ({self.school_year.name})'

    @property
    def school(self):
        return self.school_year.school


class Group(models.Model):
    """A work group for one school year, named by a number unique within that
    year. Members come from any class — a group mixes a 4ème A with a BTS 1 —
    so "7" reads unambiguously wherever it appears (dashboards, PDFs,
    assignment lists) without a class beside it.
    """

    school_year = models.ForeignKey(
        SchoolYear, on_delete=models.CASCADE, related_name='groups'
    )
    name = models.CharField(max_length=150)

    objects = school_scoped_manager('school_year__school')

    class Meta:
        # Shortest name first so numbers sort 1, 2, … 10 rather than 1, 10, 2.
        ordering = [Length('name'), 'name']
        constraints = [
            models.UniqueConstraint(
                fields=['school_year', 'name'], name='unique_group_per_year'
            )
        ]

    def __str__(self):
        return f'{self.name} ({self.school_year.name})'

    @property
    def school(self):
        return self.school_year.school


class Enrollment(models.Model):
    """Ties a persistent Student to a per-year class and to a group of that
    year; the group is free of the class, so "one class per year" and "one
    group per year" are both DB-enforced by the same unique constraint."""

    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name='enrollments'
    )
    school_year = models.ForeignKey(
        SchoolYear, on_delete=models.CASCADE, related_name='enrollments'
    )
    school_class = models.ForeignKey(
        SchoolClass, on_delete=models.CASCADE, related_name='enrollments'
    )
    group = models.ForeignKey(
        Group,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='enrollments',
    )

    objects = school_scoped_manager('school_year__school')

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['student', 'school_year'],
                name='one_enrollment_per_year',
            )
        ]

    def __str__(self):
        return f'{self.student} in {self.school_class}'

    def clean(self):
        errors = {}
        if self.school_class_id and self.school_year_id:
            if self.school_class.school_year_id != self.school_year_id:
                errors['school_class'] = (
                    'Class does not belong to this school year.'
                )
        if self.group_id and self.school_year_id:
            if self.group.school_year_id != self.school_year_id:
                errors['group'] = 'Group does not belong to this school year.'
        if self.student_id and self.school_year_id:
            if self.student.school_id != self.school_year.school_id:
                errors['student'] = (
                    'Student does not belong to this school.'
                )
        if errors:
            raise ValidationError(errors)


class Task(models.Model):
    """A chore. Two kinds share this table:

    - school-wide tasks (`school_class` empty): the rotating pool any group
      can be handed -- Vaisselle, Foyer, Extérieur...
    - class tasks (`school_class` set): cleaning a class's own room. One is
      created and renamed automatically with the class (see
      SchoolClass.save); it is never entered by hand, and only a group with
      members in that class can be given it.

    Names are unique per school for the rotating pool only. A class task
    carries the class name, and a class name repeats across school years, so
    "Classe 4ème A" legitimately exists once per year.
    """

    school = models.ForeignKey(
        School, on_delete=models.CASCADE, related_name='tasks'
    )
    school_class = models.ForeignKey(
        SchoolClass,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='cleaning_task',
        help_text=(
            'Renseigné uniquement pour le ménage de la salle de cette '
            'classe. Géré automatiquement avec la classe.'
        ),
    )
    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)

    objects = school_scoped_manager('school')

    class Meta:
        ordering = ['id']  # deterministic rotation order
        constraints = [
            models.UniqueConstraint(
                fields=['school', 'name'],
                name='unique_task_per_school',
                condition=models.Q(school_class__isnull=True),
            ),
            models.UniqueConstraint(
                fields=['school_class'], name='one_cleaning_task_per_class'
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def is_class_task(self):
        return self.school_class_id is not None

    def clean(self):
        if self.school_class_id and self.school_id:
            if self.school_class.school_year.school_id != self.school_id:
                raise ValidationError(
                    {'school_class': 'Class belongs to another school.'}
                )


class ClassPresence(models.Model):
    """Marks a class as present on-site for a given week."""

    week = models.ForeignKey(
        Week, on_delete=models.CASCADE, related_name='presences'
    )
    school_class = models.ForeignKey(
        SchoolClass, on_delete=models.CASCADE, related_name='presences'
    )

    objects = school_scoped_manager('week__school_year__school')

    class Meta:
        verbose_name_plural = 'class presences'
        constraints = [
            models.UniqueConstraint(
                fields=['week', 'school_class'], name='unique_presence'
            )
        ]

    def __str__(self):
        return f'{self.school_class} @ {self.week}'

    def clean(self):
        if self.week_id and self.school_class_id:
            if self.week.school_year_id != self.school_class.school_year_id:
                raise ValidationError(
                    {'school_class': 'Class and week belong to different school years.'}
                )


def protect_unless_class_task(collector, field, sub_objs, using):
    """on_delete for Assignment.task.

    A chore that has already been handed out is never deleted by accident:
    the history behind the fairness matrix would go with it. PROTECT.

    A class's cleaning task is the exception. It is not a chore someone
    typed, it is the class itself: it appears with the class and has to be
    able to leave with it, the way that class's enrollments and presences
    do. Without this, deleting a class -- or its school year, or the whole
    school -- would fail on a task nobody ever created by hand.
    """
    class_task_ids = set(
        Task.objects.filter(
            pk__in={assignment.task_id for assignment in sub_objs},
            school_class__isnull=False,
        ).values_list('pk', flat=True)
    )
    protected = [
        assignment for assignment in sub_objs
        if assignment.task_id not in class_task_ids
    ]
    if protected:
        raise ProtectedError(
            "Cannot delete some instances of model 'Task' because they are "
            "referenced through a protected foreign key: 'Assignment.task'",
            protected,
        )
    models.CASCADE(collector, field, sub_objs, using)


class Assignment(models.Model):
    week = models.ForeignKey(
        Week, on_delete=models.CASCADE, related_name='assignments'
    )
    task = models.ForeignKey(
        Task, on_delete=protect_unless_class_task, related_name='assignments'
    )
    group = models.ForeignKey(
        Group, on_delete=models.CASCADE, related_name='assignments'
    )
    is_manual = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = school_scoped_manager('week__school_year__school')

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['week', 'task'], name='one_group_per_task_per_week'
            ),
            models.UniqueConstraint(
                fields=['week', 'group'], name='one_task_per_group_per_week'
            ),
        ]
        indexes = [models.Index(fields=['group', 'task'])]

    def __str__(self):
        return f'{self.group} → {self.task} ({self.week})'

    def clean(self):
        errors = {}
        if self.week_id and self.group_id:
            members = Enrollment.objects.filter(
                group_id=self.group_id,
                school_class__presences__week_id=self.week_id,
            )
            # Cleaning a class's room is done by that class's own students:
            # a member on site with another class is no help here.
            class_id = self.task.school_class_id if self.task_id else None
            if class_id:
                members = members.filter(school_class_id=class_id)
            if not members.exists():
                errors['group'] = (
                    'No member of this group is present this week.'
                    if not class_id else
                    'No member of this group attends this class this week.'
                )
        if self.week_id and self.task_id:
            if self.task.school_id != self.week.school_year.school_id:
                errors['task'] = 'Task belongs to another school.'
        if errors:
            raise ValidationError(errors)
