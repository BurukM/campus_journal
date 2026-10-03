import logging

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone

from accounts.permissions import role_required
from notifications.models import Notification
from .forms import BasicInfoForm, CustomAuthenticationForm, ProfileForm, SignUpForm
from .models import AccessRequest, Profile, Role, User, UserRole

logger = logging.getLogger(__name__)

STANDARD_ROLE_NAMES = {
    Role.STUDENT: 'Student / Author',
    Role.REVIEWER: 'Staff Reviewer',
    Role.JOURNAL_MANAGER: 'Journal Manager',
    Role.NEWS_EDITOR: 'News Editor',
    Role.ADMINISTRATOR: 'Administrator',
    Role.CLUB_ADVISOR: 'Club Advisor',
    Role.SUPER_ADMIN: 'Super Admin',
}


class AccountLoginView(LoginView):
    form_class = CustomAuthenticationForm
    template_name = 'accounts/login.html'


class AccountLogoutView(LogoutView):
    pass


def signup(request):
    if request.user.is_authenticated:
        return redirect('accounts:dashboard')

    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.email = form.cleaned_data['email']
            role_slug = form.cleaned_data['role']
            dept = form.cleaned_data.get('department')
            note = form.cleaned_data.get('affiliation_note', '').strip()

            if role_slug == Role.STUDENT:
                # Instant student/author access
                user.is_active = True
                user.save()
                if dept:
                    user.profile.department = dept
                    user.profile.save(update_fields=['department'])
                login(request, user)
                messages.success(request, 'Welcome! Your student author account is ready.')
                return redirect('accounts:dashboard')
            else:
                # Elevated role requested: create inactive account and submit access request
                user.is_active = False
                user.save()
                if dept:
                    user.profile.department = dept
                if note:
                    user.profile.title = note[:100]
                user.profile.save()

                target_role, _ = Role.objects.get_or_create(
                    slug=role_slug,
                    defaults={
                        'name': STANDARD_ROLE_NAMES.get(
                            role_slug,
                            dict(SignUpForm.ROLE_CHOICES).get(role_slug, role_slug.replace('_', ' ').title())
                        ),
                        'description': f'Standard system role for {role_slug}.',
                    },
                )
                AccessRequest.objects.create(
                    user=user,
                    requested_role=target_role,
                    department=dept,
                    affiliation_note=note,
                )

                # Send in-app notification to all active journal administrators & managers (and superusers)
                try:
                    with transaction.atomic():
                        admin_users = User.objects.filter(
                            Q(is_superuser=True) | Q(roles__slug__in=[Role.ADMINISTRATOR, Role.JOURNAL_MANAGER])
                        ).distinct()
                        for admin in admin_users:
                            Notification.notify(
                                recipient=admin,
                                actor=user,
                                verb=f"requested {target_role.name} access",
                                target_title=f"{user.get_full_name() or user.username} ({user.email})",
                                link=reverse('accounts:access_requests'),
                            )
                except Exception as exc:
                    logger.warning("Could not dispatch access request notification for user %s: %s", user.username, exc)

                return render(
                    request,
                    'accounts/signup_pending.html',
                    {
                        'new_user': user,
                        'requested_role': target_role,
                        'department': dept,
                        'affiliation_note': note,
                    }
                )
    else:
        form = SignUpForm()

    return render(request, 'accounts/signup.html', {'form': form})


@login_required
def dashboard(request):
    """
    A single dashboard shell that surfaces different sections depending
    on the roles the logged-in user holds. Each card pulls real data
    from the submissions app now that Phase 2 exists.
    """
    from django.db.models import Q
    from submissions.models import Review, Submission

    user = request.user
    roles = user.role_slugs()

    my_submissions = Submission.objects.filter(
        Q(primary_author=user) | Q(authors=user)
    ).distinct()[:5]

    queue_count = Submission.objects.exclude(status=Submission.DRAFT).count()

    my_reviews = Review.objects.filter(reviewer=user).select_related('submission')[:5]

    news_drafts_count = 0
    news_published_count = 0
    if user.has_role(Role.NEWS_EDITOR, Role.ADMINISTRATOR):
        from news.models import NewsArticle
        news_drafts_count = NewsArticle.objects.filter(status__in=[NewsArticle.DRAFT, NewsArticle.IN_REVIEW]).count()
        news_published_count = NewsArticle.objects.filter(status=NewsArticle.PUBLISHED).count()

    pending_access_requests_count = 0
    if user.has_role(Role.JOURNAL_MANAGER, Role.ADMINISTRATOR):
        pending_access_requests_count = AccessRequest.objects.filter(status=AccessRequest.STATUS_PENDING).count()

    context = {
        'roles': roles,
        'is_student': user.has_role(Role.STUDENT),
        'is_reviewer': user.has_role(Role.REVIEWER),
        'is_journal_manager': user.has_role(Role.JOURNAL_MANAGER),
        'is_news_editor': user.has_role(Role.NEWS_EDITOR),
        'is_administrator': user.has_role(Role.ADMINISTRATOR, Role.SUPER_ADMIN),
        'my_submissions': my_submissions,
        'queue_count': queue_count,
        'my_reviews': my_reviews,
        'news_drafts_count': news_drafts_count,
        'news_published_count': news_published_count,
        'pending_access_requests_count': pending_access_requests_count,
    }
    return render(request, 'accounts/dashboard.html', context)


