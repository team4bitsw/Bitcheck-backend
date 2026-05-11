"""Fernet encryption for connector credential blobs."""

from __future__ import annotations

import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import models


def _fernet() -> Fernet:
    raw = settings.CONNECTOR_CREDENTIALS_KEY
    if isinstance(raw, str):
        raw = raw.encode('utf-8')
    return Fernet(raw)


def encrypt_dict(data: dict[str, Any] | None) -> bytes:
    if data is None:
        data = {}
    payload = json.dumps(data, separators=(',', ':')).encode('utf-8')
    return _fernet().encrypt(payload)


def decrypt_dict(blob: bytes | None) -> dict[str, Any]:
    if blob is None or blob == b'':
        return {}
    dec = _fernet().decrypt(blob)
    return json.loads(dec.decode('utf-8'))


class EncryptedJSONField(models.BinaryField):
    """Store a JSON-serializable dict encrypted at rest (Fernet)."""

    description = 'Encrypted JSON (Fernet)'

    def __init__(self, *args, **kwargs):
        kwargs['editable'] = False
        super().__init__(*args, **kwargs)

    def from_db_value(self, value, expression, connection):
        if value is None:
            return {}
        if value == b'':
            return {}
        try:
            return decrypt_dict(bytes(value))
        except (InvalidToken, json.JSONDecodeError, TypeError):
            return {}

    def to_python(self, value):
        if value is None or isinstance(value, dict):
            return value if value is not None else {}
        if isinstance(value, memoryview):
            value = bytes(value)
        if isinstance(value, bytes):
            if not value:
                return {}
            try:
                return decrypt_dict(value)
            except (InvalidToken, json.JSONDecodeError, TypeError):
                return {}
        return value

    def get_prep_value(self, value):
        if value is None or value == {}:
            enc = encrypt_dict({})
        elif isinstance(value, dict):
            enc = encrypt_dict(value)
        else:
            enc = value
        return super().get_prep_value(enc)
