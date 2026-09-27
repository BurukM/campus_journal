from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone
from news.models import NewsArticle, NewsCategory
from submissions.models import Submission

User = get_user_model()

CATEGORIES = [
    ('Campus Research', 'campus-research', 'Breakthroughs, lab discoveries, and peer-reviewed studies across campus.'),
    ('Technology & Innovation', 'technology-innovation', 'Hardware prototypes, robotics, AI tools, and software engineering.'),
    ('Student Spotlights', 'student-spotlights', 'Profiles of student researchers, capstone teams, and competition winners.'),
    ('Engineering & Design', 'engineering-design', 'Design briefs, technical challenges, and prototyping projects.'),
]


class Command(BaseCommand):
    help = 'Seed initial news categories and a sample published news article.'

    def handle(self, *args, **options):
        cats = {}
        for name, slug, desc in CATEGORIES:
            cat, created = NewsCategory.objects.get_or_create(
                slug=slug,
                defaults={'name': name, 'description': desc}
            )
            cats[slug] = cat
            if created:
                self.stdout.write(self.style.SUCCESS(f'Created category: {name}'))
            else:
                self.stdout.write(f'Category exists: {name}')

        # Find or use an editor/admin user
        author = User.objects.filter(is_superuser=True).first() or User.objects.first()
        if not author:
            author = User.objects.create_user(
                username='editor1', email='editor1@campus.edu', password='Password123!'
            )

        # Check if sample article exists
        article_slug = 'biomedical-students-unveil-low-cost-feeding-pump'
        article, created = NewsArticle.objects.get_or_create(
            slug=article_slug,
            defaults={
                'title': 'Biomedical Engineering Students Unveil Low-Cost Syringe Feeding Pump for Neonatal Units',
                'subtitle': 'A multidisciplinary student engineering team designs an open-source, affordable syringe pump with remote telemetry to assist rural neonatal intensive care wards.',
                'category': cats.get('campus-research'),
                'author': author,
                'content': (
                    "In pediatric and neonatal wards across the developing world, accurate micro-infusion "
                    "of nutrients and medication can mean the difference between life and death. Traditional "
                    "commercial syringe pumps often cost thousands of dollars, making widespread adoption "
                    "in underfunded community clinics prohibitively expensive.\n\n"
                    "## The Engineering Challenge\n\n"
                    "Addressing this urgent gap, a team of undergraduate biomedical engineering students "
                    "spent the last nine months prototyping an affordable, high-precision alternative.\n\n"
                    "> \"Our primary design requirement was sub-milliliter dosing precision without relying on "
                    "> expensive proprietary linear actuators,\" explained the lead student engineer. \"By pairing "
                    "> precision stepper motors with 3D-printed lead screw couplings and low-cost microcontrollers, "
                    "> we achieved volumetric flow accuracy within ±2.5%.\"\n\n"
                    "### Key Technical Features\n\n"
                    "- **Continuous Linear Precision**: Calibrated for standard 20ml and 50ml enteral syringes.\n"
                    "- **Remote Status Monitoring**: Integrated ESP32 telemetry transmits flow metrics to nursing stations.\n"
                    "- **Safety Lockouts**: Occlusion sensors and limit switches prevent over-infusion.\n"
                    "- **Battery Backup**: Operates for up to 6 hours during grid power fluctuations.\n\n"
                    "## Published Research & Open Documentation\n\n"
                    "The team has published their full Technical Design Brief, complete with motor schematics, "
                    "tolerance budgets, and testing protocols right here on the Campus Research Journal.\n\n"
                    "The team plans to begin clinical usability evaluations next semester under faculty supervision."
                ),
                'status': NewsArticle.PUBLISHED,
                'published_at': timezone.now(),
            }
        )

        if created:
            # If submission 1 exists, link it!
            first_sub = Submission.objects.filter(status=Submission.PUBLISHED).first()
            if first_sub:
                article.related_submissions.add(first_sub)
            self.stdout.write(self.style.SUCCESS(f'Created sample article: {article.title}'))
        else:
            self.stdout.write(f'Sample article already exists: {article.title}')

        self.stdout.write(self.style.SUCCESS('News seeding complete!'))
