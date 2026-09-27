"""
Lightweight role-based access control.

This is intentionally simple for Phase 1: a user either holds one of the
allowed role slugs or they don't. Later phases (submission workflow,
news workflow) will layer Django's object-level permission checks and
the state-machine transition rules on top of this -- e.g. "only the
Journal Manager assigned to *this* submission may move it to
ASSIGNED" -- but the role check below is the first line of defense for
whole views/dashboards.
"""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied


def role_required(*slugs):
    """
    View decorator: require the logged-in user to hold at least one of
    the given role slugs (superusers always pass).

        @role_required(Role.JOURNAL_MANAGER, Role.ADMINISTRATOR)
        def manager_dashboard(request): ...
    """

    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def _wrapped(request, *args, **kwargs):
            if not request.user.has_role(*slugs):
                raise PermissionDenied(
                    'You do not have the role required to view this page.'
                )
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator


class RoleRequiredMixin(LoginRequiredMixin):
    """Class-based view equivalent of @role_required."""

    allowed_roles = ()

    def handle_no_permission(self):
        # LoginRequiredMixin handles the "not logged in" case; role
        # failures raise PermissionDenied (-> Django's 403 page).
        if self.request.user.is_authenticated:
            raise PermissionDenied(
                'You do not have the role required to view this page.'
            )
        return super().handle_no_permission()

    def test_role(self):
        return self.request.user.is_authenticated and self.request.user.has_role(
            *self.allowed_roles
        )

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if self.allowed_roles and not self.test_role():
            return self.handle_no_permission()
        return super(LoginRequiredMixin, self).dispatch(request, *args, **kwargs)
