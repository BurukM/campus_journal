from django.db import migrations

CATEGORIES = [
    ('Campus Research', 'campus-research', 'Breakthroughs, lab discoveries, and peer-reviewed studies across campus.'),
    ('Technology & Innovation', 'technology-innovation', 'Hardware prototypes, robotics, AI tools, and software engineering.'),
    ('Student Spotlights', 'student-spotlights', 'Profiles of student researchers, capstone teams, and competition winners.'),
    ('Engineering & Design', 'engineering-design', 'Design briefs, technical challenges, and prototyping projects.'),
    ('Club Announcement', 'club-announcement', 'Announcements, events, and updates from campus clubs and student organizations.'),
    ('New Project', 'new-project', 'Showcases and launches of new student and faculty engineering projects.'),
    ('General', 'general', 'General campus news, announcements, and university updates.'),
]


def seed_categories(apps, schema_editor):
    NewsCategory = apps.get_model('news', 'NewsCategory')
    for name, slug, description in CATEGORIES:
        NewsCategory.objects.get_or_create(
            slug=slug,
            defaults={'name': name, 'description': description},
        )


def reverse_seed_categories(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('news', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_categories, reverse_code=reverse_seed_categories),
    ]
