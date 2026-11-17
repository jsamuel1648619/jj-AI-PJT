import json
from unittest.mock import patch
from urllib.error import URLError
from django.test import Client, TestCase
from pydantic import ValidationError
from .planning import PlanInput, build_plan


class GrowthPlanTests(TestCase):
    def payload(self, **updates):
        return {'skills': [{'name': 'Docker', 'current_level': 0, 'importance': 'preferred'},
                           {'name': 'Python', 'current_level': 1, 'importance': 'required'},
                           {'name': 'Django', 'current_level': None, 'importance': 'required'}],
                'weeks': 4, 'hours_per_week': 5, 'weaknesses': '경계값 누락', **updates}

    def test_schedule_priorities_budget_and_diagnosis(self):
        result = build_plan(PlanInput(**self.payload()))
        self.assertEqual([w['skill'] for w in result['weeks']], ['Python', 'Django', 'Docker', 'Python'])
        self.assertEqual([w['week'] for w in result['weeks']], [1, 2, 3, 4])
        self.assertEqual(result['total_hours'], 20)
        self.assertTrue(all(w['hours'] == 5 for w in result['weeks']))
        self.assertIn('진단', result['weeks'][1]['objective'])
        self.assertTrue(all('경계값 누락' in w['review'] for w in result['weeks']))

    def test_deferred_and_met_goals(self):
        result = build_plan(PlanInput(**self.payload(weeks=1)))
        self.assertEqual(result['deferred_skills'], ['Django', 'Docker'])
        result = build_plan(PlanInput(**self.payload(skills=[{'name': 'Python', 'current_level': 4}])))
        self.assertEqual(result['weeks'], [])
        self.assertEqual(result['total_hours'], 0)
        self.assertEqual(result['met_skills'], ['Python'])

    def test_validation_bounds_and_duplicate_aliases(self):
        for updates in [{'skills': []}, {'weeks': 0}, {'weeks': 13}, {'hours_per_week': 41},
                        {'hours_per_week': True}, {'weaknesses': 'a'*5001},
                        {'skills': [{'name': 'Python', 'current_level': 6}]},
                        {'skills': [{'name': 'Python', 'target_level': 0}]},
                        {'skills': [{'name': 'Python'}, {'name': '파이썬'}]}]:
            with self.subTest(updates=updates), self.assertRaises(ValidationError):
                PlanInput(**self.payload(**updates))

    def test_api_csrf_and_invalid_requests(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.get('/growthplan/').status_code, 200)
        url = '/api/growthplan/generate/'
        self.assertEqual(client.post(url, self.payload(), content_type='application/json').status_code, 403)
        response = client.post(url, self.payload(), content_type='application/json', HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['total_hours'], 20)
        for body in ['{', '{}', 'null', '[]']:
            self.assertEqual(self.client.post(url, body, content_type='application/json').status_code, 400)
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.post(url, 'text', content_type='text/plain').status_code, 415)

    @patch('growthplan.planning.request.urlopen')
    def test_qwen_keeps_schedule_and_validates_response(self, mocked):
        content = {'weeks': [{'week': 1, 'objective': '함수 기초', 'exercise': '경계값 테스트 작성', 'completion': '테스트 통과'}]}
        mocked.return_value.__enter__.return_value.read.return_value = json.dumps({'message': {'content': json.dumps(content)}}).encode()
        result = build_plan(PlanInput(**self.payload(weeks=1, use_llm=True)))
        self.assertEqual(result['source'], 'qwen')
        self.assertEqual(result['weeks'][0]['skill'], 'Python')
        self.assertEqual(result['weeks'][0]['hours'], 5)
        self.assertIn('맞춤 실습: 경계값 테스트 작성', result['weeks'][0]['exercise'])
        self.assertIn('정상 입력 1개', result['weeks'][0]['completion'])
        self.assertIn('기대 결과와 실제 결과가 일치', result['weeks'][0]['completion'])
        sent = json.loads(json.loads(mocked.call_args.args[0].data)['messages'][-1]['content'])
        self.assertEqual([skill['name'] for skill in sent['input']['skills']], ['Python'])
        self.assertEqual(set(sent['schedule'][0]), {'week', 'skill', 'hours', 'stage'})
        self.assertEqual(result['deferred_skills'], ['Django', 'Docker'])
        for invalid in [{'weeks': []}, {'weeks': [{'week': 2, 'objective': '목표', 'exercise': '실습', 'completion': '기준'}]}, {}]:
            mocked.return_value.__enter__.return_value.read.return_value = json.dumps({'message': {'content': json.dumps(invalid)}}).encode()
            response = self.client.post('/api/growthplan/generate/', self.payload(weeks=1, use_llm=True), content_type='application/json')
            self.assertEqual(response.status_code, 502)

    @patch('growthplan.planning.request.urlopen', side_effect=URLError('offline'))
    def test_qwen_connection_failure(self, mocked):
        response = self.client.post('/api/growthplan/generate/', self.payload(use_llm=True), content_type='application/json')
        self.assertEqual(response.status_code, 503)

    @patch('growthplan.planning.request.urlopen')
    def test_no_model_call_when_goals_met(self, mocked):
        result = build_plan(PlanInput(**self.payload(use_llm=True, skills=[{'name': 'Python', 'current_level': 5}])))
        self.assertEqual(result['weeks'], [])
        mocked.assert_not_called()
