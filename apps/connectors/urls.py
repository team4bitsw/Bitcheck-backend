"""Connector API routes — mounted at /api/connectors/."""

from django.urls import path

from . import views

app_name = 'connectors'

urlpatterns = [
    path('webhook/<slug:slug>/', views.ConnectorWebhookView.as_view(), name='webhook'),
    path('types/', views.ConnectorTypeListView.as_view(), name='type-list'),
    path(
        'types/<slug:slug>/interest/',
        views.ConnectorTypeInterestView.as_view(),
        name='type-interest',
    ),
    path('installs/', views.ConnectorInstallListView.as_view(), name='install-list'),
    path(
        'installs/<uuid:install_id>/',
        views.ConnectorInstallDetailView.as_view(),
        name='install-detail',
    ),
    path(
        'installs/<uuid:install_id>/events/',
        views.ConnectorInstallEventsView.as_view(),
        name='install-events',
    ),
    path(
        'install/<slug:slug>/begin/',
        views.ConnectorInstallBeginView.as_view(),
        name='install-begin',
    ),
    path(
        'install/telegram/poll/',
        views.TelegramPollView.as_view(),
        name='telegram-poll',
    ),
    path(
        'installs/<uuid:install_id>/telegram/reconfigure/',
        views.TelegramReconfigureBotView.as_view(),
        name='telegram-reconfigure',
    ),
    path(
        'oauth/<slug:slug>/callback/',
        views.ConnectorOAuthCallbackView.as_view(),
        name='oauth-callback',
    ),
]
