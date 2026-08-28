from rest_framework.test import APITestCase

from core.models import Assignment, ClassPresence
from core.services import (
    build_year_presence_grid,
    build_year_stats,
    generate_week_assignments,
)

from .factories import (
    make_class,
    make_group,
    make_presence,
    make_school,
    make_task,
    make_user,
    make_year,
)


class PresenceGridTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = make_school()
        cls.user = make_user('staff', school=cls.school)
        cls.year = make_year(cls.school)
        cls.weeks = list(cls.year.weeks.order_by('start_date'))
        cls.cls_4a = make_class(cls.year, '4A')
        cls.cls_3b = make_class(cls.year, '3B')
        cls.presence = make_presence(cls.weeks[1], cls.cls_4a)

    def setUp(self):
        self.client.force_authenticate(self.user)

    def url(self, year=None):
        return f'/api/school-years/{(year or self.year).pk}/presence-grid/'

    def test_grid_covers_every_week_of_the_year(self):
        data = self.client.get(self.url()).data
        self.assertEqual(len(data['weeks']), len(self.weeks))
        self.assertEqual(
            [w['id'] for w in data['weeks']], [w.pk for w in self.weeks]
        )
        self.assertEqual(data['weeks'][0]['label'], self.weeks[0].label)

    def test_cells_are_presence_ids_aligned_to_weeks(self):
        data = self.client.get(self.url()).data
        rows = {row['name']: row['cells'] for row in data['classes']}
        # every class gets a full-width row, absent weeks included
        for cells in rows.values():
            self.assertEqual(len(cells), len(self.weeks))
        self.assertEqual(rows['4A'][1], self.presence.pk)
        self.assertIsNone(rows['4A'][0])
        self.assertEqual(rows['3B'], [None] * len(self.weeks))

    def test_classes_ordered_by_name(self):
        data = self.client.get(self.url()).data
        self.assertEqual([row['name'] for row in data['classes']], ['3B', '4A'])

    def test_cell_id_is_the_delete_target(self):
        cells = next(
            row['cells'] for row in self.client.get(self.url()).data['classes']
            if row['name'] == '4A'
        )
        deleted = self.client.delete(f'/api/presences/{cells[1]}/')
        self.assertEqual(deleted.status_code, 204)
        refreshed = next(
            row['cells'] for row in self.client.get(self.url()).data['classes']
            if row['name'] == '4A'
        )
        self.assertEqual(refreshed, [None] * len(self.weeks))

    def test_posting_a_cell_fills_the_grid(self):
        created = self.client.post('/api/presences/', {
            'week': self.weeks[0].pk, 'school_class': self.cls_3b.pk,
        })
        self.assertEqual(created.status_code, 201)
        cells = next(
            row['cells'] for row in self.client.get(self.url()).data['classes']
            if row['name'] == '3B'
        )
        self.assertEqual(cells[0], created.data['id'])

    def test_other_school_year_is_not_found(self):
        other = make_year(make_school('MFR B'), '2026-2027')
        self.assertEqual(self.client.get(self.url(other)).status_code, 404)

    def test_grid_query_count_is_constant(self):
        for week in self.weeks[:10]:
            ClassPresence.objects.get_or_create(
                week=week, school_class=self.cls_3b
            )
        # weeks + presences + classes — never one query per cell
        with self.assertNumQueries(3):
            build_year_presence_grid(self.year)

    def test_year_without_weeks_yields_empty_rows(self):
        bare = make_year(self.school, '2027-2028', with_weeks=False)
        make_class(bare, '2nde')
        data = self.client.get(self.url(bare)).data
        self.assertEqual(data['weeks'], [])
        self.assertEqual(data['classes'][0]['cells'], [])


