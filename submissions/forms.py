from django import forms
from django.contrib.auth import get_user_model
from django.core.validators import FileExtensionValidator

from accounts.models import Role
from .models import Review, Submission

User = get_user_model()

from django.conf import settings

def get_max_upload_size_mb():
    return getattr(settings, 'MAX_SUBMISSION_UPLOAD_SIZE_MB', 50)

# Backward-compatibility alias
MAX_UPLOAD_SIZE_MB = get_max_upload_size_mb()


class SubmissionForm(forms.ModelForm):
    """
    Metadata only. The actual files are attached afterward as a
    SubmissionVersion, per the plan's separation of "submission" (the
    academic record) from "files" (versioned attachments).
    """

    co_authors_usernames = forms.CharField(
        required=False,
        label='Co-authors (usernames, comma-separated)',
        help_text='Optional. Each username must already have an account on the site.',
    )

    class Meta:
        model = Submission
        fields = ['title', 'abstract', 'keywords', 'department', 'supervisor_name']
        widgets = {
            'abstract': forms.Textarea(attrs={'rows': 5}),
        }


class VersionUploadForm(forms.Form):
    file = forms.FileField(
        validators=[FileExtensionValidator(allowed_extensions=['zip', 'pdf'])],
        help_text=(
            'Upload a .zip package containing your project files (or a .pdf). '
            'IMPORTANT: Please include a PDF file named "Technical Design Brief.pdf" '
            '(or "Design Brief.pdf") in your upload for automatic compilation into responsive HTML.'
        ),
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 2}),
        help_text='Optional: what changed since the last version.',
    )

    def clean_file(self):
        f = self.cleaned_data['file']
        max_mb = get_max_upload_size_mb()
        if f.size > max_mb * 1024 * 1024:
            raise forms.ValidationError(f'File is too large (max {max_mb} MB).')
        return f


class AssignReviewerForm(forms.Form):
    reviewer = forms.ModelChoiceField(
        queryset=User.objects.filter(roles__slug=Role.REVIEWER).distinct(),
        help_text='Only users holding the Reviewer role are listed.',
    )


class ReviewDecisionForm(forms.Form):
    DECISION_TO_STATUS = {
        Review.ACCEPT: Submission.ACCEPTED,
        Review.REVISION_REQUIRED: Submission.REVISION_REQUIRED,
        Review.REJECT: Submission.REJECTED,
    }

    decision = forms.ChoiceField(
        choices=[
            (Review.ACCEPT, 'Accept'),
            (Review.REVISION_REQUIRED, 'Request revision'),
            (Review.REJECT, 'Reject'),
        ]
    )
    comments = forms.CharField(widget=forms.Textarea(attrs={'rows': 4}), required=True)
