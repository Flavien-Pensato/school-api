import io

from openpyxl import Workbook
from rest_framework.test import APITestCase

from core.models import Enrollment, Student

from .factories import (
    make_class,
    make_school,
    make_student,
    make_user,
    make_year,
)


def csv_file(content, name='students.csv'):
    file = io.BytesIO(content.encode('utf-8'))
    file.name = name
    return file


def xlsx_file(rows, name='students.xlsx'):
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    file = io.BytesIO()
    workbook.save(file)
    file.seek(0)
    file.name = name
    return file


class StudentImportTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = make_school('MFR A')
        cls.other_school = make_school('MFR B')
        cls.user = make_user('staff-a', school=cls.school)
        cls.year = make_year(cls.school, with_weeks=False)
        cls.cls_4a = make_class(cls.year, '4A')
        cls.cls_4b = make_class(cls.year, '4B')
        cls.other_year = make_year(cls.other_school, with_weeks=False)
        cls.other_class = make_class(cls.other_year, '3C')

    def setUp(self):
        self.client.force_authenticate(self.user)

    def import_(self, file, school_class=None):
        return self.client.post('/api/students/import/', {
            'file': file,
            'school_class': (school_class or self.cls_4a).pk,
        }, format='multipart')

    def test_csv_happy_path(self):
        response = self.import_(csv_file(
            'first_name,last_name,external_id\n'
            'Jean,Dupont,E1\n'
            'Marie,Curie,E2\n'
        ))
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['created_students'], 2)
        self.assertEqual(response.data['enrollments_created'], 2)
        self.assertEqual(
            Enrollment.objects.filter(school_class=self.cls_4a).count(), 2
        )

    def test_csv_french_headers_semicolon(self):
        response = self.import_(csv_file(
            'Prénom;Nom;Identifiant\n'
            'Jean;Dupont;E1\n'
        ))
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['created_students'], 1)
        student = Student.objects.get(external_id='E1')
        self.assertEqual(student.first_name, 'Jean')
        self.assertEqual(student.last_name, 'Dupont')

    def test_xlsx_happy_path(self):
        response = self.import_(xlsx_file([
            ['prénom', 'nom'],
            ['Jean', 'Dupont'],
            ['Marie', 'Curie'],
        ]))
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['created_students'], 2)

    def test_reimport_is_noop(self):
        content = 'first_name,last_name,external_id\nJean,Dupont,E1\n'
        self.import_(csv_file(content))
        response = self.import_(csv_file(content))
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['created_students'], 0)
        self.assertEqual(response.data['reused_students'], 1)
        self.assertEqual(response.data['already_enrolled'], 1)
        self.assertEqual(Student.objects.count(), 1)
        self.assertEqual(Enrollment.objects.count(), 1)

    def test_bad_row_aborts_everything(self):
        response = self.import_(csv_file(
            'first_name,last_name\n'
            'Jean,Dupont\n'
            'Marie,\n'  # missing last_name → row 3
        ))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['errors'][0]['row'], 3)
        self.assertEqual(Student.objects.count(), 0)
        self.assertEqual(Enrollment.objects.count(), 0)

    def test_missing_header(self):
        response = self.import_(csv_file('prénom\nJean\n'))
        self.assertEqual(response.status_code, 400)
        self.assertIn('last_name', str(response.data['errors']))

    def test_unsupported_extension(self):
        response = self.import_(csv_file('x', name='students.pdf'))
        self.assertEqual(response.status_code, 400)

    def test_enrolled_in_other_class_is_error(self):
        student = make_student(self.school, 'Jean', 'Dupont')
        Enrollment.objects.create(
            student=student, school_year=self.year, school_class=self.cls_4b
        )
        response = self.import_(csv_file(
            'first_name,last_name\nJean,Dupont\n'
        ))
        self.assertEqual(response.status_code, 400)
        self.assertIn('4B', str(response.data['errors']))
        # nothing changed
        self.assertEqual(
            Enrollment.objects.get(student=student).school_class, self.cls_4b
        )

    def test_foreign_school_class_rejected(self):
        response = self.import_(
            csv_file('first_name,last_name\nJean,Dupont\n'),
            school_class=self.other_class,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Student.objects.count(), 0)

    def test_match_by_external_id_even_if_renamed(self):
        make_student(self.school, 'Jean', 'Dupont', external_id='E1')
        response = self.import_(csv_file(
            'first_name,last_name,external_id\nJohnny,Dupont,E1\n'
        ))
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['reused_students'], 1)
        self.assertEqual(Student.objects.count(), 1)
