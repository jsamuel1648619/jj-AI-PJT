from django.db import transaction
from .models import DiagnosisRoadmap, LearningTask


def task_rows(roadmap):
    weeks = {item['week']: item for item in roadmap.result.get('weeks', [])}
    rows = []
    for task in sorted(roadmap.tasks.all(), key=lambda item: item.week):
        week = weeks.get(task.week)
        if week is None:
            continue
        rows.append({**week, 'id': str(task.pk), 'roadmap_id': str(roadmap.pk), 'completed': task.completed,
                     'completed_at': task.completed_at.isoformat() if task.completed_at else None,
                     'updated_at': task.updated_at.isoformat()})
    return rows


def progress(rows):
    total = len(rows)
    done = [row for row in rows if row['completed']]
    return {'total': total, 'completed': len(done), 'percent': round(len(done) / total * 100, 1) if total else 0,
            'planned_hours': sum(row.get('hours', 0) for row in rows),
            'completed_planned_hours': sum(row.get('hours', 0) for row in done)}


def serialize_roadmap(roadmap):
    rows = task_rows(roadmap)
    return {**roadmap.result, 'roadmap_id': str(roadmap.pk), 'configuration': roadmap.configuration,
            'diagnosis_attempt_id': str(roadmap.attempt_id) if roadmap.attempt_id else None,
            'diagnosis_skills': [{'name': item['name'], 'skill_id': item['skill_id']}
                                 for item in roadmap.attempt.result['requirements']] if roadmap.attempt_id else [],
            'created_at': roadmap.created_at.isoformat(), 'tasks': rows, 'progress': progress(rows)}


@transaction.atomic
def save_roadmap(owner, configuration, result, attempt=None):
    if not owner or (attempt is not None and attempt.diagnosis.owner != owner):
        raise ValueError('학습 계획 소유자가 일치하지 않습니다.')
    roadmap = DiagnosisRoadmap.objects.create(owner=owner, attempt=attempt, configuration=configuration, result=result)
    LearningTask.objects.bulk_create([LearningTask(roadmap=roadmap, week=item['week']) for item in result.get('weeks', [])])
    return roadmap
