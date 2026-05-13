"""Typed payloads and the connector adapter contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Iterable

if TYPE_CHECKING:
    from django.http import HttpRequest

    from apps.verifications.models import Verification

    from .models import ConnectorInstall


@dataclass
class VerifiableContent:
    """One item to run through the verification pipeline."""

    kind: str  # text | image | document | audio | video
    payload: str | bytes
    filename: str | None = None
    mime_type: str | None = None
    source_locator: dict[str, Any] | None = None


@dataclass
class InstallContext:
    """Resolved install + decrypted credentials for one webhook."""

    install_id: str
    credentials: dict[str, Any]
    settings: dict[str, Any]
    org_id: str | None
    user_id: str | None


@dataclass
class ParsedEvent:
    """Normalised inbound event after webhook verification."""

    external_event_id: str
    event_type: str
    raw_payload: dict[str, Any]

    @classmethod
    def from_payload(cls, raw: dict[str, Any]) -> 'ParsedEvent':
        return cls(
            external_event_id=str(raw.get('external_event_id', '')),
            event_type=str(raw.get('event_type', '')),
            raw_payload=raw.get('raw_payload') or raw,
        )


class ConnectorAdapter(ABC):
    """One concrete implementation per ``ConnectorType.slug``."""

    slug: str

    @abstractmethod
    def verify_webhook(self, request: 'HttpRequest') -> bool:
        ...

    @abstractmethod
    def parse_event(self, request: 'HttpRequest') -> tuple[InstallContext, ParsedEvent]:
        ...

    @abstractmethod
    def extract_content(
        self,
        ctx: InstallContext,
        event: ParsedEvent,
    ) -> Iterable[VerifiableContent]:
        ...

    @abstractmethod
    def send_result(
        self,
        ctx: InstallContext,
        event: ParsedEvent,
        verification: 'Verification',
    ) -> dict[str, Any]:
        ...

    @abstractmethod
    def begin_install(
        self,
        user,
        *,
        organization=None,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ...

    @abstractmethod
    def complete_install(
        self,
        user,
        payload: dict[str, Any],
        *,
        organization=None,
    ) -> 'ConnectorInstall':
        ...

    def refresh_credentials(self, install: 'ConnectorInstall') -> None:
        """Default no-op; OAuth adapters override."""
        return None

    def acknowledge_event(self, ctx: InstallContext, event: ParsedEvent) -> None:
        """Send an immediate 'we received your content' reply. Default no-op."""
        return None
