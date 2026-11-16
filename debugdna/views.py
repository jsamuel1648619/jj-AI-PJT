import hashlib
import json
import os
from urllib.error import URLError

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from config.session_owner import session_owner
from .analysis import AnalysisInput, analyze_code
from .insights import learning_skills, session_insights
from .models import CodeAnalysis


@require_GET
def index(request):
    session_owner(request, create=True)
    return render(request, 'debugdna/index.html')


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def analysis_response(record, cached=False):
    return {**record.result, 'id': str(record.pk), 'cached': cached, 'related_skills': record.related_skills,
            'created_at': record.created_at.isoformat(), 'insights': session_insights(record.owner)}


@require_POST
def analyze(request):
    if request.content_type != 'application/json':
        return JsonResponse({'error': 'application/json 형식으로 요청하세요.'}, status=415)
    try:
        data = AnalysisInput.model_validate(json.loads(request.body))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'error': '두 코드는 각각 1~30,000자, 메모는 5,000자 이내, 관련 역량은 중복 없이 최대 10개로 입력하세요.'}, status=400)
    owner = session_owner(request)
    requested_skills = data.related_skills
    skills, attempt = learning_skills(owner, data.related_skills)
    data = data.model_copy(update={'related_skills': skills})
    code_hash = digest([data.original, data.corrected])
    model = os.environ.get('QWEN_MODEL', 'qwen3:4b-instruct-2507-q4_K_M') if data.use_llm else ''
    input_hash = digest([code_hash, data.notes, skills, data.use_llm, model])
    existing = CodeAnalysis.objects.filter(owner=owner, input_hash=input_hash).first() if owner else None
    if existing:
        return JsonResponse(analysis_response(existing, cached=True))
    try:
        result = analyze_code(data)
        result['requested_skills'] = requested_skills
    except (URLError, TimeoutError, OSError):
        return JsonResponse({'error': '분석 서비스에 연결하지 못했습니다. 입력은 유지되며 다시 시도할 수 있습니다.'}, status=503)
    except (ValueError, KeyError, TypeError):
        return JsonResponse({'error': '분석 응답의 분류·코드 근거·힌트 형식을 검증하지 못했습니다. 다시 시도하세요.'}, status=502)
    owner = session_owner(request, create=True)
    record, created = CodeAnalysis.objects.get_or_create(owner=owner, input_hash=input_hash, defaults={
        'original_code': data.original, 'corrected_code': data.corrected, 'notes': data.notes,
        'related_skills': skills, 'diagnosis': attempt.diagnosis if attempt else None,
        'code_hash': code_hash, 'findings': result['findings'], 'result': result, 'source': result['source'], 'model_name': model})
    return JsonResponse(analysis_response(record, cached=not created))


@require_GET
def history(request):
    owner = session_owner(request)
    records = CodeAnalysis.objects.filter(owner=owner).order_by('-created_at')[:30] if owner else []
    return JsonResponse({'analyses': [{'id': str(item.pk), 'created_at': item.created_at.isoformat(), 'source': item.source,
                                     'summary': item.result['summary'], 'related_skills': item.related_skills,
                                     'categories': list(dict.fromkeys(finding['category'] for finding in item.findings))} for item in records],
                         'insights': session_insights(owner)})


@require_GET
def detail(request, pk):
    record = CodeAnalysis.objects.filter(pk=pk, owner=session_owner(request)).first()
    if record is None:
        return JsonResponse({'error': '분석 기록을 찾을 수 없습니다.'}, status=404)
    return JsonResponse({**analysis_response(record), 'original_code': record.original_code, 'corrected_code': record.corrected_code, 'notes': record.notes})


@require_GET
def insights(request):
    return JsonResponse(session_insights(session_owner(request)))


@require_GET
def skills(request):
    names, attempt = learning_skills(session_owner(request))
    return JsonResponse({'skills': names, 'attempt_id': str(attempt.pk) if attempt else None})
