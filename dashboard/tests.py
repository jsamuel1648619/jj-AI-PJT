from importlib import import_module
from types import SimpleNamespace

from django.apps import apps
from django.db import connection
from django.test import Client, TestCase

from debugdna.test_integration import seed_attempt
from growthplan.models import DiagnosisRoadmap, LearningTask


class DashboardIntegrationTests(TestCase):
    def setUp(self):
        self.client.get('/')
        self.owner = self.client.session['diagnosis_owner']

    def plan(self, attempt=None, weeks=2):
        if attempt is None:
            response = self.client.post('/api/growthplan/generate/', {
                'skills': [{'name': 'Python', 'current_level': 1, 'target_level': 3}],
                'weeks': weeks, 'hours_per_week': 3, 'use_llm': False}, content_type='application/json')
        else:
            response = self.client.post('/api/growthplan/from-diagnosis/', {'attempt_id': str(attempt.pk), 'weeks': weeks,
                'hours_per_week': 3, 'use_llm': False}, content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def complete(self, task_id, value, client=None):
        return (client or self.client).post(f'/api/growthplan/tasks/{task_id}/completion/', {'completed': value}, content_type='application/json')

    def test_empty_dashboard_has_no_fabricated_scores_or_tasks_and_uses_base(self):
        response = self.client.get('/')
        self.assertTemplateUsed(response, 'base.html')
        self.assertContains(response, 'DevDNA')
        data = self.client.get('/api/dashboard/').json()
        self.assertIsNone(data['diagnosis'])
        self.assertIsNone(data['target_job'])
        self.assertIsNone(data['roadmap'])
        self.assertEqual(data['priority_tasks'], [])
        self.assertEqual(data['debugdna']['categories'], {})
        self.assertEqual(data['diagnosis_count'], 0)
        self.assertContains(self.client.get('/debugdna/'), 'id="analysis-form"')

    def test_dashboard_combines_stored_job_scores_mistakes_and_plan(self):
        attempt = seed_attempt(self.owner)
        diagnosis = attempt.diagnosis
        diagnosis.company, diagnosis.division, diagnosis.role, diagnosis.job_title = '테스트 기업', '플랫폼', '백엔드', '백엔드 채용공고'
        diagnosis.save()
        plan = self.plan(attempt)
        # A newer diagnosis must not replace the diagnosis linked to the selected plan.
        seed_attempt(self.owner)
        payload = {'original': 'for i in range(2)\n print(i)', 'corrected': 'for i in range(2):\n print(i)', 'use_llm': False}
        self.assertEqual(self.client.post('/api/analyze/', payload, content_type='application/json').status_code, 200)
        self.client.post('/api/analyze/', payload, content_type='application/json')
        data = self.client.get('/api/dashboard/').json()
        self.assertEqual(data['target_job']['role'], '백엔드')
        self.assertEqual(data['target_job']['source_url'], diagnosis.source_url)
        self.assertEqual(data['diagnosis']['attempt_id'], str(attempt.pk))
        self.assertEqual([item['score'] for item in data['diagnosis']['scores']], [1, 1])
        self.assertEqual(data['diagnosis_count'], 2)
        self.assertEqual(data['debugdna']['analysis_count'], 1)
        self.assertEqual(data['debugdna']['categories'], {'문법 오류': 1})
        self.assertEqual(data['roadmap']['roadmap_id'], plan['roadmap_id'])
        self.assertEqual(data['roadmap']['progress']['total'], 2)
        self.assertEqual(data['roadmap']['progress']['percent'], 0)
        self.assertEqual(len(data['priority_tasks']), 2)
        self.assertEqual(len(data['recent_analyses']), 1)

    def test_complete_cancel_and_dashboard_update_are_db_backed_and_idempotent(self):
        plan = self.plan(weeks=2)
        task = plan['tasks'][0]
        response = self.complete(task['id'], True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['progress']['percent'], 50)
        stamp = response.json()['task']['completed_at']
        repeated = self.complete(task['id'], True).json()
        self.assertEqual(repeated['task']['completed_at'], stamp)
        self.assertEqual(repeated['progress']['completed'], 1)
        dashboard = self.client.get('/api/dashboard/').json()
        self.assertEqual(dashboard['roadmap']['progress']['percent'], 50)
        self.assertNotIn(task['id'], [item['id'] for item in dashboard['priority_tasks']])
        reopened = Client()
        reopened.cookies = self.client.cookies.copy()
        self.assertTrue(reopened.get(f"/api/growthplan/roadmaps/{plan['roadmap_id']}/").json()['tasks'][0]['completed'])
        canceled = self.complete(task['id'], False, reopened).json()
        self.assertIsNone(canceled['task']['completed_at'])
        self.assertEqual(canceled['progress']['percent'], 0)
        self.assertEqual(self.client.get('/api/dashboard/').json()['roadmap']['progress']['completed'], 0)

    def test_plan_progress_is_independent_and_new_plans_start_incomplete(self):
        first = self.plan()
        self.complete(first['tasks'][0]['id'], True)
        second = self.plan()
        latest = self.client.get('/api/dashboard/').json()['roadmap']
        self.assertEqual(latest['roadmap_id'], second['roadmap_id'])
        self.assertEqual(latest['progress']['completed'], 0)
        old = self.client.get('/api/dashboard/', {'roadmap': first['roadmap_id']}).json()['roadmap']
        self.assertEqual(old['progress']['completed'], 1)
        self.assertNotEqual(first['tasks'][0]['id'], second['tasks'][0]['id'])

    def test_owner_isolation_for_dashboard_plan_list_and_mutations(self):
        plan = self.plan()
        other = Client()
        other.get('/')
        self.assertEqual(other.get('/api/dashboard/').json()['roadmaps'], [])
        self.assertEqual(other.get('/api/dashboard/', {'roadmap': plan['roadmap_id']}).status_code, 404)
        self.assertEqual(other.get(f"/api/growthplan/roadmaps/{plan['roadmap_id']}/").status_code, 404)
        self.assertEqual(other.get('/api/growthplan/roadmaps/').json()['roadmaps'], [])
        self.assertEqual(self.complete(plan['tasks'][0]['id'], True, other).status_code, 404)
        self.assertFalse(LearningTask.objects.get(pk=plan['tasks'][0]['id']).completed)

    def test_completion_requires_csrf_strict_boolean_and_post(self):
        plan = self.plan()
        url = f"/api/growthplan/tasks/{plan['tasks'][0]['id']}/completion/"
        secured = Client(enforce_csrf_checks=True)
        secured.cookies = self.client.cookies.copy()
        self.assertEqual(secured.post(url, {'completed': True}, content_type='application/json').status_code, 403)
        self.assertEqual(secured.post(url, {'completed': True}, content_type='application/json', HTTP_X_CSRFTOKEN=secured.cookies['csrftoken'].value).status_code, 200)
        for payload in [{}, {'completed': 'false'}, {'completed': 1}, {'completed': False, 'owner': self.owner}]:
            self.assertEqual(self.client.post(url, payload, content_type='application/json').status_code, 400)
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertTrue(LearningTask.objects.get(pk=plan['tasks'][0]['id']).completed)

    def test_two_clients_complete_different_tasks_without_overwriting_progress(self):
        plan = self.plan()
        other_tab = Client()
        other_tab.cookies = self.client.cookies.copy()
        self.complete(plan['tasks'][0]['id'], True)
        response = self.complete(plan['tasks'][1]['id'], True, other_tab).json()
        self.assertEqual(response['progress']['percent'], 100)
        self.complete(plan['tasks'][0]['id'], False)
        self.assertTrue(LearningTask.objects.get(pk=plan['tasks'][1]['id']).completed)
        self.assertEqual(other_tab.get('/api/dashboard/').json()['roadmap']['progress']['percent'], 50)

    def test_zero_tasks_and_unassessed_scores_are_not_invented(self):
        attempt = seed_attempt(self.owner)
        result = attempt.result
        result['requirements'][0]['score'] = None
        result['requirements'][0]['current_level'] = None
        attempt.result = result
        attempt.save()
        self.assertIsNone(self.client.get('/api/dashboard/').json()['diagnosis']['scores'][0]['score'])
        response = self.client.post('/api/growthplan/generate/', {'skills': [{'name': 'Python', 'current_level': 5, 'target_level': 3}], 'use_llm': False}, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        data = self.client.get('/api/dashboard/').json()
        self.assertEqual(data['roadmap']['tasks'], [])
        self.assertEqual(data['roadmap']['progress']['percent'], 0)
        self.assertEqual(data['priority_tasks'], [])

    def test_existing_plan_migration_backfills_real_tasks_and_owner_only(self):
        attempt = seed_attempt(self.owner)
        from growthplan.planning import PlanInput, build_plan
        config = PlanInput(skills=[{'name': 'Python', 'current_level': 1}], weeks=2)
        record = DiagnosisRoadmap.objects.create(attempt=attempt, owner='', configuration=config.model_dump(), result=build_plan(config))
        migration = import_module('growthplan.migrations.0002_diagnosisroadmap_owner_and_more')
        editor = SimpleNamespace(connection=connection)
        migration.backfill_tasks(apps, editor)
        migration.backfill_tasks(apps, editor)
        record.refresh_from_db()
        self.assertEqual(record.owner, self.owner)
        self.assertEqual(list(record.tasks.order_by('week').values_list('week', flat=True)), [1, 2])
        self.assertEqual(record.tasks.filter(completed=True).count(), 0)
        self.assertEqual(self.client.get('/api/dashboard/').json()['roadmap']['progress']['total'], 2)
