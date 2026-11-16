import json
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase
from pydantic import ValidationError
from selenium.common.exceptions import TimeoutException

from .analysis import EvaluationInput, Requirement, analyze_radar, normalize_model_requirement
from .collection import CollectionFailure, CollectionInput, browser, collect_posting, public_url


POSTING = '필수 역량\nPython으로 API를 독립적으로 개발하고 문제를 해결합니다.\nDjango 프로젝트 활용 경험\n우대 사항\nDocker 기초 실습 경험'


def requirements():
    return [
        {'name': 'Python', 'importance': 'required', 'evidence': 'Python으로 API를 독립적으로 개발하고 문제를 해결합니다.',
         'required_level': 4, 'level_basis': 'inferred', 'level_reason': '독립적인 구현과 문제 해결을 요구함',
         'level_evidence': '독립적으로 개발하고 문제를 해결합니다.', 'weight': 5, 'weight_reason': '핵심 필수 역량'},
        {'name': 'Django', 'importance': 'required', 'evidence': 'Django 프로젝트 활용 경험',
         'required_level': 3, 'level_basis': 'inferred', 'level_reason': '프로젝트 활용을 요구함',
         'level_evidence': 'Django 프로젝트 활용 경험', 'weight': 4, 'weight_reason': '필수 프레임워크'},
        {'name': 'Docker', 'importance': 'preferred', 'evidence': 'Docker 기초 실습 경험',
         'required_level': 2, 'level_basis': 'inferred', 'level_reason': '기초 실습 경험',
         'level_evidence': 'Docker 기초 실습 경험', 'weight': 2, 'weight_reason': '우대 역량'},
    ]


class EvaluationPipelineTests(TestCase):
    def payload(self):
        return {'job_posting': POSTING, 'source_url': 'https://example.com/job', 'use_llm': True,
                'requirements': requirements(), 'current_skills': [
                    {'name': '파이썬', 'level': 1, 'evidence': '기초 실습'},
                    {'name': 'Django', 'level': 2, 'evidence': '게시판'},
                    {'name': 'Docker', 'level': 0}]}

    def test_assessment_to_growthplan_preserves_weighted_priority(self):
        response = self.client.post('/api/skillradar/evaluate/', self.payload(), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['source_url'], 'https://example.com/job')
        self.assertEqual(data['learning_priorities'], ['Python', 'Django', 'Docker'])
        self.assertEqual([(s['gap'], s['priority_score']) for s in data['requirements']], [(3, 15), (1, 4), (2, 4)])
        fields = ('name', 'current_level', 'required_level', 'level_basis', 'importance', 'weight')
        skills = [{**{key: item[key] for key in fields}, 'target_level': item['required_level'], 'experience': item['current_evidence']} for item in data['requirements']]
        plan = self.client.post('/api/growthplan/generate/', {'skills': skills, 'weeks': 6, 'hours_per_week': 4}, content_type='application/json')
        self.assertEqual(plan.status_code, 200)
        result = plan.json()
        self.assertEqual([s['name'] for s in result['priorities']], data['learning_priorities'])
        self.assertEqual(result['weeks'][0]['gap'], 3)
        self.assertEqual(result['weeks'][0]['priority_score'], 15)
        self.assertEqual(result['priorities'][0]['experience'], '기초 실습')
        self.assertEqual(result['total_hours'], 24)

    def test_unknowns_not_converted_to_zero_and_overqualified_gap_clamped(self):
        payload = self.payload()
        payload['requirements'][1] = {'name': 'Django', 'importance': 'required', 'evidence': 'Django 프로젝트 활용 경험'}
        payload['current_skills'] = [{'name': 'Python', 'level': 5}, {'name': 'Django', 'level': 1}]
        data = analyze_radar(EvaluationInput(**payload), requirements=EvaluationInput(**payload).requirements)
        skills = {x['name']: x for x in data['requirements']}
        self.assertEqual(skills['Python']['gap'], 0)
        self.assertIsNone(skills['Python']['priority_rank'])
        self.assertIsNone(skills['Django']['gap'])
        self.assertIsNone(skills['Docker']['current_level'])
        self.assertIsNone(skills['Docker']['priority_score'])

    def test_level_validation_and_grounding(self):
        for changes in [{'required_level': 6}, {'required_level': 4, 'level_basis': 'unknown'},
                        {'required_level': 4, 'level_basis': 'inferred', 'level_reason': '', 'level_evidence': ''},
                        {'required_level': None, 'level_basis': 'explicit'}, {'weight': 0}, {'weight': True}]:
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                Requirement(**{**requirements()[0], **changes})
        for field in ['evidence', 'level_evidence']:
            payload = self.payload()
            payload['requirements'][0][field] = '공고에 없는 인용'
            self.assertEqual(self.client.post('/api/skillradar/evaluate/', payload, content_type='application/json').status_code, 400)

    def test_model_name_and_false_explicit_label_are_corrected(self):
        item = Requirement(**{**requirements()[0], 'name': 'Python API 개발', 'level_basis': 'explicit'})
        corrected = normalize_model_requirement(item)
        self.assertEqual(corrected.name, 'Python')
        self.assertEqual(corrected.level_basis, 'inferred')
        literal = Requirement(**{**requirements()[0], 'level_basis': 'explicit', 'level_evidence': '숙련도 4/5'})
        self.assertEqual(normalize_model_requirement(literal).level_basis, 'explicit')

    @patch('skillradar.analysis.request.urlopen')
    def test_qwen_schema_contains_levels_and_rejects_false_evidence(self, mocked):
        mocked.return_value.__enter__.return_value.read.return_value = json.dumps({'message': {'content': json.dumps({'requirements': requirements()})}}).encode()
        payload = {'job_posting': POSTING, 'use_llm': True}
        response = self.client.post('/api/skillradar/analyze/', payload, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['requirements'][0]['required_level'], 4)
        schema = json.loads(mocked.call_args.args[0].data)['format']
        self.assertIn('required_level', schema['$defs']['Requirement']['properties'])
        self.assertEqual(set(schema['$defs']['Requirement']['required']), set(schema['$defs']['Requirement']['properties']))
        bad = requirements()
        bad[0]['level_evidence'] = '조작된 인용'
        mocked.return_value.__enter__.return_value.read.return_value = json.dumps({'message': {'content': json.dumps({'requirements': bad})}}).encode()
        self.assertEqual(self.client.post('/api/skillradar/analyze/', payload, content_type='application/json').status_code, 502)


