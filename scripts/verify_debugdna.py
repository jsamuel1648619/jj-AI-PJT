"""Live DebugDNA/Qwen and DB-backed SkillRadar/GrowthPlan integration check.

Uses an isolated test DB and fixed diagnostic scores to verify priority changes.
The code analysis and roadmap are real local Qwen calls.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()
from django.test import Client
from django.test.utils import setup_databases, setup_test_environment, teardown_databases, teardown_test_environment
from django.utils import timezone
from skillradar.models import Diagnosis, DiagnosisAttempt
from skillradar.diagnosis import build_result


def main():
    setup_test_environment()
    databases = setup_databases(verbosity=0, interactive=False)
    try:
        client = Client()
        def post(url, data):
            response = client.post(url, data, content_type='application/json')
            if response.status_code not in (200, 201):
                raise AssertionError(f'{url}: {response.status_code} {response.content.decode()}')
            return response.json()
        first = None
        for name in ('last_value', 'last_again'):
            original = f'def {name}(values):\n    if not values:\n        return None\n    return values[len(values)]'
            corrected = f'def {name}(values):\n    if not values:\n        return None\n    return values[-1]'
            data = post('/api/analyze/', {'original': original, 'corrected': corrected, 'related_skills': ['Python']})
            print('Live categories:', [item['category'] for item in data['findings']], flush=True)
            if not any(item['category'] == '경계값 오류' for item in data['findings']):
                print('Live summary:', data['summary'], flush=True)
            assert data['source'] == 'qwen' and [hint['level'] for hint in data['hints']] == [1, 2, 3]
            assert any(item['category'] == '경계값 오류' for item in data['findings'])
            for item in data['findings']:
                assert item['original_evidence'] in original and item['corrected_evidence'] in corrected
            first = first or data
            print('Live Qwen code analysis + grounded improvement + three hints:', name, flush=True)
        stats = client.get('/api/debugdna/insights/').json()
        assert stats['analysis_count'] == 2 and stats['categories']['경계값 오류'] == 2
        assert client.get(f"/api/debugdna/analyses/{first['id']}/").status_code == 200
        print('DB reload + recurrence validated: two code pairs / two boundary mistakes', flush=True)
        owner = client.session['diagnosis_owner']
        posting = 'Python 기초 실습\nSQL 기초 실습'
        requirements = [{'skill_id': f's{index}', 'name': name, 'importance': 'required', 'weight': weight,
                         'weight_reason': '필수 역량', 'evidence': f'{name} 기초 실습', 'required_level': 2,
                         'level_basis': 'inferred', 'level_reason': '기초 실습 수준', 'level_evidence': f'{name} 기초 실습'}
                        for index, (name, weight) in enumerate([('Python', 2), ('SQL', 4)], 1)]
        diagnosis = Diagnosis.objects.create(owner=owner, job_posting=posting, requirements=requirements)
        attempt = DiagnosisAttempt.objects.create(diagnosis=diagnosis, responses=[{'skill_id': f's{i}', 'answer': '기초'} for i in (1, 2)],
                  evaluations=[{'skill_id': f's{i}', 'score': 1, 'rationale': '통합 검증용 고정 진단 점수', 'evidence': ['기초'], 'weak_points': ['실습 필요']} for i in (1, 2)])
        attempt.result = build_result(attempt)
        attempt.completed_at = timezone.now()
        attempt.save()
        plan = post('/api/growthplan/from-diagnosis/', {'attempt_id': str(attempt.pk), 'weeks': 2, 'hours_per_week': 3, 'use_llm': True})
        assert [item['name'] for item in plan['priorities']] == ['Python', 'SQL']
        assert plan['priorities'][0]['debug_boost'] >= 3
        assert plan['configuration']['skills'][0]['current_level'] == 1
        assert any('DebugDNA' in week['review'] for week in plan['weeks'])
        assert client.get(f"/api/growthplan/roadmaps/{plan['roadmap_id']}/").status_code == 200
        print('Live Qwen roadmap + DB priorities validated: Python promoted, diagnostic score unchanged', flush=True)
    finally:
        teardown_databases(databases, verbosity=0)
        teardown_test_environment()


if __name__ == '__main__':
    main()
