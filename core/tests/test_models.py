from datetime import date

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models.deletion import ProtectedError
from django.test import TestCase

from core.models import (
    Assignment,
    DEFAULT_CLASS_NAMES,
    Enrollment,
    Group,
    SchoolClass,
    Student,
    Task,
    Week,
)

from core.services import generate_week_assignments

from .factories import (
    make_class,
    make_group,
    make_presence,
    make_school,
    make_student,
    make_task,
    make_user,
    make_year,
)


class GenerateWeeksTests(TestCase):
    def test_weeks_span_year_boundary(self):
        school = make_school()
        # Sept 2026 → June 2027 crosses Dec–Jan; ISO week numbers restart.
        year = make_year(school, start=date(2026, 9, 7), end=date(2027, 6, 25))
        weeks = year.weeks.order_by('start_date')
        self.assertEqual(weeks.first().start_date, date(2026, 9, 7))
        # last generated Monday must be <= end_date
        self.assertLessEqual(weeks.last().start_date, date(2027, 6, 25))
        # all Mondays, contiguous
        starts = list(weeks.values_list('start_date', flat=True))
        self.assertTrue(all(d.weekday() == 0 for d in starts))
        self.assertEqual(
            {(b - a).days for a, b in zip(starts, starts[1:])}, {7}
        )
        # Dec–Jan boundary covered
        self.assertTrue(any(d.year == 2026 for d in starts))
        self.assertTrue(any(d.year == 2027 for d in starts))

    def test_generate_weeks_idempotent(self):
        school = make_school()
        year = make_year(school)
        count = year.weeks.count()
        year.generate_weeks()
        self.assertEqual(year.weeks.count(), count)

    def test_start_mid_week_anchors_to_monday(self):
        school = make_school()
        # Sept 9, 2026 is a Wednesday
        year = make_year(school, start=date(2026, 9, 9), end=date(2026, 10, 1))
        self.assertEqual(
            year.weeks.order_by('start_date').first().start_date,
            date(2026, 9, 7),
        )


class ConstraintTests(TestCase):
    def setUp(self):
        self.school = make_school()
        self.year = make_year(self.school, with_weeks=False)

    def test_duplicate_year_name_per_school(self):
        with self.assertRaises(IntegrityError):
            make_year(self.school, with_weeks=False)

    def test_duplicate_external_id_per_school(self):
        make_student(self.school, external_id='X1')
        with self.assertRaises(IntegrityError):
            make_student(self.school, first_name='Autre', external_id='X1')

    def test_blank_external_id_not_unique(self):
        make_student(self.school)
        make_student(self.school, first_name='Autre')  # no raise
        self.assertEqual(Student.objects.count(), 2)

    def test_one_enrollment_per_student_per_year(self):
        cls = make_class(self.year)
        student = make_student(self.school)
        Enrollment.objects.create(
            student=student, school_year=self.year, school_class=cls
        )
        cls2 = make_class(self.year, name='4B')
        with self.assertRaises(IntegrityError):
            Enrollment.objects.create(
                student=student, school_year=self.year, school_class=cls2
            )


class CleanValidationTests(TestCase):
    def setUp(self):
        self.school = make_school()
        self.other_school = make_school('MFR Autre')
        self.year = make_year(self.school)
        self.week = self.year.weeks.first()
        self.cls = make_class(self.year)
        self.group = make_group(self.year, classes=[self.cls])

    def test_enrollment_class_must_match_year(self):
        other_year = make_year(
            self.school, name='2027-2028',
            start=date(2027, 9, 6), end=date(2028, 6, 23), with_weeks=False,
        )
        student = make_student(self.school)
        enrollment = Enrollment(
            student=student, school_year=other_year, school_class=self.cls
        )
        with self.assertRaises(ValidationError):
            enrollment.full_clean()

    def test_enrollment_group_may_come_from_another_class(self):
        cls2 = make_class(self.year, name='4B')
        student = make_student(self.school)
        enrollment = Enrollment(
            student=student, school_year=self.year,
            school_class=cls2, group=self.group,
        )
        enrollment.full_clean()  # no raise

    def test_enrollment_group_must_match_year(self):
        other_year = make_year(
            self.school, name='2027-2028',
            start=date(2027, 9, 6), end=date(2028, 6, 23), with_weeks=False,
        )
        student = make_student(self.school)
        enrollment = Enrollment(
            student=student, school_year=other_year,
            school_class=make_class(other_year), group=self.group,
        )
        with self.assertRaises(ValidationError):
            enrollment.full_clean()

    def test_enrollment_student_must_belong_to_school(self):
        student = make_student(self.other_school)
        enrollment = Enrollment(
            student=student, school_year=self.year, school_class=self.cls
        )
        with self.assertRaises(ValidationError):
            enrollment.full_clean()

    def test_assignment_requires_presence(self):
        task = make_task(self.school)
        assignment = Assignment(week=self.week, task=task, group=self.group)
        with self.assertRaises(ValidationError):
            assignment.full_clean()
        make_presence(self.week, self.cls)
        assignment.full_clean()  # no raise

    def test_assignment_task_must_belong_to_school(self):
        make_presence(self.week, self.cls)
        foreign_task = make_task(self.other_school)
        assignment = Assignment(
            week=self.week, task=foreign_task, group=self.group
        )
        with self.assertRaises(ValidationError):
            assignment.full_clean()