@role_required(Role.JOURNAL_MANAGER, Role.ADMINISTRATOR)
def access_request_list(request):
    """Staff interface for reviewing and approving elevated role applications."""
    filter_status = request.GET.get('status', 'PENDING').upper()
    requests_qs = AccessRequest.objects.select_related(
        'user', 'requested_role', 'department', 'reviewed_by'
    ).order_by('-created_at')

    if filter_status in ('PENDING', 'APPROVED', 'REJECTED'):
        requests_qs = requests_qs.filter(status=filter_status)

    pending_count = AccessRequest.objects.filter(status=AccessRequest.STATUS_PENDING).count()
    approved_count = AccessRequest.objects.filter(status=AccessRequest.STATUS_APPROVED).count()
    rejected_count = AccessRequest.objects.filter(status=AccessRequest.STATUS_REJECTED).count()

    return render(
        request, 'accounts/access_requests.html',
        {
            'requests': requests_qs,
            'filter_status': filter_status,
            'pending_count': pending_count,
            'approved_count': approved_count,
            'rejected_count': rejected_count,
        }
    )


@role_required(Role.JOURNAL_MANAGER, Role.ADMINISTRATOR)
def approve_access_request(request, pk):
    """Approves an access request, activates user account, and assigns requested role."""
    if request.method != 'POST':
        return redirect('accounts:access_requests')

    acc_req = get_object_or_404(AccessRequest, pk=pk)
    acc_req.status = AccessRequest.STATUS_APPROVED
    acc_req.reviewed_by = request.user
    acc_req.reviewed_at = timezone.now()
    acc_req.save()

    target_user = acc_req.user
    target_user.is_active = True
    target_user.save(update_fields=['is_active'])

    # Grant the approved role
    UserRole.objects.get_or_create(
        user=target_user,
        role=acc_req.requested_role,
        defaults={'assigned_by': request.user}
    )

    # In-app notification for the user
    Notification.notify(
        recipient=target_user,
        actor=request.user,
        verb="approved your application for",
        target_title=acc_req.requested_role.name,
        link=reverse('accounts:dashboard'),
    )

    messages.success(
        request,
        f"Approved {acc_req.requested_role.name} access for {target_user.get_full_name() or target_user.username}. Account is now active."
    )
    return redirect('accounts:access_requests')


@role_required(Role.JOURNAL_MANAGER, Role.ADMINISTRATOR)
def reject_access_request(request, pk):
    """Declines an access request and keeps account inactive."""
    if request.method != 'POST':
        return redirect('accounts:access_requests')

    acc_req = get_object_or_404(AccessRequest, pk=pk)
    acc_req.status = AccessRequest.STATUS_REJECTED
    acc_req.reviewed_by = request.user
    acc_req.reviewed_at = timezone.now()
    acc_req.save()

    target_user = acc_req.user
    target_user.is_active = False
    target_user.save(update_fields=['is_active'])

    messages.warning(
        request,
        f"Declined {acc_req.requested_role.name} access request from {target_user.get_full_name() or target_user.username}."
    )
    return redirect('accounts:access_requests')


@login_required
def profile_edit(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        basic_form = BasicInfoForm(request.POST, instance=request.user)
        profile_form = ProfileForm(request.POST, request.FILES, instance=profile)
        if basic_form.is_valid() and profile_form.is_valid():
            basic_form.save()
            profile_form.save()
            messages.success(request, 'Your profile has been updated.')
            return redirect('accounts:profile_detail', username=request.user.username)
    else:
        basic_form = BasicInfoForm(instance=request.user)
        profile_form = ProfileForm(instance=profile)

    return render(
        request,
        'accounts/profile_edit.html',
        {'basic_form': basic_form, 'profile_form': profile_form},
    )


def profile_detail(request, username):
    user = get_object_or_404(User, username=username)
    profile, _ = Profile.objects.get_or_create(user=user)

    if not profile.is_public and request.user != user:
        if not (request.user.is_authenticated and request.user.has_role(Role.ADMINISTRATOR, Role.SUPER_ADMIN)):
            messages.info(request, 'This profile is private.')
            return redirect('accounts:dashboard')

    return render(request, 'accounts/profile_detail.html', {'profile': profile, 'member': user})
