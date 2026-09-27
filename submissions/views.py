from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from accounts.models import Department, Role
from accounts.permissions import role_required
from notifications.models import Notification
from .citations import generate_citations
from .compiler import compile_submission_version
from .forms import AssignReviewerForm, ReviewDecisionForm, SubmissionForm, VersionUploadForm
from .models import AuditLogEntry, Review, Submission, SubmissionAuthor, SubmissionVersion
from .transitions import InvalidTransition, can_transition, transition

User = get_user_model()


def _can_view(submission, user):
    if user.has_role(Role.JOURNAL_MANAGER, Role.ADMINISTRATOR):
        return True
    if submission.is_author(user):
        return True
    return submission.reviews.filter(reviewer=user).exists()


@login_required
def submission_list(request):
    """'My Projects': everything the logged-in user authored or co-authored."""
    submissions = Submission.objects.filter(
        Q(primary_author=request.user) | Q(authors=request.user)
    ).distinct()
    return render(request, 'submissions/submission_list.html', {'submissions': submissions})


@login_required
def submission_create(request):
    if request.method == 'POST':
        form = SubmissionForm(request.POST)
        if form.is_valid():
            submission = form.save(commit=False)
            submission.primary_author = request.user
            submission.save()

            usernames = [
                u.strip() for u in form.cleaned_data['co_authors_usernames'].split(',') if u.strip()
            ]
            unknown = []
            for i, username in enumerate(usernames):
                try:
                    co_author = User.objects.get(username=username)
                    SubmissionAuthor.objects.get_or_create(
                        submission=submission, user=co_author, defaults={'order': i + 1}
                    )
                except User.DoesNotExist:
                    unknown.append(username)

            AuditLogEntry.objects.create(
                submission=submission, user=request.user, action='CREATED',
                to_status=submission.status,
            )

            if unknown:
                messages.warning(
                    request,
                    f"Submission created, but these usernames weren't found and were skipped: {', '.join(unknown)}",
                )
            else:
                messages.success(request, 'Draft submission created. Upload your files to submit it for review.')
            return redirect('submissions:detail', pk=submission.pk)
    else:
        form = SubmissionForm()

    return render(request, 'submissions/submission_form.html', {'form': form})


@login_required
def submission_detail(request, pk):
    submission = get_object_or_404(Submission, pk=pk)
    if not _can_view(submission, request.user):
        raise PermissionDenied('You do not have access to this submission.')

    current_review = submission.current_review()
    latest_version = submission.latest_version()
    compiled_html = submission.get_compiled_html()

    context = {
        'submission': submission,
        'versions': submission.versions.all(),
        'latest_version': latest_version,
        'compiled_html': compiled_html,
        'audit_log': submission.audit_log.all()[:20],
        'reviews': submission.reviews.all(),
        'current_review': current_review,
        'upload_form': VersionUploadForm(),
        'assign_form': AssignReviewerForm(),
        'review_form': ReviewDecisionForm(),
        'is_author': submission.is_author(request.user),
        'can_submit': can_transition(submission, request.user, Submission.SUBMITTED),
        'can_withdraw': can_transition(submission, request.user, Submission.WITHDRAWN),
        'can_screen': can_transition(submission, request.user, Submission.SCREENING),
        'can_upload': submission.is_author(request.user)
        and submission.status in (Submission.DRAFT, Submission.REVISION_REQUIRED),
        'can_assign_reviewer': can_transition(submission, request.user, Submission.ASSIGNED),
        'can_review': submission.status == Submission.UNDER_REVIEW
        and current_review is not None
        and current_review.reviewer_id == request.user.id,
        'can_resubmit': can_transition(submission, request.user, Submission.RESUBMITTED),
        'can_resume_review': can_transition(submission, request.user, Submission.UNDER_REVIEW),
        'can_start_production': can_transition(submission, request.user, Submission.IN_PRODUCTION),
        'can_mark_ready': can_transition(submission, request.user, Submission.READY_TO_PUBLISH),
        'can_publish': can_transition(submission, request.user, Submission.PUBLISHED),
        'can_recompile': (
            submission.is_author(request.user)
            or request.user.has_role(Role.JOURNAL_MANAGER, Role.ADMINISTRATOR)
        ) and latest_version is not None,
    }
    return render(request, 'submissions/submission_detail.html', context)