class ScopedQuerySetTests(TestCase):
    def setUp(self):
        self.school_a = make_school('MFR A')
        self.school_b = make_school('MFR B')
        self.user_a = make_user('staff-a', school=self.school_a)
        self.superuser = make_user('root')
        self.superuser.is_superuser = True
        self.superuser.save()
        self.year_a = make_year(self.school_a)
        self.year_b = make_year(self.school_b)

    def test_member_sees_own_school_only(self):
        self.assertEqual(
            list(Week.objects.for_user(self.user_a).order_by().values_list(
                'school_year', flat=True).distinct()),
            [self.year_a.pk],
        )

    def test_superuser_sees_all(self):
        self.assertEqual(
            Week.objects.for_user(self.superuser).count(),
            Week.objects.count(),
        )

    def test_deep_lookup_group(self):
        from core.models import Group
        group_a = make_group(self.year_a)
        make_group(self.year_b)
        self.assertEqual(
            list(Group.objects.for_user(self.user_a)), [group_a]
        )


class GroupNamingTests(TestCase):
    """Groups are numbered 1…N for the whole year and shared by every class."""

    @classmethod
    def setUpTestData(cls):
        cls.school = make_school('MFR Chatte')
        cls.year = make_year(cls.school, with_weeks=False)

    def test_generated_names_are_numbers(self):
        groups, created = self.year.generate_groups(2)
        self.assertEqual(created, 2)
        self.assertEqual([group.name for group in groups], ['1', '2'])

    def test_regenerating_creates_nothing(self):
        self.year.generate_groups(2)
        groups, created = self.year.generate_groups(2)
        self.assertEqual(created, 0)
        self.assertEqual([group.name for group in groups], ['1', '2'])

    def test_growing_the_year_only_adds_the_missing_numbers(self):
        self.year.generate_groups(2)
        groups, created = self.year.generate_groups(4)
        self.assertEqual(created, 2)
        self.assertEqual(
            [group.name for group in groups], ['1', '2', '3', '4']
        )

    def test_same_name_twice_in_a_year_is_rejected(self):
        Group.objects.create(school_year=self.year, name='Les rouges')
        with self.assertRaises(IntegrityError):
            Group.objects.create(school_year=self.year, name='Les rouges')

    def test_same_name_in_another_year_is_allowed(self):
        next_year = make_year(
            self.school, name='2027-2028',
            start=date(2027, 9, 6), end=date(2028, 6, 30), with_weeks=False,
        )
        Group.objects.create(school_year=self.year, name='Les rouges')
        other = Group.objects.create(
            school_year=next_year, name='Les rouges',
        )
        self.assertEqual(other.school_year, next_year)


class ClassOrderingTests(TestCase):
    """Classes are listed by curriculum level, not alphabetically."""

    @classmethod
    def setUpTestData(cls):
        cls.school = make_school('MFR Chatte')
        cls.year = make_year(cls.school, with_weeks=False)

    def _names(self):
        return list(
            SchoolClass.objects.filter(school_year=self.year).values_list(
                'name', flat=True
            )
        )

    def test_generated_classes_follow_the_curriculum(self):
        self.year.generate_classes(DEFAULT_CLASS_NAMES)
        self.assertEqual(
            self._names(),
            [
                '4ème A', '4ème B', '3ème A', '3ème B',
                'Seconde', 'Première', 'Terminale',
                'BTS 1', 'BTS 2',
                'CAP 1 MACON + IMTB', 'CAP 1 CHARP BOIS + IS',
                'CAP 2 MACON + IMTB', 'CAP 2 CHARP BOIS + IS',
            ],
        )

    def test_shorthand_names_take_the_same_place(self):
        for name in ['Term', '2nde', 'BTS1', '4 ème A']:
            make_class(self.year, name)
        self.assertEqual(self._names(), ['4 ème A', '2nde', 'Term', 'BTS1'])

    def test_unknown_names_come_last_in_alphabetical_order(self):
        for name in ['Zonzon', 'Seconde', 'Apprentis']:
            make_class(self.year, name)
        self.assertEqual(self._names(), ['Seconde', 'Apprentis', 'Zonzon'])

    def test_explicit_position_is_kept(self):
        make_class(self.year, 'Seconde')
        pinned = SchoolClass.objects.create(
            school_year=self.year, name='Zonzon', position=1
        )
        self.assertEqual(self._names(), ['Zonzon', 'Seconde'])
        self.assertEqual(pinned.position, 1)


