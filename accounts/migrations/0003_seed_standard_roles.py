from django.db import migrations

ROLES = [
    ('student', 'Student / Author', 'Submits projects, tracks their own submissions, responds to reviewer feedback.'),
    ('reviewer', 'Staff Reviewer', 'Reviews assigned submissions and recommends accept / revise / reject.'),
    ('journal_manager', 'Journal Manager', 'Screens submissions, assigns reviewers, manages the editorial pipeline, publishes.'),
    ('news_editor', 'News Editor', 'Creates and reviews news/technology articles.'),
    ('administrator', 'Administrator', 'Manages users, roles, and site-wide settings.'),
    ('club_advisor', 'Club Advisor', 'Faculty oversight of the club and its editorial process.'),
    ('super_admin', 'Super Admin', 'Full system access.'),
]


def seed_standard_roles(apps, schema_editor):
    Role = apps.get_model('accounts', 'Role')
    for slug, name, description in ROLES:
        Role.objects.get_or_create(
            slug=slug,
            defaults={'name': name, 'description': description},
        )


def reverse_seed_standard_roles(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0002_accessrequest'),
    ]

    operations = [
        migrations.RunPython(seed_standard_roles, reverse_code=reverse_seed_standard_roles),
    ]
