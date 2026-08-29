from datetime import date

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
        # 4B never comes on site: its member must not show up on the sheet.
        cls.cls_4b = make_class(cls.year, '4B')
        cls.groups = [make_group(cls.year, f'Groupe {i}') for i in (1, 2)]
        cls.tasks = [make_task(cls.school, name) for name in ('Vaisselle', 'Ménage')]
        for index, group in enumerate(cls.groups):
            student = make_student(
                cls.school, f'Prénom{index}', f'Nom{index}'
            )
            Enrollment.objects.create(
                student=student, school_year=cls.year,
                school_class=cls.cls_4a, group=group,
            )
        Enrollment.objects.create(
            student=make_student(cls.school, 'Absent', 'Absent'),
            school_year=cls.year, school_class=cls.cls_4b,
            group=cls.groups[0],
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
        self.assertEqual(
            sorted(g['name'] for g in data['groups']),
            ['Groupe 1', 'Groupe 2'],
        )
        # the class cleaning leads the sheet
        self.assertEqual(data['groups'][0]['task']['school_class'], '4A')
        for group in data['groups']:
            self.assertEqual(len(group['students']), 1)
            self.assertEqual(group['students'][0]['school_class'], '4A')
            self.assertIsNotNone(group['task'])
        # 4A is on site, so one of its two groups cleans its room and the
        # other takes a rotating chore.
        cleaning = [g for g in data['groups'] if g['task']['school_class']]
        self.assertEqual(len(cleaning), 1)
        self.assertEqual(cleaning[0]['task']['school_class'], '4A')
        self.assertEqual(cleaning[0]['task']['name'], 'Classe 4A')
        rotating = [g for g in data['groups'] if not g['task']['school_class']]
        self.assertEqual(len(rotating), 1)
        self.assertIn(rotating[0]['task']['name'], {'Vaisselle', 'Ménage'})

    def test_dashboard_absent_class_excluded(self):
        week_no_presence = self.weeks[5]
        response = self.client.get(
            f'/api/weeks/{week_no_presence.pk}/dashboard/'
        )
        self.assertEqual(response.data['groups'], [])

    def test_stats_lists_this_years_tasks_only(self):
        # another year's classes carry cleaning tasks of the same school;
        # they would be a permanently empty column here.
        other_year = make_year(
            self.school, name='2027-2028',
            start=date(2027, 9, 6), end=date(2028, 6, 30), with_weeks=False,
        )
        make_class(other_year, '5A')
        response = self.client.get(f'/api/school-years/{self.year.pk}/stats/')
        tasks = response.data['tasks']
        self.assertEqual(
            [task['name'] for task in tasks],
            ['Classe 4A', 'Classe 4B', 'Vaisselle', 'Ménage'],
        )
        self.assertEqual(
            [task['school_class'] for task in tasks],
            ['4A', '4B', None, None],
        )

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
