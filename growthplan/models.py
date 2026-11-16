import uuid
from django.db import models


class DiagnosisRoadmap(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.CharField(max_length=32, db_index=True, default='')
    attempt = models.ForeignKey('skillradar.DiagnosisAttempt', on_delete=models.CASCADE, related_name='roadmaps', null=True, blank=True)
    configuration = models.JSONField()
    result = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)


class LearningTask(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    roadmap = models.ForeignKey(DiagnosisRoadmap, on_delete=models.CASCADE, related_name='tasks')
    week = models.PositiveSmallIntegerField()
    completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['roadmap', 'week'], name='unique_task_per_roadmap_week')]