@login_required
def submission_upload_version(request, pk):
    submission = get_object_or_404(Submission, pk=pk)
    if not submission.is_author(request.user):
        raise PermissionDenied('Only an author of this submission can upload a new version.')
    if submission.status not in (Submission.DRAFT, Submission.REVISION_REQUIRED):
        messages.error(request, 'New files can only be uploaded while a submission is a draft or under revision.')
        return redirect('submissions:detail', pk=pk)

    if request.method == 'POST':
        form = VersionUploadForm(request.POST, request.FILES)
        if form.is_valid():
            next_version = submission.current_version_number + 1
            version = SubmissionVersion.objects.create(
                submission=submission,
                version_number=next_version,
                file=form.cleaned_data['file'],
                notes=form.cleaned_data['notes'],
                uploaded_by=request.user,
            )
            submission.current_version_number = next_version
            submission.save(update_fields=['current_version_number', 'updated_at'])

            AuditLogEntry.objects.create(
                submission=submission, user=request.user, action='VERSION_UPLOADED',
                message=f'Uploaded version {next_version}.',
            )

            # Automatically compile the Technical Design Brief to HTML
            compiled_ok = compile_submission_version(version)
            if compiled_ok:
                messages.success(
                    request,
                    f'Version {next_version} uploaded. Technical Design Brief ({version.brief_filename}) compiled to responsive HTML successfully!'
                )
            elif version.compilation_status == SubmissionVersion.STATUS_NOT_FOUND:
                messages.warning(
                    request,
                    f'Version {next_version} uploaded, but HTML compilation could not find a PDF named "Technical Design Brief" (or "Design Brief"). Please ensure your upload package contains it.'
                )
            else:
                messages.warning(
                    request,
                    f'Version {next_version} uploaded, but HTML compilation failed: {version.compilation_error}'
                )
        else:
            messages.error(request, 'Upload failed: ' + '; '.join(
                f'{f}: {", ".join(e)}' for f, e in form.errors.items()
            ))
    return redirect('submissions:detail', pk=pk)


@login_required
def submission_submit(request, pk):
    submission = get_object_or_404(Submission, pk=pk)
    if request.method != 'POST':
        return redirect('submissions:detail', pk=pk)
    try:
        transition(submission, request.user, Submission.SUBMITTED)
        messages.success(request, 'Submission sent for review.')
    except InvalidTransition as exc:
        messages.error(request, str(exc))
    except PermissionDenied:
        messages.error(request, 'You need at least one uploaded version before you can submit.')
    return redirect('submissions:detail', pk=pk)


@login_required
def submission_withdraw(request, pk):
    submission = get_object_or_404(Submission, pk=pk)
    if request.method != 'POST':
        return redirect('submissions:detail', pk=pk)
    try:
        transition(submission, request.user, Submission.WITHDRAWN)
        messages.info(request, 'Submission withdrawn.')
    except (InvalidTransition, PermissionDenied) as exc:
        messages.error(request, str(exc) or 'You cannot withdraw this submission.')
    return redirect('submissions:detail', pk=pk)


@role_required(Role.JOURNAL_MANAGER, Role.ADMINISTRATOR)
def manager_queue(request):
    """The Journal Manager's incoming-submissions queue."""
    submissions = Submission.objects.exclude(status=Submission.DRAFT)
    return render(request, 'submissions/manager_queue.html', {'submissions': submissions})


