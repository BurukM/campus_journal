from django.conf import settings
from django.db import models


class Notification(models.Model):
    """
    In-app alert for editorial events (assignments, review decisions,
    resubmissions, and publication).
    """

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications',
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )
    verb = models.CharField(max_length=255)
    target_title = models.CharField(max_length=300)
    link = models.CharField(max_length=500, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        actor_name = (self.actor.get_full_name() or self.actor.username) if self.actor else "System"
        return f"{actor_name} {self.verb} '{self.target_title}'"

    @classmethod
    def notify(cls, recipient, verb, target_title, link='', actor=None):
        """Helper to create an in-app notification safely."""
        if recipient:
            return cls.objects.create(
                recipient=recipient,
                actor=actor,
                verb=verb,
                target_title=target_title,
                link=link,
            )
        return None
