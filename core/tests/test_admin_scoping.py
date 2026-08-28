"""Admin scoping for is_staff (non-superuser) users: which models they see,
which rows and FK choices they reach, and what stays superuser-only."""

from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import SchoolMembership, SchoolYear, Task

from .factories import (
    ADMIN_STORAGES,
    make_class,
    make_group,
    make_school,
    make_student,
    make_task,
    make_year,
)

User = get_user_model()

# The models a school member may manage, as admin changelist URLs.
STAFF_URLS = [
    '/admin/core/schoolyear/',
    '/admin/core/schoolclass/',
    '/admin/core/group/',
    '/admin/core/student/',
    '/admin/core/enrollment/',
    '/admin/core/task/',
    '/admin/core/classpresence/',
    '/admin/core/assignment/',
]
SUPERUSER_URLS = ['/admin/core/school/', '/admin/core/week/']
AUTH_URLS = ['/admin/auth/user/', '/admin/auth/group/']


@override_settings(STORAGES=ADMIN_STORAGES)
class ScopedAdminTestCase(TestCase):
    """Two schools with a full object graph each, plus the four user kinds."""

    @classmethod
    def setUpTestData(cls):
        cls.school_a = make_school('MFR Alpha')
        cls.school_b = make_school('MFR Beta')
        cls.year_a = make_year(cls.school_a)
        cls.year_b = make_year(cls.school_b)
        cls.class_a = make_class(cls.year_a, '4A')
        cls.class_b = make_class(cls.year_b, '4B')
        cls.group_a = make_group(cls.year_a)
        cls.group_b = make_group(cls.year_b)
        cls.student_a = make_student(cls.school_a, last_name='Alpha')
        cls.student_b = make_student(cls.school_b, last_name='Beta')
        cls.task_a = make_task(cls.school_a, 'Vaisselle A')
        cls.task_b = make_task(cls.school_b, 'Vaisselle B')

        cls.staff_a = User.objects.create_user(
            username='staff-a', is_staff=True
        )
        SchoolMembership.objects.create(user=cls.staff_a, school=cls.school_a)
        cls.staff_ab = User.objects.create_user(
            username='staff-ab', is_staff=True
        )
        SchoolMembership.objects.create(user=cls.staff_ab, school=cls.school_a)
        SchoolMembership.objects.create(user=cls.staff_ab, school=cls.school_b)
        cls.staff_none = User.objects.create_user(
            username='orphan', is_staff=True
        )
        cls.root = User.objects.create_superuser(username='root')

    def add_form(self, model_name, user=None):
        """The bound admin form of an add page, for FK queryset assertions."""
        self.client.force_login(user or self.staff_a)
        response = self.client.get(f'/admin/core/{model_name}/add/')
        self.assertEqual(response.status_code, 200)
        return response.context['adminform'].form


class ScopedAdminIndexTests(ScopedAdminTestCase):
    def test_index_lists_staff_manageable_models(self):
        self.client.force_login(self.staff_a)
        response = self.client.get('/admin/')
        for url in STAFF_URLS:
            self.assertContains(response, url)

    def test_index_hides_superuser_only_models(self):
        self.client.force_login(self.staff_a)
        response = self.client.get('/admin/')
        for url in SUPERUSER_URLS:
            self.assertNotContains(response, url)

    def test_index_hides_auth_models(self):
        # Hidden because no Permission rows exist; guard against a future grant.
        self.client.force_login(self.staff_a)
        response = self.client.get('/admin/')
        for url in AUTH_URLS:
            self.assertNotContains(response, url)

    def test_index_empty_without_membership(self):
        self.client.force_login(self.staff_none)
        response = self.client.get('/admin/')
        self.assertEqual(response.status_code, 200)
        for url in STAFF_URLS + SUPERUSER_URLS:
            self.assertNotContains(response, url)

    def test_app_index_404_without_membership(self):
        self.client.force_login(self.staff_none)
        self.assertEqual(self.client.get('/admin/core/').status_code, 404)

    def test_superuser_index_unchanged(self):
        self.client.force_login(self.root)
        response = self.client.get('/admin/')
        for url in STAFF_URLS + SUPERUSER_URLS + AUTH_URLS:
            self.assertContains(response, url)


class ScopedAdminAccessTests(ScopedAdminTestCase):
    def test_superuser_only_changelists_forbidden_for_staff(self):
        self.client.force_login(self.staff_a)
        for url in SUPERUSER_URLS + AUTH_URLS:
            self.assertEqual(self.client.get(url).status_code, 403, url)

    def test_scoped_changelist_forbidden_without_membership(self):
        self.client.force_login(self.staff_none)
        response = self.client.get('/admin/core/schoolyear/')
        self.assertEqual(response.status_code, 403)

    def test_changelist_excludes_other_school(self):
        self.client.force_login(self.staff_a)
        response = self.client.get('/admin/core/schoolyear/')
        self.assertEqual(
            list(response.context['cl'].queryset.values_list('pk', flat=True)),
            [self.year_a.pk],
        )
        self.assertNotContains(response, 'MFR Beta')

    def test_own_object_change_view_ok(self):
        self.client.force_login(self.staff_a)
        url = f'/admin/core/schoolyear/{self.year_a.pk}/change/'
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_other_school_object_views_redirect_to_index(self):
        # get_object() returns None through the scoped queryset, so Django
        # redirects with a "doesn't exist" warning rather than 404-ing.
        self.client.force_login(self.staff_a)
        for suffix in ['change', 'delete', 'history']:
            url = f'/admin/core/schoolyear/{self.year_b.pk}/{suffix}/'
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertEqual(response['Location'], '/admin/', url)


