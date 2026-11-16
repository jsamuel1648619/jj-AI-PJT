from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST
from pydantic import BaseModel, ConfigDict, Field

from config.session_owner import session_owner
from skillradar.diagnosis_views import MissingDiagnosis, diagnostic_api, parse_input
from .models import LearningTask
from .progress import task_rows, progress


class TaskCompletion(BaseModel):
    model_config = ConfigDict(extra='forbid')
    completed: bool = Field(strict=True)


@require_POST
@diagnostic_api
def completion(request, pk):
    data = parse_input(TaskCompletion, request)
    owner = session_owner(request)
    task = LearningTask.objects.select_related('roadmap').filter(pk=pk, roadmap__owner=owner).first() if owner else None
    if task is None:
        return JsonResponse({'error': '학습 과제를 찾을 수 없습니다.'}, status=404)
    now = timezone.now()
    # Conditional updates make duplicate complete/cancel requests idempotent.
    LearningTask.objects.filter(pk=pk, completed=not data.completed).update(
        completed=data.completed, completed_at=now if data.completed else None, updated_at=now)
    rows = task_rows(task.roadmap)
    return JsonResponse({'task': next(row for row in rows if row['id'] == str(task.pk)),
                         'roadmap_id': str(task.roadmap_id), 'progress': progress(rows)})
