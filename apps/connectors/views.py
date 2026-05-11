"""HTTP views — inbound webhooks (plain Django) and connector REST API (DRF)."""

from __future__ import annotations

import logging
from typing import Any

from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Organization, User

from .exceptions import ConnectorError, InvalidPayload
from .models import ConnectorEvent, ConnectorInstall, ConnectorType, ConnectorTypeInterest
from .permissions import IsConnectorInstallOwner
from .rate_limit import check_install_limit, check_type_limit
from .registry import get as get_adapter
from .serializers import (
    ConnectorEventSerializer,
    ConnectorInstallBeginResponseSerializer,
    ConnectorInstallSerializer,
    ConnectorInstallWriteSettingsSerializer,
    ConnectorTypeSerializer,
)
from .tasks import process_connector_event

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name='dispatch')
class ConnectorWebhookView(View):
    """POST /api/connectors/webhook/<slug>/."""

    def post(self, request, slug: str, *args, **kwargs):
        try:
            adapter = get_adapter(slug)
        except ConnectorError:
            return JsonResponse({'detail': 'Unknown connector slug.'}, status=404)

        if not check_type_limit(slug):
            return JsonResponse({'detail': 'Rate limit exceeded.'}, status=429)

        if not adapter.verify_webhook(request):
            return JsonResponse({'detail': 'Invalid webhook signature.'}, status=401)

        try:
            ctx, parsed = adapter.parse_event(request)
        except InvalidPayload as e:
            return JsonResponse({'detail': str(e)}, status=400)
        except ConnectorError as e:
            return JsonResponse({'detail': str(e)}, status=400)

        if not check_install_limit(ctx.install_id):
            return JsonResponse({'detail': 'Rate limit exceeded.'}, status=429)

        try:
            install = ConnectorInstall.objects.get(pk=ctx.install_id)
        except ConnectorInstall.DoesNotExist:
            return JsonResponse({'detail': 'Install not found.'}, status=404)

        install.last_event_at = timezone.now()
        install.save(update_fields=['last_event_at', 'updated_at'])

        event, created = ConnectorEvent.objects.get_or_create(
            install=install,
            external_event_id=parsed.external_event_id,
            defaults={
                'event_type': parsed.event_type,
                'raw_payload': parsed.raw_payload,
                'status': ConnectorEvent.Status.RECEIVED,
            },
        )
        if not created:
            return JsonResponse({'status': 'duplicate'}, status=200)

        process_connector_event.delay(str(event.id))
        return JsonResponse({'status': 'queued'}, status=200)


class ConnectorTypeListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: ConnectorTypeSerializer(many=True)})
    def get(self, request):
        qs = ConnectorType.objects.all().order_by('name')
        if request.user.account_type == User.AccountType.BUSINESS:
            qs = qs.filter(supports_b2b=True)
        else:
            qs = qs.filter(supports_b2c=True)
        return Response(ConnectorTypeSerializer(qs, many=True).data)


class ConnectorInstallListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: ConnectorInstallSerializer(many=True)})
    def get(self, request):
        org_ids = Organization.objects.filter(
            memberships__user=request.user,
        ).values_list('id', flat=True)
        qs = ConnectorInstall.objects.filter(
            Q(user=request.user) | Q(organization_id__in=org_ids),
        ).select_related('type').order_by('-created_at')
        return Response(ConnectorInstallSerializer(qs, many=True).data)


class ConnectorInstallBeginView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        responses={200: ConnectorInstallBeginResponseSerializer},
    )
    def post(self, request, slug: str):
        try:
            adapter = get_adapter(slug)
        except ConnectorError:
            return Response(
                {'detail': 'Unknown connector slug.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        payload = adapter.begin_install(request.user, organization=None)
        return Response(payload, status=status.HTTP_200_OK)


class ConnectorInstallCompleteView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request={
            'application/json': {
                'type': 'object',
                'additionalProperties': True,
            },
        },
        responses={200: ConnectorInstallSerializer},
    )
    def post(self, request, slug: str):
        try:
            adapter = get_adapter(slug)
        except ConnectorError:
            return Response(
                {'detail': 'Unknown connector slug.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        body: dict[str, Any] = request.data if isinstance(request.data, dict) else {}
        install = adapter.complete_install(request.user, body, organization=None)
        return Response(
            ConnectorInstallSerializer(install).data,
            status=status.HTTP_200_OK,
        )


class ConnectorOAuthCallbackView(APIView):
    """OAuth return URL placeholder — providers redirect here with ?code=&state=."""

    authentication_classes = []
    permission_classes = []

    def get(self, request, slug: str):
        html = (
            '<!DOCTYPE html><html><body><script>'
            'if(window.opener){window.opener.postMessage('
            '{"source":"bitcheck-connector-install","status":"ok"}, "*");}'
            'window.close();'
            '</script><p>Authorization complete. You can close this window.</p></body></html>'
        )
        return HttpResponse(html, content_type='text/html; charset=utf-8')


class ConnectorInstallDetailView(APIView):
    permission_classes = [IsAuthenticated, IsConnectorInstallOwner]

    @extend_schema(
        request=ConnectorInstallWriteSettingsSerializer,
        responses={200: ConnectorInstallSerializer},
    )
    def patch(self, request, install_id):
        try:
            install = ConnectorInstall.objects.select_related('type').get(pk=install_id)
        except ConnectorInstall.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        self.check_object_permissions(request, install)
        ser = ConnectorInstallWriteSettingsSerializer(
            install,
            data=request.data,
            partial=True,
        )
        ser.is_valid(raise_exception=True)
        ser.save()
        install.refresh_from_db()
        return Response(ConnectorInstallSerializer(install).data)

    def delete(self, request, install_id):
        try:
            install = ConnectorInstall.objects.get(pk=install_id)
        except ConnectorInstall.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        self.check_object_permissions(request, install)
        install.is_active = False
        install.save(update_fields=['is_active', 'updated_at'])
        return Response(status=status.HTTP_204_NO_CONTENT)


class InstallEventsPagination(PageNumberPagination):
    page_size = 25


class ConnectorInstallEventsView(ListAPIView):
    permission_classes = [IsAuthenticated, IsConnectorInstallOwner]
    pagination_class = InstallEventsPagination
    serializer_class = ConnectorEventSerializer

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        from django.shortcuts import get_object_or_404

        self._install = get_object_or_404(
            ConnectorInstall,
            pk=kwargs['install_id'],
        )
        self.check_object_permissions(request, self._install)

    def get_queryset(self):
        return ConnectorEvent.objects.filter(install=self._install).order_by(
            '-created_at',
        )


class ConnectorTypeInterestView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        responses={
            200: OpenApiResponse(description='Interest registered or removed'),
        },
    )
    def post(self, request, slug: str):
        try:
            ct = ConnectorType.objects.get(slug=slug)
        except ConnectorType.DoesNotExist:
            return Response(
                {'detail': 'Unknown connector type.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        interest = ConnectorTypeInterest.objects.filter(
            user=request.user,
            connector_type=ct,
        ).first()
        if interest:
            interest.delete()
            return Response({'registered': False}, status=status.HTTP_200_OK)
        ConnectorTypeInterest.objects.create(user=request.user, connector_type=ct)
        return Response({'registered': True}, status=status.HTTP_201_CREATED)
