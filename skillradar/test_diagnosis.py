import json
from datetime import timedelta
from unittest.mock import patch
from urllib.error import URLError

from django.test import Client, TestCase
from django.utils import timezone
from pydantic import ValidationError

from .diagnosis import DiagnosticQuestion, QuestionsOutput, GradesOutput, ask_qwen, core_question
from .models import Diagnosis, DiagnosisAttempt
from .test_pipeline import POSTING, requirements
from growthplan.models import DiagnosisRoadmap


def question_fixture(ids):
    return {'questions': [{'skill_id': skill_id, 'question': f'{skill_id}에서 오류 상황을 어떻게 해결하고 검증하나요?',
                          'answer_guidance': '접근 방법과 이유를 설명하세요.',
                          'rubric': [{'level': level, 'description': f'{level} 수준의 개념과 검증 능력'} for level in range(6)]} for skill_id in ids]}


def fake_qwen(schema, system, data):
    if schema is QuestionsOutput:
        return schema.model_validate(question_fixture([item['skill_id'] for item in data['requirements']]))
    return schema.model_validate({'evaluations': [
        {'skill_id': item['skill_id'], 'score': {'s1': 1, 's2': 2, 's3': 0}.get(item['skill_id'], 1),
         'rationale': '기초 설명은 있으나 실패 상황 검증이 부족합니다.', 'evidence': [item['answer'][:100]],
         'weak_points': ['예외 처리와 경계값 검증']} for item in data['responses']]})


