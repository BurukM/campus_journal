from django.contrib import admin
from .models import NewsArticle, NewsCategory


@admin.register(NewsCategory)
class NewsCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name',)


@admin.register(NewsArticle)
class NewsArticleAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'author', 'status', 'published_at', 'created_at')
    list_filter = ('status', 'category', 'published_at')
    search_fields = ('title', 'subtitle', 'content', 'author__username')
    prepopulated_fields = {'slug': ('title',)}
    filter_horizontal = ('related_submissions',)
    date_hierarchy = 'published_at'
