import json
import logging
import os
import uuid
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import (
    FileResponse,
    Http404,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    HttpResponseNotAllowed,
    HttpResponseRedirect,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import get_valid_filename, slugify

from accounts.models import Department, Role
from accounts.permissions import role_required
from notifications.models import Notification
from .citations import generate_citations
from .compiler import compile_submission_version
from .forms import AssignReviewerForm, ReviewDecisionForm, SubmissionForm, VersionUploadForm, get_max_upload_size_mb
from .models import AuditLogEntry, Review, Submission, SubmissionAuthor, SubmissionVersion
from .storage import (
    StorageServiceError,
    create_signed_download_url,
    create_signed_upload_url,
    is_supabase_configured,
    verify_storage_object,
)
from .transitions import InvalidTransition, can_transition, transition

logger = logging.getLogger(__name__)

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
        'max_upload_size_mb': getattr(settings, 'MAX_SUBMISSION_UPLOAD_SIZE_MB', 50),
    }
    return render(request, 'submissions/submission_detail.html', context)


@login_required
def submission_upload_init(request, pk):
    """
    Initializes a direct file upload to Supabase Storage.
    Validates user authorization, file metadata, and generates a unique storage path
    and signed upload URL/token.
    """
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    submission = get_object_or_404(Submission, pk=pk)
    if not submission.is_author(request.user):
        return JsonResponse({'error': 'Only an author of this submission can upload a new version.'}, status=403)
    if submission.status not in (Submission.DRAFT, Submission.REVISION_REQUIRED):
        return JsonResponse(
            {'error': 'New files can only be uploaded while a submission is a draft or under revision.'},
            status=400,
        )

    # Parse request data (JSON or POST)
    filename = ''
    file_size = 0
    content_type = ''
    if request.body:
        try:
            body_data = json.loads(request.body.decode('utf-8'))
            filename = body_data.get('filename', '')
            file_size = body_data.get('file_size', 0)
            content_type = body_data.get('content_type', '')
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass

    if not filename:
        filename = request.POST.get('filename', '')
        file_size = request.POST.get('file_size', 0)
        content_type = request.POST.get('content_type', '')

    filename = os.path.basename(filename.strip())
    if not filename:
        return JsonResponse({'error': 'Filename is required.'}, status=400)

    # Validate file extension
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ('.zip', '.pdf'):
        return JsonResponse({'error': 'Invalid file type. Only .zip and .pdf files are accepted.'}, status=400)

    # Validate file size
    max_mb = getattr(settings, 'MAX_SUBMISSION_UPLOAD_SIZE_MB', 50)
    max_bytes = max_mb * 1024 * 1024
    try:
        file_size = int(file_size)
    except (ValueError, TypeError):
        file_size = 0

    if file_size <= 0:
        return JsonResponse({'error': 'File size must be greater than 0.'}, status=400)
    if file_size > max_bytes:
        return JsonResponse(
            {'error': f'File is too large ({file_size / (1024 * 1024):.1f} MB). Maximum allowed size is {max_mb} MB.'},
            status=400,
        )

    # Generate unique, safe storage object path: submissions/<submission_id>/<unique-id>/<safe-filename>
    safe_filename = get_valid_filename(filename)
    unique_token = uuid.uuid4().hex
    next_version = submission.current_version_number + 1
    storage_path = f"submissions/{submission.id}/v{next_version}/{unique_token}/{safe_filename}"

    try:
        upload_meta = create_signed_upload_url(storage_path, request=request)
    except Exception as exc:
        logger.error(f"Error creating signed upload URL for submission {submission.id}: {exc}")
        return JsonResponse({'error': f"Failed to initialize secure upload: {str(exc)}"}, status=500)

    return JsonResponse({
        'upload_url': upload_meta['upload_url'],
        'token': upload_meta.get('token', ''),
        'storage_path': storage_path,
        'original_filename': safe_filename,
        'next_version': next_version,
        'max_size_bytes': max_bytes,
        'max_size_mb': max_mb,
    })


