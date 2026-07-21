from datetime import date

from rest_framework.test import APITestCase

from .factories import make_school, make_user, make_year


class SchoolScopingAPITests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school_a = make_school('MFR A')
        cls.school_b = make_school('MFR B')
        cls.user_a = make_user('staff-a', school=cls.school_a)
        cls.superuser = make_user('root')
        cls.superuser.is_superuser = True
        cls.superuser.save()
        cls.no_school_user = make_user('orphan')
        cls.year_a = make_year(cls.school_a)
        cls.year_b = make_year(cls.school_b)

    def test_unauthenticated_401(self):
        response = self.client.get('/api/schools/')
        self.assertEqual(response.status_code, 401)

    def test_member_without_school_403(self):
        self.client.force_authenticate(self.no_school_user)
        response = self.client.get('/api/schools/')
        self.assertEqual(response.status_code, 403)

    def test_list_excludes_other_school(self):
        self.client.force_authenticate(self.user_a)
        response = self.client.get('/api/school-years/')
        ids = [row['id'] for row in response.data['results']]
        self.assertEqual(ids, [self.year_a.pk])

    def test_detail_other_school_404(self):
        self.client.force_authenticate(self.user_a)
        response = self.client.get(f'/api/school-years/{self.year_b.pk}/')
        self.assertEqual(response.status_code, 404)

    def test_superuser_sees_all(self):
        self.client.force_authenticate(self.superuser)
        response = self.client.get('/api/schools/')
        self.assertEqual(response.data['count'], 2)

    def test_create_year_in_foreign_school_400(self):
        self.client.force_authenticate(self.user_a)
        response = self.client.post('/api/school-years/', {
            'school': self.school_b.pk,
            'name': '2027-2028',
            'start_date': '2027-09-06',
            'end_date': '2028-06-23',
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn('school', response.data)

    def test_create_year_generates_weeks(self):
        self.client.force_authenticate(self.user_a)
        response = self.client.post('/api/school-years/', {
            'school': self.school_a.pk,
            'name': '2027-2028',
            'start_date': '2027-09-06',
            'end_date': '2028-06-23',
        })
        self.assertEqual(response.status_code, 201)
        year_id = response.data['id']
        weeks = self.client.get(f'/api/weeks/?school_year={year_id}')
        self.assertGreater(weeks.data['count'], 30)

    def test_year_rejects_inverted_dates(self):
        self.client.force_authenticate(self.user_a)
        response = self.client.post('/api/school-years/', {
            'school': self.school_a.pk,
            'name': '2028-2029',
            'start_date': '2028-06-23',
            'end_date': '2027-09-06',
        })
        self.assertEqual(response.status_code, 400)

    def test_week_date_filter(self):
        self.client.force_authenticate(self.user_a)
        # a Thursday inside the first week of year_a (starts Mon 2026-09-07)
        response = self.client.get('/api/weeks/?date=2026-09-10')
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(
            response.data['results'][0]['start_date'], '2026-09-07'
        )
        self.assertEqual(response.data['results'][0]['label'], '2026-W37')

    def test_week_list_scoped(self):
        self.client.force_authenticate(self.user_a)
        response = self.client.get('/api/weeks/')
        years = {row['school_year'] for row in response.data['results']}
        self.assertEqual(years, {self.year_a.pk})
