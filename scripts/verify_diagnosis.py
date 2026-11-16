"""Live Qwen diagnosis/DB/roadmap check in an isolated temporary test database."""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()
from django.test import Client
from django.test.utils import setup_databases, setup_test_environment, teardown_databases, teardown_test_environment
from skillradar.analysis import RadarInput, analyze_radar
from skillradar.collection import CollectionInput, collect_posting


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', help='Optional public posting URL for live Selenium collection')
    args = parser.parse_args()
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
