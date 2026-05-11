"""HTTP views — inbound webhooks (plain Django) and connector REST API (DRF)."""

from __future__ import annotations

import json
import logging
from typing import Any

from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Membership, Organization, User

from apps.connectors.adapters.telegram.link import poll_link_status

from .exceptions import CommandHandled, ConnectorError, InvalidPayload
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


def _resolve_connector_install_organization(request) -> Organization | None:
    """B2B installs attach to the user's organization (first membership)."""
    user = request.user
    if getattr(user, 'account_type', None) != User.AccountType.BUSINESS:
        return None
    m = Membership.objects.select_related('organization').filter(user=user).first()
    if m:
        return m.organization
    return None


def _oauth_popup_response(status: str, detail: str = '') -> HttpResponse:
    msg: dict[str, Any] = {'source': 'bitcheck-connector-install', 'status': status}
    if detail:
        msg['detail'] = detail
    payload = json.dumps(msg, separators=(',', ':'))
    html = (
        '<!DOCTYPE html><html><body><script>'
        f'if(window.opener){{window.opener.postMessage({payload},"*");}}'
        'window.close();'
        '</script><p>Authorization complete. You can close this window.</p></body></html>'
    )
    return HttpResponse(html, content_type='text/html; charset=utf-8')


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
        except CommandHandled:
            return JsonResponse({'status': 'handled'}, status=200)
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
        org = _resolve_connector_install_organization(request)
        opts: dict[str, Any] = {}
        if isinstance(request.data, dict):
            opts = request.data
        payload = adapter.begin_install(request.user, organization=org, options=opts)
        return Response(payload, status=status.HTTP_200_OK)


class TelegramPollView(APIView):
    """GET /api/connectors/install/telegram/poll/?code= — shared-bot link status for UI polling."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter(name='code', type=str, location=OpenApiParameter.QUERY, required=True),
        ],
        responses={200: OpenApiResponse(description='linked, detail, install_id')},
    )
    def get(self, request):
        code = (request.query_params.get('code') or '').strip()
        if not code:
            return Response(
                {'detail': 'code is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(poll_link_status(request.user, code), status=status.HTTP_200_OK)


class TelegramReconfigureBotView(APIView):
    """POST — re-apply BotFather commands/description via Telegram Bot API (own-bot installs)."""

    permission_classes = [IsAuthenticated, IsConnectorInstallOwner]

    @extend_schema(request=None, responses={200: OpenApiResponse()})
    def post(self, request, install_id):
        try:
            install = ConnectorInstall.objects.select_related('type').get(pk=install_id)
        except ConnectorInstall.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        self.check_object_permissions(request, install)
        if install.type.slug != 'telegram':
            return Response(
                {'detail': 'Not a Telegram connection.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        adapter = get_adapter('telegram')
        try:
            adapter.reconfigure_bot(install)
        except InvalidPayload as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except RuntimeError as e:
            logger.warning('telegram reconfigure failed install=%s err=%s', install_id, e)
            return Response({'detail': str(e)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response({'status': 'ok'}, status=status.HTTP_200_OK)


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
        org = _resolve_connector_install_organization(request)
        install = adapter.complete_install(request.user, body, organization=org)
        return Response(
            ConnectorInstallSerializer(install).data,
            status=status.HTTP_200_OK,
        )


class ConnectorOAuthCallbackView(APIView):
    """OAuth return URL — Google redirects here with ?code=&state=."""

    authentication_classes = []
    permission_classes = []

    def get(self, request, slug: str):
        oauth_error = request.GET.get('error')
        if oauth_error:
            desc = request.GET.get('error_description') or oauth_error
            return _oauth_popup_response('error', desc)
        code = request.GET.get('code')
        state = request.GET.get('state')
        if not code or not state:
            return _oauth_popup_response('error', 'Missing authorization code or state.')

        try:
            adapter = get_adapter(slug)
        except ConnectorError:
            return _oauth_popup_response('error', 'Unknown connector.')

        from apps.connectors.adapters.gmail.oauth import parse_oauth_state

        try:
            claims = parse_oauth_state(str(state))
        except InvalidPayload as e:
            return _oauth_popup_response('error', str(e))

        if claims.get('slug') != slug:
            return _oauth_popup_response('error', 'OAuth state does not match connector.')

        try:
            user = User.objects.get(pk=claims['user_id'])
        except User.DoesNotExist:
            return _oauth_popup_response('error', 'User not found for this OAuth session.')

        org = None
        oid = claims.get('org_id')
        if oid:
            try:
                org = Organization.objects.get(pk=oid)
            except Organization.DoesNotExist:
                return _oauth_popup_response('error', 'Organization not found for this OAuth session.')

        try:
            adapter.complete_install(
                user,
                {'code': str(code), 'state': str(state)},
                organization=org,
            )
        except InvalidPayload as e:
            return _oauth_popup_response('error', str(e))
        except Exception:
            logger.exception('OAuth callback failed slug=%s', slug)
            return _oauth_popup_response('error', 'Could not complete connector installation.')

        return _oauth_popup_response('ok')


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
