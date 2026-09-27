from django.shortcuts import render
from news.models import NewsArticle
from submissions.models import Submission


def home(request):
    """
    Public homepage showcasing the latest news articles and
    recently published campus research projects without requiring authentication.
    """
    latest_news = (
        NewsArticle.objects.filter(status=NewsArticle.PUBLISHED)
        .select_related('category', 'author')
        .order_by('-published_at')[:4]
    )
    published_projects = (
        Submission.objects.filter(status=Submission.PUBLISHED)
        .select_related('department', 'primary_author')
        .order_by('-published_at')[:4]
    )

    return render(
        request, 'home.html',
        {
            'latest_news': latest_news,
            'published_projects': published_projects,
        }
    )
