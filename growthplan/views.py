import json
from urllib.error import URLError

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from .planning import PlanInput, build_plan
from config.session_owner import session_owner
from debugdna.insights import session_insights
from .progress import save_roadmap, serialize_roadmap


@require_GET
def index(request):
    return render(request, 'growthplan/index.html')


@require_POST
def generate(request):
    if request.content_type != 'application/json':
        return JsonResponse({'error': 'application/json 형식으로 요청하세요.'}, status=415)
    try:
        data = PlanInput.model_validate(json.loads(request.body))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'error': '역량 1~30개(중복 불가), 현재 수준 0~5 또는 미평가, 목표 1~5, 기간 1~12주, 주당 1~40시간, 취약점 메모 5,000자 이내로 입력하세요.'}, status=400)
    try:
        result = build_plan(data, debug_context=session_insights(session_owner(request)))
        roadmap = save_roadmap(session_owner(request, create=True), data.model_dump(), result)
        return JsonResponse(serialize_roadmap(roadmap))
    except (URLError, TimeoutError, OSError):
        return JsonResponse({'error': 'Qwen에 연결하지 못했습니다. Ollama 설정을 확인하거나 기본 계획을 사용하세요.'}, status=503)
    except (ValueError, KeyError, TypeError):
        return JsonResponse({'error': 'Qwen 계획의 형식이나 주차 구성을 검증하지 못했습니다. 다시 시도하세요.'}, status=502)
