from django.urls import path

from . import views

app_name = 'submissions'

urlpatterns = [
    path('', views.submission_list, name='list'),
    path('new/', views.submission_create, name='create'),
    path('queue/', views.manager_queue, name='manager_queue'),
    path('review-queue/', views.reviewer_queue, name='reviewer_queue'),
    path('<int:pk>/', views.submission_detail, name='detail'),
    path('<int:pk>/upload/', views.submission_upload_version, name='upload_version'),
    path('<int:pk>/upload/init/', views.submission_upload_init, name='upload_init'),
    path('<int:pk>/upload/complete/', views.submission_upload_complete, name='upload_complete'),
    path('<int:pk>/versions/<int:version_number>/download/', views.submission_version_download, name='version_download'),
    path('local-upload/', views.local_upload, name='local_upload'),
    path('<int:pk>/submit/', views.submission_submit, name='submit'),
    path('<int:pk>/withdraw/', views.submission_withdraw, name='withdraw'),
    path('<int:pk>/screen/', views.submission_screen, name='screen'),
    path('<int:pk>/assign-reviewer/', views.assign_reviewer, name='assign_reviewer'),
    path('<int:pk>/begin-review/', views.begin_review, name='begin_review'),
    path('<int:pk>/submit-review/', views.submit_review, name='submit_review'),
    path('<int:pk>/resubmit/', views.submission_resubmit, name='resubmit'),
    path('<int:pk>/start-production/', views.submission_start_production, name='start_production'),
    path('<int:pk>/mark-ready/', views.submission_mark_ready, name='mark_ready'),
    path('<int:pk>/publish/', views.submission_publish, name='publish'),
    path('<int:pk>/recompile/', views.submission_recompile, name='recompile'),
]
