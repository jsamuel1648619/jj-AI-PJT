import uuid
from django.db import models


class CodeAnalysis(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.CharField(max_length=32, db_index=True)
    original_code = models.TextField()
    corrected_code = models.TextField()
    notes = models.TextField(blank=True)
    related_skills = models.JSONField(default=list)
    diagnosis = models.ForeignKey('skillradar.Diagnosis', on_delete=models.SET_NULL, null=True, blank=True)
    code_hash = models.CharField(max_length=64)
    input_hash = models.CharField(max_length=64)
    findings = models.JSONField(default=list)
    result = models.JSONField()
    source = models.CharField(max_length=10)
    model_name = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['owner', 'input_hash'], name='unique_debug_input_per_owner')]
