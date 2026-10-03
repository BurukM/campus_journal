"""
Phase 2: research submission workflow.

This follows the architecture plan closely:

- `Submission.status` is a controlled state machine (see `STATUS_CHOICES`
  and `transitions.py`), not a free-text or boolean flag, so the system
  can enforce which role may move a submission from which state to
  which other state.
- File uploads are versioned (`SubmissionVersion`) rather than
  overwriting a single file field -- old versions are never deleted.
- `AuditLogEntry` records every meaningful state change, so "what
  happened to my paper?" always has an answer.
- Authors are a through-model (`SubmissionAuthor`) rather than a bare
  ManyToMany, because a submission needs an author *order* and a
  corresponding-author flag, and this leaves room to record who added
  whom later.

Phase 2 only wires up the early states (DRAFT -> SUBMITTED -> SCREENING,
plus WITHDRAWN). The rest of the enum (ASSIGNED, UNDER_REVIEW,
REVISION_REQUIRED, ACCEPTED, IN_PRODUCTION, READY_TO_PUBLISH, PUBLISHED,
REJECTED) is defined now so the database schema doesn't need to change
shape in Phase 3/4 -- only `transitions.py` grows.
"""

from django.conf import settings
from django.core.validators import FileExtensionValidator
from django.db import models

from accounts.models import Department


def submission_version_upload_path(instance, filename):
    return f'submissions/{instance.submission_id}/versions/v{instance.version_number}/{filename}'


class Submission(models.Model):
    DRAFT = 'DRAFT'
    SUBMITTED = 'SUBMITTED'
    SCREENING = 'SCREENING'
    ASSIGNED = 'ASSIGNED'
    UNDER_REVIEW = 'UNDER_REVIEW'
    REVISION_REQUIRED = 'REVISION_REQUIRED'
    RESUBMITTED = 'RESUBMITTED'
    ACCEPTED = 'ACCEPTED'
    IN_PRODUCTION = 'IN_PRODUCTION'
    READY_TO_PUBLISH = 'READY_TO_PUBLISH'
    PUBLISHED = 'PUBLISHED'
    REJECTED = 'REJECTED'
    WITHDRAWN = 'WITHDRAWN'

    STATUS_CHOICES = [
        (DRAFT, 'Draft'),
        (SUBMITTED, 'Submitted'),
        (SCREENING, 'Screening'),
        (ASSIGNED, 'Assigned'),
        (UNDER_REVIEW, 'Under review'),
        (REVISION_REQUIRED, 'Revision required'),
        (RESUBMITTED, 'Resubmitted'),
        (ACCEPTED, 'Accepted'),
        (IN_PRODUCTION, 'In production'),
        (READY_TO_PUBLISH, 'Ready to publish'),
        (PUBLISHED, 'Published'),
        (REJECTED, 'Rejected'),
        (WITHDRAWN, 'Withdrawn'),
    ]

    title = models.CharField(max_length=300)
    abstract = models.TextField()
    keywords = models.CharField(
        max_length=300, blank=True, help_text='Comma-separated, e.g. "neonatal care, syringe pump"'
    )
    department = models.ForeignKey(
        Department, on_delete=models.SET_NULL, null=True, blank=True, related_name='submissions'
    )
    supervisor_name = models.CharField(max_length=150, blank=True)

    primary_author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='submissions_authored'
    )
    authors = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through='SubmissionAuthor',
        related_name='submissions_coauthored',
        blank=True,
    )

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=DRAFT)
    current_version_number = models.PositiveIntegerField(default=0)

    slug = models.SlugField(
        max_length=330, unique=True, null=True, blank=True,
        help_text='Set automatically when the submission is published; used in its public URL.',
    )
    published_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return self.title

    def keyword_list(self):
        return [k.strip() for k in self.keywords.split(',') if k.strip()]

    def latest_version(self):
        return self.versions.order_by('-version_number').first()

    def latest_compiled_version(self):
        return self.versions.filter(compilation_status=SubmissionVersion.STATUS_COMPILED).order_by('-version_number').first()

    def get_compiled_html(self):
        compiled_v = self.latest_compiled_version()
        if compiled_v and compiled_v.compiled_html:
            return compiled_v.compiled_html
        latest = self.latest_version()
        return latest.compiled_html if latest else ''

    def current_review(self):
        return self.reviews.order_by('-assigned_at').first()

    def get_absolute_url(self):
        from django.urls import reverse
        if self.slug and self.status == self.PUBLISHED:
            return reverse('projects:detail', kwargs={'slug': self.slug})
        return None

    def is_author(self, user):
        return self.primary_author_id == user.id or self.authors.filter(pk=user.id).exists()


class SubmissionAuthor(models.Model):
    """Through-model for Submission <-> author, preserving order."""

    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name='+')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    order = models.PositiveIntegerField(default=0)
    is_corresponding = models.BooleanField(default=False)

    class Meta:
        unique_together = ('submission', 'user')
        ordering = ['order']

    def __str__(self):
        return f'{self.user} on {self.submission}'


