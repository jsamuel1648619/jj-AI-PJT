from uuid import UUID

from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.cache import never_cache
from pydantic import BaseModel, ConfigDict, Field

from skillradar.diagnosis import BusyDiagnosis
from skillradar.diagnosis_views import (InvalidInput, MissingDiagnosis, diagnostic_api,
                                       owned_attempt, parse_input)
from .models import DiagnosisRoadmap
from .planning import PlanInput, build_plan
from config.session_owner import session_owner
from debugdna.insights import session_insights
from .progress import save_roadmap, serialize_roadmap


class Target(BaseModel):
    model_config = ConfigDict(extra='forbid')
    skill_id: str = Field(min_length=1, max_length=10)
    level: int = Field(ge=1, le=5, strict=True)


class DiagnosisPlanInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    attempt_id: UUID
    targets: list[Target] = Field(default_factory=list, max_length=30)
    weeks: int = Field(default=4, ge=1, le=12, strict=True)
    hours_per_week: int = Field(default=5, ge=1, le=40, strict=True)
    weaknesses: str = Field(default='', max_length=5000)
    use_llm: bool = True


@require_POST
@diagnostic_api
def generate(request):
    data = parse_input(DiagnosisPlanInput, request)
    attempt = owned_attempt(request, data.attempt_id)
    if attempt.result is None:
        raise BusyDiagnosis('진단 평가를 먼저 완료하세요.')
    targets = {item.skill_id: item.level for item in data.targets}
    results = attempt.result['requirements']
    if len(targets) != len(data.targets) or set(targets) - {item['skill_id'] for item in results}:
        raise InvalidInput('중복되거나 진단에 없는 학습 목표입니다.')
    skills = []
    for item in results:
        target = targets.get(item['skill_id'], item['required_level'])
        if target is None:
            raise InvalidInput(f"{item['name']}의 학습 목표를 선택하세요.")
        skills.append({'name': item['name'], 'current_level': item['score'], 'target_level': target,
                       'required_level': item['required_level'], 'level_basis': item['level_basis'],
                       'importance': item['importance'], 'weight': item['weight'],
                       'experience': item['evaluation_reason'][:1000], 'evaluation_reason': item['evaluation_reason'],
                       'weak_points': item['weak_points']})
    configuration = PlanInput(skills=skills, weeks=data.weeks, hours_per_week=data.hours_per_week,
                              weaknesses=data.weaknesses, use_llm=data.use_llm)
    result = build_plan(configuration, debug_context=session_insights(session_owner(request)))
    result.update(diagnosis_attempt_id=str(attempt.pk), source_url=attempt.diagnosis.source_url)
    roadmap = save_roadmap(session_owner(request), configuration.model_dump(), result, attempt=attempt)
    return JsonResponse(serialize_roadmap(roadmap))


@require_GET
@never_cache
@diagnostic_api
def detail(request, pk):
    owner = session_owner(request)
    roadmap = DiagnosisRoadmap.objects.filter(pk=pk, owner=owner).first() if owner else None
    if roadmap is None:
        raise MissingDiagnosis()
    return JsonResponse(serialize_roadmap(roadmap))


@require_GET
@never_cache
@diagnostic_api
def history(request):
    owner = session_owner(request)
    roadmaps = DiagnosisRoadmap.objects.filter(owner=owner).order_by('-created_at')[:20] if owner else []
    return JsonResponse({'roadmaps': [{'id': str(item.pk), 'created_at': item.created_at.isoformat(),
                                     'weeks': len(item.result.get('weeks', []))} for item in roadmaps]})
