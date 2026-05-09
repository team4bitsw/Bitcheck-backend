"""
API Keys URL configuration.

All routes are mounted under /api/keys/ by the root urlconf.
"""

from django.urls import path
from . import views

app_name = 'api_keys'

urlpatterns = [
    path('', views.api_key_list_view, name='api-key-list'),
    path('<uuid:key_id>/revoke/', views.api_key_revoke_view, name='api-key-revoke'),
]
