import uuid
from django.db import models


class Diagnosis(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.CharField(max_length=32, db_index=True)
    job_posting = models.TextField()
    source_url = models.CharField(max_length=2000, blank=True)
    company = models.CharField(max_length=100, blank=True)
    division = models.CharField(max_length=100, blank=True)
    role = models.CharField(max_length=100, blank=True)
    job_title = models.CharField(max_length=300, blank=True)
    requirements = models.JSONField()
    questionnaire = models.JSONField(default=list)
    model_name = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    processing_token = models.CharField(max_length=32, blank=True)
    processing_started_at = models.DateTimeField(null=True, blank=True)


class DiagnosisAttempt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    diagnosis = models.ForeignKey(Diagnosis, on_delete=models.CASCADE, related_name='attempts')
    responses = models.JSONField()
    evaluations = models.JSONField(default=list)
    result = models.JSONField(null=True, blank=True)
    model_name = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    processing_token = models.CharField(max_length=32, blank=True)
    processing_started_at = models.DateTimeField(null=True, blank=True)
