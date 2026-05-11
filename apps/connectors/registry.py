"""Registry of connector slug → adapter class."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from .exceptions import ConnectorError

if TYPE_CHECKING:
    from .base import ConnectorAdapter

T = TypeVar('T', bound='ConnectorAdapter')

_REGISTRY: dict[str, type[ConnectorAdapter]] = {}


def register(adapter_cls: type[T]) -> type[T]:
    slug = getattr(adapter_cls, 'slug', None)
    if not slug:
        raise ValueError(f'{adapter_cls.__name__} must define slug')
    if slug in _REGISTRY:
        raise ValueError(f'Duplicate connector adapter slug: {slug}')
    _REGISTRY[slug] = adapter_cls
    return adapter_cls


def get(slug: str) -> 'ConnectorAdapter':
    cls = _REGISTRY.get(slug)
    if not cls:
        raise ConnectorError(f"No adapter registered for slug '{slug}'")
    return cls()


def registered_slugs() -> frozenset[str]:
    return frozenset(_REGISTRY.keys())
