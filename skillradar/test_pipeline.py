import json
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase
from pydantic import ValidationError
from selenium.common.exceptions import TimeoutException

from .analysis import EvaluationInput, Requirement, RadarInput, extract_requirements, analyze_radar, normalize_model_requirement, source_importance, parse_extraction
from .collection import CollectionFailure, CollectionInput, browser, collect_posting, public_url, search_links, source_matches


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
    def test_section_evidence_corrects_model_importance(self, mocked):
        posting = 'Role\nFirmware 개발\nRecommended Subject\n수치해석\nRequirements\nPython 기초 실습\nPluses\nISTQB 자격증'
        extracted = [{'name': name, 'importance': 'required', 'evidence': evidence, 'weight': 5}
                     for name, evidence in [('Firmware', 'Firmware 개발'), ('수치해석', '수치해석'),
                                            ('Python', 'Python 기초 실습'), ('ISTQB', 'ISTQB 자격증')]]
        mocked.return_value.__enter__.return_value.read.return_value = json.dumps({'message': {'content': json.dumps({'requirements': extracted})}}).encode()
        data = analyze_radar(EvaluationInput(job_posting=posting, requirements=[], use_llm=True))
        self.assertEqual([item['importance'] for item in data['requirements']], ['unspecified', 'unspecified', 'required', 'preferred'])
        self.assertEqual([item['weight'] for item in data['requirements']], [3, 3, 5, 2])
        self.assertEqual(data['summary']['required'], 1)
        self.assertIsNone(source_importance('Requirements\nPython\nPluses\nPython', 'Python'))
        self.assertIsNone(source_importance('Python 경험', 'Python 경험'))

    def test_null_model_level_is_conservatively_unknown_without_relaxing_client_validation(self):
        item = {**requirements()[0], 'required_level': None, 'level_basis': 'inferred'}
        parsed = parse_extraction(json.dumps({'requirements': [item]})).requirements[0]
        self.assertIsNone(parsed.required_level)
        self.assertEqual((parsed.level_basis, parsed.level_reason, parsed.level_evidence), ('unknown', '', ''))
        with self.assertRaises(ValidationError):
            Requirement(**item)
        with self.assertRaises(ValidationError):
            parse_extraction(json.dumps({'requirements': [{**item, 'required_level': 9}]}))
        with self.assertRaises(ValidationError):
            parse_extraction(json.dumps({'requirements': [{**item, 'level_basis': 'invalid'}]}))

    @patch('skillradar.analysis.request.urlopen')
    def test_qwen_schema_contains_levels_and_rejects_false_evidence(self, mocked):
        mocked.return_value.__enter__.return_value.read.return_value = json.dumps({'message': {'content': json.dumps({'requirements': requirements()})}}).encode()
        payload = {'job_posting': POSTING, 'use_llm': True}
        response = self.client.post('/api/skillradar/analyze/', payload, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['requirements'][0]['required_level'], 4)
        schema = json.loads(mocked.call_args.args[0].data)['format']
        first_payload = mocked.call_args.args[0].data
        self.client.post('/api/skillradar/analyze/', payload, content_type='application/json')
        self.assertEqual(mocked.call_args.args[0].data, first_payload)
        self.assertIsInstance(json.loads(first_payload)['options']['seed'], int)
        self.assertIn('required_level', schema['$defs']['Requirement']['properties'])
        self.assertEqual(set(schema['$defs']['Requirement']['required']), set(schema['$defs']['Requirement']['properties']))
        bad = requirements()
        bad[0]['level_evidence'] = '조작된 인용'
        mocked.return_value.__enter__.return_value.read.return_value = json.dumps({'message': {'content': json.dumps({'requirements': bad})}}).encode()
        self.assertEqual(self.client.post('/api/skillradar/analyze/', payload, content_type='application/json').status_code, 502)


