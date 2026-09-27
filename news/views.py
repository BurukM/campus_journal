from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.models import Role
from accounts.permissions import role_required
from .forms import NewsArticleForm
from .models import NewsArticle, NewsCategory


def article_list(request):
    """Public, no-login-required catalog of published news and tech articles."""
    articles_qs = (
        NewsArticle.objects.filter(status=NewsArticle.PUBLISHED)
        .select_related('category', 'author')
        .order_by('-published_at')
    )

    selected_category_slug = request.GET.get('category', '').strip()
    selected_category = None
    if selected_category_slug:
        selected_category = get_object_or_404(NewsCategory, slug=selected_category_slug)
        articles_qs = articles_qs.filter(category=selected_category)

    search_query = request.GET.get('q', '').strip()
    if search_query:
        articles_qs = articles_qs.filter(
            Q(title__icontains=search_query)
            | Q(subtitle__icontains=search_query)
            | Q(content__icontains=search_query)
        )

    articles = list(articles_qs)
    featured_article = articles[0] if (articles and not search_query and not selected_category) else None
    remaining_articles = articles[1:] if featured_article else articles

    categories = NewsCategory.objects.annotate(
        article_count=Count('articles', filter=Q(articles__status=NewsArticle.PUBLISHED))
    )

    return render(
        request, 'news/article_list.html',
        {
            'featured_article': featured_article,
            'articles': remaining_articles,
            'categories': categories,
            'selected_category': selected_category,
            'search_query': search_query,
            'is_news_editor': (
                request.user.is_authenticated
                and request.user.has_role(Role.NEWS_EDITOR, Role.ADMINISTRATOR)
            ),
        }
    )


def article_detail(request, slug):
    """Public, no-login-required view for a single published news article."""
    article = get_object_or_404(NewsArticle, slug=slug)

    # If article is not published, only News Editors or Administrators may preview it
    if article.status != NewsArticle.PUBLISHED:
        if not (request.user.is_authenticated and request.user.has_role(Role.NEWS_EDITOR, Role.ADMINISTRATOR)):
            raise PermissionDenied("This article has not been published yet.")

    related_stories = (
        NewsArticle.objects.filter(status=NewsArticle.PUBLISHED)
        .exclude(pk=article.pk)
        .order_by('-published_at')
    )
    if article.category:
        related_stories = related_stories.filter(category=article.category)[:3]
    else:
        related_stories = related_stories[:3]

    related_submissions = article.related_submissions.filter(status='PUBLISHED')

    return render(
        request, 'news/article_detail.html',
        {
            'article': article,
            'content_html': article.get_content_html(),
            'related_stories': related_stories,
            'related_submissions': related_submissions,
            'is_news_editor': (
                request.user.is_authenticated
                and request.user.has_role(Role.NEWS_EDITOR, Role.ADMINISTRATOR)
            ),
        }
    )


@role_required(Role.NEWS_EDITOR, Role.ADMINISTRATOR)
def editorial_desk(request):
    """Staff-only editorial workspace for managing all campus news articles."""
    articles = NewsArticle.objects.all().select_related('category', 'author').order_by('-updated_at')

    drafts = articles.filter(status=NewsArticle.DRAFT)
    in_review = articles.filter(status=NewsArticle.IN_REVIEW)
    published = articles.filter(status=NewsArticle.PUBLISHED)
    archived = articles.filter(status=NewsArticle.ARCHIVED)

    return render(
        request, 'news/editorial_desk.html',
        {
            'drafts': drafts,
            'in_review': in_review,
            'published': published,
            'archived': archived,
            'total_count': articles.count(),
        }
    )


@role_required(Role.NEWS_EDITOR, Role.ADMINISTRATOR)
def article_create(request):
    """Staff-only creation of a new campus news article."""
    if request.method == 'POST':
        form = NewsArticleForm(request.POST, request.FILES)
        if form.is_valid():
            article = form.save(commit=False)
            article.author = request.user
            if article.status == NewsArticle.PUBLISHED and not article.published_at:
                article.published_at = timezone.now()
            article.save()
            form.save_m2m()
            messages.success(request, f'Article "{article.title}" saved successfully.')
            return redirect('news:detail', slug=article.slug)
    else:
        form = NewsArticleForm(initial={'status': NewsArticle.DRAFT})

    return render(request, 'news/article_form.html', {'form': form, 'is_create': True})


@role_required(Role.NEWS_EDITOR, Role.ADMINISTRATOR)
def article_edit(request, slug):
    """Staff-only editing of an existing news article."""
    article = get_object_or_404(NewsArticle, slug=slug)

    if request.method == 'POST':
        form = NewsArticleForm(request.POST, request.FILES, instance=article)
        if form.is_valid():
            article = form.save(commit=False)
            if article.status == NewsArticle.PUBLISHED and not article.published_at:
                article.published_at = timezone.now()
            article.save()
            form.save_m2m()
            messages.success(request, f'Article "{article.title}" updated.')
            return redirect('news:detail', slug=article.slug)
    else:
        form = NewsArticleForm(instance=article)

    return render(
        request, 'news/article_form.html',
        {'form': form, 'article': article, 'is_create': False}
    )


@role_required(Role.NEWS_EDITOR, Role.ADMINISTRATOR)
def article_toggle_publish(request, slug):
    """Quickly publish or unpublish an article from the desk."""
    if request.method != 'POST':
        return redirect('news:desk')

    article = get_object_or_404(NewsArticle, slug=slug)
    if article.status == NewsArticle.PUBLISHED:
        article.status = NewsArticle.ARCHIVED
        messages.info(request, f'Article "{article.title}" archived.')
    else:
        article.status = NewsArticle.PUBLISHED
        if not article.published_at:
            article.published_at = timezone.now()
        messages.success(request, f'Article "{article.title}" is now published live.')

    article.save(update_fields=['status', 'published_at', 'updated_at'])
    return redirect('news:desk')