@role_required(Role.JOURNAL_MANAGER, Role.ADMINISTRATOR)
def submission_screen(request, pk):
    submission = get_object_or_404(Submission, pk=pk)
    if request.method != 'POST':
        return redirect('submissions:detail', pk=pk)
    try:
        transition(submission, request.user, Submission.SCREENING, message='Moved to screening by manager.')
        messages.success(request, 'Submission moved to Screening.')
    except (InvalidTransition, PermissionDenied) as exc:
        messages.error(request, str(exc))
    return redirect('submissions:detail', pk=pk)


@role_required(Role.JOURNAL_MANAGER, Role.ADMINISTRATOR)
def assign_reviewer(request, pk):
    """
    Manager picks a reviewer. This both creates the Review row (the
    assignment record) and moves the submission SCREENING -> ASSIGNED
    in one step -- the reviewer then explicitly begins the review
    (ASSIGNED -> UNDER_REVIEW), so there's a clear record of when they
    actually picked it up versus when it was merely handed to them.
    """
    submission = get_object_or_404(Submission, pk=pk)
    if request.method != 'POST':
        return redirect('submissions:detail', pk=pk)

    form = AssignReviewerForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Please choose a valid reviewer.')
        return redirect('submissions:detail', pk=pk)

    reviewer = form.cleaned_data['reviewer']
    next_round = submission.reviews.count() + 1

    try:
        transition(
            submission, request.user, Submission.ASSIGNED,
            message=f'Assigned to {reviewer} (round {next_round}).',
        )
    except (InvalidTransition, PermissionDenied) as exc:
        messages.error(request, str(exc))
        return redirect('submissions:detail', pk=pk)

    Review.objects.create(
        submission=submission, reviewer=reviewer, assigned_by=request.user, round=next_round,
    )
    Notification.notify(
        recipient=reviewer,
        actor=request.user,
        verb='assigned you to review',
        target_title=submission.title,
        link=reverse('submissions:detail', kwargs={'pk': submission.pk}),
    )
    messages.success(request, f'{reviewer} has been assigned to review this submission.')
    return redirect('submissions:detail', pk=pk)


@login_required
def begin_review(request, pk):
    """The assigned reviewer moves ASSIGNED/RESUBMITTED -> UNDER_REVIEW."""
    submission = get_object_or_404(Submission, pk=pk)
    if request.method != 'POST':
        return redirect('submissions:detail', pk=pk)
    try:
        transition(submission, request.user, Submission.UNDER_REVIEW)
        messages.success(request, 'Review started.')
    except (InvalidTransition, PermissionDenied) as exc:
        messages.error(request, str(exc) or 'You are not the assigned reviewer for this submission.')
    return redirect('submissions:detail', pk=pk)


@login_required
def submit_review(request, pk):
    """The assigned reviewer records their decision: accept / revise / reject."""
    submission = get_object_or_404(Submission, pk=pk)
    current_review = submission.current_review()

    if current_review is None or current_review.reviewer_id != request.user.id:
        raise PermissionDenied('You are not the assigned reviewer for this submission.')
    if request.method != 'POST':
        return redirect('submissions:detail', pk=pk)

    form = ReviewDecisionForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Please choose a decision and add your comments.')
        return redirect('submissions:detail', pk=pk)

    decision = form.cleaned_data['decision']
    comments = form.cleaned_data['comments']
    to_status = ReviewDecisionForm.DECISION_TO_STATUS[decision]

    try:
        transition(submission, request.user, to_status, message=comments)
    except (InvalidTransition, PermissionDenied) as exc:
        messages.error(request, str(exc))
        return redirect('submissions:detail', pk=pk)

    current_review.decision = decision
    current_review.comments = comments
    current_review.decided_at = timezone.now()
    current_review.save(update_fields=['decision', 'comments', 'decided_at'])

    decision_label = dict(Review.DECISION_CHOICES).get(decision, decision)
    Notification.notify(
        recipient=submission.primary_author,
        actor=request.user,
        verb=f'recorded review decision ({decision_label}) on',
        target_title=submission.title,
        link=reverse('submissions:detail', kwargs={'pk': submission.pk}),
    )

    messages.success(request, 'Your review has been recorded.')
    return redirect('submissions:detail', pk=pk)


