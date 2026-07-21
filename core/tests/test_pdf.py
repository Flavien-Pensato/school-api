import unittest

from rest_framework.test import APITestCase

from core.models import Enrollment
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


def weasyprint_available():
    try:
        import weasyprint  # noqa: F401
        return True
    except OSError:
        return False


class WeekDashboardPdfTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = make_school()
        cls.user = make_user('staff', school=cls.school)
        cls.year = make_year(cls.school)
        cls.week = cls.year.weeks.order_by('start_date').first()
        cls.cls_4a = make_class(cls.year)
        group = make_group(cls.cls_4a)
        student = make_student(cls.school)
        Enrollment.objects.create(
            student=student, school_year=cls.year,
            school_class=cls.cls_4a, group=group,
        )
        make_task(cls.school)
        make_presence(cls.week, cls.cls_4a)
        generate_week_assignments(cls.week)

    def setUp(self):
        self.client.force_authenticate(self.user)

    @unittest.skipUnless(
        weasyprint_available(),
        'weasyprint system libraries unavailable '
        '(set DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib on macOS)',
    )
    def test_pdf_endpoint(self):
        response = self.client.get(f'/api/weeks/{self.week.pk}/dashboard/pdf/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF'))
        self.assertIn('semaine-', response['Content-Disposition'])
