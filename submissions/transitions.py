"""
The submission state machine.

Each entry in TRANSITIONS maps (from_status, to_status) -> a check
function that decides whether the given user is allowed to make that
move. This is deliberately centralized in one place, per the plan's
"give every submission a state" guidance -- so the rules are never
duplicated or drift between views.

Phase 2 wires up:
    DRAFT      -> SUBMITTED   (author, requires at least one version)
    DRAFT      -> WITHDRAWN   (author)
    SUBMITTED  -> WITHDRAWN   (author)
    SUBMITTED  -> SCREENING   (journal manager / administrator)

Phase 3 adds the reviewer-assignment and decision transitions:
    SCREENING          -> ASSIGNED          (manager assigns a reviewer)
    ASSIGNED           -> UNDER_REVIEW      (that reviewer begins review)
    UNDER_REVIEW       -> ACCEPTED          (reviewer decision)
    UNDER_REVIEW       -> REVISION_REQUIRED (reviewer decision)
    UNDER_REVIEW       -> REJECTED          (reviewer decision)
    REVISION_REQUIRED  -> RESUBMITTED       (author, requires a new version
                                              uploaded after the decision)
    RESUBMITTED        -> UNDER_REVIEW      (the same reviewer resumes)

By design, WITHDRAWN stays reachable only from DRAFT and SUBMITTED --
once a submission reaches Screening or later, the author can no
longer unilaterally withdraw it.

Phase 4 adds the publishing pipeline (manager-only for now; the actual
LaTeX/PDF conversion is a separate, later effort):
    ACCEPTED           -> IN_PRODUCTION     (manager starts production)
    IN_PRODUCTION       -> READY_TO_PUBLISH  (manager finishes prep)
    READY_TO_PUBLISH    -> PUBLISHED         (manager publishes; the view
                                              that calls this also sets
                                              the submission's public slug)
"""

from django.core.exceptions import PermissionDenied

from accounts.models import Role
from .models import AuditLogEntry, Submission


def _is_author(submission, user):
    return submission.is_author(user)


def _is_manager(submission, user):
    return user.has_role(Role.JOURNAL_MANAGER, Role.ADMINISTRATOR)


def _is_current_reviewer(submission, user):
    review = submission.current_review()
    return review is not None and review.reviewer_id == user.id


def _draft_to_submitted_guard(submission, user):
    if not _is_author(submission, user):
        return False
    return submission.versions.exists()


def _resubmit_guard(submission, user):
    """
    Author may resubmit only after a reviewer has actually asked for a
    revision *and* a new file has been uploaded since that decision --
    otherwise "Resubmit" would just re-send the same files.
    """
    if not _is_author(submission, user):
        return False
    review = submission.current_review()
    if review is None or review.decided_at is None:
        return False
    latest = submission.latest_version()
    return latest is not None and latest.uploaded_at > review.decided_at


TRANSITIONS = {
    (Submission.DRAFT, Submission.SUBMITTED): _draft_to_submitted_guard,
    (Submission.DRAFT, Submission.WITHDRAWN): _is_author,
    (Submission.SUBMITTED, Submission.WITHDRAWN): _is_author,
    (Submission.SUBMITTED, Submission.SCREENING): _is_manager,
    (Submission.SCREENING, Submission.ASSIGNED): _is_manager,
    (Submission.ASSIGNED, Submission.UNDER_REVIEW): _is_current_reviewer,
    (Submission.UNDER_REVIEW, Submission.ACCEPTED): _is_current_reviewer,
    (Submission.UNDER_REVIEW, Submission.REVISION_REQUIRED): _is_current_reviewer,
    (Submission.UNDER_REVIEW, Submission.REJECTED): _is_current_reviewer,
    (Submission.REVISION_REQUIRED, Submission.RESUBMITTED): _resubmit_guard,
    (Submission.RESUBMITTED, Submission.UNDER_REVIEW): _is_current_reviewer,
    (Submission.ACCEPTED, Submission.IN_PRODUCTION): _is_manager,
    (Submission.IN_PRODUCTION, Submission.READY_TO_PUBLISH): _is_manager,
    (Submission.READY_TO_PUBLISH, Submission.PUBLISHED): _is_manager,
}


class InvalidTransition(Exception):
    pass


def can_transition(submission, user, to_status):
    guard = TRANSITIONS.get((submission.status, to_status))
    if guard is None:
        return False
    return guard(submission, user)


def transition(submission, user, to_status, message=''):
    """
    Attempt to move `submission` to `to_status` on behalf of `user`.
    Raises InvalidTransition (not allowed by the state machine) or
    PermissionDenied (allowed in principle, but not by this user) --
    callers can catch InvalidTransition to show a friendly error, or
    let PermissionDenied bubble up to Django's 403 page.
    """
    guard = TRANSITIONS.get((submission.status, to_status))
    if guard is None:
        raise InvalidTransition(
            f'Cannot move a submission from {submission.status} to {to_status}.'
        )
    if not guard(submission, user):
        raise PermissionDenied('You are not allowed to make this change.')

    from_status = submission.status
    submission.status = to_status
    submission.save(update_fields=['status', 'updated_at'])

    AuditLogEntry.objects.create(
        submission=submission,
        user=user,
        action='STATUS_CHANGE',
        from_status=from_status,
        to_status=to_status,
        message=message,
    )
    return submission
