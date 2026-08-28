"""Shared test fixtures — plain objects.create, no factory library."""

from datetime import date

from django.contrib.auth import get_user_model

from core.models import (
    ClassPresence,
    Enrollment,
    Group,
    School,
    SchoolClass,
    SchoolMembership,
    SchoolYear,
    Student,
    Task,
)

User = get_user_model()

# Admin templates load static assets; the prod manifest storage needs a
# collectstatic run, which tests must not depend on. Use with
# @override_settings(STORAGES=ADMIN_STORAGES) on any admin TestCase.
ADMIN_STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {
        'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'
    },
}


def make_user(username='staff', school=None, **kwargs):
    user = User.objects.create_user(username=username, **kwargs)
    if school is not None:
        SchoolMembership.objects.create(user=user, school=school)
    return user


def make_school(name='MFR Test'):
    return School.objects.create(name=name)


def make_year(school, name='2026-2027',
              start=date(2026, 9, 7), end=date(2027, 6, 25),
              with_weeks=True):
    year = SchoolYear.objects.create(
        school=school, name=name, start_date=start, end_date=end
    )
    if with_weeks:
        year.generate_weeks()
    return year


def make_class(year, name='4A'):
    return SchoolClass.objects.create(school_year=year, name=name)


def make_group(year, name=None, classes=()):
    """A group of the year. `classes` enrolls one throwaway student per class:
    a group is only on duty for a week when a member's class is present."""
    group = Group.objects.create(school_year=year, name=name or '1')
    for school_class in classes:
        Enrollment.objects.create(
            student=make_student(
                year.school, 'Membre', f'{group.name}-{school_class.name}'
            ),
            school_year=year,
            school_class=school_class,
            group=group,
        )
    return group


def make_student(school, first_name='Jean', last_name='Dupont', **kwargs):
    return Student.objects.create(
        school=school, first_name=first_name, last_name=last_name, **kwargs
    )


def make_task(school, name='Vaisselle', **kwargs):
    return Task.objects.create(school=school, name=name, **kwargs)


def make_presence(week, school_class):
    return ClassPresence.objects.create(week=week, school_class=school_class)
