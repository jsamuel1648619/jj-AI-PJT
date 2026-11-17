"""Opt-in live Chrome + official Samsung page + Qwen E2E, isolated from user DB.

Run: .\venv\Scripts\python.exe scripts/verify_samsung_e2e.py
Evidence (including generated model output) stays under ignored build/.
No model, search, collection or API responses are mocked.
"""
import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()
from django.contrib.staticfiles.handlers import StaticFilesHandler
from django.core.wsgi import get_wsgi_application
from django.test.utils import setup_databases, setup_test_environment, teardown_databases, teardown_test_environment
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from skillradar.collection import browser
from skillradar.analysis import source_importance

SOURCE = 'https://www.samsung-dsrecruit.com/recruits/job_intro/memory/softwareDev.php'


class Server(ThreadingMixIn, WSGIServer):
    daemon_threads = True


class QuietHandler(WSGIRequestHandler):
    def log_message(self, *args):
        pass


def main():
    output = ROOT / 'build' / 'samsung-e2e'
    output.mkdir(parents=True, exist_ok=True)
    evidence = {'source': SOURCE, 'model': os.environ.get('QWEN_MODEL', 'qwen3:4b-instruct-2507-q4_K_M'),
                'profile': 'Synthetic beginner: Python basic list/function practice; no embedded/ARM/firmware experience.',
                'started_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'requests': [], 'checks': []}

    def checkpoint(name, value=True):
        evidence['checks'].append({'name': name, 'value': value})
        print(name, json.dumps(value, ensure_ascii=True), flush=True)

    setup_test_environment()
    databases = setup_databases(verbosity=0, interactive=False)
    application = StaticFilesHandler(get_wsgi_application())

    def trace_validation(frame, event, arg):
        if (event == 'exception' and frame.f_code.co_name == 'extract_requirements'
                and frame.f_code.co_filename.replace('\\', '/').endswith('/skillradar/analysis.py')):
            kind, error, _ = arg
            if issubclass(kind, (ValueError, KeyError, TypeError)):
                evidence.setdefault('validation_errors', []).append(str(error))
                print('VALIDATION', str(error).encode('ascii', 'backslashreplace').decode(), flush=True)
        return trace_validation
    threading.settrace(trace_validation)

    def observed_app(environ, start_response):
        started = time.monotonic()
        status = []
        def observed_start(value, headers, exc_info=None):
            status.append(value)
            return start_response(value, headers, exc_info)
        response = application(environ, observed_start)
        try:
            chunks = list(response)
        finally:
            if hasattr(response, 'close'):
                response.close()
        if environ['PATH_INFO'].startswith('/api/'):
            row = {'path': environ['PATH_INFO'], 'method': environ['REQUEST_METHOD'],
                   'status': status[0], 'seconds': round(time.monotonic() - started, 2)}
            try:
                row['data'] = json.loads(b''.join(chunks))
            except ValueError:
                row['data'] = 'non-JSON response'
            evidence['requests'].append(row)
            (output / 'results.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
            print('API', row['method'], row['path'], row['status'], row['seconds'], flush=True)
        return chunks

    server = make_server('127.0.0.1', 0, observed_app, server_class=Server, handler_class=QuietHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        with browser() as driver:
            wait = WebDriverWait(driver, 1800, poll_frequency=1)
            def el(identity):
                return driver.find_element(By.ID, identity)
            def idle():
                wait.until(lambda d: d.find_element(By.ID, 'workflow-status').get_attribute('data-busy') != 'true')
            def last(path):
                return next(row['data'] for row in reversed(evidence['requests']) if row['path'] == path and row['status'].startswith('200'))
            def get(path):
                return driver.execute_async_script('const done=arguments[arguments.length-1];fetch(arguments[0]).then(r=>r.json()).then(done);', path)
            try:
                driver.get(base + '/skillradar/')
                for identity, value in [('company', '삼성전자'), ('division', 'DS 메모리사업부'), ('role', 'S/W개발')]:
                    el(identity).send_keys(value)
                el('collect').click()
                idle()
                checkpoint('search_status', el('collection-status').text)
                candidates = [link.get_attribute('href') for link in driver.find_elements(By.CSS_SELECTOR, '.candidate a')]
                checkpoint('search_candidates', candidates)
                exact = next((card for card in driver.find_elements(By.CSS_SELECTOR, '.candidate')
                              if card.find_element(By.TAG_NAME, 'a').get_attribute('href') == SOURCE), None)
                if exact:
                    exact.find_element(By.TAG_NAME, 'button').click()
                else:
                    driver.execute_script("document.getElementById('manual-options').open=true")
                    el('job-url').send_keys(SOURCE)
                    el('collect-url').click()
                idle()
                for _ in range(2):
                    if el('to-assessment').is_displayed():
                        break
                    checkpoint('analysis_retry', el('analysis-status').text)
                    el('analyze').click()
                    idle()
                assert el('to-assessment').is_displayed(), el('analysis-status').text
                collected = last('/api/skillradar/collect/')
                assert collected['source_url'] == SOURCE and not collected['truncated']
                assert all(section in collected['body'] for section in ['Requirements', 'Pluses', 'ARM Architecture', 'Python'])
                extraction = last('/api/skillradar/analyze/')
                assert extraction['source'] == 'qwen'
                assert all(item['evidence'] in collected['body'] for item in extraction['requirements'])
                assert all(source_importance(collected['body'], item['evidence']) in (None, item['importance']) for item in extraction['requirements'])
                checkpoint('collected_characters', len(collected['body']))
                checkpoint('extracted_skills', [item['name'] for item in extraction['requirements']])
                driver.save_screenshot(str(output / '01-analysis.png'))
                el('to-assessment').click()
                idle()
                for _ in range(2):
                    if el('evaluate').is_displayed():
                        break
                    checkpoint('questions_retry', el('question-status').text)
                    el('retry-questions').click()
                    idle()
                assert el('evaluate').is_displayed(), el('question-status').text
                answers = {}
                for card in driver.find_elements(By.CSS_SELECTOR, '.skill-card'):
                    name = card.get_attribute('data-name')
                    answer = ('Python 기초 실습에서 함수와 리스트를 사용해 마지막 원소를 반환하는 함수를 작성했습니다. '
                              '인덱스를 len(values)로 써서 IndexError가 발생했고 values[-1]로 수정했습니다. '
                              '빈 리스트에서는 None을 반환하도록 분기했습니다. 자동 테스트와 성능 측정 경험은 없습니다.'
                              if 'python' in name.casefold() or '프로그래밍 언어' in name else
                              '모르겠습니다. 이 역량은 아직 학습하거나 구현한 경험이 없습니다. 독립적으로 설계하거나 문제를 해결할 수 없습니다.')
                    card.find_element(By.TAG_NAME, 'textarea').send_keys(answer)
                    answers[name] = answer
                evidence['answers'] = answers
                el('evaluate').click()
                idle()
                for _ in range(2):
                    if el('result').is_displayed():
                        break
                    checkpoint('grading_retry', el('evaluation-status').text)
                    el('evaluate').click()
                    idle()
                assert el('result').is_displayed(), el('evaluation-status').text
                evaluated_row = next(row['data'] for row in reversed(evidence['requests']) if row['path'].endswith('/evaluate/') and row['status'].startswith('200'))
                evaluated = evaluated_row['result']
                basic = next(item for item in evaluated['requirements'] if '프로그래밍 언어' in item['name'] or 'python' in item['name'].casefold())
                checkpoint('basic_experience_score', basic['score'])
                assert basic['score'] == 2, basic
                checkpoint('evaluated', el('summary').text)
                driver.save_screenshot(str(output / '02-evaluation.png'))
                radar_window = driver.current_window_handle
                driver.switch_to.new_window('tab')
                driver.get(base + '/debugdna/')
                for index, function in enumerate(['last_value', 'last_again'], 1):
                    for identity, tail in [('original', 'values[len(values)]'), ('corrected', 'values[-1]')]:
                        code = f'def {function}(values):\n    if not values:\n        return None\n    return {tail}'
                        el(identity).clear()
                        el(identity).send_keys(code)
                    # Leave related skills blank to verify automatic diagnosis linkage.
                    el('submit').click()
                    wait.until(lambda d: not d.find_element(By.ID, 'analysis-controls').get_property('disabled'))
                    assert el('result').is_displayed(), el('status').text
                    checkpoint('code_analysis', el('status').text)
                insights = get('/api/debugdna/insights/')
                assert insights['categories'].get('경계값 오류') == 2, insights
                checkpoint('repeat_boosts', [{key: skill[key] for key in ('name', 'issue_count', 'recurrence_count', 'priority_boost')} for skill in insights['weak_skills']])
                driver.save_screenshot(str(output / '03-debugdna.png'))
                driver.close()
                driver.switch_to.window(radar_window)
                el('plan').click()
                for control in driver.find_elements(By.CSS_SELECTOR, '#unknown-targets select'):
                    Select(control).select_by_value('3')
                el('generate').click()
                idle()
                assert el('roadmap').is_displayed(), el('plan-status').text
                plan = last('/api/growthplan/from-diagnosis/')
                assert plan['source'] == 'qwen' and plan['total_hours'] == 20
                boosted = [skill for skill in plan['priorities'] if skill['debug_boost'] > 0]
                checkpoint('boosted_priorities', [{key: skill[key] for key in ('name', 'gap', 'debug_boost', 'priority_score')} for skill in boosted])
                assert boosted, 'Code observations did not match extracted job skills'
                assert all('기대 결과와 실제 결과가 일치' in week['completion'] for week in plan['weeks'])
                assert any('실수 재검증' in week['completion'] for week in plan['weeks'] if week['debug_boost'])
                driver.save_screenshot(str(output / '04-roadmap.png'))
                el('manage-plan').click()
                wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, '.week')) == 4)
                restored = get('/api/growthplan/roadmaps/' + plan['roadmap_id'] + '/')
                assert restored['configuration'] == plan['configuration']
                assert restored['diagnosis_attempt_id'] == plan['diagnosis_attempt_id']
                driver.find_element(By.CSS_SELECTOR, '.week input').click()
                wait.until(lambda d: '1 / 4주 완료' in d.find_element(By.ID, 'progress-text').text)
                driver.get(base + '/')
                wait.until(lambda d: d.find_element(By.ID, 'progress-percent').text == '25%')
                dashboard = get('/api/dashboard/')
                assert dashboard['target_job']['company'] == '삼성전자'
                assert dashboard['target_job']['division'] == 'DS 메모리사업부'
                assert dashboard['target_job']['source_url'] == SOURCE
                assert dashboard['diagnosis']['attempt_id'] == plan['diagnosis_attempt_id']
                assert dashboard['debugdna']['analysis_count'] == 2
                scores = {item['name']: item['score'] for item in dashboard['diagnosis']['scores']}
                assert all(skill['current_level'] == scores[skill['name']] for skill in plan['configuration']['skills'])
                checkpoint('dashboard_consistent', True)
                driver.save_screenshot(str(output / '05-dashboard.png'))
                # Real Qwen calibration on the same saved diagnosis, using the
                # same answer repeatedly plus concept/no-experience/blank controls.
                def post(path, body):
                    return driver.execute_async_script("const done=arguments[arguments.length-1];fetch(arguments[0],{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':document.cookie.split('; ').find(v=>v.startsWith('csrftoken=')).split('=')[1]},body:JSON.stringify(arguments[1])}).then(async r=>done({status:r.status,data:await r.json()}));", path, body)
                driver.set_script_timeout(120)
                diagnosis_id = evaluated['diagnosis_id']
                cases = [('basic_repeat_1', answers[basic['name']], 2), ('basic_repeat_2', answers[basic['name']], 2),
                         ('concept', '리스트 인덱스는 0부터 시작하고 마지막 인덱스는 길이보다 1 작다는 개념을 배웠습니다. 아직 코드를 직접 구현한 경험은 없습니다.', 1),
                         ('no_experience', '모르겠습니다. 관련 개념을 배우거나 구현한 경험이 없습니다.', 0), ('blank', '', None)]
                calibration = []
                for label, answer, expected in cases:
                    responses = [{'skill_id': item['skill_id'], 'answer': answer if item['skill_id'] == basic['skill_id'] else ''} for item in evaluated['requirements']]
                    if not answer:
                        next(item for item in responses if item['skill_id'] != basic['skill_id'])['answer'] = '모르겠습니다. 경험이 없습니다.'
                    created = post(f'/api/skillradar/diagnoses/{diagnosis_id}/attempts/', {'responses': responses})
                    assert created['status'] == 201, created
                    attempt = created['data']
                    while not attempt['completed']:
                        graded = post(f"/api/skillradar/attempts/{attempt['id']}/evaluate/", {})
                        assert graded['status'] == 200, graded
                        attempt = graded['data']
                    item = next(item for item in attempt['result']['requirements'] if item['skill_id'] == basic['skill_id'])
                    calibration.append({'case': label, 'score': item['score'], 'reason': item['evaluation_reason']})
                    assert item['score'] == expected, calibration
                checkpoint('level_calibration', calibration)
                evidence['outcome'] = 'passed'
            except Exception:
                evidence['outcome'] = 'failed'
                evidence['exception'] = traceback.format_exc()
                evidence['page_text'] = driver.find_element(By.TAG_NAME, 'body').text
                driver.save_screenshot(str(output / 'failure.png'))
                raise
    finally:
        evidence['finished_at'] = time.strftime('%Y-%m-%dT%H:%M:%S%z')
        (output / 'results.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        teardown_databases(databases, verbosity=0)
        teardown_test_environment()
        threading.settrace(None)


if __name__ == '__main__':
    main()
