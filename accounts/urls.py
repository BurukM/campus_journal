from django.urls import path

from . import views

app_name = 'accounts'

urlpatterns = [
    path('signup/', views.signup, name='signup'),
    path('login/', views.AccountLoginView.as_view(), name='login'),
    path('logout/', views.AccountLogoutView.as_view(), name='logout'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('access-requests/', views.access_request_list, name='access_requests'),
    path('access-requests/<int:pk>/approve/', views.approve_access_request, name='approve_access_request'),
    path('access-requests/<int:pk>/reject/', views.reject_access_request, name='reject_access_request'),
    path('profile/edit/', views.profile_edit, name='profile_edit'),
    path('people/<str:username>/', views.profile_detail, name='profile_detail'),
]
