import json
from functools import wraps
from urllib.error import URLError

from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from .diagnosis import (AttemptInput, BusyDiagnosis, DiagnosisInput, generate_questions,
                        grade_attempt, serialize_attempt, serialize_diagnosis, validate_responses)
from .models import Diagnosis, DiagnosisAttempt
from config.session_owner import session_owner


class InvalidInput(Exception):
    pass


class MissingDiagnosis(Exception):
    pass


def parse_input(schema, request):
    try:
        return schema.model_validate(json.loads(request.body))
    except (ValueError, UnicodeDecodeError) as exc:
        raise InvalidInput('진단 역량·공고 근거·응답 형식을 확인하세요.') from exc


def diagnostic_api(function):
    @wraps(function)
    def wrapped(request, *args, **kwargs):
        if request.method == 'POST' and request.content_type != 'application/json':
            return JsonResponse({'error': 'application/json 형식으로 요청하세요.'}, status=415)
        try:
            return function(request, *args, **kwargs)
        except InvalidInput as exc:
            return JsonResponse({'error': str(exc)}, status=400)
        except MissingDiagnosis:
            return JsonResponse({'error': '진단 기록을 찾을 수 없습니다. 같은 브라우저에서 다시 확인하세요.'}, status=404)
        except BusyDiagnosis as exc:
            return JsonResponse({'error': str(exc)}, status=409)
        except (URLError, TimeoutError, OSError):
            return JsonResponse({'error': '진단 서비스에 연결하지 못했습니다. 입력은 유지되며 다시 시도할 수 있습니다.'}, status=503)
        except (ValueError, KeyError, TypeError):
            return JsonResponse({'error': '진단 응답의 평가 기준·역량·근거를 검증하지 못했습니다. 다시 시도하세요.'}, status=502)
    return wrapped


def owned_diagnosis(request, pk):
    record = Diagnosis.objects.filter(pk=pk, owner=request.session.get('diagnosis_owner', '')).first()
    if record is None:
        raise MissingDiagnosis()
    return record


def owned_attempt(request, pk):
    record = DiagnosisAttempt.objects.select_related('diagnosis').filter(pk=pk, diagnosis__owner=request.session.get('diagnosis_owner', '')).first()
    if record is None:
        raise MissingDiagnosis()
    return record


@require_POST
@diagnostic_api
def create(request):
    data = parse_input(DiagnosisInput, request)
    owner = session_owner(request, create=True)
    requirements = [{**item.model_dump(), 'skill_id': f's{index}'} for index, item in enumerate(data.requirements, 1)]
    diagnosis = Diagnosis.objects.create(owner=owner, job_posting=data.job_posting, source_url=data.source_url, requirements=requirements,
                                        company=data.company, division=data.division, role=data.role, job_title=data.job_title)
    return JsonResponse(serialize_diagnosis(diagnosis), status=201)


@require_POST
@diagnostic_api
def questions(request, pk):
    diagnosis = owned_diagnosis(request, pk)
    generate_questions(diagnosis)
    return JsonResponse(serialize_diagnosis(diagnosis))


@require_GET
@diagnostic_api
def detail(request, pk):
    diagnosis = owned_diagnosis(request, pk)
    return JsonResponse({**serialize_diagnosis(diagnosis), 'job_posting': diagnosis.job_posting})


@require_POST
@diagnostic_api
def create_attempt(request, pk):
    diagnosis = owned_diagnosis(request, pk)
    data = parse_input(AttemptInput, request)
    try:
        validate_responses(data, diagnosis)
    except ValueError as exc:
        raise InvalidInput(str(exc)) from exc
    attempt = DiagnosisAttempt.objects.create(diagnosis=diagnosis, responses=[item.model_dump() for item in data.responses])
    return JsonResponse(serialize_attempt(attempt), status=201)


@require_POST
@diagnostic_api
def evaluate(request, pk):
    attempt = owned_attempt(request, pk)
    grade_attempt(attempt)
    return JsonResponse(serialize_attempt(attempt))


@require_GET
@diagnostic_api
def attempt_detail(request, pk):
    attempt = owned_attempt(request, pk)
    return JsonResponse({**serialize_attempt(attempt), 'diagnosis': {**serialize_diagnosis(attempt.diagnosis), 'job_posting': attempt.diagnosis.job_posting},
                         'responses': attempt.responses,
                         'roadmaps': [{'id': str(plan.pk), 'created_at': plan.created_at.isoformat()} for plan in attempt.roadmaps.order_by('-created_at')[:10]]})


@require_GET
@diagnostic_api
def history(request):
    attempts = DiagnosisAttempt.objects.filter(diagnosis__owner=request.session.get('diagnosis_owner', ''), completed_at__isnull=False).select_related('diagnosis').order_by('-created_at')[:30]
    return JsonResponse({'attempts': [{**serialize_attempt(item), 'source_url': item.diagnosis.source_url} for item in attempts]})
