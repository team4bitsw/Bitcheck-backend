"""
Webhooks URL configuration.

Mounted under /api/webhooks/ by the root urlconf.
"""

from django.urls import path
from . import views

app_name = 'webhooks'

urlpatterns = [
    path('squad/', views.squad_webhook_view, name='squad-webhook'),
]