@login_required
def submission_resubmit(request, pk):
    """Author resubmits after uploading a revised version."""
    submission = get_object_or_404(Submission, pk=pk)
    if request.method != 'POST':
        return redirect('submissions:detail', pk=pk)
    try:
        transition(submission, request.user, Submission.RESUBMITTED)
        # Notify assigned reviewer if present
        current_rev = submission.current_review() or submission.reviews.order_by('-round').first()
        if current_rev and current_rev.reviewer:
            Notification.notify(
                recipient=current_rev.reviewer,
                actor=request.user,
                verb='resubmitted revised files for',
                target_title=submission.title,
                link=reverse('submissions:detail', kwargs={'pk': submission.pk}),
            )
        messages.success(request, 'Resubmitted. The reviewer has been notified.')
    except InvalidTransition as exc:
        messages.error(request, str(exc))
    except PermissionDenied:
        messages.error(request, 'Upload a revised version before resubmitting.')
    return redirect('submissions:detail', pk=pk)


@role_required(Role.REVIEWER)
def reviewer_queue(request):
    """Everything currently assigned to the logged-in reviewer."""
    reviews = Review.objects.filter(reviewer=request.user).select_related('submission')
    return render(request, 'submissions/reviewer_queue.html', {'reviews': reviews})


def _generate_unique_slug(title):
    base = slugify(title)[:300] or 'project'
    slug = base
    n = 2
    while Submission.objects.filter(slug=slug).exists():
        slug = f'{base}-{n}'
        n += 1
    return slug


def _manager_advance(request, pk, to_status, success_message):
    submission = get_object_or_404(Submission, pk=pk)
    if request.method != 'POST':
        return redirect('submissions:detail', pk=pk)
    try:
        transition(submission, request.user, to_status)
        messages.success(request, success_message)
    except (InvalidTransition, PermissionDenied) as exc:
        messages.error(request, str(exc))
    return redirect('submissions:detail', pk=pk)


@role_required(Role.JOURNAL_MANAGER, Role.ADMINISTRATOR)
def submission_start_production(request, pk):
    return _manager_advance(request, pk, Submission.IN_PRODUCTION, 'Moved to In Production.')


@role_required(Role.JOURNAL_MANAGER, Role.ADMINISTRATOR)
def submission_mark_ready(request, pk):
    return _manager_advance(request, pk, Submission.READY_TO_PUBLISH, 'Marked Ready to Publish.')


@role_required(Role.JOURNAL_MANAGER, Role.ADMINISTRATOR)
def submission_publish(request, pk):
    """
    Publish a submission. This transitions status to PUBLISHED, generates
    the public slug/timestamp, and ensures the Technical Design Brief has been
    compiled into responsive HTML for the public project page.
    """
    submission = get_object_or_404(Submission, pk=pk)
    if request.method != 'POST':
        return redirect('submissions:detail', pk=pk)

    try:
        transition(submission, request.user, Submission.PUBLISHED)
    except (InvalidTransition, PermissionDenied) as exc:
        messages.error(request, str(exc))
        return redirect('submissions:detail', pk=pk)

    if not submission.slug:
        submission.slug = _generate_unique_slug(submission.title)
    submission.published_at = timezone.now()
    submission.save(update_fields=['slug', 'published_at'])

    # Ensure the latest version's Technical Design Brief is compiled to HTML
    latest = submission.latest_version()
    if latest and latest.compilation_status != SubmissionVersion.STATUS_COMPILED:
        compile_submission_version(latest)

    Notification.notify(
        recipient=submission.primary_author,
        actor=request.user,
        verb='published your research project',
        target_title=submission.title,
        link=reverse('projects:detail', kwargs={'slug': submission.slug}),
    )

    messages.success(request, 'Published! It is now live on the public Projects page.')
    return redirect('submissions:detail', pk=pk)


