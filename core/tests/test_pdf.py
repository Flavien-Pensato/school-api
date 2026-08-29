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
        group = make_group(cls.year)
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


class SinglePagePdfTests(unittest.TestCase):
    """The roster gets posted on a wall: a real-size week must stay on one
    page. Rendering is driven directly, so no database is needed."""

    def _dashboard(self, group_count, students_per_group=5):
        # Names as long as the real ones -- a narrower sample would fit even
        # with a broken column layout and hide the regression.
        names = [
            ('Pierre-Louis', 'MARCHAND'),
            ('Mamadou Madiou', 'DIALLO'),
            ('Elyès', 'EL MOUSSAOUI--VIEL'),
            ('Florian', 'COTTAZ--TAVERNE'),
            ('Camille', 'BENEZET ODOIT'),
        ]
        classes = ['CAP 2 MACON + IMTB', 'CAP 2 CHARP BOIS + IS', 'Terminale']
        return {
            'week': {'id': 1, 'start_date': '2026-08-31', 'label': '2026-W36'},
            'school': {'id': 1, 'name': 'Chatte'},
            'groups': [
                {
                    'id': i,
                    'name': str(i + 1),
                    'students': [
                        {
                            'id': j,
                            'first_name': names[j % len(names)][0],
                            'last_name': names[j % len(names)][1],
                            'school_class': classes[i % len(classes)],
                        }
                        for j in range(students_per_group)
                    ],
                    'task': (
                        {'id': i, 'name': 'Refectoir matin/soir'}
                        if i % 2 == 0 else None
                    ),
                }
                for i in range(group_count)
            ],
        }

    @unittest.skipUnless(
        weasyprint_available(),
        'weasyprint system libraries unavailable '
        '(set DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib on macOS)',
    )
    def test_full_roster_fits_on_one_page(self):
        from django.template.loader import render_to_string
        from weasyprint import HTML

        from core.pdf import FONT_SIZES_PT

        dashboard = self._dashboard(40)
        for font_pt in FONT_SIZES_PT:
            html = render_to_string(
                'core/week_dashboard_pdf.html',
                {**dashboard, 'font_pt': font_pt},
            )
            if len(HTML(string=html).render().pages) == 1:
                return
        self.fail(
            '40 groups still spill onto a second page at the smallest font'
        )
