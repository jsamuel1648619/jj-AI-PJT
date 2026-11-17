"""Live Qwen diagnosis/DB/roadmap check in an isolated temporary test database."""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()
from django.test import Client
from django.test.utils import setup_databases, setup_test_environment, teardown_databases, teardown_test_environment
from skillradar.analysis import RadarInput, analyze_radar, normalize
from skillradar.collection import CollectionInput, collect_posting


def audit(urls, repeats, output):
    """Live repeatability checks; fixtures are test inputs, never scoring rules."""
    evidence = {'sources': [], 'grades': [], 'checks': {}}
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    def save():
        path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    fields = ('name', 'importance', 'evidence', 'required_level', 'level_basis', 'level_reason', 'level_evidence', 'weight', 'weight_reason')
    first = None
    for url in urls:
        posting = collect_posting(CollectionInput(url=url))
        row = {'posting': posting, 'sha256': hashlib.sha256(posting['body'].encode()).hexdigest(), 'runs': []}
        evidence['sources'].append(row)
        for index in range(repeats):
            try:
                result = analyze_radar(RadarInput(job_posting=posting['body'], source_url=posting['source_url']))
                row['runs'].append(result)
                if first is None:
                    first = (posting, result)
                print('EXTRACT', url, index + 1, len(result['requirements']), flush=True)
            except Exception as error:
                row['runs'].append({'error': str(error)})
                print('EXTRACT ERROR', url, index + 1, str(error).encode('ascii', 'backslashreplace').decode(), flush=True)
            save()
        signatures = [sorted((normalize(item['name']), item['importance'], item['required_level'], item['level_basis'], item['weight'], item['evidence']) for item in run['requirements'])
                      for run in row['runs'] if 'requirements' in run]
        row['consistent'] = len(signatures) == repeats and all(signature == signatures[0] for signature in signatures)
        print('CONSISTENT', url, row['consistent'], flush=True)
        save()
    if first is None:
        raise AssertionError('No live extraction succeeded')
    posting, extracted = first
    item = next((item for item in extracted['requirements'] if 'python' in item['name'].casefold() or '프로그래밍' in item['name']), extracted['requirements'][0])
    setup_test_environment()
    databases = setup_databases(verbosity=0, interactive=False)
    try:
        client = Client()
        def post(url, payload):
            response = client.post(url, payload, content_type='application/json')
            if response.status_code not in (200, 201):
                raise AssertionError(f'{url}: {response.status_code} {response.content.decode()}')
            return response.json()
        diagnosis = post('/api/skillradar/diagnoses/', {'job_posting': posting['body'], 'source_url': posting['source_url'], 'requirements': [{key: item[key] for key in fields}]})
        diagnosis = post(f"/api/skillradar/diagnoses/{diagnosis['id']}/questions/", {})
        # Synthetic experience evidence aligned with the existing fixed rubric.
        project = ('팀 주문 관리 프로젝트에서 제가 Python 주문 API와 입력 검증을 구현했습니다. '
                   '금액 계산과 저장을 함수로 분리해 변경하기 쉽게 설계했고 정상 주문, 빈 항목, 음수 수량, 중복 요청의 기대 결과를 정의했습니다. '
                   'pytest로 정상·실패 사례 24개를 실행하고 DB 저장 결과까지 확인했습니다. '
                   '새로운 장애를 독립적으로 진단하거나 대안별 성능을 측정한 경험은 아직 없습니다.')
        independent = ('운영 중인 Python 주문 API의 지연 장애를 제가 독립적으로 조사했습니다. '
                       '로그와 cProfile, SQL 실행 횟수를 분석해 반복 조회 N+1을 원인으로 재현했습니다. '
                       '캐시의 무효화 위험을 피하려고 일괄 조회로 수정하고 정상·실패·회귀 테스트 30개를 통과시켰습니다. '
                       '같은 데이터와 부하 500건으로 개선 전후를 측정해 조회 101회가 2회, p95 지연 420ms가 90ms로 줄었음을 확인했습니다. '
                       '서로 다른 설계의 종합 벤치마크나 확장 설계까지 수행하지는 않았습니다.')
        design = ('Python 주문 시스템의 확장 설계를 제가 주도했습니다. 기존 반복 조회, 일괄 조회, 캐시의 세 설계를 '
                  '같은 1천·1만 건 데이터와 동시 요청 100개로 비교하고 p95 지연 420/90/55ms, 메모리 40/45/120MB를 기록했습니다. '
                  '갱신 빈도가 높아 캐시 일관성과 메모리 비용을 고려해 일괄 조회와 인덱스를 선택했습니다. '
                  '정상·실패·동시성 회귀 테스트 60개를 실행해 중복 주문과 장애 복구를 검증했습니다. '
                  '배포 후 지연 알람과 재발 방지 회귀 테스트를 운영하고, 데이터 증가 시 파티션 분리 기준과 롤백 절차를 설계 문서에 남겼습니다.')
        for expected, answer in [(3, project), (4, independent), (5, design)]:
            scores = []
            for index in range(repeats):
                attempt = post(f"/api/skillradar/diagnoses/{diagnosis['id']}/attempts/", {'responses': [{'skill_id': 's1', 'answer': answer}]})
                attempt = post(f"/api/skillradar/attempts/{attempt['id']}/evaluate/", {})
                grade = attempt['result']['requirements'][0]
                assert grade['answer_evidence'] and all(quote in answer for quote in grade['answer_evidence'])
                evidence['grades'].append({'expected': expected, 'run': index + 1, 'answer': answer, 'result': grade})
                scores.append(grade['score'])
                print('GRADE', expected, index + 1, grade['score'], flush=True)
                save()
            evidence['checks'][f'level_{expected}'] = scores == [expected] * repeats
        evidence['checks']['extraction_consistent'] = all(row['consistent'] for row in evidence['sources'])
        evidence['outcome'] = 'passed' if all(evidence['checks'].values()) else 'failed'
        save()
        print('CHECKS', evidence['checks'], flush=True)
        if evidence['outcome'] != 'passed':
            raise AssertionError('Live repeatability or level calibration failed; see evidence JSON')
    finally:
        teardown_databases(databases, verbosity=0)
        teardown_test_environment()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', help='Optional public posting URL for live Selenium collection')
    parser.add_argument('--compare-url', help='Second official source for repeated extraction and 3~5 grading audit')
    parser.add_argument('--repeats', type=int, choices=range(2, 6), default=3)
    parser.add_argument('--output', default='build/diagnosis-audit/results.json')
    args = parser.parse_args()
    if args.compare_url:
        if not args.url:
            parser.error('--compare-url requires --url')
        return audit([args.url, args.compare_url], args.repeats, args.output)
    posting, source = '필수 역량: Python으로 API를 독립적으로 개발하고 오류를 해결할 수 있어야 합니다.', ''
    if args.url:
        collected = collect_posting(CollectionInput(url=args.url))
        posting, source = collected['body'], collected['source_url']
        print('Live posting collected:', len(posting), 'characters', source, flush=True)
    extracted = analyze_radar(RadarInput(job_posting=posting, source_url=source))
    if not extracted['requirements']:
        raise AssertionError('No requirements extracted')
    item = extracted['requirements'][0]
    fields = ('name', 'importance', 'evidence', 'required_level', 'level_basis', 'level_reason', 'level_evidence', 'weight', 'weight_reason')
    setup_test_environment()
    databases = setup_databases(verbosity=0, interactive=False)
    try:
        client = Client()
        def post(url, payload):
            response = client.post(url, payload, content_type='application/json')
            if response.status_code not in (200, 201):
                raise AssertionError(f'{url}: {response.status_code} {response.content.decode()}')
            return response.json()
        diagnosis = post('/api/skillradar/diagnoses/', {'job_posting': posting, 'source_url': source, 'requirements': [{key: item[key] for key in fields}]})
        diagnosis = post(f"/api/skillradar/diagnoses/{diagnosis['id']}/questions/", {})
        assert diagnosis['ready'] and len(diagnosis['questions'][0]['rubric']) == 6
        print('Live diagnostic question + six-level rubric validated:', item['name'], flush=True)
        attempt = post(f"/api/skillradar/diagnoses/{diagnosis['id']}/attempts/", {'responses': [{'skill_id': 's1', 'answer': '모르겠습니다. 아직 이 기술로 구현하거나 문제를 해결한 경험이 없습니다.'}]})
        attempt = post(f"/api/skillradar/attempts/{attempt['id']}/evaluate/", {})
        assert attempt['completed'] and attempt['result']['requirements'][0]['score'] == 0
        restored = client.get(f"/api/skillradar/attempts/{attempt['id']}/").json()
        assert restored['result'] == attempt['result']
        print('Live answer evaluation + grounded evidence + DB reload validated: score=0', flush=True)
        plan = post('/api/growthplan/from-diagnosis/', {'attempt_id': attempt['id'], 'targets': [{'skill_id': 's1', 'level': item['required_level'] or 3}], 'weeks': 1, 'hours_per_week': 3})
        assert len(plan['weeks']) == 1 and plan['total_hours'] == 3
        assert plan['configuration']['skills'][0]['current_level'] == 0
        assert client.get(f"/api/growthplan/roadmaps/{plan['roadmap_id']}/").status_code == 200
        print('Live diagnosis-based roadmap + DB persistence validated: 1 week / 3 hours', flush=True)
    finally:
        teardown_databases(databases, verbosity=0)
        teardown_test_environment()


if __name__ == '__main__':
    main()
