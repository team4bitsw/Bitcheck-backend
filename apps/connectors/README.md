# Connectors app

Layer for third-party inbound webhooks and connector installs. Each integration is an **adapter** subclass of `ConnectorAdapter` with a unique `slug` matching a `ConnectorType` row.

## Add a new adapter

1. Create `apps/connectors/adapters/<name>/adapter.py` implementing `ConnectorAdapter` (`verify_webhook`, `parse_event`, `extract_content`, `send_result`, `begin_install`, `complete_install`).
2. Decorate the class with `@register` from `apps.connectors.registry`.
3. Import the module from `apps/connectors/apps.py` inside `ready()` (same pattern as `adapters.echo`).
4. Add a `ConnectorType` row (migration or admin): `slug` must equal `adapter.slug`. Use `settings_schema` for install-time JSON Schema if needed.

## HTTP surface

- Webhook: `POST /api/connectors/webhook/<slug>/` (signature verified by the adapter; queues `process_connector_event`).
- REST: `GET /api/connectors/types/`, installs CRUD under `/api/connectors/installs/`, OAuth stub at `/api/connectors/oauth/<slug>/callback/`.

See `config/settings.py` for env vars: `CONNECTOR_CREDENTIALS_KEY`, `CONNECTORS_PUBLIC_BASE_URL`, rate limits, optional `REDIS_CACHE_URL`.
