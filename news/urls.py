from django.urls import path
from . import views

app_name = 'news'

urlpatterns = [
    path('', views.article_list, name='list'),
    path('desk/', views.editorial_desk, name='desk'),
    path('new/', views.article_create, name='create'),
    path('<slug:slug>/', views.article_detail, name='detail'),
    path('<slug:slug>/edit/', views.article_edit, name='edit'),
    path('<slug:slug>/toggle-publish/', views.article_toggle_publish, name='toggle_publish'),
]
