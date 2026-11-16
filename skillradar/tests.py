import json
from unittest.mock import patch
from urllib.error import URLError

from django.test import Client, SimpleTestCase
from pydantic import ValidationError

from .analysis import RadarInput, analyze_radar


class SkillRadarTests(SimpleTestCase):
    def payload(self, **changes):
        return {'job_posting': '자격 요건\nPython, Django 경험\n우대 사항\nDocker 경험',
                'current_skills': [{'name': '파이썬', 'level': 3, 'evidence': 'API 개발'}],
                'use_llm': False, **changes}

    def test_keyword_comparison_preserves_unassessed_and_evidence(self):
        result = analyze_radar(RadarInput(**self.payload()))
        skills = {item['name']: item for item in result['requirements']}
        self.assertEqual(skills['Python']['current_level'], 3)
        self.assertEqual(skills['Python']['current_evidence'], 'API 개발')
        self.assertEqual(skills['Python']['evidence'], 'Python, Django 경험')
        self.assertEqual(skills['Python']['importance'], 'required')
        self.assertIsNone(skills['Django']['current_level'])
        self.assertEqual(skills['Docker']['importance'], 'preferred')
        self.assertEqual(result['summary']['unassessed'], 2)

    def test_alias_duplicates_and_level_validation(self):
        for skills in [[{'name': 'Python', 'level': 1}, {'name': '파이썬', 'level': 2}],
                       [{'name': 'Python', 'level': 6}], [{'name': 'Python', 'level': True}],
                       [{'name': ' ', 'level': 1}]]:
            with self.assertRaises(ValidationError):
                RadarInput(**self.payload(current_skills=skills))

    def test_zero_is_distinct_from_missing_and_unknown_skills(self):
        result = analyze_radar(RadarInput(**self.payload(current_skills=[{'name': 'Python', 'level': 0}, {'name': 'Rust', 'level': 2}])))
        python = next(x for x in result['requirements'] if x['name'] == 'Python')
        self.assertEqual(python['status'], 'not_started')
        self.assertEqual(result['unmatched_skills'], ['Rust'])

    def test_keyword_boundaries_and_empty_results(self):
        result = analyze_radar(RadarInput(**self.payload(job_posting='JavaScript, GitHub, PostgreSQL')))
        self.assertEqual({x['name'] for x in result['requirements']}, {'JavaScript', 'PostgreSQL'})
        self.assertEqual(analyze_radar(RadarInput(**self.payload(job_posting='함께 성장할 동료를 찾습니다.')))['requirements'], [])

    def test_csrf_and_request_validation(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.get('/skillradar/').status_code, 200)
        url = '/api/skillradar/analyze/'
        self.assertEqual(client.post(url, self.payload(), content_type='application/json').status_code, 403)
        response = client.post(url, self.payload(), content_type='application/json', HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
        self.assertEqual(response.status_code, 200)
        for payload in ['{', '{}', json.dumps(self.payload(job_posting=' ')), json.dumps(self.payload(job_posting='a'*30001))]:
            self.assertEqual(self.client.post(url, payload, content_type='application/json').status_code, 400)
        self.assertEqual(self.client.post(url, 'text', content_type='text/plain').status_code, 415)
        self.assertEqual(self.client.get(url).status_code, 405)

    @patch('skillradar.analysis.request.urlopen')
    def test_qwen_validated_deduplicated_and_grounded(self, mocked):
        extracted = {'requirements': [{'name': 'Python', 'importance': 'preferred', 'evidence': 'Python, Django 경험'}, {'name': '파이썬', 'importance': 'required', 'evidence': 'Python, Django 경험'}]}
        mocked.return_value.__enter__.return_value.read.return_value = json.dumps({'message': {'content': json.dumps(extracted)}}).encode()
        response = self.client.post('/api/skillradar/analyze/', self.payload(use_llm=True), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['summary']['total'], 1)
        self.assertEqual(response.json()['requirements'][0]['importance'], 'required')
        extracted['requirements'][0]['evidence'] = 'invented evidence'
        mocked.return_value.__enter__.return_value.read.return_value = json.dumps({'message': {'content': json.dumps(extracted)}}).encode()
        self.assertEqual(self.client.post('/api/skillradar/analyze/', self.payload(use_llm=True), content_type='application/json').status_code, 502)
        mocked.return_value.__enter__.return_value.read.return_value = b'{"message":{"content":"{}"}}'
        self.assertEqual(self.client.post('/api/skillradar/analyze/', self.payload(use_llm=True), content_type='application/json').status_code, 502)

    @patch('skillradar.analysis.request.urlopen', side_effect=URLError('offline'))
    def test_qwen_connection_failure(self, mocked):
        self.assertEqual(self.client.post('/api/skillradar/analyze/', self.payload(use_llm=True), content_type='application/json').status_code, 503)
