from collections import Counter

from django.test import TestCase
from rest_framework.test import APITestCase

from core.models import Assignment
from core.services import generate_week_assignments

from .factories import (
    make_class,
    make_group,
    make_presence,
    make_school,
    make_task,
    make_user,
    make_year,
)


class RotationServiceTests(TestCase):
    def setUp(self):
        self.school = make_school()
        self.year = make_year(self.school)
        self.weeks = list(self.year.weeks.order_by('start_date'))
        self.cls = make_class(self.year)

    def run_weeks(self, count):
        for week in self.weeks[:count]:
            make_presence(week, self.cls)
            generate_week_assignments(week)

    def counters(self):
        total, pair = Counter(), Counter()
        for a in Assignment.objects.all():
            total[a.group_id] += 1
            pair[(a.group_id, a.task_id)] += 1
        return total, pair

    def test_deterministic(self):
        groups = [make_group(self.cls, f'G{i}') for i in range(3)]
        [make_task(self.school, f'T{i}') for i in range(3)]
        week = self.weeks[0]
        make_presence(week, self.cls)
        first = [
            (a.group_id, a.task_id)
            for a in generate_week_assignments(week)['assignments']
        ]
        second = [
            (a.group_id, a.task_id)
            for a in generate_week_assignments(week)['assignments']
        ]
        self.assertEqual(first, second)
        self.assertEqual(Assignment.objects.count(), 3)

    def test_full_cycle_3_groups_3_tasks(self):
        [make_group(self.cls, f'G{i}') for i in range(3)]
        [make_task(self.school, f'T{i}') for i in range(3)]
        self.run_weeks(3)
        _, pair = self.counters()
        # after 3 weeks every group has done every task exactly once
        self.assertEqual(len(pair), 9)
        self.assertEqual(set(pair.values()), {1})

    def test_rest_fairness_4_groups_2_tasks(self):
        [make_group(self.cls, f'G{i}') for i in range(4)]
        [make_task(self.school, f'T{i}') for i in range(2)]
        self.run_weeks(4)
        total, _ = self.counters()
        # 8 assignments over 4 groups → exactly 2 each
        self.assertEqual(sorted(total.values()), [2, 2, 2, 2])

    def test_absent_class_never_assigned(self):
        make_group(self.cls, 'G-present')
        absent_cls = make_class(self.year, '4B')
        absent_group = make_group(absent_cls, 'G-absent')
        make_task(self.school)
        week = self.weeks[0]
        make_presence(week, self.cls)  # only 4A present
        generate_week_assignments(week)
        self.assertFalse(
            Assignment.objects.filter(group=absent_group).exists()
        )

    def test_manual_assignment_survives_regeneration(self):
        groups = [make_group(self.cls, f'G{i}') for i in range(2)]
        tasks = [make_task(self.school, f'T{i}') for i in range(2)]
        week = self.weeks[0]
        make_presence(week, self.cls)
        manual = Assignment.objects.create(
            week=week, task=tasks[0], group=groups[1], is_manual=True
        )
        result = generate_week_assignments(week)
        manual.refresh_from_db()  # still exists
        self.assertTrue(manual.is_manual)
        # the other task went to the other group
        auto = Assignment.objects.get(is_manual=False)
        self.assertEqual(auto.task, tasks[1])
        self.assertEqual(auto.group, groups[0])
        self.assertEqual(len(result['assignments']), 2)

    def test_fewer_groups_than_tasks(self):
        make_group(self.cls, 'G0')
        [make_task(self.school, f'T{i}') for i in range(3)]
        week = self.weeks[0]
        make_presence(week, self.cls)
        result = generate_week_assignments(week)
        self.assertEqual(Assignment.objects.count(), 1)
        self.assertTrue(
            any('unassigned' in line for line in result['explanation'])
        )

    def test_no_presence_no_assignments(self):
        make_group(self.cls)
        make_task(self.school)
        result = generate_week_assignments(self.weeks[0])
        self.assertEqual(result['assignments'], [])
        self.assertEqual(Assignment.objects.count(), 0)

    def test_inactive_task_skipped(self):
        make_group(self.cls)
        make_task(self.school, 'Active')
        make_task(self.school, 'Retired', is_active=False)
        week = self.weeks[0]
        make_presence(week, self.cls)
        generate_week_assignments(week)
        self.assertEqual(
            Assignment.objects.get().task.name, 'Active'
        )

    def test_long_simulation_fairness_invariants(self):
        # two classes present every week, 5 groups total, 3 tasks
        cls_b = make_class(self.year, '4B')
        for i in range(3):
            make_group(self.cls, f'A{i}')
        for i in range(2):
            make_group(cls_b, f'B{i}')
        [make_task(self.school, f'T{i}') for i in range(3)]
        for week in self.weeks[:12]:
            make_presence(week, self.cls)
            make_presence(week, cls_b)
            generate_week_assignments(week)
        total, pair = self.counters()
        self.assertLessEqual(max(total.values()) - min(total.values()), 1)
        self.assertLessEqual(max(pair.values()) - min(pair.values()), 1)


class AssignmentAPITests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = make_school()
        cls.user = make_user('staff', school=cls.school)
        cls.year = make_year(cls.school)
        cls.week = cls.year.weeks.order_by('start_date').first()
        cls.cls_4a = make_class(cls.year)
        cls.groups = [make_group(cls.cls_4a, f'G{i}') for i in range(2)]
        cls.tasks = [make_task(cls.school, f'T{i}') for i in range(2)]
        make_presence(cls.week, cls.cls_4a)

    def setUp(self):
        self.client.force_authenticate(self.user)

    def test_generate_endpoint(self):
        response = self.client.post(
            f'/api/weeks/{self.week.pk}/generate-assignments/'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['assignments']), 2)
        self.assertTrue(response.data['explanation'])

    def test_staff_edit_becomes_manual(self):
        self.client.post(f'/api/weeks/{self.week.pk}/generate-assignments/')
        assignment = Assignment.objects.first()
        other_group = (
            self.groups[1]
            if assignment.group == self.groups[0] else self.groups[0]
        )
        # swap requires freeing the other group's assignment first
        Assignment.objects.exclude(pk=assignment.pk).delete()
        response = self.client.patch(
            f'/api/assignments/{assignment.pk}/', {'group': other_group.pk}
        )
        self.assertEqual(response.status_code, 200)
        assignment.refresh_from_db()
        self.assertTrue(assignment.is_manual)

    def test_assignment_without_presence_rejected(self):
        week2 = self.year.weeks.order_by('start_date')[1]  # no presence
        response = self.client.post('/api/assignments/', {
            'week': week2.pk,
            'task': self.tasks[0].pk,
            'group': self.groups[0].pk,
        })
        self.assertEqual(response.status_code, 400)
