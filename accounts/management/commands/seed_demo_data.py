"""
Creates a starter Department and a handful of Reviewer test accounts,
so the "Assign a reviewer" dropdown and the "Department" dropdown on
the New Submission form actually have something in them.

Safe to re-run: uses get_or_create everywhere, so running it twice
won't create duplicates or touch any of your existing data.
"""

from django.core.management.base import BaseCommand

from accounts.models import Department, Role, User, UserRole

DEPARTMENTS = [
    ('Biomedical Engineering', 'BME'),
]

REVIEWERS = [
    ('dr_sara', 'Sara', 'Bekele', 'sara.bekele@example.com'),
    ('dr_samuel', 'Samuel', 'Girma', 'samuel.girma@example.com'),
    ('dr_hana', 'Hana', 'Tesfaye', 'hana.tesfaye@example.com'),
]

DEMO_PASSWORD = 'Reviewer123!'


class Command(BaseCommand):
    help = 'Seed a demo Department and 3 Reviewer test accounts (idempotent -- safe to re-run).'

    def handle(self, *args, **options):
        for name, short_name in DEPARTMENTS:
            dept, created = Department.objects.get_or_create(
                name=name, defaults={'short_name': short_name}
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f'Created department: {dept.name}'))
            else:
                self.stdout.write(f'Already exists: {dept.name}')

        reviewer_role, _ = Role.objects.get_or_create(
            slug=Role.REVIEWER, defaults={'name': 'Staff Reviewer'}
        )

        self.stdout.write('')
        for username, first, last, email in REVIEWERS:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={'first_name': first, 'last_name': last, 'email': email},
            )
            if created:
                user.set_password(DEMO_PASSWORD)
                user.save()
                self.stdout.write(self.style.SUCCESS(f'Created reviewer: {username} / {DEMO_PASSWORD}'))
            else:
                self.stdout.write(f'Already exists: {username}')

            UserRole.objects.get_or_create(user=user, role=reviewer_role)

        self.stdout.write(self.style.SUCCESS('\nDone. All three accounts can log in with the password shown above.'))