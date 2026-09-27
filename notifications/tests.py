from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Department, Role, UserRole
from submissions.models import Review, Submission
from notifications.models import Notification

User = get_user_model()


class NotificationTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name='Computer Science', short_name='CS')
        self.author = User.objects.create_user(
            username='paper_author', email='author@campus.edu', password='Password123!',
            first_name='Alan', last_name='Turing'
        )
        role_author, _ = Role.objects.get_or_create(slug='author', defaults={'name': 'Author'})
        UserRole.objects.create(user=self.author, role=role_author)

        self.reviewer = User.objects.create_user(
            username='paper_reviewer', email='reviewer@campus.edu', password='Password123!',
            first_name='Grace', last_name='Hopper'
        )
        role_rev, _ = Role.objects.get_or_create(slug=Role.REVIEWER, defaults={'name': 'Reviewer'})
        UserRole.objects.create(user=self.reviewer, role=role_rev)

        self.manager = User.objects.create_user(
            username='chief_editor', email='manager@campus.edu', password='Password123!'
        )
        role_mgr, _ = Role.objects.get_or_create(slug=Role.JOURNAL_MANAGER, defaults={'name': 'Journal Manager'})
        UserRole.objects.create(user=self.manager, role=role_mgr)

        self.submission = Submission.objects.create(
            title='Autonomous Neural Navigation',
            abstract='A novel model for robotic movement.',
            department=self.dept,
            primary_author=self.author,
            status=Submission.SCREENING,
        )

    def test_notify_helper_creates_notification(self):
        notif = Notification.notify(
            recipient=self.author,
            actor=self.manager,
            verb='reviewed',
            target_title=self.submission.title,
            link='/projects/sample/',
        )
        self.assertIsNotNone(notif)
        self.assertEqual(notif.recipient, self.author)
        self.assertEqual(notif.actor, self.manager)
        self.assertFalse(notif.is_read)
        self.assertEqual(str(notif), "chief_editor reviewed 'Autonomous Neural Navigation'")

    def test_notification_list_view_and_filtering(self):
        Notification.objects.create(recipient=self.author, verb='alert 1', target_title='Doc 1', is_read=False)
        Notification.objects.create(recipient=self.author, verb='alert 2', target_title='Doc 2', is_read=True)

        self.client.login(username='paper_author', password='Password123!')
        response = self.client.get(reverse('notifications:list'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['notifications']), 2)
        self.assertEqual(response.context['unread_total'], 1)

        # Filter by unread
        response_unread = self.client.get(reverse('notifications:list') + '?filter=unread')
        self.assertEqual(response_unread.status_code, 200)
        self.assertEqual(len(response_unread.context['notifications']), 1)

    def test_mark_notification_read(self):
        notif = Notification.objects.create(
            recipient=self.author, verb='assigned', target_title='Doc',
            link='/projects/', is_read=False
        )
        self.client.login(username='paper_author', password='Password123!')
        response = self.client.get(reverse('notifications:mark_read', kwargs={'pk': notif.pk}))
        self.assertRedirects(response, '/projects/', fetch_redirect_response=False)
        notif.refresh_from_db()
        self.assertTrue(notif.is_read)

    def test_mark_all_notifications_read(self):
        Notification.objects.create(recipient=self.author, verb='alert 1', target_title='Doc 1', is_read=False)
        Notification.objects.create(recipient=self.author, verb='alert 2', target_title='Doc 2', is_read=False)

        self.client.login(username='paper_author', password='Password123!')
        response = self.client.post(reverse('notifications:mark_all_read'))
        self.assertRedirects(response, reverse('notifications:list'))
        self.assertEqual(Notification.objects.filter(recipient=self.author, is_read=False).count(), 0)

    def test_workflow_generates_notifications(self):
        # 1. Manager assigns reviewer -> reviewer gets notification
        self.client.login(username='chief_editor', password='Password123!')
        assign_url = reverse('submissions:assign_reviewer', kwargs={'pk': self.submission.pk})
        self.client.post(assign_url, {'reviewer': self.reviewer.pk})

        reviewer_notifs = Notification.objects.filter(recipient=self.reviewer)
        self.assertTrue(reviewer_notifs.exists())
        self.assertIn('assigned you to review', reviewer_notifs.first().verb)

        # 2. Reviewer submits review -> author gets notification
        self.client.login(username='paper_reviewer', password='Password123!')
        # move to under review
        self.client.post(reverse('submissions:begin_review', kwargs={'pk': self.submission.pk}))
        review_url = reverse('submissions:submit_review', kwargs={'pk': self.submission.pk})
        self.client.post(review_url, {
            'decision': Review.ACCEPT,
            'comments': 'Outstanding academic rigor. Well done!'
        })

        author_notifs = Notification.objects.filter(recipient=self.author)
        self.assertTrue(author_notifs.exists())
        self.assertIn('recorded review decision', author_notifs.first().verb)
