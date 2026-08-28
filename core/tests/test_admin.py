"""Back-office actions: generate a school's tasks (from its year), and a
year's classes, weeks and groups."""

from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import (
    DEFAULT_CLASS_NAMES,
    DEFAULT_TASK_NAMES,
    Enrollment,
    Group,
    SchoolClass,
    Task,
    Week,
)

from .factories import (
    ADMIN_STORAGES,
    make_class,
    make_school,
    make_student,
    make_task,
    make_year,
)

User = get_user_model()


@override_settings(STORAGES=ADMIN_STORAGES)
class AdminGenerateActionsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = make_school('MFR Chatte')
        cls.year = make_year(cls.school, with_weeks=False)
        cls.admin = User.objects.create_superuser(username='root')

    def setUp(self):
        self.client.force_login(self.admin)

    def post(self, url_name, objects, action, data=None):
        return self.client.post(reverse(url_name), {
            'action': action,
            ACTION_CHECKBOX_NAME: [obj.pk for obj in objects],
            **(data or {}),
        }, follow=True)

    # --- tasks -------------------------------------------------------------

    def test_generate_tasks_shows_prefilled_form_first(self):
        response = self.post(
            'admin:core_schoolyear_changelist', [self.year], 'generate_tasks'
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Générer les tâches')
        self.assertContains(response, DEFAULT_TASK_NAMES[0])
        self.assertEqual(Task.objects.count(), 0)  # nothing written yet

    def test_generate_tasks_creates_the_edited_list_in_order(self):
        response = self.post(
            'admin:core_schoolyear_changelist', [self.year], 'generate_tasks',
            {'confirmed': '1', 'names': 'Vaisselle midi\nFoyer\n\n  Véhicules  \n'},
        )
        self.assertEqual(response.status_code, 200)
        # Task.Meta.ordering is ['id'], so this is the rotation order too.
        self.assertEqual(
            list(self.school.tasks.values_list('name', flat=True)),
            ['Vaisselle midi', 'Foyer', 'Véhicules'],
        )

    def test_generate_tasks_reuses_existing_ones(self):
        existing = make_task(self.school, 'Foyer', is_active=False)
        data = {'confirmed': '1', 'names': 'Foyer\nVéhicules'}
        self.post('admin:core_schoolyear_changelist', [self.year],
                  'generate_tasks', data)
        self.post('admin:core_schoolyear_changelist', [self.year],
                  'generate_tasks', data)
        self.assertEqual(self.school.tasks.count(), 2)
        # an existing task keeps its flag — regeneration must not re-activate it
        self.assertFalse(Task.objects.get(pk=existing.pk).is_active)

    # --- classes -----------------------------------------------------------

    def test_generate_classes_shows_prefilled_form_first(self):
        response = self.post(
            'admin:core_schoolyear_changelist', [self.year], 'generate_classes'
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Générer les classes')
        self.assertContains(response, DEFAULT_CLASS_NAMES[0])
        self.assertEqual(SchoolClass.objects.count(), 0)  # nothing written yet

    def test_generate_classes_creates_the_edited_list(self):
        response = self.post(
            'admin:core_schoolyear_changelist', [self.year], 'generate_classes',
            {'confirmed': '1', 'names': '3ème A\n3ème B\n\n  4ème A  \n'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            list(self.year.classes.values_list('name', flat=True)),
            ['3ème A', '3ème B', '4ème A'],
        )

    def test_generate_classes_reuses_existing_ones(self):
        existing = make_class(self.year, '3ème A')
        data = {'confirmed': '1', 'names': '3ème A\n3ème B'}
        self.post('admin:core_schoolyear_changelist', [self.year],
                  'generate_classes', data)
        self.post('admin:core_schoolyear_changelist', [self.year],
                  'generate_classes', data)
        self.assertEqual(self.year.classes.count(), 2)
        self.assertEqual(SchoolClass.objects.get(pk=existing.pk).name, '3ème A')

    # --- groups ------------------------------------------------------------

    def test_generate_groups_numbers_the_whole_year(self):
        response = self.post(
            'admin:core_schoolyear_changelist', [self.year],
            'generate_groups', {'confirmed': '1', 'count': '10'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            list(self.year.groups.values_list('name', flat=True)),
            [str(number) for number in range(1, 11)],
        )

    def test_generate_groups_only_fills_the_gaps(self):
        kept = Group.objects.create(school_year=self.year, name='3')
        self.post('admin:core_schoolyear_changelist', [self.year],
                  'generate_groups', {'confirmed': '1', 'count': '10'})
        self.assertEqual(self.year.groups.count(), 10)
        self.assertTrue(Group.objects.filter(pk=kept.pk).exists())

    def test_generate_groups_form_writes_nothing(self):
        self.post('admin:core_schoolyear_changelist', [self.year],
                  'generate_groups')
        self.assertEqual(Group.objects.count(), 0)

    def test_reset_groups_replaces_the_old_per_class_blocks(self):
        school_class = make_class(self.year, '3ème A')
        old = Group.objects.create(school_year=self.year, name='11')
        enrollment = Enrollment.objects.create(
            student=make_student(self.school),
            school_year=self.year, school_class=school_class, group=old,
        )
        response = self.post(
            'admin:core_schoolyear_changelist', [self.year],
            'reset_groups', {'confirmed': '1', 'count': '3'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Group.objects.filter(pk=old.pk).exists())
        self.assertEqual(
            list(self.year.groups.values_list('name', flat=True)),
            ['1', '2', '3'],
        )
        enrollment.refresh_from_db()
        self.assertIsNone(enrollment.group)  # students must be re-assigned

    def test_reset_groups_form_writes_nothing(self):
        kept = Group.objects.create(school_year=self.year, name='11')
        self.post('admin:core_schoolyear_changelist', [self.year],
                  'reset_groups')
        self.assertEqual(list(Group.objects.all()), [kept])

    def test_generate_weeks_fills_the_year(self):
        """A year created in the admin has no weeks — without them the
        presence grid has no columns."""
        self.assertEqual(self.year.weeks.count(), 0)
        self.post(
            'admin:core_schoolyear_changelist', [self.year], 'generate_weeks'
        )
        weeks = list(self.year.weeks.order_by('start_date'))
        self.assertGreater(len(weeks), 40)
        self.assertTrue(all(w.start_date.weekday() == 0 for w in weeks))
        self.assertLessEqual(weeks[0].start_date, self.year.start_date)
        self.assertLessEqual(weeks[-1].start_date, self.year.end_date)

    def test_generate_weeks_is_idempotent(self):
        for _ in range(2):
            self.post(
                'admin:core_schoolyear_changelist', [self.year],
                'generate_weeks',
            )
        count = self.year.weeks.count()
        self.assertEqual(
            Week.objects.filter(school_year=self.year).count(), count
        )