class ExtractionConsistencyTests(SimpleTestCase):
    @patch('skillradar.analysis.request.urlopen')
    def test_aliases_deduplicated_before_comparison_independent_of_response_order(self, mocked):
        posting = '[우대사항]\nReact.js 경험\n## 주요 업무\nReact 개발\n**자격요건**\n리액트 활용\nTypeScript 활용'
        items = [
            {'name': 'React.js', 'importance': 'required', 'evidence': 'React.js 경험'},
            {'name': ' react   개발 ', 'importance': 'preferred', 'evidence': 'React 개발'},
            {'name': '리액트', 'importance': 'preferred', 'evidence': '리액트 활용'},
            {'name': 'TS', 'importance': 'preferred', 'evidence': 'TypeScript 활용'},
        ]
        results = []
        for ordered in (items, list(reversed(items))):
            mocked.return_value.__enter__.return_value.read.return_value = json.dumps(
                {'message': {'content': json.dumps({'requirements': ordered})}}).encode()
            results.append([item.model_dump() for item in extract_requirements(RadarInput(job_posting=posting))])
        self.assertEqual(results[0], results[1])
        self.assertEqual([item['name'] for item in results[0]], ['React', 'TypeScript'])
        self.assertEqual([item['importance'] for item in results[0]], ['required', 'required'])
        self.assertEqual(results[0][0]['evidence'], '리액트 활용')
        prompt = json.loads(mocked.call_args.args[0].data)['messages'][0]['content']
        self.assertIn('required > unspecified > preferred', prompt)
        self.assertIn('React.js'.casefold(), prompt)

    @patch('skillradar.analysis.request.urlopen')
    def test_general_requirement_precedes_preferred_and_keeps_distinct_skills(self, mocked):
        posting = 'Preferred\nPython 경험\nResponsibilities\nPython 개발\nJava 및 JavaScript 개발\n문제 해결'
        items = [
            {'name': name, 'importance': 'preferred', 'evidence': evidence}
            for name, evidence in [('PYTHON', 'Python 경험'), ('파이썬', 'Python 개발'),
                                   ('Java', 'Java 및 JavaScript 개발'),
                                   ('JS', 'Java 및 JavaScript 개발'), ('문제   해결', '문제 해결')]
        ]
        mocked.return_value.__enter__.return_value.read.return_value = json.dumps(
            {'message': {'content': json.dumps({'requirements': items})}}).encode()
        result = extract_requirements(RadarInput(job_posting=posting))
        self.assertEqual([item.name for item in result], ['Python', 'Java', 'JavaScript', '문제 해결'])
        self.assertEqual(result[0].importance, 'unspecified')
        self.assertEqual(result[0].evidence, 'Python 개발')


