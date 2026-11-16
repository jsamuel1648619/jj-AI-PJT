import json
from urllib.error import URLError

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from .analysis import RadarInput, EvaluationInput, analyze_radar
from .collection import CollectionInput, CollectionFailure, collect_posting


@require_GET
def index(request):
    return render(request, 'skillradar/index.html')


@require_POST
def analyze(request):
    if request.content_type != 'application/json':
        return JsonResponse({'error': 'application/json 형식으로 요청하세요.'}, status=415)
    try:
        data = RadarInput.model_validate(json.loads(request.body))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'error': '공고는 1~30,000자로 입력하세요. 역량은 중복 없이 최대 50개, 숙련도는 정수 0~5로 입력하세요.'}, status=400)
    try:
        return JsonResponse(analyze_radar(data))
    except (URLError, TimeoutError, OSError):
        return JsonResponse({'error': '분석 서비스에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.'}, status=503)
    except (ValueError, KeyError, TypeError):
        return JsonResponse({'error': 'Qwen 응답의 형식이나 공고 근거를 검증하지 못했습니다. 다시 시도하세요.'}, status=502)


@require_POST
def evaluate(request):
    if request.content_type != 'application/json':
        return JsonResponse({'error': 'application/json 형식으로 요청하세요.'}, status=415)
    try:
        data = EvaluationInput.model_validate(json.loads(request.body))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'error': '추출 역량·공고 근거·사용자 숙련도(0~5)를 확인하세요.'}, status=400)
    return JsonResponse(analyze_radar(data, requirements=data.requirements))


@require_POST
def collect(request):
    if request.content_type != 'application/json':
        return JsonResponse({'error': 'application/json 형식으로 요청하세요.'}, status=415)
    try:
        data = CollectionInput.model_validate(json.loads(request.body))
        return JsonResponse(collect_posting(data))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'error': '공개 채용 URL 또는 기업명·직무명을 확인하세요. 본문을 직접 입력할 수도 있습니다.', 'manual_input_required': True}, status=400)
    except CollectionFailure as exc:
        return JsonResponse({'error': str(exc), 'manual_input_required': True}, status=422)
