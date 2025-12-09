import uuid
from django.db import models


class Profile(models.Model):
    identifier = models.CharField(max_length=100, unique=True)
    display_name = models.CharField(max_length=150, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.display_name or self.identifier


class ConversationSession(models.Model):
    profile = models.ForeignKey(Profile, related_name="sessions", on_delete=models.CASCADE)
    session_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    last_activity = models.DateTimeField(auto_now=True)
    metadata = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"{self.profile} - {self.session_id}"


class ConversationTurn(models.Model):
    profile = models.ForeignKey(Profile, related_name="turns", on_delete=models.CASCADE)
    session = models.ForeignKey(ConversationSession, related_name="turns", on_delete=models.CASCADE)
    prompt = models.TextField()
    response = models.TextField()
    prompt_tokens = models.IntegerField(default=0)
    completion_tokens = models.IntegerField(default=0)
    total_tokens = models.IntegerField(default=0)
    latency_ms = models.IntegerField(default=0)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Turn {self.pk} ({self.profile})"

