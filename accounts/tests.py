from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import AccessRequest, Department, Role, UserRole
from notifications.models import Notification

User = get_user_model()


class RoleAccessApprovalWorkflowTests(TestCase):
    def setUp(self):
        # Create departments
        self.dept = Department.objects.create(name='Biomedical Engineering', short_name='BME')

        # Seed roles
        self.role_student, _ = Role.objects.get_or_create(slug=Role.STUDENT, defaults={'name': 'Student / Author'})
        self.role_reviewer, _ = Role.objects.get_or_create(slug=Role.REVIEWER, defaults={'name': 'Staff Reviewer'})
        self.role_manager, _ = Role.objects.get_or_create(slug=Role.JOURNAL_MANAGER, defaults={'name': 'Journal Manager'})
        self.role_admin, _ = Role.objects.get_or_create(slug=Role.ADMINISTRATOR, defaults={'name': 'Administrator'})

        # Create an existing active administrator
        self.admin_user = User.objects.create_user(
            username='admin_boss',
            email='boss@campus.edu',
            password='Password123!',
            first_name='Head',
            last_name='Editor',
        )
        UserRole.objects.create(user=self.admin_user, role=self.role_admin)

    def test_student_signup_is_immediately_active(self):
        client = Client()
        signup_data = {
            'first_name': 'Alice',
            'last_name': 'Student',
            'username': 'alicestudent',
            'email': 'alice@campus.edu',
            'role': Role.STUDENT,
            'department': self.dept.pk,
            'affiliation_note': '',
            'password1': 'Pass123!Secure',
            'password2': 'Pass123!Secure',
        }
        resp = client.post(reverse('accounts:signup'), signup_data)
        self.assertRedirects(resp, reverse('accounts:dashboard'))

        # Verify user state in DB
        user = User.objects.get(username='alicestudent')
        self.assertTrue(user.is_active)
        self.assertTrue(user.has_role(Role.STUDENT))
        self.assertFalse(hasattr(user, 'access_request'))

    def test_reviewer_signup_creates_inactive_account_and_access_request(self):
        client = Client()
        signup_data = {
            'first_name': 'Dr. Robert',
            'last_name': 'Reviewer',
            'username': 'robertrev',
            'email': 'robert@campus.edu',
            'role': Role.REVIEWER,
            'department': self.dept.pk,
            'affiliation_note': 'Associate Professor in Biomedical Systems Lab',
            'password1': 'Pass123!Secure',
            'password2': 'Pass123!Secure',
        }
        resp = client.post(reverse('accounts:signup'), signup_data)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Pending Administrator Approval')
        self.assertContains(resp, 'Staff Reviewer')

        # Verify user is inactive
        user = User.objects.get(username='robertrev')
        self.assertFalse(user.is_active)
        self.assertFalse(user.has_role(Role.STUDENT))
        self.assertFalse(user.has_role(Role.REVIEWER))

        # Verify AccessRequest record
        req = AccessRequest.objects.get(user=user)
        self.assertEqual(req.status, AccessRequest.STATUS_PENDING)
        self.assertEqual(req.requested_role, self.role_reviewer)
        self.assertEqual(req.department, self.dept)
        self.assertIn('Associate Professor', req.affiliation_note)

        # Verify in-app notification sent to the admin
        admin_notifs = Notification.objects.filter(recipient=self.admin_user)
        self.assertTrue(admin_notifs.exists())
        self.assertIn('requested Staff Reviewer access', admin_notifs.first().verb)

    def test_pending_user_login_attempt_shows_helpful_approval_message(self):
        # Register reviewer
        client = Client()
        signup_data = {
            'first_name': 'Dr. Robert',
            'last_name': 'Reviewer',
            'username': 'robertrev',
            'email': 'robert@campus.edu',
            'role': Role.REVIEWER,
            'department': self.dept.pk,
            'affiliation_note': 'Lab Director',
            'password1': 'Pass123!Secure',
            'password2': 'Pass123!Secure',
        }
        client.post(reverse('accounts:signup'), signup_data)

        # Attempt to login while pending
        login_resp = client.post(reverse('accounts:login'), {
            'username': 'robertrev',
            'password': 'Pass123!Secure',
        })
        self.assertEqual(login_resp.status_code, 200)
        self.assertContains(login_resp, 'pending administrator review')

    def test_admin_approving_access_request_enables_login_and_grants_role(self):
        # Register reviewer
        reviewer_user = User.objects.create_user(
            username='reviewer_pending',
            email='pending_rev@campus.edu',
            password='Pass123!Secure',
            first_name='Clara',
            last_name='Barton',
            is_active=False,
        )
        req = AccessRequest.objects.create(
            user=reviewer_user,
            requested_role=self.role_reviewer,
            department=self.dept,
            affiliation_note='Lead Researcher',
        )

        # Admin logs in and visits Access Requests queue
        admin_client = Client()
        admin_client.login(username='admin_boss', password='Password123!')

        list_resp = admin_client.get(reverse('accounts:access_requests'))
        self.assertEqual(list_resp.status_code, 200)
        self.assertContains(list_resp, 'Clara Barton')
        self.assertContains(list_resp, 'Staff Reviewer')

        # Admin clicks Approve
        approve_url = reverse('accounts:approve_access_request', kwargs={'pk': req.pk})
        post_resp = admin_client.post(approve_url)
        self.assertRedirects(post_resp, reverse('accounts:access_requests'))

        # Verify DB state
        req.refresh_from_db()
        reviewer_user.refresh_from_db()
        self.assertEqual(req.status, AccessRequest.STATUS_APPROVED)
        self.assertEqual(req.reviewed_by, self.admin_user)
        self.assertTrue(reviewer_user.is_active)
        self.assertTrue(reviewer_user.has_role(Role.REVIEWER))

        # Now the approved reviewer can successfully log in
        reviewer_client = Client()
        login_resp = reviewer_client.post(reverse('accounts:login'), {
            'username': 'reviewer_pending',
            'password': 'Pass123!Secure',
        })
        self.assertRedirects(login_resp, reverse('accounts:dashboard'))

    def test_admin_declining_access_request_leaves_user_inactive(self):
        unauthorized_user = User.objects.create_user(
            username='random_person',
            email='random@campus.edu',
            password='Pass123!Secure',
            is_active=False,
        )
        req = AccessRequest.objects.create(
            user=unauthorized_user,
            requested_role=self.role_admin,
            affiliation_note='No credentials',
        )

        admin_client = Client()
        admin_client.login(username='admin_boss', password='Password123!')

        reject_url = reverse('accounts:reject_access_request', kwargs={'pk': req.pk})
        post_resp = admin_client.post(reject_url)
        self.assertRedirects(post_resp, reverse('accounts:access_requests'))

        req.refresh_from_db()
        unauthorized_user.refresh_from_db()
        self.assertEqual(req.status, AccessRequest.STATUS_REJECTED)
        self.assertFalse(unauthorized_user.is_active)
        self.assertFalse(unauthorized_user.has_role(Role.ADMINISTRATOR))

        # Attempt to login shows declined notice
        anon_client = Client()
        login_resp = anon_client.post(reverse('accounts:login'), {
            'username': 'random_person',
            'password': 'Pass123!Secure',
        })
        self.assertEqual(login_resp.status_code, 200)
        self.assertContains(login_resp, 'declined')
