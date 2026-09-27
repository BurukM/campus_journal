from .models import Notification


def unread_notifications(request):
    """Context processor providing unread notifications count and recent alerts to all templates."""
    if request.user.is_authenticated:
        unread_count = Notification.objects.filter(recipient=request.user, is_read=False).count()
        recent_notifications = Notification.objects.filter(recipient=request.user)[:5]
        return {
            'unread_notifications_count': unread_count,
            'recent_notifications': recent_notifications,
        }
    return {
        'unread_notifications_count': 0,
        'recent_notifications': [],
    }
