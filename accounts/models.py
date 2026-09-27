"""
Phase 1 foundation models: identity, roles/permissions, and profiles.

Design notes (matching the club's architecture plan):

- Roles are a first-class model, not a fixed choices field, because a
  person can hold several roles at once and roles may be added later
  (e.g. "Copyeditor", "Club Advisor") without a migration that touches
  every user row.
- The User <-> Role relationship goes through UserRole rather than a
  bare ManyToManyField so *who granted a role and when* is recorded from
  day one -- the beginning of the audit trail the plan calls for.
- Profile is deliberately separate from User: User is about
  authentication (username/email/password), Profile is about the public
  academic identity (bio, department, photo, research interests).
"""

from django.contrib.auth.models import AbstractUser
from django.db import models


class Department(models.Model):
    """An academic department or program (e.g. 'Biomedical Engineering')."""

    name = models.CharField(max_length=150, unique=True)
    short_name = models.CharField(max_length=30, blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Role(models.Model):
    """
    A role a user can hold, e.g. student, reviewer, journal_manager,
    news_editor, administrator, club_advisor, super_admin.

    Kept as data (not a hardcoded choices list) so new roles can be added
    from the admin as the club's editorial process grows, per the plan's
    recommendation to separate "roles" from "people".
    """

    STUDENT = 'student'
    REVIEWER = 'reviewer'
    JOURNAL_MANAGER = 'journal_manager'
    NEWS_EDITOR = 'news_editor'
    ADMINISTRATOR = 'administrator'
    CLUB_ADVISOR = 'club_advisor'
    SUPER_ADMIN = 'super_admin'

    slug = models.SlugField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class User(AbstractUser):
    """
    Custom user model. We start with a custom model from day one (rather
    than the default auth.User) because swapping it in later is painful
    -- this is the classic "always customize AUTH_USER_MODEL up front"
    rule for any non-trivial Django project.
    """

    email = models.EmailField('email address', unique=True)
    roles = models.ManyToManyField(
        Role,
        through='UserRole',
        through_fields=('user', 'role'),
        related_name='users',
        blank=True,
    )

    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = ['email']

    def has_role(self, *slugs):
        """True if the user holds ANY of the given role slugs."""
        if self.is_superuser:
            return True
        return self.roles.filter(slug__in=slugs).exists()

    @property
    def is_manager(self):
        """Convenience flag for templates (e.g. the nav bar) that can't pass extra context."""
        return self.has_role(Role.JOURNAL_MANAGER, Role.ADMINISTRATOR)

    @property
    def is_reviewer_role(self):
        return self.has_role(Role.REVIEWER)

    @property
    def is_news_editor(self):
        return self.has_role(Role.NEWS_EDITOR, Role.ADMINISTRATOR)

    def role_slugs(self):
        return list(self.roles.values_list('slug', flat=True))

    def __str__(self):
        return self.get_full_name() or self.username


class UserRole(models.Model):
    """
    The through-table for User <-> Role.

    Recording assigned_by and assigned_at turns "who can do what" into
    an auditable fact rather than an opaque flag, matching the plan's
    emphasis on an audit trail for every meaningful state change.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='+')
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name='+')
    assigned_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='roles_granted',
    )
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'role')
        ordering = ['-assigned_at']

    def __str__(self):
        return f'{self.user} -> {self.role}'


class Profile(models.Model):
    """
    The public-facing academic identity for a user: what shows up on
    /people/<username>/ once that page exists. Deliberately separate
    from User (auth) per the plan's data-modeling guidance.
    """

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name='profile'
    )
    title = models.CharField(
        max_length=100,
        blank=True,
        help_text="e.g. 'Lecturer', 'Club Member', 'Biomedical Engineering — Class of 2027'",
    )
    department = models.ForeignKey(
        Department, on_delete=models.SET_NULL, null=True, blank=True, related_name='members'
    )
    class_year = models.PositiveIntegerField(null=True, blank=True)
    bio = models.TextField(blank=True)
    research_interests = models.TextField(blank=True)
    photo = models.ImageField(upload_to='profile_photos/', blank=True, null=True)
    phone = models.CharField(max_length=30, blank=True)
    is_public = models.BooleanField(
        default=True,
        help_text='Whether this profile is visible on the public People page.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'Profile<{self.user}>'


class AccessRequest(models.Model):
    """
    Application for elevated staff/reviewer/admin roles submitted during registration.
    Requires administrator approval before the account can log in.
    """

    STATUS_PENDING = 'PENDING'
    STATUS_APPROVED = 'APPROVED'
    STATUS_REJECTED = 'REJECTED'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending Review'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_REJECTED, 'Rejected'),
    ]

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='access_request',
    )
    requested_role = models.ForeignKey(
        Role,
        on_delete=models.CASCADE,
        related_name='+',
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )
    affiliation_note = models.TextField(
        blank=True,
        help_text="Position, academic lab, department, or reason for requesting elevated role.",
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} -> {self.requested_role.name} ({self.status})"