@login_required
def submission_recompile(request, pk):
    """Manually triggers recompilation of the latest version's Technical Design Brief PDF."""
    submission = get_object_or_404(Submission, pk=pk)
    if not (submission.is_author(request.user) or request.user.has_role(Role.JOURNAL_MANAGER, Role.ADMINISTRATOR)):
        raise PermissionDenied('You do not have permission to recompile this submission.')
    if request.method != 'POST':
        return redirect('submissions:detail', pk=pk)

    latest = submission.latest_version()
    if not latest:
        messages.error(request, 'No uploaded version found to compile.')
        return redirect('submissions:detail', pk=pk)

    success = compile_submission_version(latest)
    if success:
        messages.success(
            request,
            f'Technical Design Brief ({latest.brief_filename}) recompiled to responsive HTML successfully!'
        )
    elif latest.compilation_status == SubmissionVersion.STATUS_NOT_FOUND:
        messages.warning(
            request,
            f'Recompilation notice: {latest.compilation_error}'
        )
    else:
        messages.error(request, f'Recompilation failed: {latest.compilation_error}')
    return redirect('submissions:detail', pk=pk)


def project_list(request):
    """Public, no-login-required list of published projects."""
    dept_id = request.GET.get('dept', '').strip()
    submissions = (
        Submission.objects.filter(status=Submission.PUBLISHED)
        .select_related('department', 'primary_author')
        .order_by('-published_at')
    )
    if dept_id:
        submissions = submissions.filter(department_id=dept_id)

    departments = Department.objects.all()
    return render(
        request, 'submissions/project_list.html',
        {
            'submissions': submissions,
            'departments': departments,
            'selected_dept': dept_id,
        },
    )


def project_detail(request, slug):
    """Public, no-login-required project page."""
    submission = get_object_or_404(Submission, slug=slug, status=Submission.PUBLISHED)
    latest_version = submission.latest_version()
    compiled_html = submission.get_compiled_html()

    # Query similar published research articles
    published_qs = (
        Submission.objects.filter(status=Submission.PUBLISHED)
        .exclude(pk=submission.pk)
        .select_related('department', 'primary_author')
    )

    similar_projects = []
    seen_ids = set()

    # 1. Match by department
    if submission.department_id:
        dept_matches = list(published_qs.filter(department_id=submission.department_id).order_by('-published_at')[:4])
        for p in dept_matches:
            if p.pk not in seen_ids:
                similar_projects.append(p)
                seen_ids.add(p.pk)

    # 2. Match by keywords
    keywords = submission.keyword_list()
    if keywords and len(similar_projects) < 4:
        kw_q = Q()
        for kw in keywords[:5]:
            kw_q |= Q(keywords__icontains=kw) | Q(title__icontains=kw)
        kw_matches = list(published_qs.filter(kw_q).exclude(pk__in=seen_ids).order_by('-published_at')[:4])
        for p in kw_matches:
            if p.pk not in seen_ids:
                similar_projects.append(p)
                seen_ids.add(p.pk)

    # 3. Backfill with recently published articles if fewer than 4
    if len(similar_projects) < 4:
        needed = 4 - len(similar_projects)
        recent_matches = list(published_qs.exclude(pk__in=seen_ids).order_by('-published_at')[:needed])
        for p in recent_matches:
            if p.pk not in seen_ids:
                similar_projects.append(p)
                seen_ids.add(p.pk)

    citations = generate_citations(submission, request)

    return render(
        request, 'submissions/project_detail.html',
        {
            'submission': submission,
            'latest_version': latest_version,
            'compiled_html': compiled_html,
            'similar_projects': similar_projects,
            'citations': citations,
        },
    )


def download_bibtex(request, slug):
    """Public endpoint to download academic citation in BibTeX format (.bib)."""
    submission = get_object_or_404(Submission, slug=slug, status=Submission.PUBLISHED)
    citations = generate_citations(submission, request)
    response = HttpResponse(citations['bibtex'], content_type='application/x-bibtex; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{citations["cite_key"]}.bib"'
    return response
