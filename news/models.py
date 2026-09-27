import re
from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
import markdown


class NewsCategory(models.Model):
    """Category classification for campus news and tech articles."""

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        verbose_name_plural = 'News categories'
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class NewsArticle(models.Model):
    """
    Campus research news, breakthrough spotlights, and tech articles.
    Controlled by News Editors and Administrators.
    """

    DRAFT = 'DRAFT'
    IN_REVIEW = 'IN_REVIEW'
    PUBLISHED = 'PUBLISHED'
    ARCHIVED = 'ARCHIVED'

    STATUS_CHOICES = [
        (DRAFT, 'Draft'),
        (IN_REVIEW, 'In Editorial Review'),
        (PUBLISHED, 'Published'),
        (ARCHIVED, 'Archived'),
    ]

    title = models.CharField(max_length=300)
    slug = models.SlugField(
        max_length=330, unique=True, blank=True,
        help_text="URL identifier, automatically generated from title if left blank."
    )
    subtitle = models.CharField(
        max_length=350, blank=True,
        help_text="A short summary or lead sentence displayed in previews and under the headline."
    )
    category = models.ForeignKey(
        NewsCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name='articles'
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='news_articles'
    )
    featured_image = models.ImageField(
        upload_to='news/featured/%Y/%m/', blank=True, null=True,
        help_text="Cover photo or hero illustration."
    )
    featured_image_caption = models.CharField(
        max_length=255, blank=True, help_text="Photo credit or caption."
    )
    content = models.TextField(
        help_text="Full article body. Supports standard Markdown & HTML formatting."
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=DRAFT)

    related_submissions = models.ManyToManyField(
        'submissions.Submission',
        blank=True,
        related_name='related_news',
        help_text="Optionally link published campus research papers discussed in this story."
    )

    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-published_at', '-created_at']

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.title)[:300] or 'news'
            slug = base_slug
            n = 2
            while NewsArticle.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f'{base_slug}-{n}'
                n += 1
            self.slug = slug
        if self.status == self.PUBLISHED and not self.published_at:
            self.published_at = timezone.now()
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('news:detail', kwargs={'slug': self.slug})

    def get_content_html(self):
        """Compiles standard Markdown and HTML formatting into clean HTML."""
        return markdown.markdown(
            self.content,
            extensions=['extra', 'nl2br', 'sane_lists']
        )

    def reading_time_minutes(self):
        """Estimates reading time based on 200 words per minute."""
        words = len(re.findall(r'\w+', self.content))
        return max(1, round(words / 200))