@login_required
def submission_upload_complete(request, pk):
    """
    Finalizes the upload process after client uploaded file directly to Supabase Storage.
    Verifies that the object exists in Supabase Storage and adheres to size limits
    before recording the SubmissionVersion in the database.
    """
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    submission = get_object_or_404(Submission, pk=pk)
    if not submission.is_author(request.user):
        return JsonResponse({'error': 'Only an author of this submission can upload a new version.'}, status=403)
    if submission.status not in (Submission.DRAFT, Submission.REVISION_REQUIRED):
        return JsonResponse(
            {'error': 'New files can only be uploaded while a submission is a draft or under revision.'},
            status=400,
        )

    # Parse request data
    storage_path = ''
    original_filename = ''
    file_size = 0
    content_type = ''
    notes = ''

    if request.body:
        try:
            body_data = json.loads(request.body.decode('utf-8'))
            storage_path = body_data.get('storage_path', '').strip()
            original_filename = body_data.get('original_filename', '').strip()
            file_size = body_data.get('file_size', 0)
            content_type = body_data.get('content_type', '').strip()
            notes = body_data.get('notes', '').strip()
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass

    if not storage_path:
        storage_path = request.POST.get('storage_path', '').strip()
        original_filename = request.POST.get('original_filename', '').strip()
        file_size = request.POST.get('file_size', 0)
        content_type = request.POST.get('content_type', '').strip()
        notes = request.POST.get('notes', '').strip()

    if not storage_path:
        return JsonResponse({'error': 'storage_path is required.'}, status=400)

    # Security check: storage_path MUST belong to this submission
    expected_prefix = f"submissions/{submission.id}/"
    if not storage_path.startswith(expected_prefix) or '..' in storage_path:
        return JsonResponse({'error': 'Invalid storage path.'}, status=400)

    ext = os.path.splitext(storage_path)[1].lower()
    if ext not in ('.zip', '.pdf'):
        return JsonResponse({'error': 'Invalid file extension in storage path.'}, status=400)

    # Verify object in Supabase / Storage backend
    max_mb = getattr(settings, 'MAX_SUBMISSION_UPLOAD_SIZE_MB', 50)
    max_bytes = max_mb * 1024 * 1024
    is_valid, meta = verify_storage_object(storage_path, max_size_bytes=max_bytes)
    if not is_valid:
        error_msg = meta.get('error', 'Storage verification failed.')
        logger.warning(f"Upload verification failed for submission {submission.id} path {storage_path}: {error_msg}")
        return JsonResponse({'error': error_msg}, status=400)

    # Object is verified in storage! Now record the SubmissionVersion in the database.
    next_version = submission.current_version_number + 1
    actual_size = meta.get('size') or int(file_size or 0)
    actual_content_type = meta.get('content_type') or content_type or ''
    safe_filename = get_valid_filename(os.path.basename(original_filename or storage_path))

    version = SubmissionVersion.objects.create(
        submission=submission,
        version_number=next_version,
        storage_path=storage_path,
        original_filename=safe_filename,
        file_size=actual_size,
        content_type=actual_content_type,
        upload_status=SubmissionVersion.UPLOAD_COMPLETED,
        notes=notes,
        uploaded_by=request.user,
    )

    submission.current_version_number = next_version
    submission.save(update_fields=['current_version_number', 'updated_at'])

    AuditLogEntry.objects.create(
        submission=submission,
        user=request.user,
        action='VERSION_UPLOADED',
        message=f'Uploaded version {next_version} ({safe_filename}).',
    )

    # Automatically compile the Technical Design Brief to HTML in-memory
    try:
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
    except Exception as exc:
        logger.warning(f"Technical Design Brief compilation error: {exc}")
        messages.success(request, f'Version {next_version} uploaded successfully.')

    return JsonResponse({
        'success': True,
        'version_number': next_version,
        'redirect_url': reverse('submissions:detail', kwargs={'pk': submission.pk}),
    })


def submission_version_download(request, pk, version_number):
    """
    Securely serves private submission version files.
    - If submission is PUBLISHED, allows open-access download.
    - Otherwise, requires authentication and authorization (_can_view).
    - If stored in Supabase, redirects to a short-lived signed download URL (60s).
    - If stored locally (legacy or dev), serves file safely.
    """
    submission = get_object_or_404(Submission, pk=pk)
    version = get_object_or_404(SubmissionVersion, submission=submission, version_number=version_number)

    # Access control
    if submission.status != Submission.PUBLISHED:
        if not request.user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login
            return redirect_to_login(request.get_full_path(), reverse(settings.LOGIN_URL))
        if not _can_view(submission, request.user):
            raise PermissionDenied('You do not have permission to download files for this submission.')

    if version.storage_path:
        if is_supabase_configured():
            try:
                signed_url = create_signed_download_url(version.storage_path, expires_in=60)
                return HttpResponseRedirect(signed_url)
            except Exception as exc:
                logger.error(f"Error generating download URL for version {version.pk}: {exc}")
                raise Http404("File could not be retrieved from storage.")
        elif getattr(settings, 'DEBUG', False):
            full_path = Path(settings.MEDIA_ROOT) / version.storage_path
            if full_path.exists():
                return FileResponse(open(full_path, 'rb'), as_attachment=True, filename=version.filename)
            raise Http404("File not found in local storage.")
        else:
            raise Http404("Storage is not configured.")

    if version.file:
        try:
            return HttpResponseRedirect(version.file.url)
        except Exception:
            try:
                return FileResponse(version.file.open('rb'), as_attachment=True, filename=version.filename)
            except Exception:
                raise Http404("Attached file could not be found.")

    raise Http404("No file attached to this version.")


@login_required
def submission_upload_version(request, pk):
    """
    Legacy upload endpoint.
    To prevent Vercel 4.5 MB request limits and read-only filesystem errors,
    direct file upload through browser JavaScript is required.
    """
    submission = get_object_or_404(Submission, pk=pk)
    if not submission.is_author(request.user):
        raise PermissionDenied('Only an author of this submission can upload a new version.')
    if submission.status not in (Submission.DRAFT, Submission.REVISION_REQUIRED):
        messages.error(request, 'New files can only be uploaded while a submission is a draft or under revision.')
        return redirect('submissions:detail', pk=pk)

    if request.method == 'POST':
        messages.error(
            request,
            'Direct file uploads via the browser are required. Please ensure JavaScript is enabled and use the upload form.'
        )
    return redirect('submissions:detail', pk=pk)


def local_upload(request):
    """
    Local development helper to receive direct client PUT uploads when Supabase is not configured.
    Only available in DEBUG mode.
    """
    if not getattr(settings, 'DEBUG', False):
        return HttpResponseForbidden("Local storage upload is only permitted in DEBUG mode.")
    if request.method != 'PUT':
        return HttpResponseNotAllowed(['PUT'])
    path = request.GET.get('path', '').strip()
    if not path or '..' in path or not path.startswith('submissions/'):
        return HttpResponseBadRequest("Invalid storage path.")
    full_path = Path(settings.MEDIA_ROOT) / path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    with open(full_path, 'wb') as f:
        f.write(request.body)
    return HttpResponse(status=200)


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
