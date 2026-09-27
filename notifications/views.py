from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from .models import Notification


@login_required
def notification_list(request):
    """View all notifications for the logged-in user."""
    notifications = Notification.objects.filter(recipient=request.user)

    filter_type = request.GET.get('filter', '').strip()
    if filter_type == 'unread':
        notifications = notifications.filter(is_read=False)

    return render(
        request, 'notifications/notification_list.html',
        {
            'notifications': notifications,
            'filter_type': filter_type,
            'unread_total': Notification.objects.filter(recipient=request.user, is_read=False).count(),
        }
    )


@login_required
def mark_notification_read(request, pk):
    """Mark a notification as read and redirect to its target link if present."""
    notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
    notification.is_read = True
    notification.save(update_fields=['is_read'])

    if notification.link:
        return redirect(notification.link)
    return redirect('notifications:list')


@login_required
def mark_all_notifications_read(request):
    """Mark all unread notifications as read."""
    if request.method == 'POST':
        Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
        messages.success(request, 'All notifications marked as read.')
    return redirect('notifications:list')
