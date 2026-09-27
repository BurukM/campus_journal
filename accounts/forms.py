from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from .models import AccessRequest, Department, Profile, Role, User


class SignUpForm(UserCreationForm):
    ROLE_CHOICES = [
        (Role.STUDENT, 'Student / Author (Instant Access)'),
        (Role.REVIEWER, 'Staff Reviewer (Requires Admin Approval)'),
        (Role.JOURNAL_MANAGER, 'Journal Manager / Editorial Staff (Requires Admin Approval)'),
        (Role.ADMINISTRATOR, 'Administrator (Requires Admin Approval)'),
    ]

    email = forms.EmailField(required=True)
    first_name = forms.CharField(required=True, max_length=150)
    last_name = forms.CharField(required=True, max_length=150)
    role = forms.ChoiceField(
        choices=ROLE_CHOICES,
        initial=Role.STUDENT,
        widget=forms.RadioSelect(attrs={'class': 'role-radio-select'}),
        help_text="Choose the role that matches your engagement with the journal.",
    )
    department = forms.ModelChoiceField(
        queryset=Department.objects.all(),
        required=False,
        empty_label='-- Select Academic Department (Optional) --',
        help_text="Your associated university department.",
    )
    affiliation_note = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'rows': 2,
            'placeholder': 'e.g., Associate Professor, PhD Candidate in Robotics, Faculty Advisor, etc.'
        }),
        label='Academic Title / Affiliation Justification',
        help_text='Required if applying for Reviewer, Editorial Staff, or Administrator roles.',
    )

    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'email')

    def clean_email(self):
        email = self.cleaned_data['email'].lower()
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError('An account with this email already exists.')
        return email

    def clean(self):
        cleaned_data = super().clean()
        role = cleaned_data.get('role')
        affiliation_note = (cleaned_data.get('affiliation_note') or '').strip()
        department = cleaned_data.get('department')

        if role in (Role.REVIEWER, Role.JOURNAL_MANAGER, Role.ADMINISTRATOR):
            if not affiliation_note and not department:
                self.add_error(
                    'affiliation_note',
                    'Please specify your academic position or department so administrators can verify your access request.'
                )
        return cleaned_data


class CustomAuthenticationForm(AuthenticationForm):
    """
    Enhanced authentication form that explains pending review status
    when inactive accounts with access requests attempt to log in.
    """

    def clean(self):
        username = self.cleaned_data.get("username")
        password = self.cleaned_data.get("password")

        if username is not None and password:
            self.user_cache = authenticate(
                self.request, username=username, password=password
            )
            if self.user_cache is None:
                # Check if user exists with correct password but is inactive due to pending approval
                try:
                    user = User.objects.get(username=username)
                    if user.check_password(password) and not user.is_active:
                        req = getattr(user, 'access_request', None)
                        if req and req.status == AccessRequest.STATUS_PENDING:
                            raise forms.ValidationError(
                                f"Your application for {req.requested_role.name} access is currently pending administrator review. "
                                "You will be able to log in once your request is approved.",
                                code="pending_approval",
                            )
                        elif req and req.status == AccessRequest.STATUS_REJECTED:
                            raise forms.ValidationError(
                                f"Your application for {req.requested_role.name} access was reviewed and declined. "
                                "Please contact the journal administrators for further inquiries.",
                                code="request_rejected",
                            )
                        else:
                            raise forms.ValidationError(
                                "This account is inactive. Please contact the administrator.",
                                code="inactive",
                            )
                except User.DoesNotExist:
                    pass

                raise self.get_invalid_login_error()
            else:
                self.confirm_login_allowed(self.user_cache)

        return self.cleaned_data


class ProfileForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = (
            'title',
            'department',
            'class_year',
            'bio',
            'research_interests',
            'photo',
            'phone',
            'is_public',
        )
        widgets = {
            'bio': forms.Textarea(attrs={'rows': 4}),
            'research_interests': forms.Textarea(attrs={'rows': 3}),
        }


class BasicInfoForm(forms.ModelForm):
    """First name / last name live on User, not Profile."""

    class Meta:
        model = User
        fields = ('first_name', 'last_name')