class ClassCleaningTaskTests(TestCase):
    """Every class carries one chore nobody enters: cleaning its own room.
    It is born, renamed and buried with the class."""

    def setUp(self):
        self.school = make_school()
        self.year = make_year(self.school)

    def test_creating_a_class_creates_its_cleaning_task(self):
        school_class = make_class(self.year, '4A')
        task = Task.objects.get(school_class=school_class)
        self.assertEqual(task.name, 'Classe 4A')
        self.assertEqual(task.school, self.school)
        self.assertTrue(task.is_active)
        self.assertTrue(task.is_class_task)

    def test_renaming_a_class_renames_its_task(self):
        school_class = make_class(self.year, '4A')
        school_class.name = '4B'
        school_class.save()
        self.assertEqual(
            [task.name for task in Task.objects.filter(school_class=school_class)],
            ['Classe 4B'],
        )

    def test_generated_classes_get_one_task_each(self):
        self.year.generate_classes(['3A', '3B'])
        self.year.generate_classes(['3A', '3B'])  # idempotent
        self.assertEqual(
            sorted(
                Task.objects.filter(
                    school_class__school_year=self.year
                ).values_list('name', flat=True)
            ),
            ['Classe 3A', 'Classe 3B'],
        )

    def test_same_class_name_in_two_years_is_allowed(self):
        make_class(self.year, '4A')
        other = make_year(
            self.school, name='2027-2028',
            start=date(2027, 9, 6), end=date(2028, 6, 30),
            with_weeks=False,
        )
        make_class(other, '4A')
        self.assertEqual(Task.objects.filter(name='Classe 4A').count(), 2)

    def with_history(self):
        school_class = make_class(self.year, '4A')
        make_group(self.year, 'G0', classes=[school_class])
        week = self.year.weeks.first()
        make_presence(week, school_class)
        generate_week_assignments(week)
        self.assertTrue(Assignment.objects.exists())
        return school_class

    def test_deleting_the_year_takes_its_classes_cleaning_history(self):
        # The cleaning task hangs off the class, and Assignment.task is
        # protected: without the class-task exception, dropping a year (or a
        # school) would fail on a task nobody ever created by hand.
        self.with_history()
        self.year.delete()
        self.assertFalse(Assignment.objects.exists())
        self.assertFalse(Task.objects.filter(school_class__isnull=False).exists())

    def test_deleting_classes_in_bulk_works_too(self):
        school_class = self.with_history()
        SchoolClass.objects.filter(pk=school_class.pk).delete()
        self.assertFalse(Assignment.objects.exists())

    def test_a_rotating_task_with_history_is_still_protected(self):
        school_class = make_class(self.year, '4A')
        make_group(self.year, 'G0', classes=[school_class])
        make_group(self.year, 'G1', classes=[school_class])
        task = make_task(self.school, 'Vaisselle')
        week = self.year.weeks.first()
        make_presence(week, school_class)
        generate_week_assignments(week)
        self.assertTrue(Assignment.objects.filter(task=task).exists())
        with self.assertRaises(ProtectedError):
            task.delete()

    def test_deleting_a_class_takes_its_task_and_history(self):
        school_class = make_class(self.year, '4A')
        make_group(self.year, 'G0', classes=[school_class])
        week = self.year.weeks.first()
        make_presence(week, school_class)
        generate_week_assignments(week)
        self.assertTrue(Assignment.objects.exists())

        class_pk = school_class.pk
        school_class.delete()  # PROTECT on Assignment.task must not bite
        self.assertFalse(Assignment.objects.exists())
        self.assertFalse(Task.objects.filter(school_class_id=class_pk).exists())
