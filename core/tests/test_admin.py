"""Back-office actions: generate a school's tasks, a year's classes,
and a class's groups."""

from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import (
    DEFAULT_CLASS_NAMES,
    DEFAULT_TASK_NAMES,
    Group,
    SchoolClass,
    Task,
)

from .factories import make_class, make_school, make_task, make_year

User = get_user_model()


# Admin templates load static assets; the prod manifest storage needs a
# collectstatic run, which tests must not depend on.
@override_settings(STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {
        'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'
    },
})
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
            'admin:core_school_changelist', [self.school], 'generate_tasks'
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Générer les tâches')
        self.assertContains(response, DEFAULT_TASK_NAMES[0])
        self.assertEqual(Task.objects.count(), 0)  # nothing written yet

    def test_generate_tasks_creates_the_edited_list_in_order(self):
        response = self.post(
            'admin:core_school_changelist', [self.school], 'generate_tasks',
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
        self.post('admin:core_school_changelist', [self.school],
                  'generate_tasks', data)
        self.post('admin:core_school_changelist', [self.school],
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

    def test_generate_groups_defaults_to_ten_per_class(self):
        first, second = make_class(self.year, '3ème A'), make_class(self.year, '3ème B')
        response = self.post(
            'admin:core_schoolclass_changelist', [first, second],
            'generate_groups', {'confirmed': '1', 'count': '10'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(first.groups.count(), 10)
        self.assertEqual(second.groups.count(), 10)
        # numbering runs across the year: 1…10, then 11…20
        self.assertEqual(
            list(first.groups.values_list('name', flat=True)),
            [str(number) for number in range(1, 11)],
        )
        self.assertEqual(
            list(second.groups.values_list('name', flat=True)),
            [str(number) for number in range(11, 21)],
        )

    def test_generate_groups_only_fills_the_gaps(self):
        school_class = make_class(self.year, '3ème A')
        kept = Group.objects.create(
            school_class=school_class, name=school_class.group_name(3)
        )
        self.post('admin:core_schoolclass_changelist', [school_class],
                  'generate_groups', {'confirmed': '1', 'count': '10'})
        self.assertEqual(school_class.groups.count(), 10)
        self.assertTrue(Group.objects.filter(pk=kept.pk).exists())

    def test_generate_groups_form_writes_nothing(self):
        school_class = make_class(self.year, '3ème A')
        self.post('admin:core_schoolclass_changelist', [school_class],
                  'generate_groups')
        self.assertEqual(Group.objects.count(), 0)
