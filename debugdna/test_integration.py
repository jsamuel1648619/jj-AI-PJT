import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import Client, TestCase
from django.utils import timezone

from .analysis import AnalysisInput, analyze_code
from .insights import session_insights
from .models import CodeAnalysis
from skillradar.models import Diagnosis, DiagnosisAttempt
from skillradar.diagnosis import build_result

ORIGINAL = 'def last(values):\n    if not values:\n        return None\n    return values[len(values)]'
CORRECTED = 'def last(values):\n    if not values:\n        return None\n    return values[-1]'


def qwen_fixture(original=ORIGINAL, corrected=CORRECTED, skill='Python'):
    return {'summary': '인덱스 경계값을 수정했습니다.', 'findings': [
        {'mistake_type': 'boundary', 'explanation': '길이와 같은 인덱스는 범위를 벗어납니다.',
         'improvement': '음수 인덱스로 마지막 요소에 접근합니다.',
         'original_evidence': original.splitlines()[-1], 'corrected_evidence': corrected.splitlines()[-1],
         'practice': '빈 리스트와 원소 한 개의 리스트를 비교해 검증하세요.', 'related_skills': [skill]}],
        'hints': {'concept': '길이와 마지막 위치의 차이를 생각하세요.',
                  'location': '원소가 한 개인 리스트에서 인덱스를 적어 보세요.',
                  'approach': '마지막 인덱스로 수정하고 빈 입력 분기를 검증하세요.'}}


def seed_attempt(owner):
    posting = 'Python 기초 실습 경험\nSQL 기초 실습 경험'
    requirements = [{'skill_id': f's{index}', 'name': name, 'importance': 'required', 'required_level': 2,
                     'level_basis': 'inferred', 'level_reason': '기초 실습', 'level_evidence': f'{name} 기초 실습 경험',
                     'evidence': f'{name} 기초 실습 경험', 'weight': weight, 'weight_reason': '공고 필수 역량'}
                    for index, (name, weight) in enumerate([('Python', 2), ('SQL', 4)], 1)]
    diagnosis = Diagnosis.objects.create(owner=owner, job_posting=posting, source_url='https://example.com/job', requirements=requirements)
    attempt = DiagnosisAttempt.objects.create(diagnosis=diagnosis, responses=[{'skill_id': 's1', 'answer': '기초'}, {'skill_id': 's2', 'answer': '기초'}],
        evaluations=[{'skill_id': f's{i}', 'score': 1, 'rationale': '기초 설명', 'evidence': ['기초'], 'weak_points': ['실습 필요']} for i in (1, 2)])
    attempt.result = build_result(attempt)
    attempt.completed_at = timezone.now()
    attempt.save()
    return attempt