class ScopedAdminFieldTests(ScopedAdminTestCase):
    def test_fk_dropdown_lists_only_own_school(self):
        form = self.add_form('schoolyear')
        self.assertEqual(
            set(form.fields['school'].queryset.values_list('pk', flat=True)),
            {self.school_a.pk},
        )

    def test_nullable_fk_dropdown_stays_scoped_and_optional(self):
        form = self.add_form('enrollment')
        group_field = form.fields['group']
        self.assertFalse(group_field.required)
        self.assertNotIn(
            self.group_b.pk,
            set(group_field.queryset.values_list('pk', flat=True)),
        )

    def test_hidden_model_and_protected_fk_dropdowns_scoped(self):
        # week: staff cannot browse Weeks, but must still pick one here.
        # task: PROTECT target, scoped like any other FK.
        form = self.add_form('assignment')
        weeks = set(form.fields['week'].queryset.values_list('pk', flat=True))
        self.assertEqual(weeks, set(self.year_a.weeks.values_list('pk', flat=True)))
        self.assertEqual(
            set(form.fields['task'].queryset.values_list('pk', flat=True)),
            {self.task_a.pk},
        )

    def test_post_with_foreign_fk_is_rejected(self):
        self.client.force_login(self.staff_a)
        response = self.client.post('/admin/core/schoolyear/add/', {
            'school': self.school_b.pk,
            'name': '2027-2028',
            'start_date': '2027-09-06',
            'end_date': '2028-06-30',
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('school', response.context['adminform'].form.errors)
        self.assertEqual(SchoolYear.objects.filter(school=self.school_b).count(), 1)

    def test_list_filter_shows_only_own_school(self):
        self.client.force_login(self.staff_a)
        response = self.client.get('/admin/core/student/')
        self.assertContains(response, 'MFR Alpha')
        self.assertNotContains(response, 'MFR Beta')

    def test_autocomplete_is_scoped(self):
        # AutocompleteJsonView delegates to the target admin's get_queryset.
        self.client.force_login(self.staff_a)
        response = self.client.get(reverse('admin:autocomplete'), {
            'app_label': 'core',
            'model_name': 'enrollment',
            'field_name': 'student',
            'term': '',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [row['id'] for row in response.json()['results']],
            [str(self.student_a.pk)],
        )


class MultiSchoolStaffAdminTests(ScopedAdminTestCase):
    def test_two_memberships_see_both_schools_once(self):
        # unique_user_school keeps the join single-rowed — no .distinct() needed.
        self.client.force_login(self.staff_ab)
        response = self.client.get('/admin/core/schoolyear/')
        changelist = response.context['cl']
        self.assertEqual(
            set(changelist.queryset.values_list('pk', flat=True)),
            {self.year_a.pk, self.year_b.pk},
        )
        self.assertEqual(len(changelist.result_list), 2)

    def test_two_memberships_dropdown_has_both(self):
        form = self.add_form('schoolyear', user=self.staff_ab)
        self.assertEqual(
            set(form.fields['school'].queryset.values_list('pk', flat=True)),
            {self.school_a.pk, self.school_b.pk},
        )


class ScopedAdminActionTests(ScopedAdminTestCase):
    def post(self, url_name, objects, action, data=None):
        return self.client.post(reverse(url_name), {
            'action': action,
            ACTION_CHECKBOX_NAME: [obj.pk for obj in objects],
            **(data or {}),
        }, follow=True)

    def test_staff_can_generate_classes_for_own_year(self):
        self.client.force_login(self.staff_a)
        self.post('admin:core_schoolyear_changelist', [self.year_a],
                  'generate_classes', {'confirmed': '1', 'names': '3A\n3B'})
        self.assertEqual(
            set(self.year_a.classes.values_list('name', flat=True)),
            {'4A', '3A', '3B'},
        )

    def test_staff_action_on_other_school_year_does_nothing(self):
        # The pk survives the selection check but not the scoped pk__in filter.
        self.client.force_login(self.staff_a)
        self.post('admin:core_schoolyear_changelist', [self.year_b],
                  'generate_classes', {'confirmed': '1', 'names': '3A\n3B'})
        self.assertEqual(self.year_b.classes.count(), 1)

    def test_staff_generate_tasks_only_touches_own_school(self):
        self.client.force_login(self.staff_a)
        self.post('admin:core_schoolyear_changelist', [self.year_a],
                  'generate_tasks', {'confirmed': '1', 'names': 'Foyer'})
        self.assertEqual(
            set(self.school_a.tasks.values_list('name', flat=True)),
            {'Vaisselle A', 'Foyer'},
        )
        self.assertEqual(self.school_b.tasks.count(), 1)

    def test_staff_cannot_reach_the_school_changelist(self):
        self.client.force_login(self.staff_a)
        response = self.client.post('/admin/core/school/', {
            'action': 'delete_selected',
            ACTION_CHECKBOX_NAME: [self.school_a.pk],
        })
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Task.objects.count(), 2)