class SubmissionVersion(models.Model):
    """
    One uploaded version of a submission's source files. Never
    overwritten -- a new upload always creates a new row with an
    incremented version_number, per the plan's versioning guidance.
    """

    STATUS_PENDING = 'PENDING'
    STATUS_COMPILED = 'COMPILED'
    STATUS_FAILED = 'FAILED'
    STATUS_NOT_FOUND = 'NOT_FOUND'

    COMPILATION_STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_COMPILED, 'Compiled'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_NOT_FOUND, 'Design Brief PDF Not Found'),
    ]

    UPLOAD_PENDING = 'PENDING'
    UPLOAD_COMPLETED = 'COMPLETED'
    UPLOAD_FAILED = 'FAILED'

    UPLOAD_STATUS_CHOICES = [
        (UPLOAD_PENDING, 'Pending'),
        (UPLOAD_COMPLETED, 'Completed'),
        (UPLOAD_FAILED, 'Failed'),
    ]

    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name='versions')
    version_number = models.PositiveIntegerField()
    file = models.FileField(
        upload_to=submission_version_upload_path,
        validators=[FileExtensionValidator(allowed_extensions=['zip', 'pdf'])],
        blank=True,
        null=True,
    )
    storage_path = models.CharField(
        max_length=500, blank=True, help_text='Supabase Storage object path/key'
    )
    original_filename = models.CharField(max_length=255, blank=True)
    content_type = models.CharField(max_length=100, blank=True)
    file_size = models.PositiveBigIntegerField(default=0, help_text='File size in bytes')
    upload_status = models.CharField(
        max_length=30, choices=UPLOAD_STATUS_CHOICES, default=UPLOAD_COMPLETED
    )
    notes = models.TextField(blank=True, help_text='e.g. what changed since the last version')
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    # Compilation outputs for Technical Design Brief
    compilation_status = models.CharField(
        max_length=30, choices=COMPILATION_STATUS_CHOICES, default=STATUS_PENDING
    )
    brief_filename = models.CharField(max_length=255, blank=True)
    compiled_html = models.TextField(blank=True)
    compilation_error = models.TextField(blank=True)
    compiled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('submission', 'version_number')
        ordering = ['-version_number']

    def __str__(self):
        return f'{self.submission} v{self.version_number}'

    @property
    def filename(self):
        if self.original_filename:
            return self.original_filename
        if self.file:
            import os
            return os.path.basename(self.file.name)
        if self.storage_path:
            import os
            return os.path.basename(self.storage_path)
        return f'version_{self.version_number}'

    def get_file_size_display(self):
        size = self.file_size
        if not size and self.file:
            try:
                size = self.file.size
            except Exception:
                size = 0
        if not size:
            return ''
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}" if unit != 'B' else f"{size} B"
            size /= 1024
        return f"{size:.1f} TB"

    @property
    def download_url(self):
        from django.urls import reverse
        return reverse('submissions:version_download', kwargs={'pk': self.submission_id, 'version_number': self.version_number})


class AuditLogEntry(models.Model):
    """
    Every state change and every version upload gets a row here, so a
    submission's full history can always be reconstructed -- the audit
    trail the plan calls for, so "what happened to my paper?" has a
    real answer instead of a shrug.
    """

    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name='audit_log')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=100)
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20, blank=True)
    message = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f'{self.submission} — {self.action} @ {self.timestamp:%Y-%m-%d %H:%M}'


class Review(models.Model):
    """
    One reviewer's assignment to a submission and their eventual
    decision. Kept as a single evolving row per review "round" rather
    than one immutable row per comment, matching the plan's
    Reviewer/Submission/Comments/Recommendation/Date sketch -- the
    play-by-play of *why* now lives in AuditLogEntry, this row is the
    current assignment + decision.

    `round` increments each time a submission comes back for another
    look after REVISION_REQUIRED -> RESUBMITTED, so a reviewer can
    review the same submission more than once without losing the
    record of the earlier round's decision (which stays in the audit
    log's message text).
    """

    PENDING = 'PENDING'
    ACCEPT = 'ACCEPT'
    REVISION_REQUIRED = 'REVISION_REQUIRED'
    REJECT = 'REJECT'

    DECISION_CHOICES = [
        (PENDING, 'Pending'),
        (ACCEPT, 'Accept'),
        (REVISION_REQUIRED, 'Revision required'),
        (REJECT, 'Reject'),
    ]

    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name='reviews')
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reviews_assigned'
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    round = models.PositiveIntegerField(default=1)
    decision = models.CharField(max_length=20, choices=DECISION_CHOICES, default=PENDING)
    comments = models.TextField(blank=True)
    assigned_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-assigned_at']

    def __str__(self):
        return f'Review of {self.submission} by {self.reviewer} (round {self.round})'
