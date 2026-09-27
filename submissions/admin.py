from django.contrib import admin

from .models import AuditLogEntry, Review, Submission, SubmissionAuthor, SubmissionVersion


class SubmissionAuthorInline(admin.TabularInline):
    model = SubmissionAuthor
    extra = 0


class SubmissionVersionInline(admin.TabularInline):
    model = SubmissionVersion
    extra = 0
    readonly_fields = ('uploaded_at',)


class ReviewInline(admin.TabularInline):
    model = Review
    extra = 0
    readonly_fields = ('assigned_at', 'decided_at')


class AuditLogInline(admin.TabularInline):
    model = AuditLogEntry
    extra = 0
    readonly_fields = ('user', 'action', 'from_status', 'to_status', 'message', 'timestamp')
    can_delete = False


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ('title', 'primary_author', 'department', 'status', 'current_version_number', 'updated_at')
    list_filter = ('status', 'department')
    search_fields = ('title', 'abstract', 'primary_author__username')
    inlines = [SubmissionAuthorInline, SubmissionVersionInline, ReviewInline, AuditLogInline]


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ('submission', 'reviewer', 'round', 'decision', 'assigned_at', 'decided_at')
    list_filter = ('decision',)
    search_fields = ('submission__title', 'reviewer__username')
