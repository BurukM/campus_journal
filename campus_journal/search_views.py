from django.db.models import Q
from django.shortcuts import render
from accounts.models import Department
from news.models import NewsArticle, NewsCategory
from submissions.models import Submission


def unified_search(request):
    """
    Global search across published research papers and campus news articles.
    Publicly accessible without login.
    """
    query = request.GET.get('q', '').strip()
    result_type = request.GET.get('type', 'all').strip().lower()
    dept_id = request.GET.get('dept', '').strip()
    category_slug = request.GET.get('cat', '').strip()

    projects = []
    news_articles = []

    if query or dept_id or category_slug:
        # Search Research Projects
        if result_type in ('all', 'projects'):
            p_qs = (
                Submission.objects.filter(status=Submission.PUBLISHED)
                .select_related('department', 'primary_author')
                .order_by('-published_at')
            )
            if query:
                p_qs = p_qs.filter(
                    Q(title__icontains=query)
                    | Q(abstract__icontains=query)
                    | Q(keywords__icontains=query)
                    | Q(primary_author__username__icontains=query)
                    | Q(primary_author__first_name__icontains=query)
                    | Q(primary_author__last_name__icontains=query)
                )
            if dept_id:
                p_qs = p_qs.filter(department_id=dept_id)
            projects = list(p_qs)

        # Search News Articles
        if result_type in ('all', 'news'):
            n_qs = (
                NewsArticle.objects.filter(status=NewsArticle.PUBLISHED)
                .select_related('category', 'author')
                .order_by('-published_at')
            )
            if query:
                n_qs = n_qs.filter(
                    Q(title__icontains=query)
                    | Q(subtitle__icontains=query)
                    | Q(content__icontains=query)
                    | Q(author__username__icontains=query)
                )
            if category_slug:
                n_qs = n_qs.filter(category__slug=category_slug)
            news_articles = list(n_qs)

    departments = Department.objects.all()
    categories = NewsCategory.objects.all()
    total_results = len(projects) + len(news_articles)

    return render(
        request, 'search/search_results.html',
        {
            'query': query,
            'result_type': result_type,
            'selected_dept': dept_id,
            'selected_cat': category_slug,
            'projects': projects,
            'news_articles': news_articles,
            'total_results': total_results,
            'departments': departments,
            'categories': categories,
        }
    )