class CollectionTests(SimpleTestCase):
    def link(self, url, title):
        link = MagicMock()
        link.get_attribute.return_value = url
        link.text = title
        return link

    @patch('skillradar.collection.public_url', side_effect=lambda url: url)
    @patch('skillradar.collection.browser')
    def test_search_uses_discovered_corporate_and_linked_career_sources(self, mock_browser, valid_url):
        for company, host in [('가상테크', 'fiction-tech.example'), ('다른기업', 'other-company.example')]:
            with self.subTest(company=company):
                driver = mock_browser.return_value.__enter__.return_value
                driver.reset_mock()
                driver.title = company + ' 공식 홈페이지'
                driver.current_url = 'https://' + host + '/'
                career = 'https://recruit.example/teams/' + host
                official = 'https://careers.' + host + '/roles/1'
                title = company + ' 플랫폼 개발자 직무소개'
                driver.find_elements.side_effect = [
                    [self.link(driver.current_url, company)],  # homepage search
                    [object()],  # homepage body
                    [self.link(career, 'Careers')],  # official referral to external service
                    [self.link('https://board.example/jobs/1', title),
                     self.link('https://' + host + '.evil.example/jobs/1', title),
                     self.link('https://recruit.example/teams/unrelated/1', title),
                     self.link(official, title), self.link(official + '#apply', title),
                     self.link(career + '/roles/2', title),
                     self.link('https://careers.' + host + '/roles/3', company + ' 영업 채용')],
                ]
                result = collect_posting(CollectionInput(company=company, division='플랫폼', role='개발자'))
                self.assertEqual([item['url'] for item in result['candidates']], [official, career + '/roles/2'])
                self.assertEqual(result['query'], company + ' 플랫폼 개발자 직무소개 채용')
                self.assertEqual(result['kind'], 'candidates')
                driver.execute_script.assert_not_called()

    @patch('skillradar.collection.public_url', side_effect=lambda url: url)
    @patch('skillradar.collection.browser')
    def test_verified_candidate_can_be_collected_as_body(self, mock_browser, valid_url):
        driver = mock_browser.return_value.__enter__.return_value
        driver.title = '가상기업 개발자'
        driver.current_url = 'https://fiction.example/'
        url = 'https://fiction.example/jobs/1'
        driver.find_elements.side_effect = [
            [self.link(driver.current_url, '가상기업')], [object()], [],
            [self.link(url, '가상기업 개발자 직무소개')],
        ]
        candidates = collect_posting(CollectionInput(company='가상기업', role='개발자'))
        driver.find_elements.side_effect = None
        driver.find_elements.return_value = [object()]
        driver.current_url = url
        driver.execute_script.return_value = '개발자 직무소개 및 요구 역량 본문 ' * 10
        result = collect_posting(CollectionInput(url=candidates['candidates'][0]['url']))
        self.assertEqual(result['source_url'], url)
        self.assertIn('요구 역량', result['body'])

    @patch('skillradar.collection.public_url', side_effect=lambda url: url)
    @patch('skillradar.collection.browser')
    def test_unconfirmed_company_identity_or_external_results_fail_closed(self, mock_browser, valid_url):
        driver = mock_browser.return_value.__enter__.return_value
        for title, matches in [('다른 회사', False), ('가상기업', True)]:
            with self.subTest(title=title):
                driver.title = title
                driver.current_url = 'https://fiction.example/'
                driver.find_elements.side_effect = [
                    [self.link(driver.current_url, '가상기업')], [object()],
                ] + ([[], [self.link('https://board.example/jobs/1', '가상기업 개발자 공식 채용')]] if matches else [])
                with self.assertRaises(CollectionFailure):
                    collect_posting(CollectionInput(company='가상기업', role='개발자'))

    @patch('skillradar.collection.public_url')
    def test_search_decodes_redirects_deduplicates_and_skips_unsafe_urls(self, valid_url):
        driver = MagicMock()
        driver.find_elements.return_value = [
            self.link('https://duckduckgo.com/l/?uddg=https%3A%2F%2Ffiction.example%2Fjobs%2F1', '직무소개'),
            self.link('https://fiction.example/jobs/1#apply', '직무소개'),
            self.link('http://127.0.0.1/private', '직무소개'),
        ]
        def check(url):
            if '127.0.0.1' in url:
                raise ValueError('private')
            return url
        valid_url.side_effect = check
        _, results = search_links(driver, '가상기업 개발자')
        self.assertEqual(results, [{'title': '직무소개', 'url': 'https://fiction.example/jobs/1'}])

    def test_source_matching_respects_hostname_and_external_tenant_boundaries(self):
        self.assertTrue(source_matches('https://jobs.fiction.example/1', 'https://www.fiction.example/', True))
        self.assertFalse(source_matches('https://fiction.example.evil.example/1', 'https://fiction.example/', True))
        self.assertFalse(source_matches('https://evilfiction.example/1', 'https://fiction.example/', True))
        self.assertFalse(source_matches('https://ats.example/team-other/1', 'https://ats.example/team'))
        self.assertTrue(source_matches('https://ats.example/team/1', 'https://ats.example/team'))
        self.assertFalse(source_matches('https://ats.example/jobs?company=other', 'https://ats.example/jobs?company=fiction'))
        self.assertTrue(source_matches('https://ats.example/jobs/1?company=fiction', 'https://ats.example/jobs?company=fiction'))

    @patch('skillradar.collection.public_url', side_effect=lambda url: url)
    @patch('skillradar.collection.browser')
    def test_localized_homepage_and_failed_homepage_candidate(self, mock_browser, valid_url):
        driver = mock_browser.return_value.__enter__.return_value
        driver.current_url = 'https://fiction.example/ko/kr/'
        driver.title = '가상기업'
        driver.get.side_effect = [None, TimeoutException('unavailable'), None, None]
        driver.find_elements.side_effect = [
            [self.link('https://unavailable.example/', '가상기업'),
             self.link(driver.current_url, '가상기업')],
            [object()], [],
            [self.link('https://fiction.example/roles/1', '가상기업 개발자 직무소개')],
        ]
        result = collect_posting(CollectionInput(company='가상기업', role='개발자'))
        self.assertEqual(result['candidates'][0]['url'], 'https://fiction.example/roles/1')

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

    @patch('skillradar.views.collect_posting', side_effect=CollectionFailure('수집 실패'))
    def test_collection_failure_allows_manual_input(self, collect):
        response = self.client.post('/api/skillradar/collect/', {'url': 'https://example.com/job'}, content_type='application/json')
        self.assertEqual(response.status_code, 422)
        self.assertTrue(response.json()['manual_input_required'])
        response = self.client.post('/api/skillradar/analyze/', {'job_posting': POSTING, 'use_llm': False}, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['requirements'])
