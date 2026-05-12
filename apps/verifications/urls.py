"""
Verifications URL configuration.

All routes are mounted under /api/verifications/ by the root urlconf.
"""

from django.urls import path
from . import views

app_name = 'verifications'

urlpatterns = [
    path('costs/', views.verification_costs_view, name='costs'),
    path('verify/image/', views.verify_image_view, name='verify-image'),
    path('', views.verification_list_view, name='list'),
    path('<uuid:verification_id>/', views.verification_detail_view, name='detail'),
]
