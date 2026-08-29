from collections import Counter

from django.test import TestCase
from rest_framework.test import APITestCase

from core.models import Assignment, Task
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
        groups = [make_group(self.year, f'G{i}', classes=[self.cls]) for i in range(3)]
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
        [make_group(self.year, f'G{i}', classes=[self.cls]) for i in range(3)]
        [make_task(self.school, f'T{i}') for i in range(3)]
        self.run_weeks(3)
        _, pair = self.counters()
        # after 3 weeks every group has done every task exactly once
        self.assertEqual(len(pair), 9)
        self.assertEqual(set(pair.values()), {1})

    def test_rest_fairness_4_groups_2_tasks(self):
        [make_group(self.year, f'G{i}', classes=[self.cls]) for i in range(4)]
        [make_task(self.school, f'T{i}') for i in range(2)]
        self.run_weeks(4)
        total, _ = self.counters()
        # 3 chores a week (2 tasks + cleaning 4A) over 4 groups, 4 weeks
        # → 12 assignments, exactly 3 each
        self.assertEqual(sorted(total.values()), [3, 3, 3, 3])

    def test_absent_class_never_assigned(self):
        make_group(self.year, 'G-present', classes=[self.cls])
        absent_cls = make_class(self.year, '4B')
        absent_group = make_group(self.year, 'G-absent', classes=[absent_cls])
        make_task(self.school)
        week = self.weeks[0]
        make_presence(week, self.cls)  # only 4A present
        generate_week_assignments(week)
        self.assertFalse(
            Assignment.objects.filter(group=absent_group).exists()
        )

    def test_mixed_group_works_when_one_member_class_is_present(self):
        cls_b = make_class(self.year, '4B')
        mixed = make_group(self.year, 'mixed', classes=[self.cls, cls_b])
        make_task(self.school)
        week = self.weeks[0]
        make_presence(week, cls_b)  # 4A stays home, the 4B member covers
        generate_week_assignments(week)
        self.assertEqual(Assignment.objects.get().group, mixed)

    def test_group_without_members_is_never_assigned(self):
        empty = make_group(self.year, 'empty')
        make_group(self.year, 'staffed', classes=[self.cls])
        [make_task(self.school, f'T{i}') for i in range(2)]
        week = self.weeks[0]
        make_presence(week, self.cls)
        generate_week_assignments(week)
        self.assertFalse(Assignment.objects.filter(group=empty).exists())

    def test_manual_assignment_survives_regeneration(self):
        # 3 groups: one is pinned by hand, one cleans 4A, one is left for the
        # rotation.
        groups = [make_group(self.year, f'G{i}', classes=[self.cls]) for i in range(3)]
        tasks = [make_task(self.school, f'T{i}') for i in range(2)]
        week = self.weeks[0]
        make_presence(week, self.cls)
        manual = Assignment.objects.create(
            week=week, task=tasks[0], group=groups[2], is_manual=True
        )
        result = generate_week_assignments(week)
        manual.refresh_from_db()  # still exists
        self.assertTrue(manual.is_manual)
        auto = {a.task.name: a.group for a in Assignment.objects.filter(is_manual=False)}
        self.assertEqual(auto['Classe 4A'], groups[0])
        self.assertEqual(auto['T1'], groups[1])
        self.assertEqual(len(result['assignments']), 3)

    def test_fewer_groups_than_tasks(self):
        make_group(self.year, 'G0', classes=[self.cls])
        [make_task(self.school, f'T{i}') for i in range(3)]
        week = self.weeks[0]
        make_presence(week, self.cls)
        result = generate_week_assignments(week)
        self.assertEqual(Assignment.objects.count(), 1)
        self.assertTrue(
            any('unassigned' in line for line in result['explanation'])
        )

    def test_no_presence_no_assignments(self):
        make_group(self.year, classes=[self.cls])
        make_task(self.school)
        result = generate_week_assignments(self.weeks[0])
        self.assertEqual(result['assignments'], [])
        self.assertEqual(Assignment.objects.count(), 0)

    def test_inactive_task_skipped(self):
        # two groups: one cleans 4A, the other is free for the rotation --
        # which must reach for 'Active' and never for the retired task.
        make_group(self.year, 'G0', classes=[self.cls])
        make_group(self.year, 'G1', classes=[self.cls])
        make_task(self.school, 'Active')
        make_task(self.school, 'Retired', is_active=False)
        week = self.weeks[0]
        make_presence(week, self.cls)
        generate_week_assignments(week)
        self.assertEqual(
            {a.task.name for a in Assignment.objects.all()},
            {'Classe 4A', 'Active'},
        )

    def test_class_cleaning_goes_to_a_group_of_that_class(self):
        cls_b = make_class(self.year, '4B')
        a_group = make_group(self.year, 'A', classes=[self.cls])
        b_group = make_group(self.year, 'B', classes=[cls_b])
        make_task(self.school, 'T0')
        week = self.weeks[0]
        make_presence(week, self.cls)
        make_presence(week, cls_b)
        generate_week_assignments(week)
        by_task = {a.task.name: a.group for a in Assignment.objects.all()}
        self.assertEqual(by_task['Classe 4A'], a_group)
        self.assertEqual(by_task['Classe 4B'], b_group)
        # both groups are cleaning their own room: nobody is left for T0
        self.assertNotIn('T0', by_task)

    def test_cleaning_group_is_out_of_the_rotation(self):
        [make_group(self.year, f'G{i}', classes=[self.cls]) for i in range(2)]
        [make_task(self.school, f'T{i}') for i in range(2)]
        week = self.weeks[0]
        make_presence(week, self.cls)
        generate_week_assignments(week)
        cleaner = Assignment.objects.get(task__school_class=self.cls).group
        self.assertEqual(Assignment.objects.filter(group=cleaner).count(), 1)

    def test_cleaning_rotates_between_the_classes_groups(self):
        [make_group(self.year, f'G{i}', classes=[self.cls]) for i in range(3)]
        make_task(self.school, 'T0')
        self.run_weeks(3)
        cleaners = [
            assignment.group_id
            for assignment in Assignment.objects.filter(
                task__school_class=self.cls
            )
        ]
        self.assertEqual(len(cleaners), 3)
        self.assertEqual(len(set(cleaners)), 3)  # a different group each week

    def test_class_with_no_free_group_is_reported(self):
        cls_b = make_class(self.year, '4B')
        # the only group on site belongs to both classes; it can clean one
        # room, and the other class is told why it got nobody.
        make_group(self.year, 'shared', classes=[self.cls, cls_b])
        week = self.weeks[0]
        make_presence(week, self.cls)
        make_presence(week, cls_b)
        result = generate_week_assignments(week)
        self.assertEqual(Assignment.objects.count(), 1)
        self.assertEqual(
            len([
                line for line in result['explanation']
                if 'no group of that class is free' in line
            ]),
            1,
        )

    def test_inactive_class_task_is_skipped(self):
        make_group(self.year, 'G0', classes=[self.cls])
        make_task(self.school, 'T0')
        Task.objects.filter(school_class=self.cls).update(is_active=False)
        week = self.weeks[0]
        make_presence(week, self.cls)
        generate_week_assignments(week)
        self.assertEqual(Assignment.objects.get().task.name, 'T0')

    def test_long_simulation_fairness_invariants(self):
        # two classes present every week, 5 groups total, 3 rotating tasks
        # plus the two implicit cleanings -- 5 chores, so nobody rests.
        cls_b = make_class(self.year, '4B')
        a_groups = [
            make_group(self.year, f'A{i}', classes=[self.cls]) for i in range(3)
        ]
        b_groups = [
            make_group(self.year, f'B{i}', classes=[cls_b]) for i in range(2)
        ]
        [make_task(self.school, f'T{i}') for i in range(3)]
        for week in self.weeks[:12]:
            make_presence(week, self.cls)
            make_presence(week, cls_b)
            generate_week_assignments(week)
        total, pair = self.counters()
        self.assertLessEqual(max(total.values()) - min(total.values()), 1)

        # Pair fairness only compares what is comparable. A cleaning task is
        # reachable by one class's groups only, so counting it against every
        # group would report a 12-0 "unfairness" that means nothing. Rotating
        # tasks are checked across all groups, each cleaning within its class.
        groups = a_groups + b_groups
        rotating = Task.objects.filter(school_class__isnull=True)
        spread = [
            pair[(group.pk, task.pk)]
            for group in groups for task in rotating
        ]
        self.assertLessEqual(max(spread) - min(spread), 1)
        for class_groups, school_class in (
            (a_groups, self.cls), (b_groups, cls_b)
        ):
            task = Task.objects.get(school_class=school_class)
            counts = [pair[(group.pk, task.pk)] for group in class_groups]
            self.assertLessEqual(max(counts) - min(counts), 1)


class AssignmentAPITests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = make_school()
        cls.user = make_user('staff', school=cls.school)
        cls.year = make_year(cls.school)
        cls.week = cls.year.weeks.order_by('start_date').first()
        cls.cls_4a = make_class(cls.year)
        cls.groups = [make_group(cls.year, f'G{i}', classes=[cls.cls_4a]) for i in range(2)]
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