class CollectionTests(SimpleTestCase):
    def test_query_validation(self):
        for payload in [{}, {'company': '회사'}, {'url': 'x'*2001}]:
            with self.assertRaises(ValidationError):
                CollectionInput(**payload)
        self.assertEqual(CollectionInput(company='회사', division='플랫폼', role='개발').role, '개발')

    @patch('skillradar.collection.socket.getaddrinfo')
    def test_public_url_validation(self, dns):
        for url in ['file:///etc/passwd', 'http://user:pw@example.com', 'http://example.com:8000', 'javascript:alert(1)']:
            with self.assertRaises(ValueError):
                public_url(url)
        for address in ['127.0.0.1', '10.0.0.1', '169.254.169.254', '::1']:
            dns.return_value = [(0, 0, 0, '', (address, 80))]
            with self.assertRaises(ValueError):
                public_url('http://example.com')
        dns.return_value = [(0, 0, 0, '', ('93.184.216.34', 443))]
        self.assertEqual(public_url('https://example.com/job'), 'https://example.com/job')

    @patch('skillradar.collection.webdriver.Chrome')
    def test_browser_cleanup_on_failure(self, chrome):
        with self.assertRaises(TimeoutException):
            with browser():
                raise TimeoutException('failed')
        chrome.return_value.quit.assert_called_once()

    @patch('skillradar.collection.public_url', side_effect=lambda url: url)
    @patch('skillradar.collection.browser')
    def test_collection_returns_body_source_and_truncation(self, mock_browser, valid_url):
        driver = MagicMock()
        mock_browser.return_value.__enter__.return_value = driver
        driver.find_elements.return_value = [object()]
        driver.execute_script.return_value = '공고 본문 '*7000
        driver.current_url = 'https://example.com/final'
        driver.title = '개발자 채용'
        result = collect_posting(CollectionInput(url='https://example.com/job'))
        self.assertEqual(len(result['body']), 30000)
        self.assertTrue(result['truncated'])
        self.assertEqual(result['source_url'], driver.current_url)
        self.assertEqual(result['requested_url'], 'https://example.com/job')
        self.assertIn('collected_at', result)

    @patch('skillradar.collection.public_url', side_effect=lambda url: url)
    @patch('skillradar.collection.browser')
    def test_search_query_returns_candidates_for_confirmation(self, mock_browser, valid_url):
        driver = MagicMock()
        mock_browser.return_value.__enter__.return_value = driver
        link = MagicMock()
        link.get_attribute.return_value = 'https://example.com/job'
        link.text = '채용공고'
        driver.find_elements.return_value = [link]
        data = collect_posting(CollectionInput(company='회사', division='플랫폼', role='개발자'))
        self.assertEqual(data['query'], '회사 플랫폼 개발자 채용 공고')
        self.assertEqual(data['kind'], 'candidates')
        self.assertEqual(data['candidates'][0]['url'], 'https://example.com/job')

    @patch('skillradar.views.collect_posting', side_effect=CollectionFailure('수집 실패'))
    def test_collection_failure_allows_manual_input(self, collect):
        response = self.client.post('/api/skillradar/collect/', {'url': 'https://example.com/job'}, content_type='application/json')
        self.assertEqual(response.status_code, 422)
        self.assertTrue(response.json()['manual_input_required'])
        response = self.client.post('/api/skillradar/analyze/', {'job_posting': POSTING, 'use_llm': False}, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['requirements'])