class RevokePresenceTests(APITestCase):
    """Un-checking a cell must leave no Assignment behind for the groups the
    absent class just emptied — policy (a): the checkbox is the source of
    truth. A group keeping a member from another present class works on."""

    @classmethod
    def setUpTestData(cls):
        cls.school = make_school()
        cls.user = make_user('staff', school=cls.school)
        cls.year = make_year(cls.school)
        cls.weeks = list(cls.year.weeks.order_by('start_date'))
        cls.cls_4a = make_class(cls.year, '4A')
        cls.cls_3b = make_class(cls.year, '3B')
        cls.groups_4a = [
            make_group(cls.year, f'G{i}', classes=[cls.cls_4a]) for i in (1, 2)
        ]
        cls.groups_3b = [
            make_group(cls.year, f'G{i}', classes=[cls.cls_3b]) for i in (3, 4)
        ]
        cls.tasks = [
            make_task(cls.school, name) for name in ('Vaisselle', 'Ménage')
        ]

    def setUp(self):
        self.client.force_authenticate(self.user)

    def uncheck(self, presence):
        response = self.client.delete(f'/api/presences/{presence.pk}/')
        self.assertEqual(response.status_code, 204)

    def test_uncheck_deletes_the_auto_assignments(self):
        week = self.weeks[0]
        presence = make_presence(week, self.cls_4a)
        generate_week_assignments(week)
        self.assertTrue(
            Assignment.objects.filter(
                week=week, group__in=self.groups_4a
            ).exists()
        )
        self.uncheck(presence)
        self.assertFalse(Assignment.objects.filter(week=week).exists())

    def test_uncheck_deletes_manual_assignments_too(self):
        week = self.weeks[0]
        presence = make_presence(week, self.cls_4a)
        Assignment.objects.create(
            week=week, task=self.tasks[0], group=self.groups_4a[0],
            is_manual=True,
        )
        self.uncheck(presence)
        self.assertFalse(Assignment.objects.filter(week=week).exists())

    def test_uncheck_spares_the_other_classes_of_the_week(self):
        week = self.weeks[0]
        presence_4a = make_presence(week, self.cls_4a)
        make_presence(week, self.cls_3b)
        # one task per group, else rest fairness leaves a whole class idle
        # and the test would prove nothing
        for name in ('Foyer', 'Extérieur'):
            make_task(self.school, name)
        generate_week_assignments(week)
        kept = set(
            Assignment.objects.filter(
                week=week, group__in=self.groups_3b
            ).values_list('pk', flat=True)
        )
        self.assertTrue(kept)
        self.uncheck(presence_4a)
        self.assertEqual(
            set(
                Assignment.objects.filter(week=week).values_list(
                    'pk', flat=True
                )
            ),
            kept,
        )

    def test_uncheck_spares_a_group_with_a_member_still_on_site(self):
        week = self.weeks[0]
        presence_4a = make_presence(week, self.cls_4a)
        presence_3b = make_presence(week, self.cls_3b)
        mixed = make_group(
            self.year, 'G5', classes=[self.cls_4a, self.cls_3b]
        )
        Assignment.objects.create(
            week=week, task=self.tasks[0], group=mixed, is_manual=True,
        )
        self.uncheck(presence_4a)
        self.assertTrue(Assignment.objects.filter(group=mixed).exists())
        self.uncheck(presence_3b)  # nobody left on site
        self.assertFalse(Assignment.objects.filter(group=mixed).exists())

    def test_uncheck_spares_the_same_class_in_other_weeks(self):
        for week in self.weeks[:2]:
            make_presence(week, self.cls_4a)
            generate_week_assignments(week)
        self.uncheck(
            ClassPresence.objects.get(
                week=self.weeks[0], school_class=self.cls_4a
            )
        )
        self.assertFalse(
            Assignment.objects.filter(week=self.weeks[0]).exists()
        )
        self.assertTrue(
            Assignment.objects.filter(week=self.weeks[1]).exists()
        )

    def test_stats_stay_consistent_after_uncheck(self):
        """weeks_rested = weeks_present - total went negative while orphan
        assignments outlived their presence row."""
        for week in self.weeks[:3]:
            make_presence(week, self.cls_4a)
            generate_week_assignments(week)
        for week in self.weeks[:3]:
            self.uncheck(
                ClassPresence.objects.get(week=week, school_class=self.cls_4a)
            )
        rows = build_year_stats(self.year)['groups']
        for row in rows:
            self.assertEqual(row['weeks_present'], 0)
            self.assertEqual(row['total'], 0)
            self.assertEqual(row['weeks_rested'], 0)

    def test_rechecking_leaves_the_week_unassigned(self):
        week = self.weeks[0]
        presence = make_presence(week, self.cls_4a)
        generate_week_assignments(week)
        self.uncheck(presence)
        recreated = self.client.post('/api/presences/', {
            'week': week.pk, 'school_class': self.cls_4a.pk,
        })
        self.assertEqual(recreated.status_code, 201)
        self.assertFalse(Assignment.objects.filter(week=week).exists())
        generate_week_assignments(week)
        self.assertTrue(Assignment.objects.filter(week=week).exists())
