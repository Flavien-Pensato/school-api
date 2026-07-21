from datetime import date

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase

from core.models import Assignment, Enrollment, Student, Week

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
        self.group = make_group(self.cls)

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

    def test_enrollment_group_must_match_class(self):
        cls2 = make_class(self.year, name='4B')
        student = make_student(self.school)
        enrollment = Enrollment(
            student=student, school_year=self.year,
            school_class=cls2, group=self.group,
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
        cls_a = make_class(self.year_a)
        cls_b = make_class(self.year_b)
        group_a = make_group(cls_a)
        make_group(cls_b)
        self.assertEqual(
            list(Group.objects.for_user(self.user_a)), [group_a]
        )
