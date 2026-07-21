from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


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

    objects = school_scoped_manager('school_year__school')

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'school classes'
        constraints = [
            models.UniqueConstraint(
                fields=['school_year', 'name'], name='unique_class_per_year'
            )
        ]

    def __str__(self):
        return f'{self.name} ({self.school_year.name})'

    @property
    def school(self):
        return self.school_year.school


class Group(models.Model):
    school_class = models.ForeignKey(
        SchoolClass, on_delete=models.CASCADE, related_name='groups'
    )
    name = models.CharField(max_length=100)

    objects = school_scoped_manager('school_class__school_year__school')

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['school_class', 'name'], name='unique_group_per_class'
            )
        ]

    def __str__(self):
        return f'{self.name} — {self.school_class}'

    @property
    def school(self):
        return self.school_class.school_year.school


class Enrollment(models.Model):
    """Ties a persistent Student to a per-year class; group membership lives
    here so "one class per year" and "one group per year" are both
    DB-enforced by the same unique constraint."""

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
        if self.group_id and self.school_class_id:
            if self.group.school_class_id != self.school_class_id:
                errors['group'] = 'Group does not belong to this class.'
        if self.student_id and self.school_year_id:
            if self.student.school_id != self.school_year.school_id:
                errors['student'] = (
                    'Student does not belong to this school.'
                )
        if errors:
            raise ValidationError(errors)


class Task(models.Model):
    school = models.ForeignKey(
        School, on_delete=models.CASCADE, related_name='tasks'
    )
    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)

    objects = school_scoped_manager('school')

    class Meta:
        ordering = ['id']  # deterministic rotation order
        constraints = [
            models.UniqueConstraint(
                fields=['school', 'name'], name='unique_task_per_school'
            )
        ]

    def __str__(self):
        return self.name


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


class Assignment(models.Model):
    week = models.ForeignKey(
        Week, on_delete=models.CASCADE, related_name='assignments'
    )
    task = models.ForeignKey(
        Task, on_delete=models.PROTECT, related_name='assignments'
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
            present = ClassPresence.objects.filter(
                week_id=self.week_id,
                school_class_id=self.group.school_class_id,
            ).exists()
            if not present:
                errors['group'] = (
                    "Group's class is not present this week."
                )
        if self.week_id and self.task_id:
            if self.task.school_id != self.week.school_year.school_id:
                errors['task'] = 'Task belongs to another school.'
        if errors:
            raise ValidationError(errors)
