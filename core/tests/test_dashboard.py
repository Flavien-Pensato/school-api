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


class DashboardAndStatsTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = make_school()
        cls.user = make_user('staff', school=cls.school)
        cls.year = make_year(cls.school)
        cls.weeks = list(cls.year.weeks.order_by('start_date'))
        cls.cls_4a = make_class(cls.year, '4A')
        cls.groups = [make_group(cls.cls_4a, f'Groupe {i}') for i in (1, 2)]
        cls.tasks = [make_task(cls.school, name) for name in ('Vaisselle', 'Ménage')]
        for index, group in enumerate(cls.groups):
            student = make_student(
                cls.school, f'Prénom{index}', f'Nom{index}'
            )
            Enrollment.objects.create(
                student=student, school_year=cls.year,
                school_class=cls.cls_4a, group=group,
            )
        for week in cls.weeks[:3]:
            make_presence(week, cls.cls_4a)
            generate_week_assignments(week)

    def setUp(self):
        self.client.force_authenticate(self.user)

    def test_dashboard_shape(self):
        week = self.weeks[0]
        response = self.client.get(f'/api/weeks/{week.pk}/dashboard/')
        self.assertEqual(response.status_code, 200)
        data = response.data
        self.assertEqual(data['week']['id'], week.pk)
        self.assertEqual(data['school']['name'], self.school.name)
        self.assertEqual(len(data['classes']), 1)
        klass = data['classes'][0]
        self.assertEqual(klass['name'], '4A')
        self.assertEqual(len(klass['groups']), 2)
        for group in klass['groups']:
            self.assertEqual(len(group['students']), 1)
            self.assertIsNotNone(group['task'])
        assigned = {g['task']['name'] for g in klass['groups']}
        self.assertEqual(assigned, {'Vaisselle', 'Ménage'})

    def test_dashboard_absent_class_excluded(self):
        week_no_presence = self.weeks[5]
        response = self.client.get(
            f'/api/weeks/{week_no_presence.pk}/dashboard/'
        )
        self.assertEqual(response.data['classes'], [])

    def test_stats_shape_and_counts(self):
        response = self.client.get(f'/api/school-years/{self.year.pk}/stats/')
        self.assertEqual(response.status_code, 200)
        rows = response.data['groups']
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(row['weeks_present'], 3)
            self.assertEqual(row['total'], 3)
            self.assertEqual(row['weeks_rested'], 0)
            self.assertEqual(sum(row['totals'].values()), 3)
        # fairness across 3 weeks, 2 groups × 2 tasks: pair counts within 1
        all_counts = [
            count for row in rows for count in row['totals'].values()
        ]
        self.assertLessEqual(max(all_counts) - min(all_counts), 1)
