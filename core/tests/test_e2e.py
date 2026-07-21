import io

from rest_framework.test import APITestCase

from .factories import make_school, make_user


class EndToEndFlowTests(APITestCase):
    """Full staff workflow: year → import → groups → tasks → presences →
    4 weeks of rotation → stats spread ≤ 1 → dashboard."""

    @classmethod
    def setUpTestData(cls):
        cls.school = make_school()
        cls.user = make_user('staff', school=cls.school)

    def test_full_year_workflow(self):
        self.client.force_authenticate(self.user)

        year = self.client.post('/api/school-years/', {
            'school': self.school.pk,
            'name': '2026-2027',
            'start_date': '2026-09-07',
            'end_date': '2027-06-25',
        }).data
        klass = self.client.post('/api/classes/', {
            'school_year': year['id'], 'name': '4A',
        }).data

        file = io.BytesIO(
            'Prénom;Nom\nJean;Dupont\nMarie;Curie\nPaul;Martin\nLuc;Bernard\n'
            .encode('utf-8')
        )
        file.name = 'eleves.csv'
        imported = self.client.post('/api/students/import/', {
            'file': file, 'school_class': klass['id'],
        }, format='multipart')
        self.assertEqual(imported.data['created_students'], 4)

        groups = [
            self.client.post('/api/groups/', {
                'school_class': klass['id'], 'name': f'Groupe {i}',
            }).data
            for i in (1, 2)
        ]
        enrollments = self.client.get(
            f'/api/enrollments/?school_class={klass["id"]}'
        ).data['results']
        for enrollment, group in zip(
            enrollments, [groups[0], groups[0], groups[1], groups[1]]
        ):
            self.client.patch(
                f'/api/enrollments/{enrollment["id"]}/',
                {'group': group['id']},
            )

        for name in ('Vaisselle', 'Ménage'):
            created_task = self.client.post('/api/tasks/', {
                'school': self.school.pk, 'name': name,
            })
            self.assertEqual(created_task.status_code, 201, created_task.data)

        weeks = self.client.get(
            f'/api/weeks/?school_year={year["id"]}'
        ).data['results'][:4]
        for week in weeks:
            presence = self.client.post('/api/presences/', {
                'week': week['id'], 'school_class': klass['id'],
            })
            self.assertEqual(presence.status_code, 201, presence.data)
            generated = self.client.post(
                f'/api/weeks/{week["id"]}/generate-assignments/'
            )
            self.assertEqual(len(generated.data['assignments']), 2)

        stats = self.client.get(
            f'/api/school-years/{year["id"]}/stats/'
        ).data
        totals = [row['total'] for row in stats['groups']]
        self.assertEqual(totals, [4, 4])
        pair_counts = [
            count
            for row in stats['groups']
            for count in row['totals'].values()
        ]
        self.assertLessEqual(max(pair_counts) - min(pair_counts), 1)

        dashboard = self.client.get(
            f'/api/weeks/{weeks[0]["id"]}/dashboard/'
        ).data
        group_rows = dashboard['classes'][0]['groups']
        self.assertEqual(len(group_rows), 2)
        self.assertTrue(all(len(g['students']) == 2 for g in group_rows))
        self.assertTrue(all(g['task'] for g in group_rows))
