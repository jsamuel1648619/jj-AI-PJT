"""Opt-in Chrome UI tests with controlled search results, postings and model responses."""
import json
import os
import tempfile
import threading
import time
import unittest
from socketserver import ThreadingMixIn
from unittest.mock import patch
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from django.contrib.staticfiles.handlers import StaticFilesHandler
from django.core.wsgi import get_wsgi_application
from django.test import TransactionTestCase
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait

from .collection import CollectionFailure, browser, collect_posting, public_url
from .test_pipeline import POSTING, requirements
from .test_diagnosis import fake_qwen, question_fixture
from .diagnosis import GradesOutput
from debugdna.test_integration import qwen_fixture, ORIGINAL, CORRECTED


class ThreadedServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


class QuietHandler(WSGIRequestHandler):
    def log_message(self, *args):
        pass

    def handle(self):
        try:
            super().handle()
        except (ConnectionResetError, ConnectionAbortedError):
            pass


@unittest.skipUnless(os.environ.get('RUN_SELENIUM_TESTS') == '1', 'RUN_SELENIUM_TESTS=1로 실제 Chrome 검증')
class BrowserPipelineTests(TransactionTestCase):
    def setUp(self):
        self.model_requests = []
        self.api_requests = []
        self.flags = {'unknown_level': False, 'fail_analysis': False, 'fail_plan': False, 'fail_questions': False, 'fail_grading': False, 'fail_debug': False}
        application = StaticFilesHandler(get_wsgi_application())

        def fixture_app(environ, start_response):
            path = environ['PATH_INFO']
            if path == '/fixture':
                text = '<!doctype html><html lang="ko"><title>테스트 채용공고</title><body><main><h1>백엔드 개발자</h1><p>' + POSTING.replace('\n', '</p><p>') + '</p></main></body></html>'
                body, content_type = text.encode(), 'text/html; charset=utf-8'
            elif path == '/ollama/api/chat':
                payload = json.loads(environ['wsgi.input'].read(int(environ['CONTENT_LENGTH'])))
                self.model_requests.append(payload)
                is_plan = 'CoachingWeek' in payload['format'].get('$defs', {})
                is_questions = 'DiagnosticQuestion' in payload['format'].get('$defs', {})
                is_grading = 'SkillGrade' in payload['format'].get('$defs', {})
                is_debug = 'QwenFinding' in payload['format'].get('$defs', {})
                flag = 'fail_debug' if is_debug else 'fail_plan' if is_plan else 'fail_questions' if is_questions else 'fail_grading' if is_grading else 'fail_analysis'
                time.sleep(0.4)  # Exercise visible loading and duplicate-submission prevention.
                if self.flags[flag]:
                    self.flags[flag] = False
                    start_response('503 Service Unavailable', [('Content-Type', 'application/json')])
                    return [b'{}']
                if is_debug:
                    data = json.loads(payload['messages'][-1]['content'])
                    content = qwen_fixture(data['original'], data['corrected'])
                elif is_questions:
                    data = json.loads(payload['messages'][-1]['content'])
                    content = question_fixture([item['skill_id'] for item in data['requirements']])
                elif is_grading:
                    content = fake_qwen(GradesOutput, '', json.loads(payload['messages'][-1]['content'])).model_dump()
                elif is_plan:
                    schedule = json.loads(payload['messages'][-1]['content'])['schedule']
                    content = {'weeks': [{'week': w['week'], 'objective': w['skill'] + ' 단계별 학습', 'exercise': w['skill'] + ' 예제와 경계값 테스트 작성', 'completion': '정상·실패 사례 테스트와 회고 기록'} for w in schedule]}
                else:
                    skills = requirements()
                    if self.flags['unknown_level']:
                        skills[-1].update(required_level=None, level_basis='unknown', level_reason='', level_evidence='')
                    content = {'requirements': skills}
                body = json.dumps({'message': {'content': json.dumps(content)}}).encode()
                content_type = 'application/json'
            else:
                if path.startswith('/api/') and environ.get('CONTENT_LENGTH'):
                    # Record payloads without consuming Django's request body.
                    import io
                    raw = environ['wsgi.input'].read(int(environ['CONTENT_LENGTH']))
                    self.api_requests.append((path, json.loads(raw)))
                    environ['wsgi.input'] = io.BytesIO(raw)
                return application(environ, start_response)
            start_response('200 OK', [('Content-Type', content_type), ('Content-Length', str(len(body)))])
            return [body]

        self.server = make_server('127.0.0.1', 0, fixture_app, server_class=ThreadedServer, handler_class=QuietHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        self.fixture_url = self.base + '/fixture'

        def search_or_collect(data):
            if data.url:
                return collect_posting(data)
            if data.company == '실패기업':
                raise CollectionFailure('검색 실패')
            return {'kind': 'candidates', 'query': '테스트 기업 백엔드 채용', 'source_url': 'https://example.com/search', 'candidates': [{'title': '테스트 기업 · 백엔드 개발자 채용', 'url': self.fixture_url}]}

        self.patches = [patch.dict(os.environ, {'OLLAMA_BASE_URL': self.base + '/ollama'}),
                        patch('skillradar.collection.public_url', side_effect=lambda url: url if url == self.fixture_url else public_url(url)),
                        patch('skillradar.views.collect_posting', side_effect=search_or_collect)]
        for item in self.patches:
            item.start()
        self.browser = browser()
        try:
            self.driver = self.browser.__enter__()
        except Exception:
            self.tearDown()
            raise
        self.wait = WebDriverWait(self.driver, 40)

    def tearDown(self):
        if hasattr(self, 'driver'):
            self.browser.__exit__(None, None, None)
        for item in reversed(self.patches):
            item.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def find(self, identity):
        return self.driver.find_element(By.ID, identity)

    def wait_step(self, number):
        self.wait.until(lambda d: d.find_element(By.ID, f'step-{number}').is_displayed())

    def wait_percent(self, expected):
        try:
            self.wait.until(lambda d: d.find_element(By.ID, 'progress-percent').text == expected)
        except Exception as error:
            state = self.driver.execute_async_script("const done=arguments[0];fetch('/api/dashboard/').then(r=>r.json()).then(d=>done(d.roadmap&&d.roadmap.progress)).catch(e=>done(String(e)));")
            self.fail(f"Expected {expected}; UI={self.find('progress-percent').text}; task status={self.find('task-status').text}; sync={self.find('sync-status').text}; DB={state}; browser={self.driver.get_log('browser')}")

    def search(self, company='테스트 기업'):
        self.find('company').send_keys(company)
        self.find('division').send_keys('플랫폼')
        self.find('role').send_keys('백엔드 개발자')
        self.find('collect').click()

    def assess(self, open_step=True, retry_evaluation=False):
        if open_step:
            self.find('to-assessment').click()
        self.wait_step(3)
        self.wait.until(lambda d: d.find_element(By.ID, 'evaluate').is_displayed() and d.find_element(By.ID, 'evaluate').is_enabled())
        for index, card in enumerate(self.driver.find_elements(By.CSS_SELECTOR, '.skill-card')):
            card.find_element(By.TAG_NAME, 'textarea').send_keys('모르겠습니다' if index == 2 else '함수로 구현했습니다. 테스트는 작성하지 않았습니다.')
        self.find('evaluate').click()
        if retry_evaluation:
            self.wait.until(lambda d: d.find_element(By.ID, 'evaluation-status').get_attribute('data-state') == 'error')
            self.assertIn('함수로', self.driver.find_element(By.CSS_SELECTOR, '.diagnosis-answer').get_attribute('value'))
            self.find('evaluate').click()
        self.wait.until(lambda d: d.find_element(By.ID, 'result').is_displayed())

    def test_wizard_primary_path_generates_plan_without_reentry(self):
        self.driver.get(self.base + '/skillradar/')
        self.assertFalse(self.find('posting').is_displayed())
        self.assertFalse(self.find('job-url').is_displayed())
        self.assertEqual(self.driver.find_elements(By.ID, 'mode'), [])
        self.assertFalse(self.find('step-2').is_displayed())
        self.assertEqual(len([x for x in self.driver.find_elements(By.TAG_NAME, 'input') if x.is_displayed()]), 3)
        self.search()
        self.wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, '.candidate')) == 1)
        self.driver.find_element(By.CSS_SELECTOR, '.candidate button').click()
        self.wait_step(2)
        self.wait.until(lambda d: d.find_element(By.ID, 'to-assessment').is_displayed())
        self.assertEqual(self.find('step-status-1').text, '완료')
        self.assertEqual(self.find('step-status-2').text, '완료')
        self.assertFalse(self.find('posting-preview').is_displayed())
        self.assertEqual(len(self.driver.find_elements(By.CSS_SELECTOR, '.requirement')), 3)
        self.assess()
        self.assertIn('Python → Django → Docker', self.find('priorities').text)
        self.wait.until(lambda d: d.execute_script("return !!window.Chart && !!Chart.getChart('gaps')"))
        self.assertEqual(self.driver.execute_script("return Chart.getChart('gaps').data.datasets[0].data"), [3, 1, 2])
        self.assertEqual(self.driver.execute_script("return Chart.getChart('radar').data.datasets[0].data"), [4, 3, 2])
        self.find('plan').click()
        self.wait_step(4)
        self.assertTrue(self.find('plan-weeks').get_attribute('value') == '4')
        self.assertFalse(self.find('plan-weeks').is_displayed())
        main_window = self.driver.current_window_handle
        self.driver.switch_to.new_window('tab')
        self.driver.get(self.base + '/debugdna/')
        for index, name in enumerate(('last', 'last_again'), 1):
            for identity, code in [('original', ORIGINAL.replace('last(', name+'(')), ('corrected', CORRECTED.replace('last(', name+'('))]:
                field = self.find(identity)
                field.clear()
                field.send_keys(code)
            self.find('submit').click()
            self.wait.until(lambda d: f'{index}개 코드 쌍' in d.find_element(By.ID, 'insight-summary').text)
        self.assertEqual(len(self.driver.find_elements(By.CSS_SELECTOR, '#hints li')), 0)
        for count in (1, 2, 3):
            self.find('next-hint').click()
            self.assertEqual(len(self.driver.find_elements(By.CSS_SELECTOR, '#hints li')), count)
        self.assertFalse(self.find('next-hint').is_enabled())
        self.assertIn('경계값 오류 2회', self.find('weak-skills').text)
        self.find('submit').click()
        self.wait.until(lambda d: '동일한 입력' in d.find_element(By.ID, 'status').text)
        self.assertIn('2개 코드 쌍', self.find('insight-summary').text)
        self.driver.close()
        self.driver.switch_to.window(main_window)
        self.driver.execute_script("""
            const actualFetch = window.fetch;
            window.fetch = (url, options) => url.endsWith('/from-diagnosis/')
                ? new Promise(resolve => {window.releasePlan = () => {window.fetch = actualFetch; resolve(actualFetch(url, options));};})
                : actualFetch(url, options);
        """)
        self.find('generate').click()
        self.wait.until(lambda d: d.execute_script('return typeof window.releasePlan === "function"'))
        self.assertEqual(self.find('step-status-4').text, '생성 중')
        self.assertFalse(self.find('generate').is_enabled())
        self.assertFalse(self.find('plan-back').is_enabled())
        self.driver.execute_script("document.getElementById('roadmap-form').requestSubmit(); window.releasePlan();")
        self.wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, '.week')) == 4)
        self.assertIn('총 20시간', self.find('roadmap-summary').text)
        self.assertEqual(self.find('step-status-4').text, '완료')
        self.assertEqual(len(self.model_requests), 6)
        self.assertIn('DebugDNA', self.find('debug-plan-context').text)
        for path, payload in self.api_requests:
            if path.endswith('/analyze/') or path.endswith('/from-diagnosis/'):
                self.assertIs(payload['use_llm'], True)
        self.driver.save_screenshot(os.path.join(tempfile.gettempdir(), 'jj-ai-pjt-wizard.png'))
        self.find('manage-plan').click()
        self.wait.until(lambda d: '/growthplan/' in d.current_url)
        self.wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, '.week')) == 4)
        self.assertEqual(len(self.model_requests), 6)  # DB plan is loaded, not regenerated.
        self.assertEqual(self.driver.find_elements(By.CSS_SELECTOR, '.goal .target')[0].get_attribute('value'), '4')
        self.driver.find_elements(By.CSS_SELECTOR, '.week input')[0].click()
        self.wait.until(lambda d: '1 / 4주 완료' in d.find_element(By.ID, 'progress-text').text)
        self.find('save').click()
        self.driver.refresh()
        self.wait.until(lambda d: '1 / 4주 완료' in d.find_element(By.ID, 'progress-text').text)
        growth_window = self.driver.current_window_handle
        growth_origin = self.driver.execute_script('return performance.timeOrigin')
        self.driver.switch_to.new_window('tab')
        dashboard_window = self.driver.current_window_handle
        self.driver.get(self.base + '/')
        self.wait_percent('25%')
        dashboard_origin = self.driver.execute_script('return performance.timeOrigin')
        self.assertIn('테스트 기업', self.find('target-title').text)
        self.assertEqual(self.driver.execute_script("return Chart.getChart('scores-chart').data.datasets[0].data"), [1, 2, 0])
        self.assertEqual(self.driver.execute_script("return Chart.getChart('mistakes-chart').data.datasets[0].data"), [2])
        self.driver.save_screenshot(os.path.join(tempfile.gettempdir(), 'jj-ai-pjt-dashboard.png'))
        self.driver.switch_to.window(growth_window)
        self.driver.find_elements(By.CSS_SELECTOR, '.week input')[0].click()
        self.wait.until(lambda d: '0 / 4주 완료' in d.find_element(By.ID, 'progress-text').text)
        self.driver.switch_to.window(dashboard_window)
        self.wait_percent('0%')
        self.assertEqual(self.driver.execute_script('return performance.timeOrigin'), dashboard_origin)
        self.driver.find_element(By.CSS_SELECTOR, '#priority-tasks button').click()
        self.wait_percent('25%')
        self.driver.switch_to.window(growth_window)
        self.wait.until(lambda d: '1 / 4주 완료' in d.find_element(By.ID, 'progress-text').text)
        self.assertEqual(self.driver.execute_script('return performance.timeOrigin'), growth_origin)
        self.driver.switch_to.window(dashboard_window)
        self.driver.find_element(By.CSS_SELECTOR, '#all-tasks summary').click()
        self.driver.find_element(By.CSS_SELECTOR, '#task-list input:checked').click()
        self.wait_percent('0%')
        self.driver.switch_to.window(growth_window)
        self.wait.until(lambda d: '0 / 4주 완료' in d.find_element(By.ID, 'progress-text').text)
        self.driver.switch_to.window(dashboard_window)
        self.driver.close()
        self.driver.switch_to.window(growth_window)
        self.driver.get(self.base + '/skillradar/')
        self.find('load-history').find_element(By.XPATH, './ancestor::details/summary').click()
        self.find('load-history').click()
        self.wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, '#diagnosis-history button')) == 1)
        self.driver.find_element(By.CSS_SELECTOR, '#diagnosis-history button').click()
        self.wait.until(lambda d: d.find_element(By.ID, 'result').is_displayed())
        self.assertIn('저장', self.find('evaluation-status').text)
        self.assertEqual(len(self.driver.find_elements(By.CSS_SELECTOR, '#evaluation-reasons article')), 3)

    def test_dashboard_empty_state_has_no_dummy_charts_or_tasks_on_mobile(self):
        self.driver.execute_cdp_cmd('Emulation.setDeviceMetricsOverride', {'width': 390, 'height': 844, 'deviceScaleFactor': 1, 'mobile': True})
        self.driver.get(self.base + '/')
        self.wait.until(lambda d: d.find_element(By.ID, 'dashboard-content').get_attribute('aria-busy') == 'false')
        self.assertEqual(self.find('diagnosis-count').text, '0')
        self.assertEqual(self.find('analysis-count').text, '0')
        self.assertEqual(self.find('progress-percent').text, '—')
        self.assertFalse(self.find('score-chart-wrap').is_displayed())
        self.assertFalse(self.find('mistake-chart-wrap').is_displayed())
        self.assertEqual(self.driver.find_elements(By.CSS_SELECTOR, '#priority-tasks button'), [])
        self.assertIn('저장된 역량 진단 결과가 없습니다', self.find('scores-empty').text)
        self.assertLessEqual(self.driver.execute_script('return document.documentElement.scrollWidth'), 392)

    def test_mobile_fallback_retries_unknown_targets_and_stale_results(self):
        self.driver.execute_cdp_cmd('Emulation.setDeviceMetricsOverride', {'width': 390, 'height': 844, 'deviceScaleFactor': 1, 'mobile': True})
        self.driver.get(self.base + '/skillradar/')
        self.flags.update(unknown_level=True, fail_analysis=True)
        self.search('실패기업')
        self.wait.until(lambda d: d.find_element(By.ID, 'collection-status').get_attribute('data-state') == 'error')
        self.assertTrue(self.find('posting').is_displayed())
        self.find('posting').send_keys(POSTING)
        self.find('manual-start').click()
        self.wait_step(2)
        self.wait.until(lambda d: d.find_element(By.ID, 'analyze').is_displayed() and d.find_element(By.ID, 'analyze').is_enabled())
        self.assertFalse(self.find('to-assessment').is_displayed())
        self.assertIn('다시 시도', self.find('analysis-status').text)
        self.find('analyze').click()
        self.wait.until(lambda d: d.find_element(By.ID, 'to-assessment').is_displayed())
        self.flags.update(fail_questions=True, fail_grading=True)
        self.find('to-assessment').click()
        self.wait.until(lambda d: d.find_element(By.ID, 'retry-questions').is_displayed() and d.find_element(By.ID, 'retry-questions').is_enabled())
        self.find('retry-questions').click()
        self.assess(open_step=False, retry_evaluation=True)
        self.assertEqual(self.driver.execute_script("return Chart.getChart('gaps').data.datasets[0].data"), [3, 1, None])
        self.find('plan').click()
        self.wait_step(4)
        unknown = self.driver.find_element(By.CSS_SELECTOR, '#unknown-targets select')
        self.assertEqual(unknown.get_attribute('value'), '')
        self.assertFalse(self.driver.execute_script("return document.getElementById('roadmap-form').checkValidity()"))
        Select(unknown).select_by_value('2')
        self.flags['fail_plan'] = True
        self.find('generate').click()
        self.wait.until(lambda d: d.find_element(By.ID, 'plan-status').get_attribute('data-state') == 'error')
        self.assertFalse(self.find('roadmap').is_displayed())
        self.assertEqual(unknown.get_attribute('value'), '2')
        self.find('generate').click()
        self.wait.until(lambda d: d.find_element(By.ID, 'roadmap').is_displayed())
        self.assertLessEqual(self.driver.execute_script('return document.documentElement.scrollWidth'), 392)
        self.find('plan-back').click()
        self.driver.find_elements(By.CSS_SELECTOR, '.diagnosis-answer')[0].send_keys('답변 수정')
        self.assertFalse(self.find('result').is_displayed())
        self.assertFalse(self.driver.find_element(By.CSS_SELECTOR, '[data-step="4"]').is_enabled())
        self.find('assessment-back').click()
        self.find('analysis-back').click()
        self.find('company').send_keys('새 기업')
        self.assertFalse(self.driver.find_element(By.CSS_SELECTOR, '[data-step="2"]').is_enabled())
        self.assertFalse(self.driver.find_element(By.CSS_SELECTOR, '[data-step="3"]').is_enabled())
