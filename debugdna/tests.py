import json
from unittest.mock import patch
from urllib.error import URLError
from django.test import TestCase, Client
from .analysis import AnalysisInput, analyze_code


class AnalysisTests(TestCase):
    def test_syntax_and_diff(self):
        result = analyze_code(AnalysisInput(original='for i in range(3)\n print(i)', corrected='for i in range(3):\n print(i)', use_llm=False))
        self.assertFalse(result['original']['valid'])
        self.assertTrue(result['corrected']['valid'])
        self.assertEqual(result['corrected']['structures']['loops'], 1)
        self.assertIn('+for i in range(3):', result['diff'])
        self.assertEqual(result['findings'][0]['category'], '문법 오류')

    def test_api_validation(self):
        for body in ['{', '{}', json.dumps({'original': '', 'corrected': 'pass'})]:
            self.assertEqual(self.client.post('/api/analyze/', body, content_type='application/json').status_code, 400)

    def test_api_and_csrf(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.get('/').status_code, 200)
        payload = {'original': 'print(1)', 'corrected': 'print(2)', 'use_llm': False}
        self.assertEqual(client.post('/api/analyze/', payload, content_type='application/json').status_code, 403)
        response = client.post('/api/analyze/', payload, content_type='application/json', HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['source'], 'static')

    @patch('debugdna.analysis.request.urlopen', side_effect=URLError('offline'))
    def test_model_unavailable(self, mocked):
        response = self.client.post('/api/analyze/', {'original': 'pass', 'corrected': 'pass', 'use_llm': True}, content_type='application/json')
        self.assertEqual(response.status_code, 503)

    @patch('debugdna.analysis.request.urlopen')
    def test_model_schema_validation(self, mocked):
        mocked.return_value.__enter__.return_value.read.return_value = json.dumps({'message': {'content': '{"summary":"missing findings"}'}}).encode()
        response = self.client.post('/api/analyze/', {'original': 'pass', 'corrected': 'pass', 'use_llm': True}, content_type='application/json')
        self.assertEqual(response.status_code, 502)
