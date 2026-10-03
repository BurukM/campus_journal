"""
Every user gets exactly one Profile the moment they're created, and
every self-registered user starts out with the 'student' role. Extra
roles (reviewer, journal_manager, news_editor, administrator, ...) are
granted later by an administrator, from the Django admin -- see
UserRole in models.py for how that grant is recorded.
"""

from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Profile, Role, UserRole


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_profile_for_new_user(sender, instance, created, **kwargs):
    if not created:
        return

    Profile.objects.get_or_create(user=instance)

    if not instance.is_superuser and instance.is_active:
        student_role, _ = Role.objects.get_or_create(
            slug=Role.STUDENT,
            defaults={
                'name': 'Student / Author',
                'description': 'Submits projects, tracks their own submissions, responds to reviewer feedback.',
            }
        )
        UserRole.objects.get_or_create(user=instance, role=student_role)
