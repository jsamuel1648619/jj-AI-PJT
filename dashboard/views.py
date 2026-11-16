from uuid import UUID

from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET
from django.views.decorators.cache import never_cache

from config.session_owner import session_owner
from debugdna.insights import session_insights
from debugdna.models import CodeAnalysis
from growthplan.models import DiagnosisRoadmap
from growthplan.progress import serialize_roadmap
from skillradar.models import Diagnosis, DiagnosisAttempt


@require_GET
@never_cache
def index(request):
    session_owner(request, create=True)
    return render(request, 'dashboard/index.html')


def job_details(diagnosis):
    if diagnosis is None:
        return None
    excerpt = next((line.strip() for line in diagnosis.job_posting.splitlines() if line.strip()), '')[:160]
    return {'diagnosis_id': str(diagnosis.pk), 'company': diagnosis.company, 'division': diagnosis.division,
            'role': diagnosis.role, 'title': diagnosis.job_title, 'posting_excerpt': excerpt, 'source_url': diagnosis.source_url}


@require_GET
@never_cache
def data(request):
    owner = session_owner(request)
    requested = request.GET.get('roadmap')
    selected = None
    plans = DiagnosisRoadmap.objects.filter(owner=owner).select_related('attempt__diagnosis').order_by('-created_at', '-id') if owner else DiagnosisRoadmap.objects.none()
    if requested:
        try:
            selected = plans.filter(pk=UUID(requested)).first()
        except ValueError:
            pass
        if selected is None:
            return JsonResponse({'error': '학습 계획을 찾을 수 없습니다.'}, status=404)
    else:
        selected = plans.first()
    attempt = selected.attempt if selected and selected.attempt_id else None
    if attempt is None and owner:
        attempt = DiagnosisAttempt.objects.filter(diagnosis__owner=owner, completed_at__isnull=False, result__isnull=False).select_related('diagnosis').order_by('-completed_at', '-id').first()
    diagnosis = attempt.diagnosis if attempt else (Diagnosis.objects.filter(owner=owner).order_by('-created_at', '-id').first() if owner else None)
    roadmap = serialize_roadmap(selected) if selected else None
    priority_tasks = []
    if roadmap:
        ranks = {item['name']: index for index, item in enumerate(roadmap.get('priorities', []))}
        earliest = {}
        for task in roadmap['tasks']:
            if not task['completed']:
                earliest.setdefault(task['skill'], task)
        priority_tasks = sorted(earliest.values(), key=lambda item: (ranks.get(item['skill'], len(ranks)), item['week']))[:5]
    choices = list(plans[:20])
    if selected and all(item.pk != selected.pk for item in choices):
        choices.append(selected)
    recent = CodeAnalysis.objects.filter(owner=owner).order_by('-created_at')[:5] if owner else []
    return JsonResponse({
        'updated_at': timezone.now().isoformat(), 'target_job': job_details(diagnosis),
        'diagnosis': {'attempt_id': str(attempt.pk), 'completed_at': attempt.completed_at.isoformat() if attempt.completed_at else None,
                      'scores': [{'name': item['name'], 'score': item.get('score', item.get('current_level')),
                                  'required_level': item.get('required_level'), 'gap': item.get('gap'),
                                  'evaluation_reason': item.get('evaluation_reason', '')} for item in attempt.result.get('requirements', [])]} if attempt and attempt.result else None,
        'diagnosis_matches_roadmap': bool(selected and selected.attempt_id),
        'diagnosis_count': DiagnosisAttempt.objects.filter(diagnosis__owner=owner, completed_at__isnull=False).count() if owner else 0,
        'debugdna': session_insights(owner), 'roadmap': roadmap, 'priority_tasks': priority_tasks,
        'roadmaps': [{'id': str(item.pk), 'created_at': item.created_at.isoformat(), 'total_weeks': len(item.result.get('weeks', [])),
                      'target': item.attempt.diagnosis.role or item.attempt.diagnosis.job_title if item.attempt_id else '직접 설정한 학습 계획'} for item in choices],
        'recent_analyses': [{'id': str(item.pk), 'created_at': item.created_at.isoformat(), 'summary': item.result.get('summary', '')[:300],
                             'categories': list(dict.fromkeys(finding['category'] for finding in item.findings))} for item in recent],
    })