class DiagnosisTests(TestCase):
    def setUp(self):
        self.qwen = patch('skillradar.diagnosis.ask_qwen', side_effect=fake_qwen).start()
        self.addCleanup(patch.stopall)

    def create(self, count=3, client=None):
        client = client or self.client
        items = requirements()
        posting = POSTING
        for index in range(4, count + 1):
            evidence = f'기술{index} 경험'
            posting += '\n' + evidence
            items.append({'name': f'기술{index}', 'importance': 'required', 'evidence': evidence})
        response = client.post('/api/skillradar/diagnoses/', {'job_posting': posting, 'source_url': 'https://example.com/jobs/1', 'requirements': items[:count]}, content_type='application/json')
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def questions(self, diagnosis):
        while not diagnosis['ready']:
            response = self.client.post(f"/api/skillradar/diagnoses/{diagnosis['id']}/questions/", {}, content_type='application/json')
            self.assertEqual(response.status_code, 200, response.content)
            diagnosis = response.json()
        return diagnosis

    def attempt(self, diagnosis, blank_last=False):
        responses = [{'skill_id': item['skill_id'], 'answer': '모르겠습니다' if index == 2 else '작은 함수로 구현했습니다. 테스트는 작성하지 않았습니다.'} for index, item in enumerate(diagnosis['requirements'])]
        if blank_last:
            responses[-1]['answer'] = ''
        response = self.client.post(f"/api/skillradar/diagnoses/{diagnosis['id']}/attempts/", {'responses': responses}, content_type='application/json')
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def complete(self, attempt):
        while not attempt['completed']:
            response = self.client.post(f"/api/skillradar/attempts/{attempt['id']}/evaluate/", {}, content_type='application/json')
            self.assertEqual(response.status_code, 200, response.content)
            attempt = response.json()
        return attempt

    def test_grounded_questions_scores_and_db_snapshot(self):
        diagnosis = self.questions(self.create())
        result = self.complete(self.attempt(diagnosis))['result']
        self.assertEqual([item['score'] for item in result['requirements']], [1, 2, 0])
        self.assertEqual([item['gap'] for item in result['requirements']], [3, 1, 2])
        self.assertEqual(result['insufficient_skills'], ['Python', 'Django', 'Docker'])
        self.assertEqual(result['learning_priorities'], ['Python', 'Django', 'Docker'])
        self.assertEqual(result['requirements'][0]['priority_score'], 15)
        saved = DiagnosisAttempt.objects.get(pk=result['attempt_id'])
        self.assertEqual(saved.result, result)
        self.assertTrue(saved.completed_at)
        self.assertEqual(saved.diagnosis.source_url, 'https://example.com/jobs/1')
        self.assertEqual(len(saved.diagnosis.questionnaire[0]['rubric']), 6)
        self.assertIn(saved.result['requirements'][0]['answer_evidence'][0], saved.responses[0]['answer'])

    def test_fixed_core_rubric_is_independent_of_domain_scenario(self):
        diagnosis = self.questions(self.create())
        question = diagnosis['questions'][0]
        self.assertIn('심화 참고 상황 (답변 선택', question['question'])
        self.assertIn('익숙한 언어 하나', question['question'])
        self.assertIn('자동 테스트·성능 측정은 필수가 아니다', question['rubric'][2]['description'])
        self.complete(self.attempt(diagnosis))
        grading = next(call for call in self.qwen.call_args_list if call.args[0] is GradesOutput)
        self.assertNotIn('심화 참고 상황', grading.args[2]['questions'][0]['question'])
        self.assertEqual(set(grading.args[2]['requirements'][0]), {'skill_id', 'name'})
        self.assertEqual(core_question({'skill_id': 's1', 'name': 'Python'})['rubric'], question['rubric'])

    def test_batches_resume_and_completion_is_idempotent(self):
        diagnosis = self.create(count=4)
        url = f"/api/skillradar/diagnoses/{diagnosis['id']}/questions/"
        first = self.client.post(url, {}, content_type='application/json').json()
        self.assertEqual(first['generated'], 3)
        self.qwen.side_effect = URLError('offline')
        self.assertEqual(self.client.post(url, {}, content_type='application/json').status_code, 503)
        record = Diagnosis.objects.get(pk=diagnosis['id'])
        self.assertEqual(len(record.questionnaire), 3)
        self.assertEqual(record.processing_token, '')
        self.qwen.side_effect = fake_qwen
        diagnosis = self.questions(first)
        attempt = self.attempt(diagnosis)
        url = f"/api/skillradar/attempts/{attempt['id']}/evaluate/"
        partial = self.client.post(url, {}, content_type='application/json').json()
        self.assertEqual(partial['evaluated'], 3)
        self.qwen.side_effect = URLError('offline')
        self.assertEqual(self.client.post(url, {}, content_type='application/json').status_code, 503)
        self.qwen.side_effect = fake_qwen
        result = self.complete(partial)
        calls = self.qwen.call_count
        self.assertEqual(self.client.post(url, {}, content_type='application/json').json()['result'], result['result'])
        self.assertEqual(self.qwen.call_count, calls)

    def test_advanced_grades_preserve_model_scores_and_concrete_evidence(self):
        diagnosis = self.questions(self.create())
        examples = [
            (3, '프로젝트에서 API 구현을 맡아 검증 함수를 분리했습니다. 정상 요청과 실패 요청 24개에서 기대 응답을 확인했습니다.',
             '자신의 API 구현 역할과 함수 분리 선택, 정상·실패 요청 검증으로 프로젝트 적용 기준을 충족합니다. 독립적인 원인 분석과 개선 전후 검증은 확인되지 않습니다.'),
            (4, '혼자 쿼리 로그로 N+1 원인을 재현하고 일괄 조회를 선택했습니다. 같은 입력으로 변경 전 101회, 변경 후 2회 조회와 응답 일치를 확인했습니다. 복수 설계 비교는 하지 않았습니다.',
             '독립적인 N+1 원인 분석과 일괄 조회 선택, 조회 횟수 전후 비교 및 응답 검증으로 4점을 충족합니다. 복수 설계의 측정 비교는 확인되지 않습니다.'),
            (5, '캐시와 일괄 조회 설계를 같은 부하에서 비교했습니다. 지연은 20ms와 30ms, 메모리는 80MB와 40MB였습니다. 메모리 제한 때문에 일괄 조회를 선택해 최적화하고 회귀 검증을 추가해 재발을 방지했습니다.',
             '두 설계의 지연·메모리 측정과 제약에 따른 선택·최적화, 회귀 검증을 통한 재발 방지로 5점 기준을 충족합니다.'),
        ]
        responses = [{'skill_id': item['skill_id'], 'answer': example[1]}
                     for item, example in zip(diagnosis['requirements'], examples)]
        response = self.client.post(f"/api/skillradar/diagnoses/{diagnosis['id']}/attempts/",
                                    {'responses': responses}, content_type='application/json')
        self.assertEqual(response.status_code, 201)

        def advanced_grades(schema, system, data):
            self.assertIs(schema, GradesOutput)
            self.assertEqual(data['responses'], responses)
            self.assertIn('한 개선안의 전후 비교로 충분', system)
            self.assertIn('재발 방지 또는 확장 설계', system)
            self.assertIn('상위 수준 경험이 없다는 문장', system)
            self.assertIn('행동과 검증 결과를 해당 수준의 기준에 연결', system)
            self.assertEqual(set(data), {'questions', 'requirements', 'responses'})
            self.assertIn('복수 설계 비교나 확장 설계는 필수가 아니다', data['questions'][0]['rubric'][4]['description'])
            return GradesOutput.model_validate({'evaluations': [
                {'skill_id': item['skill_id'], 'score': score, 'rationale': rationale,
                 'evidence': [answer], 'weak_points': []}
                for item, (score, answer, rationale) in zip(responses, examples)]})

        self.qwen.side_effect = advanced_grades
        result = self.complete(response.json())['result']
        for item, (score, answer, rationale) in zip(result['requirements'], examples):
            self.assertEqual(item['score'], score)
            self.assertEqual(item['evaluation_reason'], rationale)
            self.assertEqual(item['answer_evidence'], [answer])
        saved = DiagnosisAttempt.objects.get(pk=result['attempt_id'])
        self.assertEqual([item['score'] for item in saved.evaluations], [3, 4, 5])

    def test_blank_is_unassessed_not_zero_and_answer_edits_create_new_attempt(self):
        diagnosis = self.questions(self.create())
        first = self.complete(self.attempt(diagnosis, blank_last=True))
        self.assertIsNone(first['result']['requirements'][-1]['score'])
        self.assertEqual(first['result']['summary']['unassessed'], 1)
        second = self.complete(self.attempt(diagnosis))
        self.assertEqual(second['result']['requirements'][-1]['score'], 0)
        self.assertNotEqual(first['id'], second['id'])
        self.assertEqual(DiagnosisAttempt.objects.count(), 2)

    def test_wrong_skill_ids_missing_rubric_and_fabricated_quotes_are_rejected(self):
        diagnosis = self.create()
        invalid = question_fixture(['wrong'])
        self.qwen.return_value = QuestionsOutput.model_validate(invalid)
        self.qwen.side_effect = None
        response = self.client.post(f"/api/skillradar/diagnoses/{diagnosis['id']}/questions/", {}, content_type='application/json')
        self.assertEqual(response.status_code, 502)
        self.assertEqual(Diagnosis.objects.get(pk=diagnosis['id']).questionnaire, [])
        self.qwen.side_effect = fake_qwen
        diagnosis = self.questions(diagnosis)
        attempt = self.attempt(diagnosis)
        def bad_grade(schema, system, data):
            result = fake_qwen(schema, system, data)
            result.evaluations[0].evidence = ['실제 답변에 없는 근거']
            return result
        self.qwen.side_effect = bad_grade
        self.assertEqual(self.client.post(f"/api/skillradar/attempts/{attempt['id']}/evaluate/", {}, content_type='application/json').status_code, 502)
        saved = DiagnosisAttempt.objects.get(pk=attempt['id'])
        self.assertEqual(saved.evaluations, [])
        self.assertIsNone(saved.result)

    def test_owner_isolation_and_persistent_history(self):
        diagnosis = self.questions(self.create())
        attempt = self.complete(self.attempt(diagnosis))
        other = Client()
        for path in [f"/api/skillradar/diagnoses/{diagnosis['id']}/", f"/api/skillradar/attempts/{attempt['id']}/"]:
            self.assertEqual(other.get(path).status_code, 404)
        self.assertEqual(other.get('/api/skillradar/diagnoses/history/').json()['attempts'], [])
        reopened = Client()
        reopened.cookies = self.client.cookies.copy()
        self.assertEqual(reopened.get('/api/skillradar/diagnoses/history/').json()['attempts'][0]['id'], attempt['id'])
        self.assertEqual(reopened.get(f"/api/skillradar/attempts/{attempt['id']}/").json()['responses'], DiagnosisAttempt.objects.get(pk=attempt['id']).responses)

    def test_busy_lease_rejects_duplicates_and_expired_lease_recovers(self):
        diagnosis = self.create()
        record = Diagnosis.objects.get(pk=diagnosis['id'])
        record.processing_token = 'busy'
        record.processing_started_at = timezone.now()
        record.save()
        url = f"/api/skillradar/diagnoses/{diagnosis['id']}/questions/"
        self.assertEqual(self.client.post(url, {}, content_type='application/json').status_code, 409)
        record.processing_started_at = timezone.now() - timedelta(seconds=121)
        record.save()
        self.assertEqual(self.client.post(url, {}, content_type='application/json').status_code, 200)

    def test_response_validation_and_incomplete_questionnaire(self):
        diagnosis = self.create()
        url = f"/api/skillradar/diagnoses/{diagnosis['id']}/attempts/"
        self.assertEqual(self.client.post(url, {'responses': [{'skill_id': 's1', 'answer': '설명'}]}, content_type='application/json').status_code, 409)
        diagnosis = self.questions(diagnosis)
        for responses in [[{'skill_id': 's1', 'answer': '설명'}], [{'skill_id': 's1', 'answer': '설명'}]*3,
                          [{'skill_id': item['skill_id'], 'answer': ''} for item in diagnosis['requirements']]]:
            self.assertEqual(self.client.post(url, {'responses': responses}, content_type='application/json').status_code, 400)
        payload = {'job_posting': POSTING, 'requirements': [{**requirements()[0], 'evidence': '없는 근거'}]}
        self.assertEqual(self.client.post('/api/skillradar/diagnoses/', payload, content_type='application/json').status_code, 400)

    def test_growthplan_uses_stored_scores_and_basis_and_saves_plan(self):
        attempt = self.complete(self.attempt(self.questions(self.create())))
        response = self.client.post('/api/growthplan/from-diagnosis/', {'attempt_id': attempt['id'], 'weeks': 4, 'hours_per_week': 3, 'use_llm': False}, content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)
        plan = response.json()
        self.assertEqual(plan['configuration']['skills'][0]['current_level'], 1)
        self.assertEqual(plan['configuration']['skills'][0]['evaluation_reason'], attempt['result']['requirements'][0]['evaluation_reason'])
        self.assertIn('예외 처리와 경계값 검증', plan['weeks'][0]['review'])
        self.assertEqual(plan['weeks'][0]['priority_score'], 15)
        self.assertEqual(DiagnosisRoadmap.objects.get(pk=plan['roadmap_id']).attempt_id, DiagnosisAttempt.objects.get(pk=attempt['id']).pk)
        self.assertEqual(self.client.get(f"/api/growthplan/roadmaps/{plan['roadmap_id']}/").status_code, 200)
        self.assertEqual(Client().get(f"/api/growthplan/roadmaps/{plan['roadmap_id']}/").status_code, 404)
        forged = self.client.post('/api/growthplan/from-diagnosis/', {'attempt_id': attempt['id'], 'skills': [{'name': 'Python', 'score': 5}]}, content_type='application/json')
        self.assertEqual(forged.status_code, 400)

    def test_unknown_target_and_incomplete_diagnosis_are_not_inferred(self):
        diagnosis = self.questions(self.create(count=4))
        attempt = self.attempt(diagnosis)
        self.assertEqual(self.client.post('/api/growthplan/from-diagnosis/', {'attempt_id': attempt['id'], 'use_llm': False}, content_type='application/json').status_code, 409)
        attempt = self.complete(attempt)
        self.assertEqual(self.client.post('/api/growthplan/from-diagnosis/', {'attempt_id': attempt['id'], 'use_llm': False}, content_type='application/json').status_code, 400)
        response = self.client.post('/api/growthplan/from-diagnosis/', {'attempt_id': attempt['id'], 'targets': [{'skill_id': 's4', 'level': 2}], 'use_llm': False}, content_type='application/json')
        self.assertEqual(response.status_code, 200)

    def test_csrf_and_methods(self):
        client = Client(enforce_csrf_checks=True)
        client.get('/skillradar/')
        payload = {'job_posting': POSTING, 'requirements': requirements()}
        self.assertEqual(client.post('/api/skillradar/diagnoses/', payload, content_type='application/json').status_code, 403)
        self.assertEqual(client.post('/api/skillradar/diagnoses/', payload, content_type='application/json', HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value).status_code, 201)
        self.assertEqual(client.get('/api/skillradar/diagnoses/').status_code, 405)

    def test_schema_rejects_incomplete_rubric_and_out_of_range_scores(self):
        question = question_fixture(['s1'])['questions'][0]
        with self.assertRaises(ValidationError):
            DiagnosticQuestion.model_validate({**question, 'rubric': question['rubric'][:5]})
        with self.assertRaises(ValidationError):
            GradesOutput.model_validate({'evaluations': [{'skill_id': 's1', 'score': 6, 'rationale': '평가', 'evidence': ['답변'], 'weak_points': []}]})

    @patch('skillradar.diagnosis.request.urlopen')
    def test_later_batch_ids_and_counts_are_constrained_in_model_schema(self, response):
        ids = ['s7', 's8']
        response.return_value.__enter__.return_value.read.return_value = json.dumps({'message': {'content': json.dumps(question_fixture(ids))}}).encode()
        ask_qwen(QuestionsOutput, 'system', {'requirements': [{'skill_id': identity} for identity in ids]})
        schema = json.loads(response.call_args.args[0].data)['format']
        self.assertEqual(schema['$defs']['DiagnosticQuestion']['properties']['skill_id']['enum'], ids)
        self.assertEqual(schema['properties']['questions']['type'], 'object')
        self.assertEqual(schema['properties']['questions']['required'], ids)
        self.assertFalse(schema['properties']['questions']['additionalProperties'])
        self.assertEqual(schema['properties']['questions']['properties']['s7']['required'], ['question'])
        mapped = {question['skill_id']: {'question': question['question']}
                  for question in question_fixture(ids)['questions']}
        response.return_value.__enter__.return_value.read.return_value = json.dumps({'message': {'content': json.dumps({'questions': mapped})}}).encode()
        result = ask_qwen(QuestionsOutput, 'system', {'requirements': [{'skill_id': identity} for identity in ids]})
        first_payload = response.call_args.args[0].data
        ask_qwen(QuestionsOutput, 'system', {'requirements': [{'skill_id': identity} for identity in ids]})
        self.assertEqual(response.call_args.args[0].data, first_payload)
        self.assertIsInstance(json.loads(first_payload)['options']['seed'], int)
        self.assertEqual([item.skill_id for item in result.questions], ids)
        mapped.pop('s8')
        response.return_value.__enter__.return_value.read.return_value = json.dumps({'message': {'content': json.dumps({'questions': mapped})}}).encode()
        with self.assertRaises(ValueError):
            ask_qwen(QuestionsOutput, 'system', {'requirements': [{'skill_id': identity} for identity in ids]})

    @patch('skillradar.diagnosis.request.urlopen')
    def test_raw_model_response_schema_is_checked(self, response):
        response.return_value.__enter__.return_value.read.return_value = b'{"message":{"content":"{}"}}'
        with self.assertRaises(ValidationError):
            ask_qwen(QuestionsOutput, 'system', {})
