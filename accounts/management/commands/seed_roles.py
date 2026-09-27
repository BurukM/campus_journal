from django.core.management.base import BaseCommand

from accounts.models import Role

ROLES = [
    (Role.STUDENT, 'Student / Author', 'Submits projects, tracks their own submissions, responds to reviewer feedback.'),
    (Role.REVIEWER, 'Staff Reviewer', 'Reviews assigned submissions and recommends accept / revise / reject.'),
    (Role.JOURNAL_MANAGER, 'Journal Manager', 'Screens submissions, assigns reviewers, manages the editorial pipeline, publishes.'),
    (Role.NEWS_EDITOR, 'News Editor', 'Creates and reviews news/technology articles.'),
    (Role.ADMINISTRATOR, 'Administrator', 'Manages users, roles, and site-wide settings.'),
    (Role.CLUB_ADVISOR, 'Club Advisor', 'Faculty oversight of the club and its editorial process.'),
    (Role.SUPER_ADMIN, 'Super Admin', 'Full system access.'),
]


class Command(BaseCommand):
    help = 'Create the standard set of roles (idempotent -- safe to re-run).'

    def handle(self, *args, **options):
        created_count = 0
        for slug, name, description in ROLES:
            role, created = Role.objects.get_or_create(
                slug=slug, defaults={'name': name, 'description': description}
            )
            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f'Created role: {role.name}'))
            else:
                self.stdout.write(f'Already exists: {role.name}')

        self.stdout.write(self.style.SUCCESS(f'\nDone. {created_count} new role(s) created.'))