class DebugDNAIntegrationTests(TestCase):
    def setUp(self):
        self.response = patch('debugdna.analysis.request.urlopen').start()
        self.addCleanup(patch.stopall)
        self.set_output(qwen_fixture())

    def set_output(self, result):
        self.response.return_value.__enter__.return_value.read.return_value = json.dumps({'message': {'content': json.dumps(result)}}).encode()

    def analyze(self, original=ORIGINAL, corrected=CORRECTED, **extra):
        return self.client.post('/api/analyze/', {'original': original, 'corrected': corrected, 'related_skills': ['Python'], **extra}, content_type='application/json')

    def test_preserves_indentation_and_never_executes_code(self):
        data = AnalysisInput(original='  value = 1\n', corrected='value = 1\n', use_llm=False)
        self.assertEqual(data.original, '  value = 1\n')
        result = analyze_code(data)
        self.assertFalse(result['original']['valid'])
        self.assertTrue(result['corrected']['valid'])
        with tempfile.TemporaryDirectory() as folder:
            marker = Path(folder) / 'must-not-exist'
            code = f'from pathlib import Path\nPath({str(marker)!r}).write_text("executed")'
            analyze_code(AnalysisInput(original=code, corrected=code + '\n', use_llm=False))
            self.assertFalse(marker.exists())

    def test_grounded_analysis_hints_and_cache_are_persisted(self):
        first = self.analyze()
        self.assertEqual(first.status_code, 200, first.content)
        data = first.json()
        self.assertEqual(data['source'], 'qwen')
        self.assertEqual([hint['level'] for hint in data['hints']], [1, 2, 3])
        saved = CodeAnalysis.objects.get(pk=data['id'])
        self.assertEqual(saved.original_code, ORIGINAL)
        self.assertIn(saved.findings[0]['corrected_evidence'], saved.corrected_code)
        again = self.analyze().json()
        self.assertEqual(again['id'], data['id'])
        self.assertTrue(again['cached'])
        self.assertEqual(self.response.call_count, 1)

    def test_frequency_deduplicates_code_pairs_and_duplicate_findings(self):
        duplicate = qwen_fixture()
        duplicate['findings'] *= 2
        self.set_output(duplicate)
        self.analyze()
        self.analyze(notes='다른 메모로 재분석')
        self.assertEqual(CodeAnalysis.objects.count(), 2)
        stats = session_insights(self.client.session['diagnosis_owner'])
        self.assertEqual(stats['categories']['경계값 오류'], 1)
        self.assertEqual(stats['analysis_count'], 1)
        original, corrected = ORIGINAL.replace('last(', 'last_again('), CORRECTED.replace('last(', 'last_again(')
        self.set_output(qwen_fixture(original, corrected))
        self.analyze(original, corrected)
        stats = session_insights(self.client.session['diagnosis_owner'])
        self.assertEqual(stats['categories']['경계값 오류'], 2)
        self.assertEqual(stats['weak_skills'][0]['priority_boost'], 3)
        self.assertEqual(stats['weak_skills'][0]['repeated_categories'], {'경계값 오류': 2})

    def test_invalid_evidence_taxonomy_skills_and_hints_do_not_save(self):
        for field, value in [('original_evidence', 'return fabricated'), ('corrected_evidence', 'not in code'), ('mistake_type', '없는 분류'), ('mistake_type', 'syntax'), ('related_skills', ['AWS'])]:
            output = qwen_fixture()
            output['findings'][0][field] = value
            self.set_output(output)
            self.assertEqual(self.analyze().status_code, 502)
        output = qwen_fixture()
        output['hints'].pop('location')
        self.set_output(output)
        self.assertEqual(self.analyze().status_code, 502)
        self.assertEqual(CodeAnalysis.objects.count(), 0)

    def test_unchanged_lines_are_not_accepted_as_improvement_evidence(self):
        output = qwen_fixture()
        output['findings'][0]['original_evidence'] = 'def last(values):'
        self.set_output(output)
        self.assertEqual(self.analyze().status_code, 502)
        self.assertEqual(CodeAnalysis.objects.count(), 0)

    def test_history_and_insights_are_session_isolated(self):
        data = self.analyze().json()
        self.assertEqual(len(self.client.get('/api/debugdna/history/').json()['analyses']), 1)
        self.assertEqual(self.client.get(f"/api/debugdna/analyses/{data['id']}/").json()['original_code'], ORIGINAL)
        other = Client()
        self.assertEqual(other.get(f"/api/debugdna/analyses/{data['id']}/").status_code, 404)
        self.assertEqual(other.get('/api/debugdna/history/').json()['analyses'], [])
        self.assertEqual(other.get('/api/debugdna/insights/').json()['analysis_count'], 0)

    def test_skillradar_candidates_and_same_owner_are_shared(self):
        self.analyze()
        owner = self.client.session['diagnosis_owner']
        attempt = seed_attempt(owner)
        candidates = self.client.get('/api/debugdna/skills/').json()
        self.assertEqual(candidates['skills'], ['Python', 'SQL'])
        self.assertEqual(candidates['attempt_id'], str(attempt.pk))
        response = self.analyze(notes='진단 연동', related_skills=[])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(CodeAnalysis.objects.get(pk=response.json()['id']).diagnosis_id, attempt.diagnosis_id)

    def test_growthplan_boost_uses_db_history_without_changing_diagnostic_scores(self):
        self.analyze()
        original, corrected = ORIGINAL.replace('last(', 'other('), CORRECTED.replace('last(', 'other(')
        self.set_output(qwen_fixture(original, corrected))
        self.analyze(original, corrected)
        attempt = seed_attempt(self.client.session['diagnosis_owner'])
        response = self.client.post('/api/growthplan/from-diagnosis/', {'attempt_id': str(attempt.pk), 'weeks': 2, 'use_llm': False}, content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)
        plan = response.json()
        self.assertEqual([item['name'] for item in plan['priorities']], ['Python', 'SQL'])
        self.assertEqual(plan['priorities'][0]['base_priority_score'], 2)
        self.assertEqual(plan['priorities'][0]['debug_boost'], 3)
        self.assertEqual(plan['priorities'][0]['priority_score'], 5)
        self.assertEqual(plan['configuration']['skills'][0]['current_level'], 1)
        attempt.refresh_from_db()
        self.assertEqual(attempt.result['requirements'][0]['score'], 1)
        self.assertIn('DebugDNA', plan['weeks'][0]['review'])
        other = Client()
        standalone = other.post('/api/growthplan/generate/', {'skills': [{'name': 'Python', 'current_level': 1, 'target_level': 2, 'weight': 2}, {'name': 'SQL', 'current_level': 1, 'target_level': 2, 'weight': 4}], 'use_llm': False}, content_type='application/json').json()
        self.assertEqual([item['name'] for item in standalone['priorities']], ['SQL', 'Python'])
        self.assertEqual(standalone['debugdna_insights']['analysis_count'], 0)

    def test_reinforcement_for_met_goal_and_group_order_are_preserved(self):
        self.analyze()
        plan = self.client.post('/api/growthplan/generate/', {'skills': [{'name': 'Python', 'current_level': 3, 'target_level': 3, 'importance': 'preferred'}, {'name': 'SQL', 'current_level': 1, 'target_level': 2, 'importance': 'required'}], 'use_llm': False}, content_type='application/json').json()
        self.assertEqual(plan['reinforcement_skills'], ['Python'])
        self.assertEqual([item['name'] for item in plan['priorities']], ['SQL', 'Python'])

    def test_skillradar_uses_mistakes_for_questions_but_not_answer_scoring(self):
        from skillradar.test_diagnosis import fake_qwen
        self.analyze()
        attempt = seed_attempt(self.client.session['diagnosis_owner'])
        with patch('skillradar.diagnosis.ask_qwen', side_effect=fake_qwen) as qwen:
            url = f'/api/skillradar/diagnoses/{attempt.diagnosis_id}'
            response = self.client.post(url + '/questions/', {}, content_type='application/json')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(qwen.call_args.args[2]['debugdna']['analysis_count'], 1)
            created = self.client.post(url + '/attempts/', {'responses': [{'skill_id': 's1', 'answer': '기초'}, {'skill_id': 's2', 'answer': '기초'}]}, content_type='application/json').json()
            response = self.client.post(f"/api/skillradar/attempts/{created['id']}/evaluate/", {}, content_type='application/json')
            self.assertEqual(response.status_code, 200)
            self.assertNotIn('debugdna', qwen.call_args.args[2])

    def test_whitespace_only_code_and_duplicate_skill_aliases_are_rejected(self):
        self.assertEqual(self.analyze(original=' \n\t').status_code, 400)
        self.assertEqual(self.analyze(related_skills=['Python', '파이썬']).status_code, 400)
        self.assertEqual(CodeAnalysis.objects.count(), 0)
