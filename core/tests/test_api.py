from rest_framework.test import APITestCase

from core.models import Enrollment

from .factories import (
    make_class,
    make_group,
    make_school,
    make_student,
    make_user,
    make_year,
)


class CrudAPITests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = make_school('MFR A')
        cls.other_school = make_school('MFR B')
        cls.user = make_user('staff-a', school=cls.school)
        cls.year = make_year(cls.school)
        cls.cls_4a = make_class(cls.year, '4A')
        cls.group1 = make_group(cls.cls_4a, 'Groupe 1')
        cls.other_year = make_year(cls.other_school)
        cls.other_class = make_class(cls.other_year, '3C')

    def setUp(self):
        self.client.force_authenticate(self.user)

    def test_student_crud_and_search(self):
        created = self.client.post('/api/students/', {
            'school': self.school.pk,
            'first_name': 'Marie', 'last_name': 'Curie',
        })
        self.assertEqual(created.status_code, 201)
        found = self.client.get('/api/students/?search=cur')
        self.assertEqual(found.data['count'], 1)
        updated = self.client.patch(
            f'/api/students/{created.data["id"]}/', {'first_name': 'Maria'}
        )
        self.assertEqual(updated.data['first_name'], 'Maria')
        deleted = self.client.delete(f'/api/students/{created.data["id"]}/')
        self.assertEqual(deleted.status_code, 204)

    def test_enrollment_move_between_groups(self):
        student = make_student(self.school)
        group2 = make_group(self.cls_4a, 'Groupe 2')
        created = self.client.post('/api/enrollments/', {
            'student': student.pk,
            'school_year': self.year.pk,
            'school_class': self.cls_4a.pk,
            'group': self.group1.pk,
        })
        self.assertEqual(created.status_code, 201)
        moved = self.client.patch(
            f'/api/enrollments/{created.data["id"]}/', {'group': group2.pk}
        )
        self.assertEqual(moved.status_code, 200)
        self.assertEqual(moved.data['group'], group2.pk)

    def test_enrollment_group_from_other_class_rejected(self):
        student = make_student(self.school)
        cls_4b = make_class(self.year, '4B')
        group_4b = make_group(cls_4b, 'Groupe B1')
        response = self.client.post('/api/enrollments/', {
            'student': student.pk,
            'school_year': self.year.pk,
            'school_class': self.cls_4a.pk,
            'group': group_4b.pk,
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn('group', response.data)
        self.assertEqual(Enrollment.objects.count(), 0)

    def test_enrollment_cross_school_class_rejected(self):
        student = make_student(self.school)
        response = self.client.post('/api/enrollments/', {
            'student': student.pk,
            'school_year': self.year.pk,
            'school_class': self.other_class.pk,
        })
        self.assertEqual(response.status_code, 400)

    def test_presence_wrong_year_rejected(self):
        week = self.year.weeks.first()
        other_year_b = make_year(
            self.school, name='2027-2028',
            start=week.start_date.replace(year=2027),
            end=week.start_date.replace(year=2028), with_weeks=False,
        )
        cls_other_year = make_class(other_year_b, '5A')
        response = self.client.post('/api/presences/', {
            'week': week.pk, 'school_class': cls_other_year.pk,
        })
        self.assertEqual(response.status_code, 400)

    def test_presence_create_and_filter(self):
        week = self.year.weeks.first()
        created = self.client.post('/api/presences/', {
            'week': week.pk, 'school_class': self.cls_4a.pk,
        })
        self.assertEqual(created.status_code, 201)
        listed = self.client.get(f'/api/presences/?week={week.pk}')
        self.assertEqual(listed.data['count'], 1)

    def test_task_crud(self):
        created = self.client.post('/api/tasks/', {
            'school': self.school.pk, 'name': 'Vaisselle',
        })
        self.assertEqual(created.status_code, 201)
        retired = self.client.patch(
            f'/api/tasks/{created.data["id"]}/', {'is_active': False}
        )
        self.assertFalse(retired.data['is_active'])

    def test_groups_filtered_by_class(self):
        response = self.client.get(f'/api/groups/?school_class={self.cls_4a.pk}')
        self.assertEqual(response.data['count'], 1)
